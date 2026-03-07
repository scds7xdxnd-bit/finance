"""Service helpers for creating journal entries from transaction payloads."""

from __future__ import annotations

import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Tuple

from finance_app import _parse_date_tuple
from finance_app.extensions import db
from finance_app.models.accounting_models import Transaction, TransactionJournalLink
from finance_app.services.account_service import ensure_account
from finance_app.services.journal_service import (
    JournalBalanceError,
    JournalLinePayload,
    create_journal_entry,
)
from flask import current_app


def save_transaction_payload(user_id: int, data: dict) -> Tuple[bool, dict, int]:
    """Create a JournalEntry with JournalLine rows from JSON payload."""
    date_raw = (data.get("date") or "").strip()
    description = (data.get("description") or "").strip()
    lines = data.get("lines") or []
    if not description:
        return False, {"ok": False, "error": "Description is required"}, 400
    if not isinstance(lines, list) or len(lines) < 2:
        return False, {"ok": False, "error": "At least one debit and one credit line are required"}, 400

    y, m, d = _parse_date_tuple(date_raw)
    date_parsed = None
    date_str = date_raw
    try:
        if y and m and d:
            date_parsed = datetime.date(y, m, d)
            date_str = f"{y}/{str(m).zfill(2)}/{str(d).zfill(2)}"
    except Exception:
        date_parsed = None

    line_payloads: list[JournalLinePayload] = []
    legacy_lines: list[dict] = []
    line_no = 1
    for l in lines:
        dc = (l.get("dc") or "D").upper()
        if dc not in ("D", "C"):
            continue
        name = (l.get("account") or "").strip()
        if not name:
            continue
        try:
            amt = Decimal(str(l.get("amount") or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except Exception:
            amt = Decimal("0.00")
        if amt <= 0:
            continue
        acc = ensure_account(user_id, name)
        line_payloads.append(
            JournalLinePayload(
                dc=dc,
                account_id=acc.id,
                amount=amt,
                memo=(l.get("memo") or ""),
                line_no=line_no,
            )
        )
        legacy_lines.append(
            {
                "dc": dc,
                "account_id": acc.id,
                "account_name": acc.name,
                "amount": float(amt),
            }
        )
        line_no += 1
    if not line_payloads:
        return False, {"ok": False, "error": "No valid journal lines provided"}, 400

    write_mode = str(current_app.config.get("LEDGER_WRITE_MODE") or "journal").strip().lower()
    if write_mode not in {"journal", "dual", "legacy"}:
        write_mode = "journal"

    def _build_legacy_pair():
        debit = next((ln for ln in legacy_lines if ln["dc"] == "D"), None)
        credit = next((ln for ln in legacy_lines if ln["dc"] == "C"), None)
        if not debit or not credit:
            return None
        if len(legacy_lines) != 2:
            return None
        return debit, credit

    try:
        if write_mode == "legacy":
            pair = _build_legacy_pair()
            if not pair:
                return False, {"ok": False, "error": "Legacy mode only supports exactly one debit and one credit line"}, 400
            debit, credit = pair
            tx = Transaction(
                date=date_str,
                date_parsed=date_parsed,
                description=description,
                debit_account=debit["account_name"],
                debit_amount=float(debit["amount"]),
                credit_account=credit["account_name"],
                credit_amount=float(credit["amount"]),
                user_id=user_id,
                debit_account_id=int(debit["account_id"]),
                credit_account_id=int(credit["account_id"]),
            )
            db.session.add(tx)
            db.session.commit()
            return True, {"ok": True, "mode": "legacy", "transaction_id": tx.id, "entry_id": None}, 200

        entry = create_journal_entry(
            user_id=user_id,
            date=date_str,
            date_parsed=date_parsed,
            description=description,
            reference=None,
            lines=line_payloads,
        )
        tx = None
        if write_mode == "dual":
            pair = _build_legacy_pair()
            if not pair:
                raise JournalBalanceError("Dual mode requires exactly one debit and one credit line.")
            debit, credit = pair
            tx = Transaction(
                date=date_str,
                date_parsed=date_parsed,
                description=description,
                debit_account=debit["account_name"],
                debit_amount=float(debit["amount"]),
                credit_account=credit["account_name"],
                credit_amount=float(credit["amount"]),
                user_id=user_id,
                debit_account_id=int(debit["account_id"]),
                credit_account_id=int(credit["account_id"]),
            )
            db.session.add(tx)
            db.session.flush()
            db.session.add(
                TransactionJournalLink(
                    user_id=user_id,
                    transaction_id=tx.id,
                    journal_entry_id=entry.id,
                    source="strong_dual_write",
                )
            )
        db.session.commit()
        return True, {"ok": True, "entry_id": entry.id, "mode": write_mode, "transaction_id": (tx.id if tx else None)}, 200
    except JournalBalanceError as e:
        db.session.rollback()
        return False, {"ok": False, "error": str(e)}, 400
    except Exception as e:
        db.session.rollback()
        return False, {"ok": False, "error": f"Failed to save entry: {e}"}, 500
