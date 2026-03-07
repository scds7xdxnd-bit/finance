"""Journal entry helpers to centralize validation and creation."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy import and_, func, or_

from finance_app import _parse_date_tuple
from finance_app.extensions import db
from finance_app.models.accounting_models import JournalEntry, JournalLine


class JournalBalanceError(Exception):
    """Raised when journal lines are missing or not balanced."""


@dataclass
class JournalLinePayload:
    dc: str
    account_id: int
    amount: Decimal
    currency_code: str | None = None
    memo: str | None = None
    line_no: int | None = None


def _validate_balanced(lines: Sequence[JournalLinePayload], tolerance: Decimal = Decimal("0.005")) -> None:
    if not lines:
        raise JournalBalanceError("No journal lines provided.")
    debit_total = sum((line.amount for line in lines if line.dc.upper() == "D"), Decimal("0.00"))
    credit_total = sum((line.amount for line in lines if line.dc.upper() == "C"), Decimal("0.00"))
    if debit_total == Decimal("0.00") or credit_total == Decimal("0.00"):
        raise JournalBalanceError("Debits and credits must both be non-zero.")
    if abs(debit_total - credit_total) > tolerance:
        raise JournalBalanceError("Debits and credits are not balanced.")


def create_journal_entry(
    *,
    user_id: int,
    date: str | None,
    date_parsed,
    description: str | None,
    reference: str | None,
    lines: Iterable[JournalLinePayload],
) -> JournalEntry:
    """Create a balanced JournalEntry with associated JournalLine rows."""
    payloads = list(lines)
    _validate_balanced(payloads)

    entry = JournalEntry(
        user_id=user_id,
        date=date,
        date_parsed=date_parsed,
        description=description,
        reference=reference,
    )
    db.session.add(entry)
    db.session.flush()

    for idx, line in enumerate(payloads, start=1):
        line_no = line.line_no if line.line_no is not None else idx
        jl = JournalLine(
            journal_id=entry.id,
            account_id=line.account_id,
            dc=line.dc.upper(),
            amount_base=Decimal(line.amount),
            currency_code=line.currency_code,
            memo=line.memo,
            line_no=line_no,
        )
        db.session.add(jl)

    return entry


def _format_entries(entries: Sequence[JournalEntry]) -> list[dict]:
    """Serialize JournalEntry rows with related lines for JSON responses."""
    if not entries:
        return []

    entry_ids = [e.id for e in entries]
    lines = (
        JournalLine.query.filter(JournalLine.journal_id.in_(entry_ids))
        .order_by(JournalLine.journal_id.asc(), JournalLine.line_no.asc(), JournalLine.id.asc())
        .all()
    )
    acc_ids = {ln.account_id for ln in lines}
    acc_map = {}
    if acc_ids:
        from finance_app import Account

        rows = Account.query.filter(Account.id.in_(acc_ids)).all()
        for row in rows:
            acc_map[row.id] = row

    from collections import defaultdict

    by_entry = defaultdict(list)
    for ln in lines:
        by_entry[ln.journal_id].append(ln)

    formatted = []
    for entry in entries:
        iso = ""
        try:
            if entry.date_parsed:
                iso = entry.date_parsed.strftime("%Y-%m-%d")
            else:
                y, m, d = _parse_date_tuple(entry.date or "")
                if y and m and d:
                    iso = f"{y:04d}-{m:02d}-{d:02d}"
        except Exception:
            iso = ""
        debit_total = 0.0
        credit_total = 0.0
        lines_payload = []
        for ln in by_entry.get(entry.id, []):
            amt = float(ln.amount_base or 0.0)
            if (ln.dc or "").upper() == "D":
                debit_total += amt
            else:
                credit_total += amt
            acc = acc_map.get(ln.account_id)
            lines_payload.append(
                {
                    "id": ln.id,
                    "account_id": ln.account_id,
                    "account_name": acc.name if acc else "",
                    "account_code": acc.code if acc else None,
                    "dc": (ln.dc or "").upper(),
                    "amount": amt,
                    "memo": ln.memo or "",
                    "line_no": ln.line_no or 0,
                }
            )
        formatted.append(
            {
                "id": entry.id,
                "date": entry.date,
                "date_iso": iso,
                "description": entry.description,
                "reference": entry.reference,
                "line_count": len(lines_payload),
                "debit_total": debit_total,
                "credit_total": credit_total,
                "lines": lines_payload,
            }
        )
    return formatted


def list_entries(
    *,
    user_id: int,
    q: str | None = None,
    start: str | None = None,
    end: str | None = None,
    account_id: int | None = None,
    page: int = 1,
    per_page: int = 25,
) -> dict:
    """List journal entries with optional filters and pagination."""
    query = JournalEntry.query.filter(JournalEntry.user_id == user_id)

    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(JournalEntry.description).like(like), func.lower(JournalEntry.reference).like(like)))

    if start:
        try:
            start_date = _dt.datetime.strptime(start, "%Y-%m-%d").date()
            start_str = start_date.strftime("%Y/%m/%d")
            query = query.filter(
                or_(JournalEntry.date_parsed >= start_date, and_(JournalEntry.date_parsed == None, JournalEntry.date >= start_str))  # type: ignore  # noqa: E711
            )
        except Exception:
            pass

    if end:
        try:
            end_date = _dt.datetime.strptime(end, "%Y-%m-%d").date()
            end_str = end_date.strftime("%Y/%m/%d")
            query = query.filter(
                or_(JournalEntry.date_parsed <= end_date, and_(JournalEntry.date_parsed == None, JournalEntry.date <= end_str))  # type: ignore  # noqa: E711
            )
        except Exception:
            pass

    if account_id:
        try:
            aid = int(account_id)
            query = query.join(JournalLine).filter(JournalLine.account_id == aid).distinct()
        except Exception:
            pass

    if page < 1:
        page = 1
    if per_page < 5:
        per_page = 5
    if per_page > 100:
        per_page = 100

    total = query.count()
    entries = (
        query.order_by(JournalEntry.date_parsed.desc(), JournalEntry.date.desc(), JournalEntry.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    data = _format_entries(entries)
    pages = (total + per_page - 1) // per_page if per_page else 1
    return {"ok": True, "entries": data, "page": page, "pages": pages, "total": total}
