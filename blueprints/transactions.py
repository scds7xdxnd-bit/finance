import datetime
import os

from finance_app.extensions import db
from finance_app.lib.auth import csrf_token_valid, current_user
from finance_app.lib.dates import _parse_date_tuple
from finance_app.models.accounting_models import Account, AccountCategory, JournalEntry, JournalLine, Transaction
from finance_app.services.schema_guard_service import guard_capabilities, validate_schema_guard_bypass
from finance_app.services.transaction_import_service import import_csv_transactions
from finance_app.services.transaction_service import delete_transaction_for_user
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import and_, distinct, or_
from werkzeug.utils import secure_filename

transactions_bp = Blueprint("transactions_bp", __name__)


def _allowed_upload(filename: str) -> bool:
    allowed = current_app.config.get("UPLOAD_ALLOWED_EXTENSIONS") or set()
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {ext.lower() for ext in allowed}


def _maybe_scan_file(path: str) -> None:
    # Placeholder hook for AV scanning; integrate with external scanner if available.
    return


def _check_csrf() -> bool:
    return csrf_token_valid()


def _record_last_import_result(
    *,
    imported_count: int,
    duplicate_count: int,
    failed_count: int,
    summary_text: str,
    source_filename: str | None = None,
) -> None:
    session["last_import_result_v1"] = {
        "imported_count": int(imported_count or 0),
        "duplicate_count": int(duplicate_count or 0),
        "failed_count": int(failed_count or 0),
        "summary_text": (summary_text or "").strip(),
        "source_filename": (source_filename or "").strip() or None,
        "recorded_at": datetime.datetime.utcnow().isoformat(),
    }


def _guard_write_capabilities(required_caps, *, user_id):
    enforce_guard = bool(current_app.config.get("SCHEMA_GUARD_ENFORCE", True))
    bypass_ok, bypass_meta = validate_schema_guard_bypass(current_app.config)
    if not bypass_ok:
        return False, bypass_meta, 503
    if not enforce_guard:
        current_app.logger.warning(
            "schema_guard_bypass_enabled path=%s method=%s user_id=%s until=%s reason=%s",
            request.path,
            request.method,
            user_id,
            bypass_meta.get("until"),
            bypass_meta.get("reason"),
        )
    ok_guard, payload, status = guard_capabilities(required_caps, enforce=enforce_guard)
    if not ok_guard:
        return False, payload, 503 if status < 500 else status
    return True, payload, status


@transactions_bp.route('/upload_csv', methods=['POST'])
def upload_csv():
    user = current_user()
    if not user:
        flash('Login required.')
        return redirect(url_for('auth_bp.login'))
    if not _check_csrf():
        return {"ok": False, "error": "CSRF token missing or invalid."}, 400
    file = request.files.get('csv_file')
    if not file or not file.filename:
        flash('Please upload a valid CSV file.')
        return redirect(url_for('transactions_bp.transactions'))
    if not _allowed_upload(file.filename):
        flash('Please upload a valid CSV file.')
        return redirect(url_for('transactions_bp.transactions'))
    if request.content_length and request.content_length > int(current_app.config.get("MAX_CONTENT_LENGTH") or 0):
        flash('File exceeds size limit.')
        return redirect(url_for('transactions_bp.transactions'))
    ok_guard, payload, status = _guard_write_capabilities(["csv_idempotency", "journal_integrity"], user_id=user.id)
    if not ok_guard:
        return payload, status
    try:
        upload_root = current_app.config.get("UPLOAD_FOLDER") or "instance/uploads"
        os.makedirs(upload_root, exist_ok=True)
        tmp_path = os.path.join(upload_root, secure_filename(file.filename))
        file.save(tmp_path)
        _maybe_scan_file(tmp_path)
        with open(tmp_path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        summary = import_csv_transactions(
            raw,
            user.id,
            filename=file.filename,
            force=str(request.form.get("force") or request.args.get("force") or "").strip().lower() in ("1", "true", "yes"),
            write_mode=str(current_app.config.get("LEDGER_WRITE_MODE") or "journal"),
            idempotency_enabled=bool(current_app.config.get("CSV_IDEMPOTENCY_ENABLED", True)),
        )
        if summary.get("skipped_duplicate_batch"):
            _record_last_import_result(
                imported_count=0,
                duplicate_count=int(summary.get("rows_duplicate") or (summary.get("totals") or {}).get("rows_duplicate") or 0),
                failed_count=0,
                summary_text="CSV already imported previously; no new entries created.",
                source_filename=file.filename,
            )
            flash("CSV already imported previously; no new entries created.")
            return redirect(url_for('transactions_bp.transactions'))
        parts = []
        if summary.get("count_journal"):
            parts.append(f"{summary['count_journal']} journal entries")
        if summary.get("count_simple"):
            parts.append(f"{summary['count_simple']} transactions")
        msg_summary = " and ".join(parts) if parts else "0 records"
        extra = (
            f" Normalized dates: {summary.get('normalized_dates', 0)}."
            f" Unparsable dates: {summary.get('unparsable_dates', 0)}."
        )
        skipped_unbalanced = summary.get("skipped_unbalanced") or []
        skipped_existing = summary.get("skipped_existing") or []
        duplicate_reasons = summary.get("duplicate_reasons") or {}
        error_reasons = summary.get("error_reasons") or {}
        if skipped_unbalanced:
            extra += f" Skipped unbalanced transaction IDs: {', '.join(sorted(skipped_unbalanced))}."
        if skipped_existing:
            extra += f" Skipped existing transaction IDs: {', '.join(sorted(skipped_existing))}."
        if summary.get("rows_duplicate"):
            extra += f" Duplicate rows skipped: {summary.get('rows_duplicate', 0)}."
            if duplicate_reasons:
                reason_txt = ", ".join(f"{k}={v}" for k, v in sorted(duplicate_reasons.items()))
                extra += f" Duplicate reasons: {reason_txt}."
        if summary.get("rows_error"):
            extra += f" Error rows skipped: {summary.get('rows_error', 0)}."
            if error_reasons:
                reason_txt = ", ".join(f"{k}={v}" for k, v in sorted(error_reasons.items()))
                extra += f" Error reasons: {reason_txt}."
        full_summary = f"Successfully imported {msg_summary}." + extra
        _record_last_import_result(
            imported_count=int(summary.get("rows_new") or 0),
            duplicate_count=int(summary.get("rows_duplicate") or 0),
            failed_count=int(summary.get("rows_error") or 0),
            summary_text=full_summary,
            source_filename=file.filename,
        )
        flash(full_summary)
    except Exception:
        current_app.logger.exception("csv_import_failed path=%s user_id=%s", request.path, user.id)
        _record_last_import_result(
            imported_count=0,
            duplicate_count=0,
            failed_count=1,
            summary_text="Error importing CSV. Please review the file and try again.",
            source_filename=file.filename,
        )
        flash("Error importing CSV. Please review the file and try again.")
    return redirect(url_for('transactions_bp.transactions'))


@transactions_bp.route('/transactions', methods=['GET'])
def transactions():
    user = current_user()
    if not user:
        flash('Login required.')
        return redirect(url_for('auth_bp.login'))

    # Base query for classical two-line transactions
    tx_query = Transaction.query
    if not user.is_admin:
        tx_query = tx_query.filter_by(user_id=user.id)

    # Filter inputs
    q = (request.args.get('q') or '').strip()
    category = (request.args.get('category') or '').strip()
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    account = request.args.get('account')
    min_amount = request.args.get('min_amount')
    max_amount = request.args.get('max_amount')

    def _parse_date(s):
        if not s:
            return None
        try:
            y, m, d = _parse_date_tuple(s)
            if y and m and d:
                return datetime.date(y, m, d)
        except Exception:
            return None

    def _norm_date_str(s):
        if not s:
            return None
        try:
            parts = str(s).replace('-', '/').split('/')
            if len(parts) == 3:
                y = parts[0]
                m = parts[1].zfill(2)
                d = parts[2].zfill(2)
                return f"{y}/{m}/{d}"
        except Exception:
            pass
        return s

    _sd = _parse_date(start_date)
    _ed = _parse_date(end_date)
    _sd_str = _norm_date_str(start_date)
    _ed_str = _norm_date_str(end_date)

    if account:
        tx_query = tx_query.filter((Transaction.debit_account == account) | (Transaction.credit_account == account))
    if min_amount:
        try:
            amt = float(min_amount)
            tx_query = tx_query.filter(
                (Transaction.debit_amount >= amt) | (Transaction.credit_amount >= amt)
            )
        except Exception:
            pass
    if max_amount:
        try:
            amt = float(max_amount)
            tx_query = tx_query.filter(
                (Transaction.debit_amount <= amt) | (Transaction.credit_amount <= amt)
            )
        except Exception:
            pass
    if _sd:
        tx_query = tx_query.filter(
            or_(
                Transaction.date_parsed >= _sd,
                and_(Transaction.date_parsed == None, _sd_str is not None, Transaction.date >= _sd_str)
            )
        )
    if _ed:
        tx_query = tx_query.filter(
            or_(
                Transaction.date_parsed <= _ed,
                and_(Transaction.date_parsed == None, _ed_str is not None, Transaction.date <= _ed_str)
            )
        )
    tx_query = tx_query.order_by(Transaction.date_parsed.desc(), Transaction.id.desc())

    try:
        page = max(1, int(request.args.get('page') or 1))
    except Exception:
        page = 1
    try:
        per_page = max(1, min(1000, int(request.args.get('per_page') or 100)))
    except Exception:
        per_page = 100

    # Build account list for filters from transactions (extend later with journal lines)
    accs = set()
    for row in db.session.query(distinct(Transaction.debit_account)).filter(Transaction.user_id == user.id).all():
        name = (row[0] or '').strip()
        if name:
            accs.add(name)
    for row in db.session.query(distinct(Transaction.credit_account)).filter(Transaction.user_id == user.id).all():
        name = (row[0] or '').strip()
        if name:
            accs.add(name)

    journal_entries = []
    journal_lines_by_entry = {}
    account_names = {}
    account_category_ids = {}
    if JournalEntry and JournalLine and Account:
        je_query = JournalEntry.query.filter_by(user_id=user.id)
        if _sd:
            je_query = je_query.filter(
                or_(
                    JournalEntry.date_parsed >= _sd,
                    and_(JournalEntry.date_parsed == None, _sd_str is not None, JournalEntry.date >= _sd_str)
                )
            )
        if _ed:
            je_query = je_query.filter(
                or_(
                    JournalEntry.date_parsed <= _ed,
                    and_(JournalEntry.date_parsed == None, _ed_str is not None, JournalEntry.date <= _ed_str)
                )
            )
        je_query = je_query.order_by(JournalEntry.date_parsed.desc(), JournalEntry.id.desc())
        journal_entries = je_query.all()
        entry_ids = [e.id for e in journal_entries]
        if entry_ids:
            lines = JournalLine.query.filter(JournalLine.journal_id.in_(entry_ids)) \
                .order_by(JournalLine.journal_id.asc(), JournalLine.line_no.asc(), JournalLine.id.asc()).all()
            account_ids = {ln.account_id for ln in lines if ln.account_id}
            if account_ids:
                for row in Account.query.filter(Account.id.in_(account_ids)).all():
                    account_names[row.id] = row.name
                    account_category_ids[row.id] = row.category_id
                    if row.name:
                        accs.add(row.name)
            for ln in lines:
                journal_lines_by_entry.setdefault(ln.journal_id, []).append(ln)

    simple_rows = tx_query.all()
    simple_account_ids = set()
    for row in simple_rows:
        if row.debit_account_id:
            simple_account_ids.add(row.debit_account_id)
        if row.credit_account_id:
            simple_account_ids.add(row.credit_account_id)
    if simple_account_ids:
        for row in Account.query.filter(Account.id.in_(simple_account_ids)).all():
            account_names.setdefault(row.id, row.name)
            account_category_ids[row.id] = row.category_id
            if row.name:
                accs.add(row.name)

    category_name_by_id = {}
    category_names = set()
    category_ids = {cid for cid in account_category_ids.values() if cid}
    if category_ids:
        for row in AccountCategory.query.filter(AccountCategory.user_id == user.id, AccountCategory.id.in_(category_ids)).all():
            category_name_by_id[row.id] = row.name
            if row.name:
                category_names.add(row.name)
    # Preserve available category filter options even when no rows match current filters.
    for row in AccountCategory.query.filter(AccountCategory.user_id == user.id).all():
        if row.name:
            category_names.add(row.name)

    combined = []
    for t in simple_rows:
        debit_category = category_name_by_id.get(account_category_ids.get(t.debit_account_id), '')
        credit_category = category_name_by_id.get(account_category_ids.get(t.credit_account_id), '')
        combined.append({
            'kind': 'simple',
            'id': t.id,
            'date': t.date,
            'date_parsed': t.date_parsed,
            'description': t.description,
            'total_debit': float(t.debit_amount or 0.0),
            'lines': [
                {'dc': 'D', 'account': t.debit_account, 'category': debit_category, 'amount': float(t.debit_amount or 0.0)},
                {'dc': 'C', 'account': t.credit_account, 'category': credit_category, 'amount': float(t.credit_amount or 0.0)}
            ]
        })

    q_filter = q.lower() if q else ''
    account_filter = (account or '').strip().lower() if account else ''
    category_filter = (category or '').strip().lower() if category else ''

    def _entry_matches_filters(entry_dict):
        if q_filter:
            description_text = (entry_dict.get('description') or '').strip().lower()
            reference_text = (entry_dict.get('reference') or '').strip().lower()
            line_match = any(
                q_filter in (ln.get('account') or '').strip().lower()
                or q_filter in (ln.get('memo') or '').strip().lower()
                for ln in entry_dict['lines']
            )
            if q_filter not in description_text and q_filter not in reference_text and not line_match:
                return False
        if account_filter:
            if not any((ln.get('account') or '').strip().lower() == account_filter for ln in entry_dict['lines']):
                return False
        if category_filter:
            if not any((ln.get('category') or '').strip().lower() == category_filter for ln in entry_dict['lines']):
                return False
        if min_amount:
            try:
                if entry_dict['total_debit'] < float(min_amount):
                    return False
            except Exception:
                pass
        if max_amount:
            try:
                if entry_dict['total_debit'] > float(max_amount):
                    return False
            except Exception:
                pass
        return True

    for je in journal_entries:
        lines = journal_lines_by_entry.get(je.id, [])
        total_debit = 0.0
        formatted_lines = []
        for ln in lines:
            amt = float(ln.amount_base or 0.0)
            if (ln.dc or '').upper() == 'D':
                total_debit += amt
            formatted_lines.append({
                'dc': (ln.dc or '').upper(),
                'account': account_names.get(ln.account_id, ''),
                'category': category_name_by_id.get(account_category_ids.get(ln.account_id), ''),
                'amount': amt,
                'memo': ln.memo or ''
            })
        entry_dict = {
            'kind': 'journal',
            'id': je.id,
            'date': je.date,
            'date_parsed': je.date_parsed,
            'description': je.description,
            'reference': je.reference,
            'total_debit': total_debit,
            'lines': formatted_lines
        }
        if _entry_matches_filters(entry_dict):
            combined.append(entry_dict)

    filtered_combined = []
    for entry in combined:
        if _entry_matches_filters(entry):
            filtered_combined.append(entry)

    def _sort_key(entry):
        dt = entry.get('date_parsed')
        if dt is None:
            try:
                y, m, d = _parse_date_tuple(entry.get('date'))
                if y and m and d:
                    dt = datetime.date(y, m, d)
            except Exception:
                dt = None
        return (
            dt or datetime.date.min,
            entry.get('id', 0)
        )

    filtered_combined.sort(key=_sort_key, reverse=True)
    total_count = len(filtered_combined)
    pages = (total_count + per_page - 1) // per_page if per_page else 1
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = filtered_combined[start_idx:end_idx]

    accounts = sorted(accs, key=lambda x: x.lower())
    categories = sorted(category_names, key=lambda x: x.lower())
    last_import_result = session.get("last_import_result_v1")
    now = datetime.datetime.now()
    return render_template('transactions.html', entries=paginated, user=user, accounts=accounts, categories=categories, now=now,
                           last_import_result=last_import_result,
                           page=page, pages=pages, per_page=per_page, total_count=total_count,
                           filters={
                               'q': q or '',
                               'category': category or '',
                               'start_date': start_date or '',
                               'end_date': end_date or '',
                               'account': account or '',
                               'min_amount': min_amount or '',
                               'max_amount': max_amount or ''
                           })


@transactions_bp.route('/transactions/delete/<int:tx_id>', methods=['POST'])
def delete_transaction(tx_id):
    if not _check_csrf():
        return {"ok": False, "error": "CSRF token missing or invalid."}, 400
    user = current_user()
    if not delete_transaction_for_user(tx_id, user):
        flash('Unauthorized.' if user else 'Login required.')
        return redirect(url_for('transactions_bp.transactions'))
    flash('Transaction deleted.')
    return redirect(url_for('transactions_bp.transactions'))


@transactions_bp.route('/add_transaction', methods=['GET', 'POST'])
def add_transaction():
    user = current_user()
    if not user:
        if request.method == 'POST' and request.is_json:
            return {'ok': False, 'error': 'Unauthorized'}, 401
        return ("Unauthorized", 401)
    # JSON API used by the transactions.html UI
    if request.method == 'POST' and request.is_json:
        if not _check_csrf():
            return {'ok': False, 'error': 'CSRF token missing or invalid.'}, 400
        ok_guard, payload, status = _guard_write_capabilities(["journal_integrity"], user_id=user.id)
        if not ok_guard:
            return payload, status
        data = request.get_json(silent=True) or {}
        ok, result, status = save_transaction(data)
        return (result, status)
    # Fallback (not used by current UI)
    if request.method == 'POST':
        return {'ok': False, 'error': 'Expected JSON payload'}, 400
    # For GET, simply redirect to main transactions view
    return redirect(url_for('transactions_bp.transactions'))


# Updated transaction list endpoint to support multiline display and refined filter aesthetics
@transactions_bp.route('/transactions/list', methods=['GET'])
def transaction_list():
    user = current_user()
    if not user:
        flash('Login required.')
        return redirect(url_for('auth_bp.login'))

    # Base query for classical two-line transactions
    tx_query = Transaction.query
    if not user.is_admin:
        tx_query = tx_query.filter_by(user_id=user.id)

    # Filter inputs
    q = (request.args.get('q') or '').strip()
    category = (request.args.get('category') or '').strip()
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    account = request.args.get('account')
    min_amount = request.args.get('min_amount')
    max_amount = request.args.get('max_amount')

    def _parse_date(s):
        if not s:
            return None
        try:
            y, m, d = _parse_date_tuple(s)
            if y and m and d:
                return datetime.date(y, m, d)
        except Exception:
            return None

    def _norm_date_str(s):
        if not s:
            return None
        try:
            parts = str(s).replace('-', '/').split('/')
            if len(parts) == 3:
                y = parts[0]
                m = parts[1].zfill(2)
                d = parts[2].zfill(2)
                return f"{y}/{m}/{d}"
        except Exception:
            pass
        return s

    _sd = _parse_date(start_date)
    _ed = _parse_date(end_date)
    _sd_str = _norm_date_str(start_date)
    _ed_str = _norm_date_str(end_date)

    if account:
        tx_query = tx_query.filter((Transaction.debit_account == account) | (Transaction.credit_account == account))
    if min_amount:
        try:
            amt = float(min_amount)
            tx_query = tx_query.filter(
                (Transaction.debit_amount >= amt) | (Transaction.credit_amount >= amt)
            )
        except Exception:
            pass
    if max_amount:
        try:
            amt = float(max_amount)
            tx_query = tx_query.filter(
                (Transaction.debit_amount <= amt) | (Transaction.credit_amount <= amt)
            )
        except Exception:
            pass
    if _sd:
        tx_query = tx_query.filter(
            or_(
                Transaction.date_parsed >= _sd,
                and_(Transaction.date_parsed == None, _sd_str is not None, Transaction.date >= _sd_str)
            )
        )
    if _ed:
        tx_query = tx_query.filter(
            or_(
                Transaction.date_parsed <= _ed,
                and_(Transaction.date_parsed == None, _ed_str is not None, Transaction.date <= _ed_str)
            )
        )
    tx_query = tx_query.order_by(Transaction.date_parsed.desc(), Transaction.id.desc())

    try:
        page = max(1, int(request.args.get('page') or 1))
    except Exception:
        page = 1
    try:
        per_page = max(1, min(1000, int(request.args.get('per_page') or 100)))
    except Exception:
        per_page = 100

    # Build account list for filters from transactions (extend later with journal lines)
    accs = set()
    for row in db.session.query(distinct(Transaction.debit_account)).filter(Transaction.user_id == user.id).all():
        name = (row[0] or '').strip()
        if name:
            accs.add(name)
    for row in db.session.query(distinct(Transaction.credit_account)).filter(Transaction.user_id == user.id).all():
        name = (row[0] or '').strip()
        if name:
            accs.add(name)

    journal_entries = []
    journal_lines_by_entry = {}
    account_names = {}
    account_category_ids = {}
    if JournalEntry and JournalLine and Account:
        je_query = JournalEntry.query.filter_by(user_id=user.id)
        if _sd:
            je_query = je_query.filter(
                or_(
                    JournalEntry.date_parsed >= _sd,
                    and_(JournalEntry.date_parsed == None, _sd_str is not None, JournalEntry.date >= _sd_str)
                )
            )
        if _ed:
            je_query = je_query.filter(
                or_(
                    JournalEntry.date_parsed <= _ed,
                    and_(JournalEntry.date_parsed == None, _ed_str is not None, JournalEntry.date <= _ed_str)
                )
            )
        je_query = je_query.order_by(JournalEntry.date_parsed.desc(), JournalEntry.id.desc())
        journal_entries = je_query.all()
        entry_ids = [e.id for e in journal_entries]
        if entry_ids:
            lines = JournalLine.query.filter(JournalLine.journal_id.in_(entry_ids)) \
                .order_by(JournalLine.journal_id.asc(), JournalLine.line_no.asc(), JournalLine.id.asc()).all()
            account_ids = {ln.account_id for ln in lines if ln.account_id}
            if account_ids:
                for row in Account.query.filter(Account.id.in_(account_ids)).all():
                    account_names[row.id] = row.name
                    account_category_ids[row.id] = row.category_id
                    if row.name:
                        accs.add(row.name)
            for ln in lines:
                journal_lines_by_entry.setdefault(ln.journal_id, []).append(ln)

    simple_rows = tx_query.all()
    simple_account_ids = set()
    for row in simple_rows:
        if row.debit_account_id:
            simple_account_ids.add(row.debit_account_id)
        if row.credit_account_id:
            simple_account_ids.add(row.credit_account_id)
    if simple_account_ids:
        for row in Account.query.filter(Account.id.in_(simple_account_ids)).all():
            account_names.setdefault(row.id, row.name)
            account_category_ids[row.id] = row.category_id
            if row.name:
                accs.add(row.name)

    category_name_by_id = {}
    category_names = set()
    category_ids = {cid for cid in account_category_ids.values() if cid}
    if category_ids:
        for row in AccountCategory.query.filter(AccountCategory.user_id == user.id, AccountCategory.id.in_(category_ids)).all():
            category_name_by_id[row.id] = row.name
            if row.name:
                category_names.add(row.name)
    for row in AccountCategory.query.filter(AccountCategory.user_id == user.id).all():
        if row.name:
            category_names.add(row.name)

    combined = []
    for t in simple_rows:
        debit_category = category_name_by_id.get(account_category_ids.get(t.debit_account_id), '')
        credit_category = category_name_by_id.get(account_category_ids.get(t.credit_account_id), '')
        combined.append({
            'kind': 'simple',
            'id': t.id,
            'date': t.date,
            'date_parsed': t.date_parsed,
            'description': t.description,
            'total_debit': float(t.debit_amount or 0.0),
            'lines': [
                {'dc': 'D', 'account': t.debit_account, 'category': debit_category, 'amount': float(t.debit_amount or 0.0)},
                {'dc': 'C', 'account': t.credit_account, 'category': credit_category, 'amount': float(t.credit_amount or 0.0)}
            ]
        })

    q_filter = q.lower() if q else ''
    account_filter = (account or '').strip().lower() if account else ''
    category_filter = (category or '').strip().lower() if category else ''

    def _entry_matches_filters(entry_dict):
        if q_filter:
            description_text = (entry_dict.get('description') or '').strip().lower()
            reference_text = (entry_dict.get('reference') or '').strip().lower()
            line_match = any(
                q_filter in (ln.get('account') or '').strip().lower()
                or q_filter in (ln.get('memo') or '').strip().lower()
                for ln in entry_dict['lines']
            )
            if q_filter not in description_text and q_filter not in reference_text and not line_match:
                return False
        if account_filter:
            if not any((ln.get('account') or '').strip().lower() == account_filter for ln in entry_dict['lines']):
                return False
        if category_filter:
            if not any((ln.get('category') or '').strip().lower() == category_filter for ln in entry_dict['lines']):
                return False
        if min_amount:
            try:
                if entry_dict['total_debit'] < float(min_amount):
                    return False
            except Exception:
                pass
        if max_amount:
            try:
                if entry_dict['total_debit'] > float(max_amount):
                    return False
            except Exception:
                pass
        return True

    for je in journal_entries:
        lines = journal_lines_by_entry.get(je.id, [])
        total_debit = 0.0
        formatted_lines = []
        for ln in lines:
            amt = float(ln.amount_base or 0.0)
            if (ln.dc or '').upper() == 'D':
                total_debit += amt
            formatted_lines.append({
                'dc': (ln.dc or '').upper(),
                'account': account_names.get(ln.account_id, ''),
                'category': category_name_by_id.get(account_category_ids.get(ln.account_id), ''),
                'amount': amt,
                'memo': ln.memo or ''
            })
        entry_dict = {
            'kind': 'journal',
            'id': je.id,
            'date': je.date,
            'date_parsed': je.date_parsed,
            'description': je.description,
            'reference': je.reference,
            'total_debit': total_debit,
            'lines': formatted_lines
        }
        if _entry_matches_filters(entry_dict):
            combined.append(entry_dict)

    filtered_combined = []
    for entry in combined:
        if _entry_matches_filters(entry):
            filtered_combined.append(entry)

    def _sort_key(entry):
        dt = entry.get('date_parsed')
        if dt is None:
            try:
                y, m, d = _parse_date_tuple(entry.get('date'))
                if y and m and d:
                    dt = datetime.date(y, m, d)
            except Exception:
                dt = None
        return (
            dt or datetime.date.min,
            entry.get('id', 0)
        )

    filtered_combined.sort(key=_sort_key, reverse=True)
    total_count = len(filtered_combined)
    pages = (total_count + per_page - 1) // per_page if per_page else 1
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = filtered_combined[start_idx:end_idx]

    accounts = sorted(accs, key=lambda x: x.lower())
    categories = sorted(category_names, key=lambda x: x.lower())
    last_import_result = session.get("last_import_result_v1")
    now = datetime.datetime.now()
    return render_template('transactions.html', entries=paginated, user=user, accounts=accounts, categories=categories, now=now,
                           last_import_result=last_import_result,
                           page=page, pages=pages, per_page=per_page, total_count=total_count,
                           filters={
                               'q': q or '',
                               'category': category or '',
                               'start_date': start_date or '',
                               'end_date': end_date or '',
                               'account': account or '',
                               'min_amount': min_amount or '',
                               'max_amount': max_amount or ''
                           })


def save_transaction(data):
    """Create a JournalEntry with JournalLine rows from JSON payload.
    Expected payload shape:
      { "date": "YYYY-MM-DD", "description": str, "lines": [ {"dc":"D|C", "account": str, "amount": number, "memo": str?} ... ] }
    Returns (ok: bool, response_dict: dict, http_status: int).
    """
    from finance_app.services.transaction_create_service import save_transaction_payload

    user = current_user()
    if not user:
        return False, { 'ok': False, 'error': 'Unauthorized' }, 401

    return save_transaction_payload(user.id, data)


# Helper function to retrieve transactions, optionally filtering them
def get_all_transactions(filter_query=''):
    # ...existing code to query database; apply filter if filter_query is provided...
    # Example: Transaction.query.filter(Transaction.description.ilike(f'%{filter_query}%')).all()
    return []
