import datetime
import os
from decimal import Decimal, InvalidOperation

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


TRANSACTIONS_FILTER_PARAM_KEYS = (
    "q",
    "account",
    "category",
    "min_amount",
    "max_amount",
    "start_date",
    "end_date",
    "page",
    "per_page",
)


def _extract_preserved_filter_params(values) -> dict[str, str]:
    preserved: dict[str, str] = {}
    for key in TRANSACTIONS_FILTER_PARAM_KEYS:
        if key in values:
            preserved[key] = (values.get(key) or "").strip()
    return preserved


def _non_negative_int(value) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return 0


def _normalize_failure_samples(samples) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    if not isinstance(samples, (list, tuple)):
        return normalized
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        line_number_raw = sample.get("line_number", sample.get("row"))
        message = str(sample.get("message") or "").strip()
        try:
            line_number = int(line_number_raw)
        except Exception:
            line_number = 0
        if line_number >= 1 and message:
            normalized.append({"line_number": line_number, "message": message})
    return normalized


def _normalize_warnings(warnings) -> list[str]:
    normalized: list[str] = []
    if not isinstance(warnings, (list, tuple)):
        return normalized
    for warning in warnings:
        text = str(warning or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _normalize_filter_token(raw: str | None) -> str:
    token = (raw or "").strip()
    if token.lower() == "all":
        return ""
    return token


def _parse_filter_decimal(raw: str | None, *, field: str, errors: list[str]) -> tuple[float | None, str]:
    token = (raw or "").strip()
    if not token:
        return None, ""
    try:
        value = float(Decimal(token))
        return value, token
    except (InvalidOperation, ValueError, TypeError):
        errors.append(f"Invalid filter {field}; expected decimal value.")
        return None, ""


def _parse_filter_date(raw: str | None, *, field: str, errors: list[str]) -> tuple[datetime.date | None, str]:
    token = (raw or "").strip()
    if not token:
        return None, ""
    try:
        return datetime.datetime.strptime(token, "%Y-%m-%d").date(), token
    except Exception:
        errors.append(f"Invalid filter {field}; expected YYYY-MM-DD.")
        return None, ""


def _parse_transactions_filters() -> dict:
    errors: list[str] = []

    q = (request.args.get("q") or "").strip()
    account = _normalize_filter_token(request.args.get("account"))
    category = _normalize_filter_token(request.args.get("category"))

    min_amount_value, min_amount = _parse_filter_decimal(
        request.args.get("min_amount"), field="min_amount", errors=errors
    )
    max_amount_value, max_amount = _parse_filter_decimal(
        request.args.get("max_amount"), field="max_amount", errors=errors
    )
    start_parsed, start_date = _parse_filter_date(
        request.args.get("start_date"), field="start_date", errors=errors
    )
    end_parsed, end_date = _parse_filter_date(
        request.args.get("end_date"), field="end_date", errors=errors
    )

    try:
        page = max(1, int((request.args.get("page") or "1").strip() or "1"))
    except Exception:
        page = 1
        errors.append("Invalid filter page; defaulting to 1.")

    try:
        per_page = max(1, min(1000, int((request.args.get("per_page") or "100").strip() or "100")))
    except Exception:
        per_page = 100
        errors.append("Invalid filter per_page; defaulting to 100.")

    return {
        "q": q,
        "account": account,
        "category": category,
        "min_amount": min_amount,
        "max_amount": max_amount,
        "min_amount_value": min_amount_value,
        "max_amount_value": max_amount_value,
        "start_date": start_date,
        "end_date": end_date,
        "start_date_parsed": start_parsed,
        "end_date_parsed": end_parsed,
        "page": page,
        "per_page": per_page,
        "errors": errors,
    }


def _record_last_import_result(
    *,
    imported_count: int,
    duplicate_count: int,
    failed_count: int,
    summary_text: str,
    source_filename: str | None = None,
    failure_samples=None,
    write_mode: str | None = None,
    warnings=None,
) -> None:
    summary = (summary_text or "").strip() or "CSV import result recorded."
    payload = {
        "imported_count": _non_negative_int(imported_count),
        "duplicate_count": _non_negative_int(duplicate_count),
        "failed_count": _non_negative_int(failed_count),
        "summary_text": summary,
        "source_filename": (source_filename or "").strip() or None,
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    normalized_samples = _normalize_failure_samples(failure_samples)
    if normalized_samples:
        payload["failure_samples"] = normalized_samples
    mode_token = (write_mode or "").strip()
    if mode_token:
        payload["write_mode"] = mode_token
    normalized_warnings = _normalize_warnings(warnings)
    if normalized_warnings:
        payload["warnings"] = normalized_warnings
    session["last_import_result_v1"] = payload


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
    file = request.files.get('csv_file')
    source_filename = (getattr(file, "filename", None) or "").strip() or None
    if not _check_csrf():
        message = "CSRF token missing or invalid."
        _record_last_import_result(
            imported_count=0,
            duplicate_count=0,
            failed_count=1,
            summary_text=message,
            source_filename=source_filename,
        )
        flash(message)
        return message, 400
    if not file or not file.filename:
        _record_last_import_result(
            imported_count=0,
            duplicate_count=0,
            failed_count=1,
            summary_text="Please upload a valid CSV file.",
            source_filename=source_filename,
        )
        flash('Please upload a valid CSV file.')
        return redirect(url_for('transactions_bp.transactions'))
    if not _allowed_upload(file.filename):
        _record_last_import_result(
            imported_count=0,
            duplicate_count=0,
            failed_count=1,
            summary_text="Please upload a valid CSV file.",
            source_filename=source_filename,
        )
        flash('Please upload a valid CSV file.')
        return redirect(url_for('transactions_bp.transactions'))
    if request.content_length and request.content_length > int(current_app.config.get("MAX_CONTENT_LENGTH") or 0):
        _record_last_import_result(
            imported_count=0,
            duplicate_count=0,
            failed_count=1,
            summary_text="File exceeds size limit.",
            source_filename=source_filename,
        )
        flash('File exceeds size limit.')
        return redirect(url_for('transactions_bp.transactions'))
    ok_guard, payload, status = _guard_write_capabilities(["csv_idempotency", "journal_integrity"], user_id=user.id)
    if not ok_guard:
        message = str((payload or {}).get("error") or "CSV import unavailable.")
        _record_last_import_result(
            imported_count=0,
            duplicate_count=0,
            failed_count=1,
            summary_text=message,
            source_filename=source_filename,
        )
        flash(message)
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
                write_mode=str(summary.get("write_mode") or ""),
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
        warning_messages: list[str] = []
        if skipped_unbalanced:
            warning_messages.append(
                f"Skipped unbalanced transaction IDs: {', '.join(sorted(skipped_unbalanced))}"
            )
        if skipped_existing:
            warning_messages.append(
                f"Skipped existing transaction IDs: {', '.join(sorted(skipped_existing))}"
            )
        _record_last_import_result(
            imported_count=int(summary.get("rows_new") or 0),
            duplicate_count=int(summary.get("rows_duplicate") or 0),
            failed_count=int(summary.get("rows_error") or 0),
            summary_text=full_summary,
            source_filename=file.filename,
            write_mode=str(summary.get("write_mode") or ""),
            warnings=warning_messages,
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

    filters_state = _parse_transactions_filters()
    q = filters_state["q"]
    category = filters_state["category"]
    start_date = filters_state["start_date"]
    end_date = filters_state["end_date"]
    account = filters_state["account"]
    min_amount = filters_state["min_amount"]
    max_amount = filters_state["max_amount"]
    min_amount_value = filters_state["min_amount_value"]
    max_amount_value = filters_state["max_amount_value"]
    _sd = filters_state["start_date_parsed"]
    _ed = filters_state["end_date_parsed"]
    _sd_str = _sd.strftime("%Y/%m/%d") if _sd else None
    _ed_str = _ed.strftime("%Y/%m/%d") if _ed else None
    page = filters_state["page"]
    per_page = filters_state["per_page"]
    filter_errors = filters_state["errors"]

    if account:
        tx_query = tx_query.filter((Transaction.debit_account == account) | (Transaction.credit_account == account))
    if min_amount_value is not None:
        tx_query = tx_query.filter(
            (Transaction.debit_amount >= min_amount_value) | (Transaction.credit_amount >= min_amount_value)
        )
    if max_amount_value is not None:
        tx_query = tx_query.filter(
            (Transaction.debit_amount <= max_amount_value) | (Transaction.credit_amount <= max_amount_value)
        )
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
            if q_filter not in description_text and q_filter not in reference_text:
                return False
        if account_filter:
            if not any((ln.get('account') or '').strip().lower() == account_filter for ln in entry_dict['lines']):
                return False
        if category_filter:
            if not any((ln.get('category') or '').strip().lower() == category_filter for ln in entry_dict['lines']):
                return False
        if min_amount_value is not None and float(entry_dict['total_debit'] or 0.0) < float(min_amount_value):
            return False
        if max_amount_value is not None and float(entry_dict['total_debit'] or 0.0) > float(max_amount_value):
            return False
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
    dismiss_import_result_url = url_for(
        "transactions_bp.dismiss_last_import_result",
        **_extract_preserved_filter_params(request.args),
    )
    now = datetime.datetime.now()
    return render_template('transactions.html', entries=paginated, user=user, accounts=accounts, categories=categories, now=now,
                           last_import_result=last_import_result,
                           dismiss_import_result_url=dismiss_import_result_url,
                           filter_errors=filter_errors,
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

    filters_state = _parse_transactions_filters()
    q = filters_state["q"]
    category = filters_state["category"]
    start_date = filters_state["start_date"]
    end_date = filters_state["end_date"]
    account = filters_state["account"]
    min_amount = filters_state["min_amount"]
    max_amount = filters_state["max_amount"]
    min_amount_value = filters_state["min_amount_value"]
    max_amount_value = filters_state["max_amount_value"]
    _sd = filters_state["start_date_parsed"]
    _ed = filters_state["end_date_parsed"]
    _sd_str = _sd.strftime("%Y/%m/%d") if _sd else None
    _ed_str = _ed.strftime("%Y/%m/%d") if _ed else None
    page = filters_state["page"]
    per_page = filters_state["per_page"]
    filter_errors = filters_state["errors"]

    if account:
        tx_query = tx_query.filter((Transaction.debit_account == account) | (Transaction.credit_account == account))
    if min_amount_value is not None:
        tx_query = tx_query.filter(
            (Transaction.debit_amount >= min_amount_value) | (Transaction.credit_amount >= min_amount_value)
        )
    if max_amount_value is not None:
        tx_query = tx_query.filter(
            (Transaction.debit_amount <= max_amount_value) | (Transaction.credit_amount <= max_amount_value)
        )
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
            if q_filter not in description_text and q_filter not in reference_text:
                return False
        if account_filter:
            if not any((ln.get('account') or '').strip().lower() == account_filter for ln in entry_dict['lines']):
                return False
        if category_filter:
            if not any((ln.get('category') or '').strip().lower() == category_filter for ln in entry_dict['lines']):
                return False
        if min_amount_value is not None and float(entry_dict['total_debit'] or 0.0) < float(min_amount_value):
            return False
        if max_amount_value is not None and float(entry_dict['total_debit'] or 0.0) > float(max_amount_value):
            return False
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
    dismiss_import_result_url = url_for(
        "transactions_bp.dismiss_last_import_result",
        **_extract_preserved_filter_params(request.args),
    )
    now = datetime.datetime.now()
    return render_template('transactions.html', entries=paginated, user=user, accounts=accounts, categories=categories, now=now,
                           last_import_result=last_import_result,
                           dismiss_import_result_url=dismiss_import_result_url,
                           filter_errors=filter_errors,
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
