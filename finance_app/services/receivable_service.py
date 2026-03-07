"""Receivable-related helpers."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from finance_app.extensions import db
from finance_app.models.accounting_models import (
    Account,
    AccountCategory,
    ReceivableManualEntry,
    ReceivableTracker,
)

# --- Classification helpers ----------------------------------------------------


def classify_receivable_category(cat) -> str | None:
    """Classify categories into receivable/debt buckets based on name heuristics."""
    name = ((cat.name or "").strip().lower()) if cat else ""
    if "receivable" in name:
        return "receivable"
    if "short" in name and ("debt" in name or "loan" in name or "liability" in name):
        return "debt"
    if "short-term" in name and "debt" in name:
        return "debt"
    return None


def resolve_receivable_scope(user_id: int) -> tuple[dict, dict, dict]:
    """
    Return (scoped_cats, scoped_accounts, cat_map) for receivable/debt buckets.

    scoped_cats: {'receivable': [cat_id, ...], 'debt': [cat_id, ...]}
    scoped_accounts: {'receivable': set(account_ids), 'debt': set(account_ids)}
    cat_map: {cat_id: AccountCategory}
    """
    categories = AccountCategory.query.filter_by(user_id=user_id).all()
    cat_map = {c.id: c for c in categories}
    scoped_cats = {"receivable": [], "debt": []}
    for cat in categories:
        kind = classify_receivable_category(cat)
        if kind:
            scoped_cats[kind].append(cat.id)

    scoped_accounts = {"receivable": set(), "debt": set()}
    all_cat_ids = scoped_cats["receivable"] + scoped_cats["debt"]
    if all_cat_ids:
        rows = Account.query.filter(
            Account.user_id == user_id,
            Account.active.is_(True),
            Account.category_id.in_(all_cat_ids),
        ).all()
        for acc in rows:
            kind = classify_receivable_category(cat_map.get(acc.category_id)) if acc.category_id else None
            if kind:
                scoped_accounts[kind].add(acc.id)

    return scoped_cats, scoped_accounts, cat_map


def coerce_number(value) -> float:
    """Best-effort float conversion."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

# Flow labels shared with the accounting blueprint
_BASE_FLOWS = {"loan_provided", "debt_received"}
_SETTLEMENT_FLOWS = {"loan_repaid", "debt_paid"}


def _to_iso(date_obj, fallback=None):
    if isinstance(date_obj, date):
        return date_obj.isoformat()
    if fallback:
        try:
            y, m, d = fallback(date_obj)
            if y and m and d:
                return f"{y:04d}-{m:02d}-{d:02d}"
        except Exception:
            return None
    return None


def _flow_for_line(kind: str, direction: str) -> str:
    direction = (direction or "").upper()
    if kind == "receivable":
        return "loan_provided" if direction == "D" else "loan_repaid"
    return "debt_received" if direction == "C" else "debt_paid"


def _ensure_tracker(user_id: int, line, account, kind: str) -> ReceivableTracker:
    tracker = ReceivableTracker.query.filter_by(user_id=user_id, journal_line_id=line.id).first()
    if not tracker:
        tracker = ReceivableTracker(
            user_id=user_id,
            journal_id=line.journal_id,
            journal_line_id=line.id,
            account_id=account.id,
            category=kind,
        )
        db.session.add(tracker)
    tracker.category = kind
    tracker.journal_id = line.journal_id
    tracker.account_id = account.id
    tracker.ignored = False
    return tracker


def serialize_receivable_line(user_id: int, line, entry, account, kind: str, cat_map, tracker, date_parser):
    """Serialize a journal receivable/debt line to dict for API responses."""
    default_currency = (line.currency_code or (account.currency_code if account else None) or "KRW") or "KRW"
    currency = (default_currency or "KRW").upper()
    amount_tx = line.amount_tx if getattr(line, "amount_tx", None) not in (None, "") else None
    amount_primary = amount_tx if amount_tx is not None else line.amount_base
    amount = abs(coerce_number(amount_primary))
    base_amount = abs(coerce_number(line.amount_base))

    contact = (tracker.contact_name if tracker and tracker.contact_name else "").strip()
    txn_value = tracker.transaction_value if tracker and tracker.transaction_value not in (None, "") else amount
    txn_value = coerce_number(txn_value)

    amount_paid = tracker.amount_paid if tracker and tracker.amount_paid not in (None, "") else 0.0
    amount_paid = coerce_number(amount_paid)

    default_due = _to_iso(entry.date_parsed, lambda _: date_parser(entry.date) if entry and entry.date else None)
    due_iso = tracker.due_date.isoformat() if tracker and tracker.due_date else default_due

    payment_dates = []
    if tracker and tracker.payment_dates:
        try:
            parsed = json.loads(tracker.payment_dates)
            if isinstance(parsed, list):
                payment_dates = [str(it) for it in parsed if it]
            elif parsed:
                payment_dates = [str(parsed)]
        except Exception:
            payment_dates = [tracker.payment_dates]

    remaining_raw = tracker.remaining_amount if tracker and tracker.remaining_amount not in (None, "") else None
    if remaining_raw is None:
        remaining_raw = txn_value - amount_paid
    remaining = max(0.0, round(coerce_number(remaining_raw), 2))

    status = (tracker.status or "").upper() if tracker and tracker.status else ""
    if remaining <= 0.0005:
        remaining = 0.0
        status = "PAID"
    elif status not in ("PAID", "UNPAID"):
        status = "UNPAID"

    direction = (line.dc or "").upper()
    if kind == "receivable":
        if direction == "D":
            flow = "loan_provided"
            flow_label = "Loan provided / receivable created"
        else:
            flow = "loan_repaid"
            flow_label = "Loan repaid / receivable collected"
    else:
        if direction == "C":
            flow = "debt_received"
            flow_label = "Debt received / liability increased"
        else:
            flow = "debt_paid"
            flow_label = "Debt repaid / liability reduced"

    cat = cat_map.get(account.category_id) if account else None

    return {
        "line_id": line.id,
        "journal_id": entry.id if entry else None,
        "type": kind,
        "account_id": account.id if account else None,
        "account_name": account.name if account else "",
        "account_code": account.code if account else None,
        "category_id": account.category_id if account else None,
        "category_name": cat.name if cat else "",
        "currency": currency,
        "amount": round(amount, 2),
        "amount_base": round(base_amount, 2),
        "direction": direction,
        "entry_date": entry.date if entry else None,
        "date_iso": entry.date_parsed.isoformat() if entry and entry.date_parsed else _to_iso(entry.date if entry else None, date_parser),
        "description": entry.description if entry else "",
        "reference": entry.reference if entry else "",
        "memo": line.memo or "",
        "contact_name": contact,
        "transaction_value": round(txn_value, 2),
        "amount_paid": round(amount_paid, 2),
        "due_date": due_iso,
        "payment_dates": payment_dates,
        "remaining_amount": remaining,
        "status": status,
        "tracker_id": tracker.id if tracker else None,
        "is_new": tracker is None,
        "is_saved": bool(contact),
        "is_paid": status == "PAID",
        "flow": flow,
        "flow_label": flow_label,
        "linked_line_id": tracker.linked_line_id if tracker else None,
        "link_kind": tracker.link_kind if tracker else None,
        "linked_summary": None,
        "linked_entries": [],
        "ignored": bool(tracker.ignored) if tracker else False,
        "default_transaction_value": amount,
        "default_due_date": default_due,
        "default_payment_dates": payment_dates,
    }


def serialize_manual_receivable(manual, account, kind, cat_map):
    """Serialize a manual receivable/debt entry to dict."""
    currency = (manual.currency_code or account.currency_code or "KRW").upper()
    amount = abs(coerce_number(manual.amount or manual.transaction_value or 0.0))
    txn_value = coerce_number(manual.transaction_value if manual.transaction_value not in (None, "") else amount)
    date_iso = manual.date_parsed.isoformat() if isinstance(manual.date_parsed, date) else (manual.date or None)
    payment_dates = []
    if manual.payment_dates:
        try:
            parsed = json.loads(manual.payment_dates)
            if isinstance(parsed, list):
                payment_dates = [str(it) for it in parsed if it]
            elif parsed:
                payment_dates = [str(parsed)]
        except Exception:
            payment_dates = [manual.payment_dates]
    due_iso = manual.due_date.isoformat() if manual.due_date else date_iso
    status = (manual.status or "").upper()
    if status not in ("PAID", "UNPAID"):
        status = "UNPAID"
    remaining = 0.0 if status == "PAID" else txn_value
    flow = "loan_provided" if kind == "receivable" else "debt_received"
    flow_label = "Loan provided / receivable created" if kind == "receivable" else "Debt received / liability increased"
    cat = cat_map.get(account.category_id) if account else None
    saved = True
    line_id = f"manual-{manual.id}"
    return {
        "line_id": line_id,
        "journal_id": None,
        "manual_entry_id": manual.id,
        "is_manual": True,
        "type": kind,
        "account_id": account.id if account else None,
        "account_name": account.name if account else "",
        "account_code": account.code if account else None,
        "category_id": account.category_id if account else None,
        "category_name": cat.name if cat else "",
        "currency": currency,
        "amount": round(amount, 2),
        "amount_base": round(amount, 2),
        "direction": "D" if kind == "receivable" else "C",
        "entry_date": manual.date,
        "date_iso": date_iso,
        "description": manual.description or "",
        "reference": manual.reference or "",
        "memo": manual.memo or "",
        "contact_name": manual.contact_name or "",
        "transaction_value": round(txn_value, 2),
        "amount_paid": 0.0,
        "due_date": due_iso,
        "payment_dates": payment_dates,
        "remaining_amount": round(remaining, 2),
        "status": status,
        "tracker_id": None,
        "is_new": False,
        "is_saved": saved,
        "is_paid": status == "PAID",
        "flow": flow,
        "flow_label": flow_label,
        "linked_line_id": None,
        "link_kind": None,
        "linked_summary": None,
        "linked_entries": [],
        "ignored": False,
        "default_transaction_value": txn_value,
        "default_due_date": due_iso,
        "default_payment_dates": payment_dates,
    }


def clear_links(user_id: int, line_id: int, tracker: ReceivableTracker) -> None:
    tracker.linked_line_id = None
    tracker.link_kind = None
    siblings = ReceivableTracker.query.filter_by(user_id=user_id, linked_line_id=line_id).all()
    for sibling in siblings:
        sibling.linked_line_id = None
        sibling.link_kind = None


def remove_link(user_id: int, tracker: ReceivableTracker, line_flow: str, target_id: Optional[int]) -> None:
    if target_id is None:
        target_id = tracker.linked_line_id if line_flow in _SETTLEMENT_FLOWS else None
    if not target_id:
        return
    target_tracker = ReceivableTracker.query.filter_by(user_id=user_id, journal_line_id=target_id).first()
    if line_flow in _SETTLEMENT_FLOWS and tracker.linked_line_id == target_id:
        tracker.linked_line_id = None
        tracker.link_kind = None
    if line_flow in _BASE_FLOWS and target_tracker and target_tracker.linked_line_id == tracker.journal_line_id:
        target_tracker.linked_line_id = None
        target_tracker.link_kind = None


def link_receivable_lines(
    *,
    user_id: int,
    line,
    account,
    kind: str,
    action: str,
    linked_line=None,
    linked_account=None,
    linked_kind: Optional[str] = None,
    link_kind: Optional[str] = None,
) -> dict:
    """
    Link or unlink receivable trackers between journal lines.
    Returns {"ok": bool, "error"?: str}.
    """
    tracker = _ensure_tracker(user_id, line, account, kind)
    line_flow = _flow_for_line(kind, line.dc)

    if action == "clear":
        clear_links(user_id, line.id, tracker)
        return {"ok": True}

    if action == "remove":
        remove_link(user_id, tracker, line_flow, linked_line.id if linked_line else None)
        return {"ok": True}

    if action not in ("set", "add"):
        return {"ok": False, "error": "Invalid action"}
    if not linked_line or not linked_account or not linked_kind:
        return {"ok": False, "error": "linked_line and linked account/kind are required"}

    other_flow = _flow_for_line(linked_kind, linked_line.dc)
    default_link_kind = "installment" if (line_flow in _BASE_FLOWS or other_flow in _BASE_FLOWS) else "paired"
    lk_value = link_kind or default_link_kind

    if line_flow in _BASE_FLOWS and other_flow in _SETTLEMENT_FLOWS:
        payment_tracker = _ensure_tracker(user_id, linked_line, linked_account, linked_kind)
        payment_tracker.linked_line_id = line.id
        payment_tracker.link_kind = lk_value
        tracker.linked_line_id = None
        tracker.link_kind = None
    elif line_flow in _SETTLEMENT_FLOWS and other_flow in _BASE_FLOWS:
        tracker.linked_line_id = linked_line.id
        tracker.link_kind = lk_value
        other_tracker = _ensure_tracker(user_id, linked_line, linked_account, linked_kind)
        other_tracker.linked_line_id = None
        other_tracker.link_kind = None
    else:
        return {"ok": False, "error": "Transactions are not compatible for linking"}

    return {"ok": True}


def create_manual_receivable(
    *,
    user_id: int,
    account_id: int,
    direction: str,
    amount: Decimal,
    currency: str,
    description: str,
    reference: Optional[str],
    memo: str,
    contact_name: str,
    transaction_value: float,
    entry_date: date,
    date_str: str,
    due_date: Optional[date],
    payment_dates: Iterable[str],
    notes: str,
) -> ReceivableManualEntry:
    """Persist a manual receivable/debt entry."""
    normalized_dates = [d for d in payment_dates if d]
    manual = ReceivableManualEntry(
        user_id=user_id,
        account_id=account_id,
        category=direction,
        amount=amount,
        currency_code=currency,
        description=description,
        reference=reference,
        memo=memo,
        contact_name=contact_name,
        transaction_value=transaction_value,
        due_date=due_date,
        payment_dates=json.dumps(normalized_dates),
        notes=notes,
        date=date_str,
        date_parsed=entry_date,
        status="UNPAID",
    )
    db.session.add(manual)
    db.session.commit()
    return manual
