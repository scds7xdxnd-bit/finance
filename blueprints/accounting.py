import datetime as _dt
import json
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Set

from finance_app import LoanGroup, LoanGroupLink, current_user, db
from finance_app.lib.auth import require_admin
from finance_app.services.journal_service import (
    JOURNAL_ERROR_UNBALANCED,
    JOURNAL_ERROR_WRITE_FAILED,
    JournalBalanceError,
    JournalLinePayload,
    _validate_balanced,
    journal_error_payload,
    map_journal_db_exception,
)
from finance_app.services.loan_group_service import (
    create_group as loan_group_create,
)
from finance_app.services.loan_group_service import (
    delete_group as loan_group_delete,
)
from finance_app.services.loan_group_service import (
    get_group as loan_group_get,
)
from finance_app.services.loan_group_service import (
    group_summary as loan_group_summary,
)
from finance_app.services.loan_group_service import (
    link_journal_lines as loan_group_link_lines,
)
from finance_app.services.loan_group_service import (
    suggest_allocation,
)
from finance_app.services.loan_group_service import (
    unlink as loan_group_unlink,
)
from finance_app.services.loan_group_service import (
    update_group as loan_group_update,
)
from finance_app.services.ledger_query_service import (
    statement_period as ledger_statement_period,
)
from finance_app.services.ledger_query_service import (
    trial_balance_month as ledger_trial_balance_month,
)
from finance_app.services.receivable_service import (
    create_manual_receivable,
    link_receivable_lines,
    resolve_receivable_scope,
    serialize_manual_receivable,
    serialize_receivable_line,
)
from finance_app.services.trial_balance_service import (
    create_tb_snapshot,
)
from finance_app.services.trial_balance_service import (
    reset_data as tb_reset_data,
)
from finance_app.services.trial_balance_service import (
    set_first_month as tb_set_first_month_service,
)
from finance_app.services.trial_balance_service import (
    set_initialization as tb_set_initialization,
)
from finance_app.services.schema_guard_service import guard_capabilities, validate_schema_guard_bypass
from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func

# We avoid importing from app at module import time to prevent circular imports.
# Instead, import needed symbols inside route functions.

accounting_bp = Blueprint('accounting_bp', __name__)

_VALID_GROUP_DIRECTIONS = {'receivable', 'payable'}
_VALID_GROUP_STATUSES = {'open', 'closed', 'overpaid'}


def _normalized_name(value):
    return (value or '').strip().lower()


def _classify_receivable_category(cat):
    from finance_app.services.receivable_service import classify_receivable_category

    return classify_receivable_category(cat)


def _coerce_number(value):
    from finance_app.services.receivable_service import coerce_number

    return coerce_number(value)


def _parse_receivable_date(raw, date_helper):
    if not raw:
        return None
    try:
        return _dt.date.fromisoformat(raw)
    except Exception:
        pass
    try:
        y, m, d = date_helper(raw)
        if y and m and d:
            return _dt.date(y, m, d)
    except Exception:
        pass
    return None


def _to_iso(date_obj, fallback=None):
    if isinstance(date_obj, _dt.date):
        return date_obj.isoformat()
    if fallback:
        try:
            y, m, d = fallback(date_obj)
            if y and m and d:
                return f"{y:04d}-{m:02d}-{d:02d}"
        except Exception:
            return None
    return None


def _parse_iso_date(value):
    if not value:
        return None
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date.fromisoformat(str(value))
    except Exception:
        return None


def _ensure_ranked_report_source():
    report_source = (request.args.get("source") or "journal").strip().lower()
    if report_source == "mixed":
        return {"ok": False, "error": "Mixed report source is not allowed."}, 400
    if report_source != "journal":
        if not current_app.config.get("ALLOW_LEGACY_REPORT_FALLBACK", False):
            return {"ok": False, "error": "Legacy report fallback is disabled."}, 400
        return {"ok": False, "error": "Legacy report source is not implemented in this release."}, 503
    return None


def _parse_cash_folder_ids_arg() -> List[int]:
    ids: Set[int] = set()
    raw_values = request.args.getlist("cash_folders")
    if not raw_values and request.args.get("cash_folders"):
        raw_values = [request.args.get("cash_folders")]
    for raw in raw_values:
        if not raw:
            continue
        for part in str(raw).split(","):
            token = part.strip()
            if not token:
                continue
            try:
                ids.add(int(token))
            except Exception:
                continue
    return sorted(list(ids))


def _parse_month_period(ym: str):
    try:
        year_str, month_str = ym.split("-")
        year, month = int(year_str), int(month_str)
        start = _dt.date(year, month, 1)
        end = _dt.date(year + (1 if month == 12 else 0), (month % 12) + 1, 1) - _dt.timedelta(days=1)
    except Exception:
        return None
    return year, month, start, end


def _resolve_receivable_scope(user):
    return resolve_receivable_scope(user.id)


def _serialize_receivable_line(user, line, entry, account, kind, cat_map, tracker, date_parser):
    return serialize_receivable_line(user.id, line, entry, account, kind, cat_map, tracker, date_parser)


def _serialize_manual_receivable(manual, account, kind, cat_map):
    serialized = serialize_manual_receivable(manual, account, kind, cat_map)
    # Preserve local manual id encoding for UI if needed
    serialized["line_id"] = _manual_line_id(manual.id)
    serialized.setdefault("loan_groups", [])
    serialized.setdefault("manual_notes", manual.notes or "")
    return serialized

_BASE_FLOWS = {'loan_provided', 'debt_received'}
_SETTLEMENT_FLOWS = {'loan_repaid', 'debt_paid'}
_MANUAL_LINE_BASE = 10 ** 12


def _is_manual_line_id(line_id):
    try:
        return int(line_id) >= _MANUAL_LINE_BASE
    except Exception:
        return False


def _manual_line_id(manual_id):
    return _MANUAL_LINE_BASE + manual_id


def _manual_id_from_line(line_id):
    return int(line_id) - _MANUAL_LINE_BASE


def _to_decimal(amount):
    if amount is None:
        return Decimal('0')
    if isinstance(amount, Decimal):
        return amount
    try:
        return Decimal(str(amount))
    except Exception:
        return Decimal('0')


def _loan_group_flow(direction, line_dc):
    if direction == 'receivable':
        return 'origin' if (line_dc or '').upper() == 'D' else 'settlement'
    return 'origin' if (line_dc or '').upper() == 'C' else 'settlement'


def _loan_group_status_from_balance(remaining):
    epsilon = Decimal('0.005')
    if remaining > epsilon:
        return 'open'
    if remaining < -epsilon:
        return 'overpaid'
    return 'closed'


def _loan_group_to_dict(group, summary=None):
    payload = {
        'id': group.id,
        'name': group.name,
        'direction': group.direction,
        'counterparty': group.counterparty,
        'currency': group.currency,
        'principal_amount': float(_to_decimal(group.principal_amount)),
        'start_date': group.start_date.isoformat() if isinstance(group.start_date, _dt.date) else None,
        'status': group.status,
        'notes': group.notes or '',
        'created_at': group.created_at.isoformat() if group.created_at else None,
        'updated_at': group.updated_at.isoformat() if group.updated_at else None,
    }
    if summary:
        payload['summary'] = summary
    return payload


def _compute_loan_group_summary(user, group, include_entries=False):
    summary, entries = loan_group_summary(user.id, group)

    def _flt(val):
        return float(Decimal(val)) if val is not None else None

    normalized_summary = {
        'principal': _flt(summary.get('principal')),
        'origin_linked': _flt(summary.get('total_out')),
        'repaid': _flt(summary.get('total_in')),
        'remaining': _flt(summary.get('remaining')),
        'status': summary.get('status'),
        'transactions': len(entries),
    }
    if include_entries:
        norm_entries = []
        for e in entries:
            norm_entries.append({
                'link_id': e.get('id'),
                'line_id': e.get('journal_line_id') or e.get('line_id'),
                'journal_id': e.get('journal_id'),
                'flow': e.get('flow'),
                'description': e.get('description'),
                'date': e.get('date'),
                'linked_amount': _flt(e.get('amount')),
                'currency': e.get('currency'),
                'status': e.get('status'),
                'reference': e.get('reference'),
                'balance_after': _flt(e.get('balance_after')),
            })
        normalized_summary['entries'] = norm_entries
    return normalized_summary, normalized_summary.get('entries', [])


def _flow_for_line(kind, direction):
    direction = (direction or '').upper()
    if kind == 'receivable':
        return 'loan_provided' if direction == 'D' else 'loan_repaid'
    return 'debt_received' if direction == 'C' else 'debt_paid'


def _summarize_linked_row(row):
    if not row:
        return None
    flow = row.get('flow')
    summary = {
        'line_id': row.get('line_id'),
        'type': row.get('type'),
        'flow': row.get('flow'),
        'flow_label': row.get('flow_label'),
        'currency': row.get('currency'),
        'amount': row.get('amount'),
        'date': row.get('date_iso') or row.get('entry_date'),
        'status': row.get('status'),
        'description': row.get('description'),
        'reference': row.get('reference'),
        'contact_name': row.get('contact_name'),
    }
    if flow in _BASE_FLOWS:
        summary['flow_group'] = 'origin'
    elif flow in _SETTLEMENT_FLOWS:
        summary['flow_group'] = 'settlement'
    else:
        summary['flow_group'] = 'other'
    return summary


def _attach_linked_entries(rows, row_map, tracker_map, incoming_map, line_index, line_kind_map, cat_map, scoped_accounts, user, date_parser):
    def ensure_row(line_id):
        cached = row_map.get(line_id)
        if cached:
            return cached
        triple = line_index.get(line_id)
        if not triple:
            return None
        line, entry, account = triple
        kind = line_kind_map.get(line_id)
        if not kind and account is not None:
            if account.id in scoped_accounts['receivable']:
                kind = 'receivable'
            elif account.id in scoped_accounts['debt']:
                kind = 'debt'
        if not kind:
            return None
        tracker = tracker_map.get(line_id)
        generated = _serialize_receivable_line(user, line, entry, account, kind, cat_map, tracker, date_parser)
        row_map[line_id] = generated
        return generated

    for row in rows:
        linked = []
        seen = set()
        tracker = tracker_map.get(row['line_id'])
        if tracker and tracker.linked_line_id:
            target_row = ensure_row(tracker.linked_line_id)
            summary = _summarize_linked_row(target_row)
            if summary:
                summary['link_role'] = 'outgoing'
                summary['link_kind'] = tracker.link_kind or None
                seen.add(summary['line_id'])
                linked.append(summary)
        for child_id in incoming_map.get(row['line_id'], []):
            if child_id in seen:
                continue
            child_row = ensure_row(child_id)
            summary = _summarize_linked_row(child_row)
            if summary:
                child_tracker = tracker_map.get(child_id)
                summary['link_role'] = 'incoming'
                summary['link_kind'] = child_tracker.link_kind if child_tracker else None
                seen.add(summary['line_id'])
                linked.append(summary)

        def sort_key(item):
            group_weight = {'origin': 0, 'settlement': 1}.get(item.get('flow_group'), 2)
            return (group_weight, item.get('date') or '', item.get('line_id') or 0)

        linked.sort(key=sort_key)
        row['linked_entries'] = linked
        row['linked_summary'] = linked[0] if linked else None


def _accumulate_contact_group(contact_groups, row):
    key = _normalized_name(row.get('contact_name'))
    if not key:
        return
    grp = contact_groups.setdefault(key, {
        'contact_name': row.get('contact_name'),
        'entries': 0,
        'currencies': {},
        'flow_totals': {'loan_provided': 0.0, 'loan_repaid': 0.0, 'debt_received': 0.0, 'debt_paid': 0.0}
    })
    grp['contact_name'] = row.get('contact_name') or grp['contact_name']
    grp['entries'] += 1
    flow = row.get('flow')
    amount_val = float(row.get('amount') or 0.0)
    if flow in grp['flow_totals']:
        grp['flow_totals'][flow] += amount_val
    ccy = (row.get('currency') or 'KRW').upper()
    stats = grp['currencies'].setdefault(ccy, {
        'currency': ccy,
        'loan_provided': 0.0,
        'loan_repaid': 0.0,
        'debt_received': 0.0,
        'debt_paid': 0.0
    })
    if flow in stats:
        stats[flow] += amount_val


@accounting_bp.route('/accounting', methods=['GET'])
def accounting():
    from finance_app import (
        Account,
        AccountCategory,
        AccountOpeningBalance,
        Transaction,
        TrialBalanceSetting,
        _get_csrf_token,
        current_user,
        db,
    )
    user = current_user()
    if not user:
        flash('Login required.')
        return redirect(url_for('auth_bp.login'))
    # Optional: prepopulate accounts from user's transactions if none exist yet
    has_any_acc = Account.query.filter_by(user_id=user.id).first()
    if not has_any_acc:
        user_txs = Transaction.query.filter_by(user_id=user.id).all()
        names = []
        for t in user_txs:
            if t.debit_account and t.debit_account.strip():
                names.append(t.debit_account.strip())
            if t.credit_account and t.credit_account.strip():
                names.append(t.credit_account.strip())
        seen = set()
        ordered = [x for x in names if not (x in seen or seen.add(x))]
        for i, name in enumerate(ordered):
            db.session.add(Account(user_id=user.id, name=name, side='both', order=i))
        if ordered:
            db.session.commit()
    # Fetch all categories and accounts for this user
    categories = AccountCategory.query.filter_by(user_id=user.id).order_by(AccountCategory.order.asc(), AccountCategory.id.asc()).all()
    # Unassigned accounts
    unassigned = Account.query.filter_by(user_id=user.id, category_id=None, active=True).order_by(Account.order.asc(), Account.id.asc()).all()
    # Map accounts by category id for efficient rendering
    accounts_by_category = {}
    for cat in categories:
        accounts_by_category[cat.id] = Account.query.filter_by(user_id=user.id, category_id=cat.id, active=True).order_by(Account.order.asc(), Account.id.asc()).all()
    # All accounts for accounts view (alphabetical, deduped by lower(name))
    all_q = Account.query.filter_by(user_id=user.id, active=True).order_by(Account.name.asc(), Account.id.asc()).all()
    dedup = {}
    for a in all_q:
        key = (a.name or '').strip().lower()
        if key and key not in dedup:
            dedup[key] = a
    all_accounts = sorted(dedup.values(), key=lambda x: (x.name or '').lower())
    receivable_accounts = []
    debt_accounts = []
    try:
        _, scoped_accounts, _ = _resolve_receivable_scope(user)
        receivable_ids = list(scoped_accounts.get('receivable') or [])
        debt_ids = list(scoped_accounts.get('debt') or [])
        if receivable_ids:
            receivable_accounts = Account.query.filter(Account.id.in_(receivable_ids)).order_by(Account.name.asc()).all()
        if debt_ids:
            debt_accounts = Account.query.filter(Account.id.in_(debt_ids)).order_by(Account.name.asc()).all()
    except Exception:
        receivable_accounts = []
        debt_accounts = []
    # Opening balances for this user (map account_id -> amount)
    ob_rows = AccountOpeningBalance.query.filter_by(user_id=user.id).all()
    opening_balances = { r.account_id: (r.amount or 0.0) for r in ob_rows }
    opening_balance_dates = { r.account_id: (r.as_of_date.isoformat() if r.as_of_date else None) for r in ob_rows }
    tbs = TrialBalanceSetting.query.filter_by(user_id=user.id).first()
    tb_first_month = tbs.first_month if tbs else None
    tb_initialized_on = tbs.initialized_on if tbs else None
    csrf_token = _get_csrf_token()
    return render_template('accounting.html', user=user,
                           categories=categories,
                           accounts_by_category=accounts_by_category,
                           unassigned=unassigned,
                           all_accounts=all_accounts,
                           receivable_accounts=receivable_accounts,
                           debt_accounts=debt_accounts,
                           csrf_token=csrf_token,
                           opening_balances=opening_balances,
                           opening_balance_dates=opening_balance_dates,
                           tb_first_month=tb_first_month,
                           tb_initialized_on=tb_initialized_on)


def _check_csrf():
    token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
    return token and token == session.get('csrf_token')


def _guard_schema_caps(required_caps, *, user_id=None):
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


def _format_journal_entries(entries):
    """Serialize JournalEntry rows with related lines for JSON responses."""
    if not entries:
        return []
    try:
        from finance_app import Account, JournalLine, _parse_date_tuple
    except Exception:
        return []
    from collections import defaultdict

    entry_ids = [e.id for e in entries]
    lines = JournalLine.query.filter(JournalLine.journal_id.in_(entry_ids))\
        .order_by(JournalLine.journal_id.asc(), JournalLine.line_no.asc(), JournalLine.id.asc())\
        .all()
    acc_ids = {ln.account_id for ln in lines}
    acc_map = {}
    if acc_ids:
        rows = Account.query.filter(Account.id.in_(acc_ids)).all()
        for row in rows:
            acc_map[row.id] = row
    by_entry = defaultdict(list)
    for ln in lines:
        by_entry[ln.journal_id].append(ln)

    formatted = []
    for entry in entries:
        iso = ''
        try:
            if entry.date_parsed:
                iso = entry.date_parsed.strftime('%Y-%m-%d')
            else:
                y, m, d = _parse_date_tuple(entry.date or '')
                if y and m and d:
                    iso = f"{y:04d}-{m:02d}-{d:02d}"
        except Exception:
            iso = ''
        debit_total = 0.0
        credit_total = 0.0
        lines_payload = []
        for ln in by_entry.get(entry.id, []):
            amt = float(ln.amount_base or 0.0)
            if (ln.dc or '').upper() == 'D':
                debit_total += amt
            else:
                credit_total += amt
            acc = acc_map.get(ln.account_id)
            lines_payload.append({
                'id': ln.id,
                'account_id': ln.account_id,
                'account_name': acc.name if acc else '',
                'account_code': acc.code if acc else None,
                'dc': (ln.dc or '').upper(),
                'amount': amt,
                'memo': ln.memo or '',
                'line_no': ln.line_no or 0
            })
        formatted.append({
            'id': entry.id,
            'date': entry.date,
            'date_iso': iso,
            'description': entry.description,
            'reference': entry.reference,
            'line_count': len(lines_payload),
            'debit_total': debit_total,
            'credit_total': credit_total,
            'lines': lines_payload
        })
    return formatted


@accounting_bp.route('/accounting/codes/refresh', methods=['POST'])
def refresh_codes():
    from finance_app import assign_codes_for_user, current_user
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    if not user.is_admin:
        return ("Forbidden", 403)
    try:
        assign_codes_for_user(user.id, refresh=True)
        return {'ok': True}
    except Exception:
        return {'ok': False}, 500


@accounting_bp.route('/accounting/category/add', methods=['POST'])
def add_account_category():
    from finance_app import current_user
    from finance_app.services.account_service import add_category
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    name = (request.form.get('name') or (request.json.get('name') if request.is_json else '')).strip()
    cat, err = add_category(user.id, name)
    if err:
        if request.is_json:
            return {'ok': False, 'error': err}, 400
        flash('Invalid category inputs.')
        return redirect(url_for('accounting_bp.accounting'))
    if request.is_json:
        return {'ok': True, 'id': cat.id}
    return redirect(url_for('accounting_bp.accounting'))


@accounting_bp.route('/accounting/account/add', methods=['POST'])
def add_account():
    from finance_app import current_user
    from finance_app.services.account_service import create_account
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    data = request.get_json() if request.is_json else request.form
    name = (data.get('name') or '').strip()
    code = (data.get('code') or '').strip()
    category_id = data.get('category_id')
    category_id = int(category_id) if category_id not in (None, '', 'null') else None
    acc, err = create_account(user.id, name=name, code=code, category_id=category_id)
    if err:
        if request.is_json:
            return {'ok': False, 'error': err}, 400
        flash('Invalid account inputs.' if err == "Invalid inputs" else err)
        return redirect(url_for('accounting_bp.accounting'))
    if request.is_json:
        return {'ok': True, 'id': acc.id}
    return redirect(url_for('accounting_bp.accounting'))


@accounting_bp.route('/accounting/account/move', methods=['POST'])
def move_account():
    from finance_app import current_user
    from finance_app.services.account_service import move_account_to_category
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    data = request.get_json(force=True)
    account_id = int(data.get('account_id'))
    to_category_id = data.get('category_id')
    to_order = data.get('order')  # kept for compatibility
    to_category_id = int(to_category_id) if to_category_id not in (None, '', 'null') else None
    result = move_account_to_category(user.id, account_id, to_category_id, to_order)
    status = 200 if result.get("ok") else 400
    return result, status


@accounting_bp.route('/accounting/category/reorder', methods=['POST'])
def reorder_categories():
    from finance_app import AccountCategory, current_user, db
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    data = request.get_json(force=True)
    ids = data.get('ordered_ids') or []
    for idx, cid in enumerate(ids):
        cat = AccountCategory.query.get(int(cid))
        if cat and cat.user_id == user.id:
            cat.order = idx
    db.session.commit()
    return {'ok': True}


@accounting_bp.route('/accounting/category/delete/<int:cat_id>', methods=['POST'])
def delete_category(cat_id):
    from finance_app import Account, AccountCategory, current_user, db
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        flash('Login required.')
        return redirect(url_for('auth_bp.login'))
    cat = AccountCategory.query.get_or_404(cat_id)
    if cat.user_id != user.id:
        flash('Unauthorized.')
        return redirect(url_for('accounting_bp.accounting'))
    Account.query.filter_by(user_id=user.id, category_id=cat.id).update({Account.category_id: None})
    db.session.delete(cat)
    db.session.commit()
    if request.is_json:
        return {'ok': True}
    flash('Category deleted.')
    return redirect(url_for('accounting_bp.accounting'))


@accounting_bp.route('/accounting/account/delete/<int:acc_id>', methods=['POST'])
def delete_account(acc_id):
    from finance_app import Account, AccountOpeningBalance, Transaction, current_user, db
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        flash('Login required.')
        return redirect(url_for('auth_bp.login'))
    acc = Account.query.get_or_404(acc_id)
    if acc.user_id != user.id:
        flash('Unauthorized.')
        return redirect(url_for('accounting_bp.accounting'))
    # Null-out transaction FK references to preserve history but remove linkage
    try:
        Transaction.query.filter_by(user_id=user.id, debit_account_id=acc.id).update({Transaction.debit_account_id: None})
        Transaction.query.filter_by(user_id=user.id, credit_account_id=acc.id).update({Transaction.credit_account_id: None})
    except Exception:
        pass
    # Delete any stored opening balance rows for this account
    try:
        AccountOpeningBalance.query.filter_by(user_id=user.id, account_id=acc.id).delete()
    except Exception:
        pass
    db.session.delete(acc)
    db.session.commit()
    if request.is_json:
        return {'ok': True}
    flash('Account deleted.')
    return redirect(url_for('accounting_bp.accounting'))


@accounting_bp.route('/accounting/account/bulk_currency', methods=['POST'])
def bulk_set_currency():
    """Bulk-assign currency_code for selected accounts and auto-refresh codes.
    Body JSON: { account_ids: [int], currency_code: 'KRW' }
    """
    from finance_app import Account, current_user, db
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    data = request.get_json(silent=True) or {}
    ids = data.get('account_ids') or []
    ccy = (data.get('currency_code') or '').strip().upper()
    if not isinstance(ids, list) or not ids:
        return {'ok': False, 'error': 'account_ids required'}, 400
    if not ccy or len(ccy) not in (3,4):
        return {'ok': False, 'error': 'currency_code must be a valid code (e.g., KRW, MYR, CNY)'}, 400
    q = Account.query.filter(Account.user_id == user.id, Account.id.in_(ids))
    updated = 0
    for acc in q.all():
        acc.currency_code = ccy
        updated += 1
    db.session.commit()
    # Recompute codes to reflect new currency prefix
    try:
        import sys
        app_module = sys.modules.get('app') or sys.modules.get('__main__')
        assign_fn = getattr(app_module, 'assign_codes_for_user', None)
        if callable(assign_fn):
            assign_fn(user.id, refresh=True)
    except Exception:
        pass
    return {'ok': True, 'updated': updated, 'currency_code': ccy}


@accounting_bp.route('/accounting/category/rename/<int:cat_id>', methods=['POST'])
def rename_category(cat_id):
    from finance_app import AccountCategory, current_user, db
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    cat = AccountCategory.query.get_or_404(cat_id)
    if cat.user_id != user.id:
        return ("Forbidden", 403)
    data = request.get_json() if request.is_json else request.form
    new_name = (data.get('name') or '').strip()
    if not new_name:
        if request.is_json:
            return {'ok': False, 'error': 'Name required'}, 400
        flash('Folder name is required.')
        return redirect(url_for('accounting_bp.accounting'))
    cat.name = new_name
    db.session.commit()
    if request.is_json:
        return {'ok': True, 'id': cat.id, 'name': cat.name}
    return redirect(url_for('accounting_bp.accounting'))


@accounting_bp.route('/accounting/account/rename/<int:acc_id>', methods=['POST'])
def rename_account(acc_id):
    from finance_app import Account, Transaction, _account_sort_key, current_user, db
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    acc = Account.query.get_or_404(acc_id)
    if acc.user_id != user.id:
        return ("Forbidden", 403)
    data = request.get_json() if request.is_json else request.form
    new_name = (data.get('name') or '').strip()
    if not new_name:
        if request.is_json:
            return {'ok': False, 'error': 'Name required'}, 400
        flash('Account name is required.')
        return redirect(url_for('accounting_bp.accounting'))
    old_name = acc.name or ''
    existing = Account.query.filter(Account.user_id == user.id, Account.id != acc.id, Account.active == True).filter(Account.name.ilike(new_name)).order_by(Account.id.asc()).first()
    acc.name = new_name
    db.session.flush()
    Transaction.query.filter_by(user_id=user.id, debit_account=old_name).update({Transaction.debit_account: new_name})
    Transaction.query.filter_by(user_id=user.id, credit_account=old_name).update({Transaction.credit_account: new_name})
    if existing:
        db.session.delete(existing)
    siblings = Account.query.filter_by(user_id=user.id, category_id=acc.category_id, active=True).all()
    siblings.sort(key=_account_sort_key)
    for i, s in enumerate(siblings):
        s.order = i
    db.session.commit()
    if request.is_json:
        return {'ok': True, 'id': acc.id, 'name': acc.name}
    return redirect(url_for('accounting_bp.accounting'))


@accounting_bp.route('/accounting/account/code/<int:acc_id>', methods=['POST'])
def update_account_code(acc_id):
    from finance_app import Account, _account_sort_key, current_user, db
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    acc = Account.query.get_or_404(acc_id)
    if acc.user_id != user.id:
        return ("Forbidden", 403)
    data = request.get_json() if request.is_json else request.form
    new_code = (data.get('code') or '').strip()
    acc.code = new_code or None
    # Resort siblings consistently after code change
    siblings = Account.query.filter_by(user_id=user.id, category_id=acc.category_id, active=True).all()
    siblings.sort(key=_account_sort_key)
    for i, s in enumerate(siblings):
        s.order = i
    db.session.commit()
    return {'ok': True, 'id': acc.id, 'code': acc.code or ''}


@accounting_bp.route('/accounting/category/set_group', methods=['POST'])
def set_category_group():
    """Assign or clear Trial Balance group for a folder (AccountCategory).
    JSON: { category_id: int, tb_group: 'asset'|'liability'|'equity'|'expense'|'income'|null }
    """
    from finance_app import AccountCategory, current_user, db
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    data = request.get_json(force=True)
    cat_id = int(data.get('category_id', 0) or 0)
    tb_group = data.get('tb_group')
    # Normalize
    if isinstance(tb_group, str):
        tb_group = tb_group.strip().lower() or None
    if tb_group not in (None, 'asset', 'liability', 'equity', 'expense', 'income'):
        return {'ok': False, 'error': 'Invalid group'}, 400
    cat = AccountCategory.query.get_or_404(cat_id)
    if cat.user_id != user.id:
        return ("Forbidden", 403)
    cat.tb_group = tb_group
    db.session.commit()
    return {'ok': True, 'id': cat.id, 'tb_group': cat.tb_group}


@accounting_bp.route('/accounting/tb/opening_balance', methods=['POST'])
def set_opening_balance():
    from finance_app import Account, AccountOpeningBalance, current_user, db
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    data = request.get_json(force=True)
    try:
        account_id = int(data.get('account_id'))
    except Exception:
        return {'ok': False, 'error': 'Invalid account id'}, 400
    try:
        amount = float(data.get('amount') or 0.0)
    except Exception:
        return {'ok': False, 'error': 'Invalid amount'}, 400
    as_of_date = data.get('as_of_date') or None
    # Validate ownership
    acc = Account.query.get_or_404(account_id)
    if acc.user_id != user.id:
        return ("Forbidden", 403)
    # Upsert
    row = AccountOpeningBalance.query.filter_by(user_id=user.id, account_id=account_id).first()
    from datetime import datetime as _dt
    asof = None
    if as_of_date:
        try:
            # Accept YYYY-MM-DD
            asof = _dt.strptime(as_of_date, '%Y-%m-%d').date()
        except Exception:
            asof = None
    if not row:
        row = AccountOpeningBalance(user_id=user.id, account_id=account_id, amount=amount, as_of_date=asof)
        db.session.add(row)
    else:
        row.amount = amount
        row.as_of_date = asof
    db.session.commit()
    return {'ok': True, 'account_id': account_id, 'amount': amount}


@accounting_bp.route('/accounting/tb/initialize', methods=['POST'])
def set_tb_initialization():
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    data = request.get_json(force=True)
    date_raw = (data.get('initialized_on') or '').strip()
    result = tb_set_initialization(user.id, date_raw)
    status = 200 if result.get("ok") else 400
    return result, status


@accounting_bp.route('/accounting/tb/reset', methods=['POST'])
@require_admin
def reset_tb_data():
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    ok_guard, payload, status = _guard_schema_caps(["tb_snapshot", "admin_audit"], user_id=user.id)
    if not ok_guard:
        return payload, status
    data = request.get_json(silent=True) if request.is_json else request.form
    confirm = (data.get("confirm_phrase") or "").strip().upper() if data else ""
    if confirm != "RESET TB":
        return {"ok": False, "error": "confirm_phrase must equal 'RESET TB'"}, 400
    confirm_at_raw = (data.get("confirm_at_ms") or "").strip() if data else ""
    if not confirm_at_raw:
        return {"ok": False, "error": "confirm_at_ms is required for cooldown confirmation."}, 400
    try:
        confirm_at_ms = int(confirm_at_raw)
    except Exception:
        return {"ok": False, "error": "Invalid confirm_at_ms."}, 400
    try:
        cooldown_seconds = max(0, int(current_app.config.get("ADMIN_ACTION_COOLDOWN_SECONDS", 5)))
    except Exception:
        cooldown_seconds = 5
    now_ms = int(_dt.datetime.now(_dt.timezone.utc).timestamp() * 1000)
    age_ms = now_ms - confirm_at_ms
    if age_ms < cooldown_seconds * 1000:
        return {"ok": False, "error": f"Please wait {cooldown_seconds} seconds before resetting TB."}, 400
    if age_ms > 10 * 60 * 1000:
        return {"ok": False, "error": "Confirmation expired. Please confirm reset again."}, 400
    reason = (data.get("reason") or "").strip() if data else ""
    snap = create_tb_snapshot(user.id, reason=reason, created_by_admin_id=user.id if getattr(user, "is_admin", False) else None)
    if not snap.get("ok"):
        return snap, 400
    result = tb_reset_data(user.id)
    try:
        from finance_app.models.accounting_models import AdminActionAudit

        db.session.add(
            AdminActionAudit(
                actor_user_id=user.id,
                action="tb_reset",
                target_type="user",
                target_id=str(user.id),
                status="ok" if isinstance(result, dict) and result.get("ok") else "failed",
                reason=(reason[:255] if reason else None),
                details={
                    "snapshot_id": snap.get("snapshot_id"),
                    "db_copy_path": snap.get("db_copy_path"),
                    "sha256": snap.get("sha256"),
                },
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
    if isinstance(result, dict):
        result["snapshot"] = {
            "snapshot_id": snap.get("snapshot_id"),
            "db_copy_path": snap.get("db_copy_path"),
            "sha256": snap.get("sha256"),
        }
    return result


@accounting_bp.route('/accounting/account/bulk_move', methods=['POST'])
def bulk_move_accounts():
    from finance_app import current_user
    from finance_app.services.account_service import bulk_move_accounts as bulk_move_service
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    data = request.get_json(force=True)
    ids = data.get('account_ids') or []
    to_category_id = data.get('category_id')
    to_category_id = int(to_category_id) if to_category_id not in (None, '', 'null') else None
    result = bulk_move_service(user.id, [int(i) for i in ids], to_category_id)
    status = 200 if result.get("ok") else 400
    return result, status


@accounting_bp.route('/accounting/account/bulk_unassign', methods=['POST'])
def bulk_unassign_accounts():
    from finance_app import current_user
    from finance_app.services.account_service import bulk_unassign_accounts as bulk_unassign_service
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    data = request.get_json(force=True)
    ids = data.get('account_ids') or []
    result = bulk_unassign_service(user.id, [int(i) for i in ids])
    status = 200 if result.get("ok") else 400
    return result, status


@accounting_bp.route('/accounting/receivables/data', methods=['GET'])
def receivables_data():
    from finance_app import (
        Account,
        JournalEntry,
        JournalLine,
        LoanGroup,
        ReceivableManualEntry,
        ReceivableTracker,
        TrialBalanceSetting,
        _parse_date_tuple,
        current_user,
        db,
    )
    from sqlalchemy import and_, or_

    user = current_user()
    if not user:
        return ("Unauthorized", 401)

    scoped_cats, scoped_accounts, cat_map = _resolve_receivable_scope(user)
    tbs = TrialBalanceSetting.query.filter_by(user_id=user.id).first()
    init_cutoff_date = tbs.initialized_on if tbs and tbs.initialized_on else None
    init_cutoff_str = None
    if init_cutoff_date:
        init_cutoff_str = f"{init_cutoff_date.year}/{str(init_cutoff_date.month).zfill(2)}/{str(init_cutoff_date.day).zfill(2)}"
    account_ids = set().union(scoped_accounts['receivable'], scoped_accounts['debt'])

    if not account_ids:
        empty_payload = {
            'ok': True,
            'rows': [],
            'saved_rows': [],
            'unsaved_rows': [],
            'contact_groups': [],
            'currencies': [],
            'summary': {'receivable': 0, 'debt': 0, 'saved': 0, 'unsaved': 0},
            'init_cutoff': init_cutoff_date.isoformat() if init_cutoff_date else None
        }
        return empty_payload

    type_filter = (request.args.get('type') or '').strip().lower()
    currency_filter = (request.args.get('currency') or '').strip().upper()

    query = (db.session.query(JournalLine, JournalEntry, Account)
             .join(JournalEntry, JournalLine.journal_id == JournalEntry.id)
             .join(Account, JournalLine.account_id == Account.id)
             .filter(JournalEntry.user_id == user.id)
             .filter(JournalLine.account_id.in_(account_ids)))

    if init_cutoff_date:
        query = query.filter(
            or_(
                JournalEntry.date_parsed >= init_cutoff_date,
                and_(JournalEntry.date_parsed == None, JournalEntry.date >= init_cutoff_str)
            )
        )

    query = query.order_by(JournalEntry.date_parsed.desc().nullslast(),
                           JournalEntry.date.desc().nullslast(),
                           JournalLine.id.desc())

    records = query.all()
    if not records:
        return {
            'ok': True,
            'rows': [],
            'saved_rows': [],
            'unsaved_rows': [],
            'contact_groups': [],
            'currencies': [],
            'summary': {'receivable': 0, 'debt': 0, 'saved': 0, 'unsaved': 0},
            'init_cutoff': init_cutoff_date.isoformat() if init_cutoff_date else None
        }

    line_index = {line.id: (line, entry, account) for line, entry, account in records}
    line_ids = list(line_index.keys())
    tracker_rows = ReceivableTracker.query.filter(
        ReceivableTracker.user_id == user.id,
        ReceivableTracker.journal_line_id.in_(line_ids)
    ).all()
    tracker_map = {t.journal_line_id: t for t in tracker_rows}
    incoming_map = defaultdict(list)
    for t in tracker_rows:
        if t.linked_line_id:
            incoming_map[t.linked_line_id].append(t.journal_line_id)
    line_kind_map = {}

    rows = []
    saved_rows = []
    unsaved_rows = []
    contact_groups = {}
    currencies = set()
    counts = {'receivable': 0, 'debt': 0}

    for line, entry, account in records:
        if account.id in scoped_accounts['receivable']:
            kind = 'receivable'
        elif account.id in scoped_accounts['debt']:
            kind = 'debt'
        else:
            continue
        line_kind_map[line.id] = kind
        tracker = tracker_map.get(line.id)
        if tracker and tracker.ignored:
            continue
        row = _serialize_receivable_line(user, line, entry, account, kind, cat_map, tracker, _parse_date_tuple)
        if type_filter and row['type'] != type_filter:
            continue
        if currency_filter and row['currency'].upper() != currency_filter:
            continue
        rows.append(row)
        currencies.add(row['currency'])
        counts[kind] += 1

        if row.get('is_saved'):
            saved_rows.append(row)
            _accumulate_contact_group(contact_groups, row)
        else:
            unsaved_rows.append(row)

    manual_entries = ReceivableManualEntry.query.filter_by(user_id=user.id).all()
    if manual_entries:
        manual_account_ids = {m.account_id for m in manual_entries if m.account_id}
        manual_acc_map = {}
        if manual_account_ids:
            manual_accounts = Account.query.filter(Account.id.in_(manual_account_ids)).all()
            for acc in manual_accounts:
                manual_acc_map[acc.id] = acc
        for manual in manual_entries:
            account = manual_acc_map.get(manual.account_id)
            if not account:
                continue
            kind = manual.category if manual.category in ('receivable', 'debt') else None
            if not kind:
                continue
            scoped_set = scoped_accounts.get(kind, set())
            if account.id not in scoped_set:
                continue
            row = _serialize_manual_receivable(manual, account, kind, cat_map)
            if type_filter and row['type'] != type_filter:
                continue
            if currency_filter and row['currency'].upper() != currency_filter:
                continue
            rows.append(row)
            currencies.add(row['currency'])
            counts[kind] += 1
            if row.get('is_saved'):
                saved_rows.append(row)
                _accumulate_contact_group(contact_groups, row)
            else:
                unsaved_rows.append(row)

    def sort_key(row_item):
        date_val = row_item.get('date_iso') or row_item.get('entry_date') or ''
        return (date_val, row_item.get('line_id') or 0)

    rows.sort(key=sort_key, reverse=True)
    saved_rows.sort(key=sort_key, reverse=True)
    unsaved_rows.sort(key=sort_key, reverse=True)

    contact_group_list = []
    for key, grp in contact_groups.items():
        currencies_list = []
        for ccy, stats in grp['currencies'].items():
            receivable_origin = stats['loan_provided']
            receivable_settlement = stats['loan_repaid']
            debt_origin = stats['debt_received']
            debt_settlement = stats['debt_paid']
            currencies_list.append({
                'currency': ccy,
                'receivable_origin': round(receivable_origin, 2),
                'receivable_settlement': round(receivable_settlement, 2),
                'receivable_net': round(receivable_origin - receivable_settlement, 2),
                'debt_origin': round(debt_origin, 2),
                'debt_settlement': round(debt_settlement, 2),
                'debt_net': round(debt_origin - debt_settlement, 2),
                'flows': {
                    'loan_provided': round(stats['loan_provided'], 2),
                    'loan_repaid': round(stats['loan_repaid'], 2),
                    'debt_received': round(stats['debt_received'], 2),
                    'debt_paid': round(stats['debt_paid'], 2)
                }
            })
        currencies_list.sort(key=lambda it: it['currency'])
        remaining_total = (grp['flow_totals']['loan_provided'] - grp['flow_totals']['loan_repaid']) + (grp['flow_totals']['debt_received'] - grp['flow_totals']['debt_paid'])
        open_items = sum(1 for cur in currencies_list if abs(cur['receivable_net']) > 0.005 or abs(cur['debt_net']) > 0.005)
        contact_group_list.append({
            'key': key,
            'contact_name': grp['contact_name'],
            'entries': grp['entries'],
            'open_items': open_items,
            'status': 'PAID' if abs(remaining_total) <= 0.005 else 'OPEN',
            'currencies': currencies_list,
            'flow_totals': {k: round(v, 2) for k, v in grp['flow_totals'].items()},
            'remaining_total': round(remaining_total, 2)
        })

    contact_group_list.sort(key=lambda it: (it['contact_name'] or '').lower())

    row_map = {r['line_id']: r for r in rows}
    _attach_linked_entries(rows, row_map, tracker_map, incoming_map, line_index, line_kind_map, cat_map, scoped_accounts, user, _parse_date_tuple)

    loan_links_map = defaultdict(list)
    if rows:
        line_ids = [r['line_id'] for r in rows]
        link_rows = LoanGroupLink.query.filter(LoanGroupLink.user_id == user.id, LoanGroupLink.journal_line_id.in_(line_ids)).all()
        if link_rows:
            group_ids = {ln.loan_group_id for ln in link_rows}
            groups = LoanGroup.query.filter(LoanGroup.user_id == user.id, LoanGroup.id.in_(group_ids)).all()
            group_map = {g.id: g for g in groups}
            summary_map = {}
            for g in groups:
                summary, _ = _compute_loan_group_summary(user, g, include_entries=False)
                summary_map[g.id] = summary
            for link in link_rows:
                group = group_map.get(link.loan_group_id)
                if not group:
                    continue
                summary = summary_map.get(group.id, {})
                loan_links_map[link.journal_line_id].append({
                    'link_id': link.id,
                    'loan_group_id': group.id,
                    'name': group.name,
                    'status': group.status,
                    'direction': group.direction,
                    'counterparty': group.counterparty,
                    'currency': group.currency,
                    'linked_amount': float(_to_decimal(link.linked_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                    'summary': summary
                })
    for row in rows:
        row['loan_groups'] = loan_links_map.get(row['line_id'], [])

    summary = {
        'receivable': counts.get('receivable', 0),
        'debt': counts.get('debt', 0),
        'saved': len(saved_rows),
        'unsaved': len(unsaved_rows)
    }

    return {
        'ok': True,
        'rows': rows,
        'saved_rows': saved_rows,
        'unsaved_rows': unsaved_rows,
        'contact_groups': contact_group_list,
        'currencies': sorted(currencies),
        'summary': summary,
        'init_cutoff': init_cutoff_date.isoformat() if init_cutoff_date else None
    }


@accounting_bp.route('/accounting/receivables/save', methods=['POST'])
def receivables_save():
    from finance_app import (
        Account,
        JournalEntry,
        JournalLine,
        ReceivableManualEntry,
        ReceivableTracker,
        _parse_date_tuple,
        current_user,
        db,
    )

    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)

    user = current_user()
    if not user:
        return ("Unauthorized", 401)

    data = request.get_json(force=True) or {}
    line_id_raw = data.get('line_id')
    try:
        line_id = int(line_id_raw or 0)
    except Exception:
        line_id = 0
    if not line_id:
        return {'ok': False, 'error': 'line_id required'}, 400

    if _is_manual_line_id(line_id):
        manual_id = _manual_id_from_line(line_id)
        manual = ReceivableManualEntry.query.filter_by(id=manual_id, user_id=user.id).first()
        if not manual:
            return {'ok': False, 'error': 'Manual receivable not found'}, 404
        scoped_cats, scoped_accounts, cat_map = _resolve_receivable_scope(user)
        account = Account.query.filter_by(id=manual.account_id, user_id=user.id, active=True).first()
        if not account:
            return {'ok': False, 'error': 'Account not found'}, 404
        kind = manual.category if manual.category in ('receivable', 'debt') else 'receivable'
        currency = (data.get('currency') or manual.currency_code or account.currency_code or 'KRW').strip().upper() or 'KRW'
        txn_value = data.get('transaction_value')
        if txn_value in (None, ''):
            txn_value = manual.transaction_value or manual.amount
        txn_value = _coerce_number(txn_value)
        due_date = _parse_receivable_date(data.get('due_date'), _parse_date_tuple)
        payment_dates_in = data.get('payment_dates') or []
        if isinstance(payment_dates_in, str):
            payment_dates_in = [payment_dates_in]
        normalized_dates = []
        for item in payment_dates_in:
            dt = _parse_receivable_date(item, _parse_date_tuple)
            if dt:
                normalized_dates.append(dt.isoformat())
        manual.contact_name = (data.get('contact_name') or '').strip()
        manual.transaction_value = txn_value
        manual.currency_code = currency
        manual.due_date = due_date
        manual.payment_dates = json.dumps(normalized_dates)
        db.session.commit()
        row = _serialize_manual_receivable(manual, account, kind, cat_map)
        return {'ok': True, 'row': row}

    record = (db.session.query(JournalLine, JournalEntry, Account)
              .join(JournalEntry, JournalLine.journal_id == JournalEntry.id)
              .join(Account, JournalLine.account_id == Account.id)
              .filter(JournalLine.id == line_id, JournalEntry.user_id == user.id)
              .first())

    if not record:
        return {'ok': False, 'error': 'Journal line not found'}, 404

    line, entry, account = record
    scoped_cats, scoped_accounts, cat_map = _resolve_receivable_scope(user)
    kind = None
    if account.id in scoped_accounts['receivable']:
        kind = 'receivable'
    elif account.id in scoped_accounts['debt']:
        kind = 'debt'
    if not kind:
        return {'ok': False, 'error': 'Account is not classified as receivable or short-term debt'}, 400

    tracker = ReceivableTracker.query.filter_by(user_id=user.id, journal_line_id=line.id).first()
    if not tracker:
        tracker = ReceivableTracker(user_id=user.id, journal_id=line.journal_id, journal_line_id=line.id, account_id=account.id, category=kind)
        db.session.add(tracker)

    tracker.category = kind
    tracker.journal_id = line.journal_id
    tracker.account_id = account.id
    tracker.contact_name = (data.get('contact_name') or '').strip()

    txn_value = data.get('transaction_value')
    if txn_value in (None, ''):
        serialized = _serialize_receivable_line(user, line, entry, account, kind, cat_map, tracker, _parse_date_tuple)
        txn_value = serialized.get('default_transaction_value', 0.0)
    txn_value = _coerce_number(txn_value)
    tracker.transaction_value = txn_value

    currency = (data.get('currency') or data.get('currency_code') or line.currency_code or account.currency_code or 'KRW').strip().upper()
    tracker.currency_code = currency or 'KRW'

    due_date = _parse_receivable_date(data.get('due_date'), _parse_date_tuple)
    tracker.due_date = due_date

    payment_dates_in = data.get('payment_dates') or []
    if isinstance(payment_dates_in, str):
        payment_dates_in = [payment_dates_in]
    normalized_dates = []
    for item in payment_dates_in:
        dt = _parse_receivable_date(item, _parse_date_tuple)
        if dt:
            normalized_dates.append(dt.isoformat())
    tracker.payment_dates = json.dumps(normalized_dates)

    tracker.amount_paid = None
    tracker.remaining_amount = None
    tracker.status = 'UNPAID'

    tracker.notes = (data.get('notes') or '').strip()

    db.session.commit()

    tracker = ReceivableTracker.query.filter_by(user_id=user.id, journal_line_id=line.id).first()
    row = _serialize_receivable_line(user, line, entry, account, kind, cat_map, tracker, _parse_date_tuple)

    return {'ok': True, 'row': row}


@accounting_bp.route('/accounting/receivables/link', methods=['POST'])
def receivables_link():
    from finance_app import Account, JournalEntry, JournalLine, current_user, db

    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)

    user = current_user()
    if not user:
        return ("Unauthorized", 401)

    data = request.get_json(force=True) or {}
    line_id_raw = data.get('line_id')
    try:
        line_id = int(line_id_raw or 0)
    except Exception:
        line_id = 0
    linked_line_id = data.get('linked_line_id')
    if linked_line_id not in (None, '', 'null'):
        try:
            linked_line_id = int(linked_line_id)
        except Exception:
            return {'ok': False, 'error': 'linked_line_id invalid'}, 400
    else:
        linked_line_id = None
    link_kind = (data.get('link_kind') or '').strip().lower() or None
    action = (data.get('action') or 'set').strip().lower()
    if action not in ('set', 'add', 'remove', 'clear'):
        action = 'set'

    if not line_id:
        return {'ok': False, 'error': 'line_id required'}, 400
    if linked_line_id is not None and linked_line_id == line_id:
        return {'ok': False, 'error': 'Cannot link a transaction to itself'}, 400
    if _is_manual_line_id(line_id):
        return {'ok': False, 'error': 'Manual receivable entries cannot be linked'}, 400
    if linked_line_id is not None and _is_manual_line_id(linked_line_id):
        return {'ok': False, 'error': 'Target entry cannot be a manual placeholder'}, 400

    record = (db.session.query(JournalLine, JournalEntry, Account)
              .join(JournalEntry, JournalLine.journal_id == JournalEntry.id)
              .join(Account, JournalLine.account_id == Account.id)
              .filter(JournalLine.id == line_id, JournalEntry.user_id == user.id)
              .first())
    if not record:
        return {'ok': False, 'error': 'Journal line not found'}, 404

    line, entry, account = record
    scoped_cats, scoped_accounts, cat_map = _resolve_receivable_scope(user)
    if account.id in scoped_accounts['receivable']:
        kind = 'receivable'
    elif account.id in scoped_accounts['debt']:
        kind = 'debt'
    else:
        return {'ok': False, 'error': 'Account is not classified as receivable or short-term debt'}, 400

    other_line = None
    other_account = None
    other_kind = None
    if action in ('set', 'add', 'remove') and linked_line_id:
        other_record = (db.session.query(JournalLine, JournalEntry, Account)
                        .join(JournalEntry, JournalLine.journal_id == JournalEntry.id)
                        .join(Account, JournalLine.account_id == Account.id)
                        .filter(JournalLine.id == linked_line_id, JournalEntry.user_id == user.id)
                        .first())
        if not other_record:
            return {'ok': False, 'error': 'Linked journal line not found'}, 404
        other_line, other_entry, other_account = other_record
        if other_account.id in scoped_accounts['receivable']:
            other_kind = 'receivable'
        elif other_account.id in scoped_accounts['debt']:
            other_kind = 'debt'
        else:
            return {'ok': False, 'error': 'Linked account is not receivable or short-term debt'}, 400

    result = link_receivable_lines(
        user_id=user.id,
        line=line,
        account=account,
        kind=kind,
        action=action,
        linked_line=other_line,
        linked_account=other_account,
        linked_kind=other_kind,
        link_kind=link_kind,
    )
    if not result.get('ok'):
        return {'ok': False, 'error': result.get('error', 'Unable to link')}, 400

    db.session.commit()
    return {'ok': True}

@accounting_bp.route('/accounting/receivables/delete', methods=['POST'])
def receivables_delete():
    from finance_app import (
        Account,
        JournalEntry,
        JournalLine,
        ReceivableManualEntry,
        ReceivableTracker,
        current_user,
        db,
    )

    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)

    user = current_user()
    if not user:
        return ("Unauthorized", 401)

    data = request.get_json(force=True) or {}
    try:
        line_id = int(data.get('line_id') or 0)
    except Exception:
        line_id = 0
    if not line_id:
        return {'ok': False, 'error': 'line_id required'}, 400

    if _is_manual_line_id(line_id):
        manual_id = _manual_id_from_line(line_id)
        manual = ReceivableManualEntry.query.filter_by(id=manual_id, user_id=user.id).first()
        if not manual:
            return {'ok': False, 'error': 'Manual receivable not found'}, 404
        db.session.delete(manual)
        db.session.commit()
        return {'ok': True}

    record = (db.session.query(JournalLine, JournalEntry, Account)
              .join(JournalEntry, JournalLine.journal_id == JournalEntry.id)
              .join(Account, JournalLine.account_id == Account.id)
              .filter(JournalLine.id == line_id, JournalEntry.user_id == user.id)
              .first())
    if not record:
        return {'ok': False, 'error': 'Journal line not found'}, 404

    jl, je, acc = record
    scoped_cats, scoped_accounts, _ = _resolve_receivable_scope(user)
    if acc.id in scoped_accounts['receivable']:
        derived_kind = 'receivable'
    elif acc.id in scoped_accounts['debt']:
        derived_kind = 'debt'
    else:
        derived_kind = 'receivable'

    tracker = ReceivableTracker.query.filter_by(user_id=user.id, journal_line_id=line_id).first()
    if not tracker:
        tracker = ReceivableTracker(user_id=user.id,
                                    journal_id=jl.journal_id,
                                    journal_line_id=line_id,
                                    account_id=jl.account_id,
                                    category=derived_kind)
        db.session.add(tracker)
    else:
        tracker.category = derived_kind

    tracker.ignored = True
    tracker.linked_line_id = None
    tracker.link_kind = None

    # Clear counterpart link if present
    existing = ReceivableTracker.query.filter_by(user_id=user.id, linked_line_id=line_id).all()
    for other in existing:
        other.linked_line_id = None
        other.link_kind = None

    db.session.commit()
    return {'ok': True}


@accounting_bp.route('/accounting/receivables/create', methods=['POST'])
def receivables_create():
    from finance_app import Account, _parse_date_tuple, current_user, db

    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)

    user = current_user()
    if not user:
        return ("Unauthorized", 401)

    data = request.get_json(force=True) or {}
    direction = (data.get('direction') or 'receivable').strip().lower()
    if direction not in ('receivable', 'debt'):
        return {'ok': False, 'error': 'Direction must be receivable or debt'}, 400

    try:
        account_id = int(data.get('account_id') or 0)
    except Exception:
        account_id = 0
    if not account_id:
        return {'ok': False, 'error': 'Primary account is required'}, 400

    scoped_cats, scoped_accounts, cat_map = _resolve_receivable_scope(user)
    allowed_ids = scoped_accounts.get(direction) if direction in scoped_accounts else set()
    if not allowed_ids or account_id not in allowed_ids:
        return {'ok': False, 'error': 'Selected account is not classified for this direction'}, 400

    account = Account.query.filter_by(id=account_id, user_id=user.id, active=True).first()
    if not account:
        return {'ok': False, 'error': 'Account not found'}, 404

    try:
        amount = Decimal(str(data.get('amount') or '0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:
        amount = Decimal('0.00')
    if amount <= 0:
        return {'ok': False, 'error': 'Amount must be greater than zero'}, 400

    date_raw = (data.get('date') or '').strip()
    entry_date = _parse_receivable_date(date_raw, _parse_date_tuple)
    if not entry_date:
        return {'ok': False, 'error': 'Valid date is required'}, 400
    date_str = entry_date.strftime('%Y/%m/%d')

    description = (data.get('description') or '').strip() or ('New receivable' if direction == 'receivable' else 'New short-term debt')
    reference = (data.get('reference') or '').strip() or None
    memo = (data.get('memo') or '').strip()
    currency = (data.get('currency') or account.currency_code or 'KRW').strip().upper() or 'KRW'

    txn_value_raw = data.get('transaction_value')
    txn_value = _coerce_number(txn_value_raw if txn_value_raw not in (None, '') else amount)

    due_date = _parse_receivable_date(data.get('due_date'), _parse_date_tuple)
    payment_dates_in = data.get('payment_dates') or []
    if isinstance(payment_dates_in, str):
        payment_dates_in = [payment_dates_in]
    normalized_dates = []
    for item in payment_dates_in:
        dt = _parse_receivable_date(item, _parse_date_tuple)
        if dt:
            normalized_dates.append(dt.isoformat())

    notes = (data.get('notes') or '').strip()
    contact_name = (data.get('contact_name') or '').strip()
    if not contact_name:
        return {'ok': False, 'error': 'Contact name is required'}, 400

    try:
        manual = create_manual_receivable(
            user_id=user.id,
            account_id=account.id,
            direction=direction,
            amount=amount,
            currency=currency,
            description=description,
            reference=reference,
            memo=memo,
            contact_name=contact_name,
            transaction_value=txn_value,
            entry_date=entry_date,
            date_str=date_str,
            due_date=due_date,
            payment_dates=normalized_dates,
            notes=notes,
        )
        row = _serialize_manual_receivable(manual, account, direction, cat_map)
        return {'ok': True, 'row': row}
    except Exception as exc:
        db.session.rollback()
        return {'ok': False, 'error': f'Unable to create receivable: {exc}'}, 500


def _loan_group_response(user, group, include_entries=False):
    summary, entries = loan_group_summary(user.id, group)
    payload = _loan_group_to_dict(group, summary)
    if include_entries:
        payload['entries'] = entries
    return payload


def _sync_group_status(group, summary, session):
    status = (summary or {}).get('status')
    if status and group.status != status:
        group.status = status
        session.commit()


def _load_group_or_404(user, group_id):
    from finance_app import LoanGroup
    group = LoanGroup.query.filter_by(user_id=user.id, id=group_id).first()
    if not group:
        return None
    return group


@accounting_bp.route('/accounting/loan-groups', methods=['GET'])
def loan_groups_index():
    user = current_user()
    if not user:
        return ("Unauthorized", 401)

    query = LoanGroup.query.filter_by(user_id=user.id)
    status = (request.args.get('status') or '').strip().lower()
    if status:
        if status not in _VALID_GROUP_STATUSES:
            return {'ok': False, 'error': 'Invalid status filter'}, 400
        query = query.filter(LoanGroup.status == status)
    direction = (request.args.get('direction') or '').strip().lower()
    if direction:
        if direction not in _VALID_GROUP_DIRECTIONS:
            return {'ok': False, 'error': 'Invalid direction filter'}, 400
        query = query.filter(LoanGroup.direction == direction)
    counterparty = (request.args.get('counterparty') or '').strip()
    if counterparty:
        lowered = counterparty.lower()
        query = query.filter(func.lower(LoanGroup.counterparty) == lowered)
    currency = (request.args.get('currency') or '').strip().upper()
    if currency:
        query = query.filter(LoanGroup.currency == currency)

    include_summary = (request.args.get('include_summary', 'true').lower() != 'false')
    groups = query.order_by(LoanGroup.start_date.asc(), LoanGroup.created_at.asc()).all()
    payload = []
    for group in groups:
        if include_summary:
            payload.append(_loan_group_response(user, group, include_entries=False))
        else:
            payload.append(_loan_group_to_dict(group))
    return {'ok': True, 'groups': payload}


@accounting_bp.route('/accounting/loan-groups', methods=['POST'])
def loan_groups_create():
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)

    user = current_user()
    if not user:
        return ("Unauthorized", 401)

    data = request.get_json(force=True) or {}
    name = (data.get('name') or '').strip()
    direction = (data.get('direction') or '').strip().lower()
    counterparty = (data.get('counterparty') or '').strip() or None
    currency = (data.get('currency') or 'KRW').strip().upper() or 'KRW'
    notes = (data.get('notes') or '').strip() or None
    start_date = _parse_iso_date(data.get('start_date')) or _dt.date.today()

    if not name:
        return {'ok': False, 'error': 'Name is required'}, 400
    if direction not in _VALID_GROUP_DIRECTIONS:
        return {'ok': False, 'error': 'Direction must be receivable or payable'}, 400

    principal_raw = data.get('principal_amount')
    principal = _to_decimal(principal_raw).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if principal <= Decimal('0'):
        return {'ok': False, 'error': 'Principal amount must be greater than zero'}, 400

    group = loan_group_create(
        user_id=user.id,
        name=name,
        direction=direction,
        counterparty=counterparty,
        currency=currency,
        principal_amount=principal,
        start_date=start_date,
        notes=notes,
    )
    payload = _loan_group_response(user, group, include_entries=False)
    return {'ok': True, 'group': payload}, 201


@accounting_bp.route('/accounting/loan-groups/<group_id>', methods=['GET'])
def loan_groups_get(group_id):
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    group = loan_group_get(user.id, group_id)
    if not group:
        return {'ok': False, 'error': 'Loan group not found'}, 404
    include_entries = request.args.get('include_entries', 'false').lower() == 'true'
    payload = _loan_group_response(user, group, include_entries=include_entries)
    return {'ok': True, 'group': payload}


@accounting_bp.route('/accounting/loan-groups/<group_id>', methods=['DELETE'])
def loan_groups_delete(group_id):
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)

    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    if not loan_group_delete(user.id, group_id):
        return {'ok': False, 'error': 'Loan group not found'}, 404
    return {'ok': True}


@accounting_bp.route('/accounting/loan-groups/<group_id>', methods=['PATCH'])
def loan_groups_update(group_id):
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)

    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    data = request.get_json(force=True) or {}
    name = data.get('name')
    counterparty = data.get('counterparty')
    currency = data.get('currency')
    notes = data.get('notes')
    direction = data.get('direction')
    status = data.get('status')
    start_date = data.get('start_date')
    principal_amount = data.get('principal_amount')

    updates = {}
    if name is not None:
        clean = name.strip()
        if not clean:
            return {'ok': False, 'error': 'Name cannot be empty'}, 400
        updates["name"] = clean
    if counterparty is not None:
        updates["counterparty"] = counterparty.strip() or None
    if currency is not None:
        updates["currency"] = currency.strip().upper() or None
    if direction is not None:
        normalized_dir = direction.strip().lower()
        if normalized_dir not in _VALID_GROUP_DIRECTIONS:
            return {'ok': False, 'error': 'Direction must be receivable or payable'}, 400
        updates["direction"] = normalized_dir
    if notes is not None:
        updates["notes"] = notes.strip() or None
    if status is not None:
        normalized = status.strip().lower()
        if normalized not in _VALID_GROUP_STATUSES:
            return {'ok': False, 'error': 'Invalid status value'}, 400
        updates["status"] = normalized
    if start_date is not None:
        parsed = _parse_iso_date(start_date)
        if not parsed:
            return {'ok': False, 'error': 'Invalid start date'}, 400
        updates["start_date"] = parsed
    if principal_amount is not None:
        principal = _to_decimal(principal_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if principal <= Decimal('0'):
            return {'ok': False, 'error': 'Principal amount must be greater than zero'}, 400
        updates["principal_amount"] = principal

    group = loan_group_update(user.id, group_id, **updates)
    if not group:
        return {'ok': False, 'error': 'Loan group not found'}, 404

    payload = _loan_group_response(user, group, include_entries=False)
    summary = payload.get('summary') or {}
    if _sync_group_status(group, summary, db.session):
        payload = _loan_group_response(user, group, include_entries=False)
    return {'ok': True, 'group': payload}


@accounting_bp.route('/accounting/loan-groups/<group_id>/summary', methods=['GET'])
def loan_groups_summary(group_id):
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    group = loan_group_get(user.id, group_id)
    if not group:
        return {'ok': False, 'error': 'Loan group not found'}, 404
    summary, _ = loan_group_summary(user.id, group)
    return {'ok': True, 'group_id': group_id, 'summary': summary}


@accounting_bp.route('/accounting/loan-groups/<group_id>/entries', methods=['GET'])
def loan_groups_entries(group_id):
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    group = loan_group_get(user.id, group_id)
    if not group:
        return {'ok': False, 'error': 'Loan group not found'}, 404
    summary, entries = loan_group_summary(user.id, group)
    return {'ok': True, 'group_id': group_id, 'summary': summary, 'entries': entries}


@accounting_bp.route('/accounting/transaction-links', methods=['POST'])
def loan_group_links_create():
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)

    user = current_user()
    if not user:
        return ("Unauthorized", 401)

    data = request.get_json(force=True) or {}
    journal_line_id = data.get('journal_line_id') or data.get('transaction_id')
    try:
        journal_line_id_int = int(journal_line_id)
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'journal_line_id is required'}, 400
    links_payload = data.get('links')
    if not isinstance(links_payload, list) or not links_payload:
        return {'ok': False, 'error': 'links array is required'}, 400

    link_groups = []
    link_amounts = []
    for item in links_payload:
        if not isinstance(item, dict):
            return {'ok': False, 'error': 'Invalid link payload'}, 400
        group_id = item.get('loan_group_id')
        linked_amount = _to_decimal(item.get('linked_amount')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if not group_id or linked_amount <= Decimal('0'):
            return {'ok': False, 'error': 'loan_group_id and positive linked_amount are required'}, 400
        link_groups.append(group_id)
        link_amounts.append(linked_amount)

    # Apply links
    for gid, amt in zip(link_groups, link_amounts):
        created, error = loan_group_link_lines(user.id, gid, [journal_line_id_int], [amt])
        if error:
            return {'ok': False, 'error': error}, 400

    responses = []
    for gid in set(link_groups):
        grp = loan_group_get(user.id, gid)
        if grp:
            payload = _loan_group_response(user, grp, include_entries=False)
            responses.append(payload)
            _sync_group_status(grp, payload.get('summary'), db.session)

    return {'ok': True, 'groups': responses}


@accounting_bp.route('/accounting/transaction-links/<link_id>', methods=['DELETE'])
def loan_group_links_delete(link_id):
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)

    user = current_user()
    if not user:
        return ("Unauthorized", 401)

    group = loan_group_unlink(user.id, link_id)
    if not group:
        return {'ok': False, 'error': 'Link not found'}, 404
    payload = _loan_group_response(user, group, include_entries=False)
    _sync_group_status(group, payload.get('summary'), db.session)
    return {'ok': True, 'group': payload}


@accounting_bp.route('/accounting/allocation/suggest', methods=['POST'])
def loan_group_suggest():
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)

    user = current_user()
    if not user:
        return ("Unauthorized", 401)

    data = request.get_json(force=True) or {}
    journal_line_id_raw = data.get('journal_line_id') or data.get('transaction_id')
    try:
        journal_line_id = int(journal_line_id_raw)
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'journal_line_id is required'}, 400
    strategy = (data.get('strategy') or 'oldest-first').strip().lower()
    if strategy not in ('oldest-first', 'lowest-balance-first'):
        strategy = 'oldest-first'

    from finance_app import Account, JournalEntry, JournalLine
    from finance_app.models.accounting_models import ReceivableTracker

    record = (
        db.session.query(JournalLine, JournalEntry, Account)
        .join(JournalEntry, JournalLine.journal_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .filter(JournalLine.id == journal_line_id, JournalEntry.user_id == user.id)
        .first()
    )
    if not record:
        return {'ok': False, 'error': 'Journal line not found'}, 404
    line, entry, account = record
    tracker = ReceivableTracker.query.filter_by(user_id=user.id, journal_line_id=journal_line_id).first()

    scoped_cats, scoped_accounts, _ = _resolve_receivable_scope(user)
    if account.id in scoped_accounts['receivable']:
        direction = 'receivable'
    elif account.id in scoped_accounts['debt']:
        direction = 'payable'
    else:
        return {'ok': False, 'error': 'Account is not classified as receivable or short-term debt'}, 400

    flow = _loan_group_flow(direction, line.dc)
    if flow == 'origin':
        return {'ok': True, 'suggestions': [], 'note': 'Allocation suggestions apply to repayments only.'}

    line_currency = (line.currency_code or account.currency_code or 'KRW').upper()
    counterparty = (tracker.contact_name.strip() if tracker and tracker.contact_name else '')
    if not counterparty and isinstance(data, dict):
        counterparty = (data.get('counterparty') or '').strip()

    cap_raw = data.get('cap')
    cap = _to_decimal(cap_raw).quantize(Decimal('0.01')) if cap_raw is not None else None

    resp = suggest_allocation(
        user_id=user.id,
        journal_line_id=journal_line_id,
        direction=direction,
        counterparty=counterparty or None,
        cap=cap,
        strategy=strategy,
    )
    return resp
@accounting_bp.route('/accounting/tb/monthly', methods=['GET'])
def tb_monthly(ym_override=None):
    """Return monthly trial balance aggregates by group and category (folder)."""
    from finance_app import current_user
    user = current_user()
    if not user:
        return {"ok": False, "error": "Unauthorized"}, 401
    ok_guard, payload, status = _guard_schema_caps(["journal_report_perf"], user_id=user.id)
    if not ok_guard:
        return payload, status
    source_error = _ensure_ranked_report_source()
    if source_error:
        return source_error
    import datetime as _dt
    ym = (ym_override or (request.args.get('ym') or '')).strip()
    if not ym:
        today = _dt.date.today()
        ym = f"{today.year:04d}-{today.month:02d}"
    ccy = (request.args.get('ccy') or '').strip().upper() or None
    result = ledger_trial_balance_month(user.id, ym, currency=ccy)
    if not isinstance(result, dict):
        return {"ok": False, "error": "Failed to compute monthly trial balance"}, 400
    if bool(result.get("ok")):
        result.setdefault("groups", {})
        result.setdefault("grand_totals", {})
        result.setdefault("source", {"mode": "journal"})
        return result, 200
    result["ok"] = False
    if not isinstance(result.get("error"), str) or not result.get("error"):
        result["error"] = "Failed to compute monthly trial balance"
    return result, 400
@accounting_bp.route('/accounting/tb/close', methods=['POST'])
def tb_close_month():
    """Persist monthly per-account balances for faster future reports.

    Body JSON: { ym: 'YYYY-MM' }
    Admin-only for now.
    """
    from finance_app import AccountMonthlyBalance, current_user, db
    if not _check_csrf():
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user or not user.is_admin:
        return ("Unauthorized", 401)
    data = request.get_json(silent=True) or {}
    ym = (data.get('ym') or '').strip()
    if not ym:
        return {'ok': False, 'error': 'ym required (YYYY-MM)'}, 400
    # Compute TB for the requested month within a request context so tb_monthly sees args
    with current_app.test_request_context(f"/accounting/tb/monthly?ym={ym}"):
        monthly = tb_monthly()
    if not isinstance(monthly, dict) or not monthly.get('ok', False):
        return {'ok': False, 'error': 'Failed to compute monthly balances'}, 400
    try:
        y_str, m_str = ym.split('-'); y, m = int(y_str), int(m_str)
    except Exception:
        return {'ok': False, 'error': 'Invalid ym'}, 400
    # Upsert rows per account from groups.accounts
    count = 0
    for items in (monthly.get('groups') or {}).values():
        for folder in (items or []):
            for acc in (folder.get('accounts') or []):
                try:
                    row = AccountMonthlyBalance.query.filter_by(user_id=user.id, account_id=int(acc.get('id') or 0), year=y, month=m).first()
                    if not row:
                        row = AccountMonthlyBalance(user_id=user.id, account_id=int(acc.get('id') or 0), year=y, month=m)
                        db.session.add(row)
                    row.opening_bd = float(acc.get('bd') or 0.0)
                    row.period_debit = float(acc.get('period_debit') or 0.0)
                    row.period_credit = float(acc.get('period_credit') or 0.0)
                    row.closing_balance = float(acc.get('balance') or 0.0)
                    count += 1
                except Exception:
                    continue
    db.session.commit()
    return {'ok': True, 'saved': count}


@accounting_bp.route('/accounting/statement/data', methods=['GET'])
def statement_data():
    """Return statement-ready data for the requested month."""
    import datetime as _dt

    from finance_app import current_user

    user = current_user()
    if not user:
        return {"ok": False, "error": "Unauthorized"}, 401
    ok_guard, payload, status = _guard_schema_caps(["journal_report_perf"], user_id=user.id)
    if not ok_guard:
        return payload, status
    source_error = _ensure_ranked_report_source()
    if source_error:
        return source_error

    ym = (request.args.get('ym') or '').strip()
    if not ym:
        return {'ok': False, 'error': 'Missing ym (YYYY-MM)'}, 400

    ccy = (request.args.get('ccy') or '').strip().upper() or None
    period = _parse_month_period(ym)
    if not period:
        return {'ok': False, 'error': 'Invalid ym'}, 400
    year, month, start, end = period
    cash_folder_ids = _parse_cash_folder_ids_arg()

    canonical_stmt = ledger_statement_period(
        user.id,
        start,
        end,
        currency=ccy,
        cash_folder_ids=cash_folder_ids,
    )
    if not isinstance(canonical_stmt, dict) or not canonical_stmt.get("ok", False):
        err = canonical_stmt.get("error") if isinstance(canonical_stmt, dict) else "Failed to build canonical statements"
        return {"ok": False, "error": err}, 400

    monthly = ledger_trial_balance_month(user.id, ym, currency=ccy, include_coverage=False)
    if not isinstance(monthly, dict) or not monthly.get("ok", False):
        err = monthly.get("error") if isinstance(monthly, dict) else "Failed to compute monthly data"
        return {"ok": False, "error": err}, 400

    compare_ym = (request.args.get('ym_compare') or '').strip()
    compare_stmt: Dict[str, Any] | None = None
    compare_period: Dict[str, str] | None = None
    if compare_ym:
        compare_period_tuple = _parse_month_period(compare_ym)
        if not compare_period_tuple:
            return {'ok': False, 'error': 'Invalid compare month'}, 400
        _, _, compare_start, compare_end = compare_period_tuple
        compare_period = {'start': compare_start.isoformat(), 'end': compare_end.isoformat()}
        compare_stmt = ledger_statement_period(
            user.id,
            compare_start,
            compare_end,
            currency=ccy,
            cash_folder_ids=cash_folder_ids,
            include_coverage=False,
        )
        if not isinstance(compare_stmt, dict) or not compare_stmt.get("ok", False):
            err = compare_stmt.get("error") if isinstance(compare_stmt, dict) else "Failed to compute comparison data"
            return {'ok': False, 'error': err}, 400

    from statements_pdf import _fmt

    org = (request.args.get('org') or 'PALS Finance').strip() or 'PALS Finance'
    include_trend = request.args.get('include_trend')
    trend_months = max(1, min(12, int(request.args.get('trend_months', 6) or 6)))
    selected_ccy = ccy or ""
    include_expense_trend = True
    asset_folders = (monthly.get('groups', {}).get('asset') or [])

    def _looks_like_cash(name: str) -> bool:
        lowered = (name or '').strip().lower()
        return any(word in lowered for word in ('cash', 'bank', 'checking', 'savings'))

    def _fmt_num(val: float | int | None) -> str:
        try:
            return _fmt(float(val or 0.0))
        except Exception:
            try:
                return f"{float(val):,.0f}"
            except Exception:
                return "—"

    def _fmt_pct(val: float | None) -> str:
        if val is None:
            return "—"
        return f"{val:.1f}%"

    def _coerce_amount(val: object) -> float:
        if val is None:
            return 0.0
        try:
            return float(val)
        except Exception:
            try:
                txt = str(val)
                cleaned = ''.join(ch for ch in txt if (ch.isdigit() or ch in {'.', '-', '+'}))
                return float(cleaned) if cleaned not in {'', '+', '-'} else 0.0
            except Exception:
                return 0.0

    def _delta_pair(current_val: float | int | None, compare_val: float | int | None) -> tuple[float, float | None]:
        cur = float(current_val or 0.0)
        comp = float(compare_val or 0.0)
        delta = cur - comp
        pct = None
        if comp != 0:
            pct = (delta / comp) * 100.0
        return delta, pct

    def _apply_compare_rows(base_rows: list[Dict[str, Any]], compare_rows: list[Dict[str, Any]]) -> None:
        if not base_rows:
            return
        lookup: Dict[tuple[str, str], Dict[str, Any]] = {}
        for row in compare_rows or []:
            key = ((row.get('cat') or '').lower(), (row.get('name') or '').lower())
            lookup[key] = row
        for row in base_rows:
            key = ((row.get('cat') or '').lower(), (row.get('name') or '').lower())
            comp = lookup.get(key)
            comp_amt = float(comp.get('amt') or 0.0) if comp else 0.0
            delta, pct = _delta_pair(row.get('amt'), comp_amt)
            row['compare_amt'] = comp_amt
            row['compare_amt_fmt'] = _fmt_num(comp_amt)
            row['delta_amt'] = delta
            row['delta_amt_fmt'] = _fmt_num(delta)
            row['delta_pct'] = pct
            row['delta_pct_fmt'] = _fmt_pct(pct)

    def _apply_compare_sections(sections: list[Dict[str, Any]], compare_sections: list[Dict[str, Any]]) -> None:
        if not sections:
            return
        section_lookup: Dict[tuple[str, str], Dict[str, Any]] = {}
        for sec in compare_sections or []:
            for row in sec.get('rows') or []:
                key = ((row.get('key') or row.get('group') or '').lower(), (row.get('name') or '').lower())
                section_lookup[key] = row
        for sec in sections:
            for row in sec.get('rows') or []:
                key = ((row.get('key') or row.get('group') or '').lower(), (row.get('name') or '').lower())
                comp = section_lookup.get(key)
                comp_amt = _coerce_amount(comp.get('amt')) if comp else 0.0
                delta, pct = _delta_pair(row.get('amt'), comp_amt)
                row['compare_amt'] = comp_amt
                row['compare_amt_fmt'] = _fmt_num(comp_amt)
                row['delta_amt'] = delta
                row['delta_amt_fmt'] = _fmt_num(delta)
                row['delta_pct'] = pct
                row['delta_pct_fmt'] = _fmt_pct(pct)

    def _apply_compare_totals(base_totals: Dict[str, Any], compare_totals: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        delta_totals: Dict[str, Any] = {}
        delta_pct_totals: Dict[str, Any] = {}
        if not base_totals:
            return delta_totals, delta_pct_totals
        for key, val in base_totals.items():
            if key.endswith('_fmt'):
                continue
            comp_val = compare_totals.get(key) if compare_totals else 0.0
            delta, pct = _delta_pair(val, comp_val)
            delta_totals[key] = _fmt_num(delta)
            delta_totals[f"{key}_fmt"] = _fmt_num(delta)
            delta_pct_totals[key] = _fmt_pct(pct)
            delta_pct_totals[f"{key}_fmt"] = _fmt_pct(pct)
        return delta_totals, delta_pct_totals

    def _apply_compare_cashflow_sections(sections: list[Dict[str, Any]], compare_sections: list[Dict[str, Any]]) -> None:
        comp_map: Dict[tuple[str, str], Dict[str, Any]] = {}
        for sec in compare_sections or []:
            sec_key = (sec.get('title') or sec.get('key') or '').lower()
            for row in sec.get('rows') or []:
                comp_map[(sec_key, (row.get('name') or '').lower())] = row
        for sec in sections or []:
            sec_key = (sec.get('title') or sec.get('key') or '').lower()
            for row in sec.get('rows') or []:
                comp_row = comp_map.get((sec_key, (row.get('name') or '').lower()))
                comp_amt = 0.0
                if comp_row:
                    comp_amt = _coerce_amount((comp_row.get('amounts') or {}).get('__BASE__'))
                cur_amt = _coerce_amount((row.get('amounts') or {}).get('__BASE__'))
                delta, pct = _delta_pair(cur_amt, comp_amt)
                row['compare_amt'] = comp_amt
                row['compare_amt_fmt'] = _fmt_num(comp_amt)
                row['delta_amt'] = delta
                row['delta_amt_fmt'] = _fmt_num(delta)
                row['delta_pct'] = pct
                row['delta_pct_fmt'] = _fmt_pct(pct)

    folder_lookup: Dict[int, str] = {}
    cash_folder_options: List[Dict[str, Any]] = []
    for folder in asset_folders:
        cid = folder.get('category_id')
        if cid is None:
            continue
        try:
            cid_int = int(cid)
        except Exception:
            continue
        name = folder.get('category_name') or folder.get('name') or 'Asset Folder'
        folder_lookup[cid_int] = name
        cash_folder_options.append({
            'id': cid_int,
            'name': name,
            'is_default': _looks_like_cash(name),
        })
    cash_folder_options.sort(key=lambda item: (item['name'] or '').lower())

    income_statement = dict((canonical_stmt.get("statements", {}) or {}).get("income") or {})
    balance_statement = dict((canonical_stmt.get("statements", {}) or {}).get("balance") or {})
    cashflow_statement = dict((canonical_stmt.get("statements", {}) or {}).get("cashflow") or {})
    if cashflow_statement.get('applied_folder_ids'):
        cashflow_statement['applied_folders'] = [
            {'id': fid, 'name': folder_lookup.get(fid, '')}
            for fid in cashflow_statement['applied_folder_ids']
        ]

    if compare_stmt:
        compare_statements = compare_stmt.get("statements", {}) or {}
        income_compare = compare_statements.get("income") or {}
        balance_compare = compare_statements.get("balance") or {}
        cashflow_compare = compare_statements.get("cashflow") or {}
        _apply_compare_rows(income_statement.get('rows') or [], income_compare.get('rows') or [])
        income_delta, income_delta_pct = _apply_compare_totals(income_statement.get('totals') or {}, income_compare.get('totals') or {})
        income_statement['compare_period'] = compare_period
        income_statement['compare_label'] = compare_period['end'] if compare_period else compare_ym
        income_statement['compare_totals'] = income_compare.get('totals') or {}
        income_statement['delta_totals'] = income_delta
        income_statement['delta_totals_pct'] = income_delta_pct

        _apply_compare_sections(balance_statement.get('sections') or [], balance_compare.get('sections') or [])
        bal_delta, bal_delta_pct = _apply_compare_totals(balance_statement.get('totals') or {}, balance_compare.get('totals') or {})
        balance_statement['compare_period'] = compare_period
        balance_statement['compare_label'] = compare_period['end'] if compare_period else compare_ym
        balance_statement['compare_totals'] = balance_compare.get('totals') or {}
        balance_statement['delta_totals'] = bal_delta
        balance_statement['delta_totals_pct'] = bal_delta_pct

        _apply_compare_cashflow_sections(cashflow_statement.get('sections') or [], cashflow_compare.get('sections') or [])
        cf_delta, cf_delta_pct = _apply_compare_totals(cashflow_statement.get('totals') or {}, cashflow_compare.get('totals') or {})
        cashflow_statement['compare_period'] = compare_period
        cashflow_statement['compare_label'] = compare_period['end'] if compare_period else compare_ym
        cashflow_statement['compare_totals'] = cashflow_compare.get('totals') or {}
        cashflow_statement['delta_totals'] = cf_delta
        cashflow_statement['delta_totals_pct'] = cf_delta_pct

    payload: Dict[str, Any] = {
        'ok': True,
        'ym': ym,
        'organization': org,
        'period': {'start': start.isoformat(), 'end': end.isoformat()},
        'source': canonical_stmt.get("source") or {'mode': 'journal'},
        'statements': {
            'income': income_statement,
            'balance': balance_statement,
            'cashflow': cashflow_statement,
        },
        'generated_at': _dt.datetime.utcnow().isoformat(),
        'initialized_on': canonical_stmt.get('initialized_on'),
        'cash_folder_options': cash_folder_options,
        'selected_cash_folders': cash_folder_ids,
    }
    if canonical_stmt.get("coverage") is not None:
        payload["coverage"] = canonical_stmt.get("coverage")
        if isinstance(payload["coverage"], dict):
            payload["coverage"].setdefault("coverage_count", 0)
            payload["coverage"].setdefault("coverage_amount", 0)
    if compare_period:
        payload['compare_period'] = compare_period
        payload['ym_compare'] = compare_ym

    if include_trend is not None:
        trend_rows: List[Dict[str, Any]] = []
        try:
            base_year, base_month = year, month
            for i in range(trend_months - 1, -1, -1):
                t_year = base_year
                t_month = base_month - i
                while t_month <= 0:
                    t_month += 12
                    t_year -= 1
                ym_trend = f"{t_year}-{str(t_month).zfill(2)}"
                trend_period = _parse_month_period(ym_trend)
                if not trend_period:
                    continue
                _, _, t_start, t_end = trend_period
                trend_stmt = ledger_statement_period(
                    user.id,
                    t_start,
                    t_end,
                    currency=selected_ccy or None,
                    cash_folder_ids=cash_folder_ids,
                    include_coverage=False,
                )
                if not isinstance(trend_stmt, dict) or not trend_stmt.get("ok", False):
                    continue
                inc_data = (trend_stmt.get("statements", {}) or {}).get("income") or {}
                rev = float(inc_data.get('totals', {}).get('revenue') or 0.0)
                exp = float(inc_data.get('totals', {}).get('expense') or 0.0)
                net = rev - exp
                rev_ccy = exp_ccy = net_ccy = None
                if selected_ccy:
                    for entry in inc_data.get('currency_totals') or []:
                        if (entry.get('currency') or '').upper() == selected_ccy:
                            rev_ccy = float(entry.get('revenue') or 0.0)
                            exp_ccy = float(entry.get('expense') or 0.0)
                            net_ccy = float(entry.get('net_income') or 0.0)
                            break
                label = _dt.date(t_year, t_month, 1).strftime("%b %Y")
                trend_rows.append({
                    'ym': ym_trend,
                    'label': label,
                    'revenue': rev,
                    'expense': exp,
                    'net': net,
                    'revenue_ccy': rev_ccy,
                    'expense_ccy': exp_ccy,
                    'net_ccy': net_ccy,
                })
        except Exception:
            trend_rows = []
        payload['trend'] = {'months': trend_rows}
        # Pre-compute average outflow (base and selected currency) across available history (exclude current month if >1)
        if trend_rows:
            hist_rows = trend_rows[:-1] if len(trend_rows) > 1 else trend_rows
            base_vals = [max(0.0, float(entry.get('expense') or 0.0)) for entry in hist_rows]
            ccy_vals = [max(0.0, float(entry.get('expense_ccy') or 0.0)) for entry in hist_rows if entry.get('expense_ccy') is not None]
            payload['trend']['avg_outflow'] = (sum(base_vals) / len(base_vals)) if base_vals else None
            payload['trend']['avg_outflow_ccy'] = (sum(ccy_vals) / len(ccy_vals)) if ccy_vals else None
        # Expense category trend (top 3)
        if include_expense_trend:
            exp_trend: Dict[str, List[Dict[str, Any]]] = {}
            acc_trend: Dict[str, List[Dict[str, Any]]] = {}
            try:
                cat_sums: Dict[str, List[tuple[str, float]]] = {}
                acc_sums: Dict[str, List[tuple[str, float]]] = {}
                for entry in trend_rows:
                    ym_cur = entry['ym']
                    monthly_trend = ledger_trial_balance_month(
                        user.id,
                        ym_cur,
                        currency=selected_ccy or None,
                        include_coverage=False,
                    )
                    if not isinstance(monthly_trend, dict) or not monthly_trend.get('ok', False):
                        continue
                    exp_groups = (monthly_trend.get('groups', {}).get('expense') or [])
                    month_data: Dict[str, float] = {}
                    acc_data: Dict[str, float] = {}
                    for item in exp_groups:
                        name = item.get('category_name') or item.get('name') or ''
                        amt = float(item.get('period_debit') or 0.0) - float(item.get('period_credit') or 0.0)
                        month_data[name] = month_data.get(name, 0.0) + amt
                        for acc in (item.get('accounts') or []):
                            acc_name = acc.get('name') or acc.get('category_name') or ''
                            acc_amt = float(acc.get('period_debit') or 0.0) - float(acc.get('period_credit') or 0.0)
                            acc_data[acc_name] = acc_data.get(acc_name, 0.0) + acc_amt
                    for k, v in month_data.items():
                        cat_sums.setdefault(k, []).append((entry['label'], v))
                    for k, v in acc_data.items():
                        acc_sums.setdefault(k, []).append((entry['label'], v))
                top = sorted(((k, v[-1][1]) for k, v in cat_sums.items() if v), key=lambda kv: abs(kv[1]), reverse=True)[:3]
                for name, _ in top:
                    exp_trend[name] = [{'label': lbl, 'value': val} for lbl, val in cat_sums.get(name, [])]
                top_accounts = sorted(((k, v[-1][1]) for k, v in acc_sums.items() if v), key=lambda kv: abs(kv[1]), reverse=True)[:3]
                for name, _ in top_accounts:
                    acc_trend[name] = [{'label': lbl, 'value': val} for lbl, val in acc_sums.get(name, [])]
            except Exception:
                exp_trend = {}
                acc_trend = {}
            if exp_trend:
                payload['expense_trend'] = exp_trend
            if acc_trend:
                payload['expense_account_trend'] = acc_trend

    if canonical_stmt.get('message'):
        payload['message'] = canonical_stmt['message']
    # FX impact note: difference between base total and selected currency total (income net)
    if selected_ccy:
        try:
            income_stmt = payload['statements']['income']
            base_net = float(income_stmt.get('totals', {}).get('net_income') or 0.0)
            ccy_map = {entry.get('currency'): entry for entry in (income_stmt.get('currency_totals') or [])}
            ccy_entry = ccy_map.get(selected_ccy)
            ccy_net = float(ccy_entry.get('net_income') or 0.0) if ccy_entry else None
            if ccy_net is not None:
                payload['fx_impact'] = {
                    'currency': selected_ccy,
                    'base_net': base_net,
                    'ccy_net': ccy_net,
                    'difference': base_net - ccy_net,
                }
        except Exception:
            pass
    return payload


@accounting_bp.route('/accounting/statement/export', methods=['GET'])
def statement_export():
    """Export statement data as CSV or XLSX."""
    import csv
    import io
    from decimal import Decimal, ROUND_HALF_UP

    from finance_app import current_user

    user = current_user()
    if not user:
        return ("Unauthorized", 401)

    fmt = (request.args.get('format') or 'csv').lower()
    if fmt not in {'csv', 'xlsx'}:
        return {'ok': False, 'error': 'Unsupported format'}, 400

    # Reuse statement_data to build payload using the current request context/session.
    payload = statement_data()
    if isinstance(payload, tuple):
        return payload
    if not isinstance(payload, dict) or not payload.get('ok'):
        return {'ok': False, 'error': payload.get('error', 'Failed to build data')}, 400
    ym = (payload.get('ym') or request.args.get('ym') or '').strip()
    if not ym:
        return {'ok': False, 'error': 'Missing ym (YYYY-MM)'}, 400

    kind = (request.args.get('kind') or 'income').strip().lower()
    data = payload.get('statements', {}).get(kind)
    if not data:
        return {'ok': False, 'error': 'No statement data'}, 400

    def _decimal_str(val):
        try:
            return format(Decimal(str(val)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')
        except Exception:
            return ""

    def _meta_value_str(val):
        if isinstance(val, bool):
            return "true" if val else "false"
        if val is None:
            return ""
        return str(val)

    def _is_numeric_value(val):
        return isinstance(val, (int, float, Decimal)) and not isinstance(val, bool)

    def _build_reserved_parity_rows():
        parity_rows = []
        totals = data.get('totals') or {}
        for total_key, total_value in totals.items():
            if str(total_key).endswith('_fmt'):
                continue
            if not _is_numeric_value(total_value):
                continue
            parity_rows.append(
                {
                    'Section': '__TOTAL__',
                    'Label': str(total_key),
                    'amount_base': _decimal_str(total_value),
                    'meta_value': '',
                }
            )

        source = payload.get('source') or {}
        coverage = payload.get('coverage')
        parity_rows.append(
            {
                'Section': '__META__',
                'Label': 'source.mode',
                'amount_base': '',
                'meta_value': _meta_value_str(source.get('mode')),
            }
        )
        parity_rows.append(
            {
                'Section': '__META__',
                'Label': 'source.mixed_mode_allowed',
                'amount_base': '',
                'meta_value': _meta_value_str(source.get('mixed_mode_allowed')),
            }
        )
        parity_rows.append(
            {
                'Section': '__META__',
                'Label': 'source.legacy_rows_included_in_totals',
                'amount_base': '',
                'meta_value': _meta_value_str(source.get('legacy_rows_included_in_totals')),
            }
        )
        coverage_present = isinstance(coverage, dict)
        parity_rows.append(
            {
                'Section': '__META__',
                'Label': 'coverage.present',
                'amount_base': '',
                'meta_value': "true" if coverage_present else "false",
            }
        )
        if coverage_present:
            for cov_key, cov_val in coverage.items():
                if not _is_numeric_value(cov_val):
                    continue
                parity_rows.append(
                    {
                        'Section': '__META__',
                        'Label': f'coverage.{cov_key}',
                        'amount_base': _decimal_str(cov_val),
                        'meta_value': _meta_value_str(cov_val),
                    }
                )
        return parity_rows

    # Normalize rows per kind with the same currency/compare resolution as the UI
    selected_ccy = (request.args.get('ccy') or '').upper()
    available_currencies = data.get('currency_columns') or []
    compare_mode = bool(data.get('compare_period'))

    def column_labels(cols):
        label_map = {
            '__BASE__': 'Amount',
            'CURRENT': 'This',
            'COMPARE': 'Compare',
            'DELTA': 'Δ',
            'DELTA_PCT': 'Δ %',
        }
        return [label_map.get(col, col) for col in cols]

    def resolve_columns():
        if compare_mode:
            return ['CURRENT', 'COMPARE', 'DELTA', 'DELTA_PCT']
        if selected_ccy and selected_ccy in available_currencies:
            return [selected_ccy]
        if available_currencies:
            return list(available_currencies)
        return ['__BASE__']

    def resolve_amount_income(row, col):
        if compare_mode:
            return {
                'CURRENT': row.get('amt_fmt') or '',
                'COMPARE': row.get('compare_amt_fmt') or '',
                'DELTA': row.get('delta_amt_fmt') or '',
                'DELTA_PCT': row.get('delta_pct_fmt') or '',
            }.get(col, '')
        if col == '__BASE__':
            return row.get('amt_fmt') or ''
        currencies = row.get('currencies') or {}
        return (currencies.get(col) or {}).get('fmt') or ''

    def resolve_amount_balance(row, col):
        if compare_mode:
            return {
                'CURRENT': row.get('amt_fmt') or '',
                'COMPARE': row.get('compare_amt_fmt') or '',
                'DELTA': row.get('delta_amt_fmt') or '',
                'DELTA_PCT': row.get('delta_pct_fmt') or '',
            }.get(col, '')
        if col == '__BASE__':
            return row.get('amt_fmt') or ''
        currencies = row.get('currencies') or {}
        return (currencies.get(col) or {}).get('fmt') or ''

    def resolve_amount_cashflow(row, col):
        if compare_mode:
            return {
                'CURRENT': (row.get('amounts') or {}).get('__BASE__') or '',
                'COMPARE': row.get('compare_amt_fmt') or '',
                'DELTA': row.get('delta_amt_fmt') or '',
                'DELTA_PCT': row.get('delta_pct_fmt') or '',
            }.get(col, '')
        if col == '__BASE__':
            return (row.get('amounts') or {}).get('__BASE__') or ''
        return (row.get('amounts') or {}).get(col) or ''

    cols = resolve_columns()
    headers = ['Section', 'Label'] + column_labels(cols)
    if 'amount_base' not in headers:
        headers.append('amount_base')
    if 'meta_value' not in headers:
        headers.append('meta_value')
    rows = []
    if kind == 'income':
        for row in data.get('rows') or []:
            out_row = {'Section': row.get('cat') or '', 'Label': row.get('name') or ''}
            for col in cols:
                out_row[column_labels([col])[0]] = resolve_amount_income(row, col)
            rows.append(out_row)
    elif kind == 'balance':
        for section in data.get('sections') or []:
            for item in section.get('rows') or []:
                out_row = {'Section': section.get('title') or section.get('key') or '', 'Label': item.get('name') or ''}
                for col in cols:
                    out_row[column_labels([col])[0]] = resolve_amount_balance(item, col)
                rows.append(out_row)
    elif kind == 'cashflow':
        for sec in data.get('sections') or []:
            for item in sec.get('rows') or []:
                out_row = {'Section': sec.get('title') or sec.get('key') or '', 'Label': item.get('name') or ''}
                for col in cols:
                    out_row[column_labels([col])[0]] = resolve_amount_cashflow(item, col)
                rows.append(out_row)
    rows.extend(_build_reserved_parity_rows())

    filename = f"{kind}_statement_{ym}"
    if fmt == 'csv':
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        csv_bytes = output.getvalue().encode('utf-8')
        return Response(csv_bytes, mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=\"{filename}.csv\"'})

    # XLSX output must be a valid OOXML zip container (PK...).
    from openpyxl import Workbook

    workbook = Workbook(write_only=False)
    sheet = workbook.active
    sheet.title = "statement_export"
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header, '') for header in headers])

    out = io.BytesIO()
    workbook.save(out)
    xlsx_bytes = out.getvalue()
    headers_out = {'Content-Disposition': f'attachment; filename=\"{filename}.xlsx\"'}
    return Response(
        xlsx_bytes,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers=headers_out,
    )


@accounting_bp.route('/accounting/statement/pdf', methods=['GET'])
def statement_pdf():
    """Generate Income Statement, Balance Sheet, or Cash Flow for a month.

    Query params:
      - kind: 'income' | 'balance' | 'cashflow'
      - ym: 'YYYY-MM' (month)
      - org: optional org name in header
      - logo: optional logo path/url
    Returns PDF, or HTML fallback if PDF rendering fails.
    """
    from pathlib import Path

    from finance_app import current_user
    from flask import Response, send_file

    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    ok_guard, payload, status = _guard_schema_caps(["journal_report_perf"], user_id=user.id)
    if not ok_guard:
        return payload, status
    source_error = _ensure_ranked_report_source()
    if source_error:
        return source_error

    kind = (request.args.get('kind') or 'income').strip().lower()
    ym = (request.args.get('ym') or '').strip()
    if not ym:
        return {'ok': False, 'error': 'Missing ym (YYYY-MM)'}, 400

    period = _parse_month_period(ym)
    if not period:
        return {'ok': False, 'error': 'Invalid ym'}, 400
    _, _, start, end = period

    ccy = (request.args.get('ccy') or '').strip().upper() or None
    cash_folder_ids = _parse_cash_folder_ids_arg()
    canonical_stmt = ledger_statement_period(
        user.id,
        start,
        end,
        currency=ccy,
        cash_folder_ids=cash_folder_ids,
    )
    if not isinstance(canonical_stmt, dict) or not canonical_stmt.get("ok", False):
        err = canonical_stmt.get("error") if isinstance(canonical_stmt, dict) else "Failed to compute statement data"
        return {"ok": False, "error": err}, 400

    org = (request.args.get('org') or 'PALS Finance').strip() or 'PALS Finance'
    logo = (request.args.get('logo') or '').strip() or None
    out_path = Path('instance') / f"stmt_{kind}_{user.id}_{ym}.pdf"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    statements = (canonical_stmt.get("statements") or {})

    try:
        if kind == 'income':
            from statements_pdf import generate_income_statement_pdf_from_data

            data = statements.get("income") or {}
            generate_income_statement_pdf_from_data(data, org, start.isoformat(), end.isoformat(), out_path, logo=logo)
            return send_file(str(out_path), as_attachment=True, download_name=f"income_statement_{ym}.pdf", mimetype='application/pdf')
        if kind == 'balance':
            from statements_pdf import generate_balance_sheet_pdf_from_data

            data = statements.get("balance") or {}
            generate_balance_sheet_pdf_from_data(data, org, end.isoformat(), out_path, logo=logo)
            return send_file(str(out_path), as_attachment=True, download_name=f"balance_sheet_{ym}.pdf", mimetype='application/pdf')
        if kind == 'cashflow':
            from statements_pdf import generate_cashflow_pdf_from_data

            data = statements.get("cashflow") or {}
            generate_cashflow_pdf_from_data(data, org, start.isoformat(), end.isoformat(), out_path, logo=logo)
            return send_file(str(out_path), as_attachment=True, download_name=f"cashflow_{ym}.pdf", mimetype='application/pdf')
        return {'ok': False, 'error': 'Unknown kind'}, 400
    except Exception as e:
        # HTML fallback on PDF render failure, using the same canonical statement payload.
        try:
            if kind == 'income':
                from statements_pdf import render_income_statement_html_from_data

                html = render_income_statement_html_from_data(
                    statements.get("income") or {},
                    org,
                    start.isoformat(),
                    end.isoformat(),
                    logo=logo,
                )
                return Response(html, status=200, mimetype='text/html')
            if kind == 'balance':
                from statements_pdf import render_balance_sheet_html_from_data

                html = render_balance_sheet_html_from_data(
                    statements.get("balance") or {},
                    org,
                    end.isoformat(),
                    logo=logo,
                )
                return Response(html, status=200, mimetype='text/html')
            if kind == 'cashflow':
                from statements_pdf import render_cashflow_html_from_data

                html = render_cashflow_html_from_data(
                    statements.get("cashflow") or {},
                    org,
                    start.isoformat(),
                    end.isoformat(),
                    logo=logo,
                )
                return Response(html, status=200, mimetype='text/html')
        except Exception:
            pass
        return {'ok': False, 'error': f'Failed to render statement: {e}'}, 500


@accounting_bp.route('/accounting/tb/set_first_month', methods=['POST'])
def set_tb_first_month():
    if request.headers.get('X-CSRF-Token') != session.get('csrf_token'):
        return ("CSRF token missing or invalid", 400)
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    data = request.get_json(force=True) if request.is_json else request.form
    ym = (data.get('ym') or '').strip()
    result = tb_set_first_month_service(user.id, ym)
    status = 200 if result.get("ok") else 400
    return result, status


@accounting_bp.route('/accounting/journal/list', methods=['GET'])
def journal_entries_list():
    from finance_app import current_user
    from finance_app.services.journal_service import list_entries as journal_list
    user = current_user()
    if not user:
        return {"ok": False, "error": "Unauthorized"}, 401

    search = (request.args.get('q') or '').strip()
    start = (request.args.get('start') or '').strip() or None
    end = (request.args.get('end') or '').strip() or None
    account_filter = (request.args.get('account_id') or '').strip() or None
    category_filter = (request.args.get('category_id') or '').strip() or None
    min_amount_filter = (request.args.get('min_amount') or '').strip() or None
    max_amount_filter = (request.args.get('max_amount') or '').strip() or None
    try:
        page = int(request.args.get('page', '1'))
    except Exception:
        page = 1
    try:
        per_page = int(request.args.get('per_page', '25'))
    except Exception:
        per_page = 25
    account_id = None
    if account_filter:
        try:
            account_id = int(account_filter)
        except Exception:
            account_id = None
    category_id = None
    if category_filter:
        try:
            category_id = int(category_filter)
        except Exception:
            category_id = None

    return journal_list(
        user_id=user.id,
        q=search or None,
        start=start,
        end=end,
        account_id=account_id,
        category_id=category_id,
        min_amount=min_amount_filter,
        max_amount=max_amount_filter,
        page=page,
        per_page=per_page,
    )


@accounting_bp.route('/accounting/journal/<int:entry_id>', methods=['PUT'])
def update_journal_entry(entry_id):
    if not _check_csrf():
        return {"ok": False, "error": "CSRF token missing or invalid"}, 400
    from finance_app import current_user, db, ensure_account
    try:
        from finance_app import Account, JournalEntry, JournalLine, _parse_date_tuple
    except Exception:
        return {'ok': False, 'error': 'Journal model not available'}, 500

    user = current_user()
    if not user:
        return {"ok": False, "error": "Unauthorized"}, 401
    ok_guard, payload, status = _guard_schema_caps(["journal_integrity"], user_id=user.id)
    if not ok_guard:
        return payload, status

    entry = JournalEntry.query.get_or_404(entry_id)
    if entry.user_id != user.id:
        return {"ok": False, "error": "Forbidden"}, 403

    data = request.get_json(force=True)
    date_raw = (data.get('date') or '').strip()
    description = (data.get('description') or '').strip()
    reference = (data.get('reference') or '').strip()
    lines_in = data.get('lines') or []
    if not date_raw or not description or not isinstance(lines_in, list) or len(lines_in) < 2:
        return {'ok': False, 'error': 'Invalid inputs'}, 400

    import datetime as _dt
    from decimal import ROUND_HALF_UP, Decimal

    try:
        parsed = _dt.datetime.strptime(date_raw.replace('-', '/'), '%Y/%m/%d')
        date_str = parsed.strftime('%Y/%m/%d')
        y, m, d = _parse_date_tuple(date_str)
        date_parsed = _dt.date(y, m, d) if y and m and d else None
    except Exception:
        date_str = date_raw
        date_parsed = None

    built: list[JournalLinePayload] = []

    for idx, ln in enumerate(lines_in, start=1):
        dc = (ln.get('dc') or '').strip().upper()
        account_id = ln.get('account_id')
        account_name = (ln.get('account') or '').strip()
        memo = (ln.get('memo') or '').strip()
        amount_val = ln.get('amount')
        if dc not in ('D', 'C'):
            return {'ok': False, 'error': 'Invalid line entries'}, 400
        try:
            amt = Decimal(str(amount_val)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            return {'ok': False, 'error': 'Invalid amount'}, 400
        if amt <= 0:
            return {'ok': False, 'error': 'Amounts must be > 0'}, 400

        acc_obj = None
        if account_id not in (None, '', 'null'):
            try:
                aid = int(account_id)
            except Exception:
                aid = None
            if aid:
                acc_obj = Account.query.get(aid)
                if not acc_obj or acc_obj.user_id != user.id:
                    return {'ok': False, 'error': 'Account not found'}, 400
        if not acc_obj:
            if not account_name:
                return {'ok': False, 'error': 'Account name required'}, 400
            acc_obj = ensure_account(user.id, account_name)

        built.append(
            JournalLinePayload(
                account_id=acc_obj.id,
                dc=dc,
                amount=amt,
                memo=memo or None,
                line_no=idx,
            )
        )

    try:
        _validate_balanced(built)
    except JournalBalanceError as exc:
        return journal_error_payload(JOURNAL_ERROR_UNBALANCED, str(exc)), 400

    try:
        entry.date = date_str
        entry.date_parsed = date_parsed
        entry.description = description
        entry.reference = reference or None
        # Keep as draft while line set is being rebuilt.
        entry.posted_at = None

        for existing in list(entry.lines):
            db.session.delete(existing)
        db.session.flush()

        for payload in built:
            db.session.add(
                JournalLine(
                    journal_id=entry.id,
                    account_id=payload.account_id,
                    dc=payload.dc,
                    amount_base=payload.amount,
                    memo=payload.memo or None,
                    line_no=payload.line_no,
                )
            )

        # Finalize only after all lines exist.
        db.session.flush()
        entry.posted_at = _dt.datetime.utcnow()
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        mapped = map_journal_db_exception(exc)
        if mapped:
            error_code, error_message, mapped_status = mapped
            if str(error_code) in {"JOURNAL_ENTRY_NOT_BALANCED", "JOURNAL_NOT_BALANCED"}:
                return journal_error_payload("JOURNAL_NOT_BALANCED", "Journal entry must be balanced before finalizing."), mapped_status
            return journal_error_payload(error_code, error_message), mapped_status
        current_app.logger.exception("journal_update_failed entry_id=%s user_id=%s", entry_id, user.id)
        return journal_error_payload(JOURNAL_ERROR_WRITE_FAILED, "Failed to update entry."), 500

    serialized = _format_journal_entries([entry])
    return {'ok': True, 'entry': serialized[0] if serialized else None}


@accounting_bp.route('/accounting/tb/pdf', methods=['GET'])
def tb_pdf():
    """Generate a Trial Balance PDF for a given month (ym=YYYY-MM).

    Query params:
      - ym: required, YYYY-MM
      - org: optional, organization name for header
      - engine: optional, 'auto' (default), 'weasy', or 'wkhtmltopdf'
      - logo: optional, path/URL to logo image
    Returns application/pdf.
    """
    import datetime as _dt
    from pathlib import Path

    from finance_app import current_user
    from flask import send_file

    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    ok_guard, payload, status = _guard_schema_caps(["journal_report_perf"], user_id=user.id)
    if not ok_guard:
        return payload, status
    source_error = _ensure_ranked_report_source()
    if source_error:
        return source_error

    ym = (request.args.get('ym') or '').strip()
    if not ym:
        return { 'ok': False, 'error': 'Missing ym parameter (YYYY-MM)' }, 400
    period = _parse_month_period(ym)
    if not period:
        return { 'ok': False, 'error': 'Invalid ym parameter' }, 400
    _, _, start, end = period

    selected_ccy = (request.args.get('ccy') or '').strip().upper() or None
    monthly = ledger_trial_balance_month(
        user.id,
        ym,
        currency=selected_ccy,
        include_coverage=False,
    )
    if not isinstance(monthly, dict) or not monthly.get('ok', False):
        return { 'ok': False, 'error': (monthly.get('error') if isinstance(monthly, dict) else 'Failed to compute monthly TB') }, 400

    groups = monthly.get('groups') or {}
    # Flatten categories under each group into rows expected by the PDF generator
    rows = []
    group_map = {
        'asset': 'Asset', 'liability': 'Liability', 'equity': 'Equity', 'expense': 'Expense', 'income': 'Income'
    }
    scope = (request.args.get('scope') or 'folders').strip().lower()
    for gkey, items in groups.items():
        gname = group_map.get(str(gkey).lower(), str(gkey).title())
        for it in (items or []):
            if scope in ('full', 'detail', 'detailed', 'accounts'):
                # Per-account rows
                for acc in (it.get('accounts') or []):
                    rows.append({
                        'group': gname,
                        'category': it.get('category_name') or it.get('name') or '',
                        'account': acc.get('name') or '',
                        'currency': (acc.get('currency') or selected_ccy or 'KRW'),
                        'bd': float(acc.get('bd') or 0.0),
                        'debit': float(acc.get('period_debit') or 0.0),
                        'credit': float(acc.get('period_credit') or 0.0),
                    })
            else:
                # Folder total rows
                rows.append({
                    'group': gname,
                    'category': it.get('category_name') or it.get('name') or '',
                    'account': '',
                    'currency': (selected_ccy or 'KRW'),
                    'bd': float(it.get('bd') or 0.0),
                    'debit': float(it.get('period_debit') or 0.0),
                    'credit': float(it.get('period_credit') or 0.0),
                })

    data = { 'rows': rows }

    # Render PDF into memory
    try:
        from trial_balance_pdf import _format_amount, _prepare_rows, generate_trial_balance_pdf, render_html
    except Exception as e:
        return { 'ok': False, 'error': f'PDF generator not available: {e}' }, 500

    # Force WeasyPrint-only rendering to avoid wkhtmltopdf requirement on macOS
    engine = 'weasy'
    org = (request.args.get('org') or 'Trial Balance').strip() or 'Trial Balance'
    logo = (request.args.get('logo') or '').strip() or None

    try:
        # Prefer WeasyPrint PDF
        out_path = Path('instance') / f"tb_{user.id}_{ym}.pdf"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pages, sha = generate_trial_balance_pdf(
            data=data,
            org=org,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            out_pdf=out_path,
            logo=logo,
        )
        return send_file(
            str(out_path),
            as_attachment=True,
            download_name=f"trial_balance_{ym}.pdf",
            mimetype='application/pdf'
        )
    except Exception:
        # Fallback: serve HTML so the user can save/print to PDF (no banner)
        try:
            rows, totals_fmt, imbalance = _prepare_rows(data)
            ctx = {
                'org': org,
                'period': f"{start.isoformat()} to {end.isoformat()}",
                'generated_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'rows': rows,
                'totals': totals_fmt,
                'out_of_balance': abs(imbalance) > 0.005,
                'out_of_balance_str': _format_amount(imbalance, 'KRW'),
                'logo': logo,
            }
            html = render_html(ctx)
            from flask import Response
            headers = { 'Content-Disposition': f'inline; filename=trial_balance_{ym}.html' }
            return Response(html, status=200, mimetype='text/html', headers=headers)
        except Exception as e2:
            return { 'ok': False, 'error': f'Failed to render PDF and HTML fallback: {e2}' }, 500


@accounting_bp.route('/accounting/journal/delete/<int:entry_id>', methods=['POST'])
def delete_journal_entry(entry_id):
    """Delete a journal entry belonging to the current user."""
    if not _check_csrf():
        return {"ok": False, "error": "CSRF token missing or invalid"}, 400
    from finance_app import current_user, db
    try:
        from finance_app import JournalEntry
    except Exception:
        return {'ok': False, 'error': 'Journal model not available'}, 500

    user = current_user()
    if not user:
        return {"ok": False, "error": "Unauthorized"}, 401
    ok_guard, payload, status = _guard_schema_caps(["journal_integrity"], user_id=user.id)
    if not ok_guard:
        return payload, status

    entry = JournalEntry.query.get_or_404(entry_id)
    if entry.user_id != user.id:
        return {"ok": False, "error": "Forbidden"}, 403

    try:
        db.session.delete(entry)
        db.session.commit()
        return {'ok': True}
    except Exception as exc:
        db.session.rollback()
        mapped = map_journal_db_exception(exc)
        if mapped:
            error_code, error_message, mapped_status = mapped
            return journal_error_payload(error_code, error_message), mapped_status
        current_app.logger.exception("journal_delete_failed entry_id=%s user_id=%s", entry_id, user.id)
        return journal_error_payload(JOURNAL_ERROR_WRITE_FAILED, "Failed to delete entry."), 500


@accounting_bp.route('/first_tb_month', methods=['GET'])
def first_tb_month():
    from finance_app import TrialBalanceSetting, current_user
    user = current_user()
    if not user:
        return {"error": "User not authenticated."}, 401

    # Fetch the first trial balance month from the database
    tbs = TrialBalanceSetting.query.filter_by(user_id=user.id).first()
    if not tbs or not tbs.first_month:
        return {"error": "No trial balance data available."}, 404

    return {"first_tb_month": tbs.first_month}, 200
