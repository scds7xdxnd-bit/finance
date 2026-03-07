"""Canonical report query surface (journal-only)."""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Sequence

from finance_app.models.accounting_models import (
    Account,
    AccountCategory,
    AccountOpeningBalance,
    JournalEntry,
    JournalLine,
)
from finance_app.services.ledger_convergence_service import compute_convergence_metrics
from finance_app.services.trial_balance_service import monthly as tb_monthly

_SOURCE_POLICY = {
    "mode": "journal",
    "mixed_mode_allowed": False,
    "legacy_rows_included_in_totals": False,
}


def _coverage_payload(user_id: int) -> Dict[str, Any]:
    try:
        metrics = compute_convergence_metrics(user_id=user_id)
    except Exception:
        return {
            "available": False,
            "error": "coverage_metrics_unavailable",
        }
    return {
        "available": True,
        "coverage_count": float(metrics.get("coverage_count", 0.0) or 0.0),
        "coverage_amount": float(metrics.get("coverage_amount", 0.0) or 0.0),
        "total_legacy_tx": int(metrics.get("total_legacy_tx", 0) or 0),
        "linked_legacy_tx": int(metrics.get("linked_legacy_tx", 0) or 0),
        "total_legacy_amount": float(metrics.get("total_legacy_amount", 0.0) or 0.0),
        "linked_legacy_amount": float(metrics.get("linked_legacy_amount", 0.0) or 0.0),
        "unlinked_recent_90d_count": int(metrics.get("unlinked_recent_90d_count", 0) or 0),
    }


def _canonical_meta(user_id: int, include_coverage: bool) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"source": dict(_SOURCE_POLICY)}
    if include_coverage:
        payload["coverage"] = _coverage_payload(user_id=user_id)
    return payload


def trial_balance_month(
    user_id: int,
    ym: str,
    currency: str | None = None,
    *,
    include_coverage: bool = True,
) -> Dict[str, Any]:
    """Canonical monthly TB query (journal source-of-truth, no mixed rows)."""
    result = tb_monthly(user_id, ym, currency=currency)
    if not isinstance(result, dict):
        return {"ok": False, "error": "Invalid trial balance payload"}
    if not result.get("ok"):
        return result
    out = dict(result)
    out.update(_canonical_meta(user_id=user_id, include_coverage=include_coverage))
    return out


def account_balance_as_of(
    user_id: int,
    account_id: int,
    as_of: _dt.date,
    currency: str | None = None,
    *,
    include_coverage: bool = True,
) -> Dict[str, Any]:
    """Return account balance as-of date using journal lines and opening balance."""
    account = Account.query.filter_by(id=account_id, user_id=user_id, active=True).first()
    if not account:
        return {"ok": False, "error": "Account not found"}

    req_currency = (currency or "").upper() or None
    account_currency = (account.currency_code or "KRW").upper()
    if req_currency and account_currency != req_currency:
        payload = {
            "ok": True,
            "account_id": int(account_id),
            "as_of": as_of.isoformat(),
            "balance": 0.0,
            "currency": req_currency,
        }
        payload.update(_canonical_meta(user_id=user_id, include_coverage=include_coverage))
        return payload

    category = AccountCategory.query.filter_by(id=account.category_id).first() if account.category_id else None
    group = ((category.tb_group if category else "") or "").strip().lower()
    credit_nature = group in {"liability", "equity", "income"}

    opening = AccountOpeningBalance.query.filter_by(user_id=user_id, account_id=account_id).first()
    opening_amt = float(opening.amount or 0.0) if opening else 0.0

    rows = (
        JournalLine.query.join(JournalEntry, JournalEntry.id == JournalLine.journal_id)
        .filter(JournalEntry.user_id == user_id)
        .filter(JournalLine.account_id == account_id)
        .filter(JournalEntry.date_parsed != None)  # noqa: E711
        .filter(JournalEntry.date_parsed <= as_of)
        .all()
    )
    debit = 0.0
    credit = 0.0
    for row in rows:
        amt = float(row.amount_base or 0.0)
        if (row.dc or "").upper() == "D":
            debit += amt
        else:
            credit += amt

    balance = (opening_amt + credit - debit) if credit_nature else (opening_amt + debit - credit)
    payload = {
        "ok": True,
        "account_id": int(account_id),
        "as_of": as_of.isoformat(),
        "balance": round(balance, 2),
        "currency": account_currency,
    }
    payload.update(_canonical_meta(user_id=user_id, include_coverage=include_coverage))
    return payload


def statement_period(
    user_id: int,
    start_date: _dt.date,
    end_date: _dt.date,
    currency: str | None = None,
    cash_folder_ids: Sequence[int] | None = None,
    *,
    include_coverage: bool = True,
) -> Dict[str, Any]:
    """Build statements for a period from canonical monthly TB data (journal-only)."""
    from statements_pdf import (
        build_balance_sheet_data,
        build_cashflow_statement_data,
        build_income_statement_data,
    )

    if start_date > end_date:
        return {"ok": False, "error": "Invalid period: start_date must be <= end_date"}

    ym = f"{end_date.year:04d}-{end_date.month:02d}"
    monthly = trial_balance_month(
        user_id,
        ym,
        currency=currency,
        include_coverage=False,
    )
    if not isinstance(monthly, dict) or not monthly.get("ok"):
        return {
            "ok": False,
            "error": (monthly.get("error") if isinstance(monthly, dict) else "Unable to compute monthly data"),
        }

    folder_lookup: Dict[int, str] = {}
    for folder in (monthly.get("groups", {}).get("asset") or []):
        cid = folder.get("category_id")
        if cid is None:
            continue
        try:
            folder_lookup[int(cid)] = folder.get("category_name") or folder.get("name") or "Asset Folder"
        except Exception:
            continue

    normalized_cash_folders: List[int] = []
    for raw in (cash_folder_ids or []):
        try:
            normalized_cash_folders.append(int(raw))
        except Exception:
            continue

    income_statement = build_income_statement_data(monthly, end_date)
    balance_statement = build_balance_sheet_data(monthly, end_date)
    cashflow_statement = build_cashflow_statement_data(
        monthly,
        cash_folder_ids=normalized_cash_folders,
        folder_lookup=folder_lookup,
        statement_date=end_date,
    )

    payload: Dict[str, Any] = {
        "ok": True,
        "ym": ym,
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
        "statements": {
            "income": income_statement,
            "balance": balance_statement,
            "cashflow": cashflow_statement,
        },
        "initialized_on": monthly.get("initialized_on"),
        "message": monthly.get("message"),
        "cash_folder_options": [
            {
                "id": cid,
                "name": name,
            }
            for cid, name in sorted(folder_lookup.items(), key=lambda item: (item[1] or "").lower())
        ],
        "selected_cash_folders": sorted(set(normalized_cash_folders)),
    }
    payload.update(_canonical_meta(user_id=user_id, include_coverage=include_coverage))
    return payload
