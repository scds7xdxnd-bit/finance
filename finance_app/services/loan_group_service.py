"""Loan group service helpers."""
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import func

from finance_app.extensions import db
from finance_app.models.accounting_models import Account, JournalEntry, JournalLine, LoanGroup, LoanGroupLink


def create_group(user_id: int, name: str, direction: str, counterparty: str | None, currency: str, principal_amount, start_date, notes: str | None = None) -> LoanGroup:
    group = LoanGroup(
        user_id=user_id,
        name=name,
        direction=direction,
        counterparty=counterparty,
        currency=currency,
        principal_amount=principal_amount,
        start_date=start_date,
        notes=notes,
    )
    db.session.add(group)
    db.session.commit()
    return group


def update_group(user_id: int, group_id: str, **updates) -> Optional[LoanGroup]:
    group = LoanGroup.query.filter_by(id=group_id, user_id=user_id).first()
    if not group:
        return None
    for k, v in updates.items():
        setattr(group, k, v)
    db.session.commit()
    return group


def delete_group(user_id: int, group_id: str) -> bool:
    group = LoanGroup.query.filter_by(id=group_id, user_id=user_id).first()
    if not group:
        return False
    db.session.delete(group)
    db.session.commit()
    return True


def _loan_group_flow(direction: str, line_dc: str) -> str:
    if direction == "receivable":
        return "inflow" if line_dc == "D" else "outflow"
    return "inflow" if line_dc == "C" else "outflow"


def _loan_group_status_from_balance(remaining: Decimal) -> str:
    if remaining > Decimal("0.005"):
        return "open"
    if remaining < Decimal("-0.005"):
        return "overpaid"
    return "closed"


def group_summary(user_id: int, group: LoanGroup) -> Tuple[dict, List[dict]]:
    links = (
        LoanGroupLink.query.filter_by(user_id=user_id, loan_group_id=group.id)
        .join(JournalLine, LoanGroupLink.journal_line_id == JournalLine.id)
        .join(JournalEntry, JournalLine.journal_id == JournalEntry.id)
        .order_by(JournalEntry.date_parsed.asc().nullsfirst(), JournalEntry.id.asc())
        .all()
    )
    entries = []
    remaining = Decimal(group.principal_amount or 0)
    total_in = Decimal("0")
    total_out = Decimal("0")
    total_repaid = Decimal("0")
    for link in links:
        line = link.journal_line
        entry = link.journal_line.journal
        flow = _loan_group_flow(group.direction, line.dc)
        amt = Decimal(link.linked_amount or line.amount_base or 0)
        if flow == "inflow":
            total_in += amt
            remaining += amt
        else:
            total_out += amt
            total_repaid += amt
            remaining -= amt
        entries.append(
            {
                "id": link.id,
                "journal_id": entry.id if entry else None,
                "date": entry.date if entry else None,
                "date_parsed": entry.date_parsed.isoformat() if entry and entry.date_parsed else None,
                "description": entry.description if entry else "",
                "account": line.account.name if getattr(line, "account", None) else None,
                "dc": line.dc,
                "amount": amt,
                "linked_amount": link.linked_amount,
                "balance_after": remaining,
                "flow": flow,
            }
        )
    status = _loan_group_status_from_balance(remaining)
    summary = {
        "principal": Decimal(group.principal_amount or 0),
        "total_in": total_in,
        "total_out": total_out,
        "repaid": total_repaid,
        "remaining": remaining,
        "status": status,
    }
    return summary, entries


def get_group(user_id: int, group_id: str) -> Optional[LoanGroup]:
    return LoanGroup.query.filter_by(user_id=user_id, id=group_id).first()


def list_groups(user_id: int) -> List[LoanGroup]:
    return LoanGroup.query.filter_by(user_id=user_id).order_by(LoanGroup.created_at.desc()).all()


def link_journal_lines(user_id: int, group_id: str, line_ids: List[int], amounts: List[Decimal]) -> Tuple[List[LoanGroupLink], str | None]:
    group = get_group(user_id, group_id)
    if not group:
        return [], "Group not found"
    created: List[LoanGroupLink] = []
    for line_id, amt in zip(line_ids, amounts):
        line = db.session.get(JournalLine, line_id)
        if not line or line.journal.user_id != user_id:
            return [], "Journal line not found or unauthorized"
        link = LoanGroupLink(
            user_id=user_id,
            loan_group_id=group.id,
            journal_line_id=line.id,
            linked_amount=amt,
        )
        db.session.add(link)
        created.append(link)
    db.session.commit()
    return created, None


def unlink(user_id: int, link_id: str) -> Optional[LoanGroup]:
    link = LoanGroupLink.query.filter_by(user_id=user_id, id=link_id).first()
    if not link:
        return None
    group = link.loan_group
    db.session.delete(link)
    db.session.commit()
    return group


def suggest_allocation(
    user_id: int,
    journal_line_id: int,
    direction: str,
    counterparty: str | None = None,
    cap: Decimal | None = None,
    strategy: str = "oldest-first",
) -> dict:
    """Suggest loan group allocations for a repayment line."""
    line = db.session.get(JournalLine, journal_line_id)
    if not line or not getattr(line.journal, "user_id", None) == user_id:
        return {"ok": False, "error": "Journal line not found"}, 404

    acct = db.session.get(Account, line.account_id) if line.account_id else None
    line_currency = (line.currency_code or (acct.currency_code if acct else None) or "KRW").upper()

    query = (
        LoanGroup.query.filter_by(user_id=user_id, direction=direction, status="open")
        .filter(LoanGroup.currency == line_currency)
    )
    if counterparty:
        lowered = counterparty.strip().lower()
        query = query.filter(func.lower(LoanGroup.counterparty) == lowered)
    candidates = list(query.all())

    groups_meta = []
    for group in candidates:
        summary, _ = group_summary(user_id, group)
        remaining = summary.get("remaining") or Decimal("0")
        if remaining <= Decimal("0"):
            continue
        groups_meta.append({"group": group, "remaining": remaining, "summary": summary})

    if strategy == "lowest-balance-first":
        groups_meta.sort(
            key=lambda g: (g["remaining"], g["group"].start_date or None, g["group"].created_at or None)
        )
    else:
        groups_meta.sort(
            key=lambda g: (g["group"].start_date or None, g["group"].created_at or None)
        )

    line_total = Decimal(str(line.amount_base or 0)).copy_abs()
    linked_total = sum(
        (Decimal(str(ln.linked_amount or 0)) for ln in LoanGroupLink.query.filter_by(user_id=user_id, journal_line_id=journal_line_id).all()),
        Decimal("0"),
    )
    available = (line_total - linked_total).quantize(Decimal("0.01"))
    if cap is not None:
        available = min(available, cap)
    if available <= Decimal("0"):
        return {"ok": True, "suggestions": [], "note": "Transaction already fully allocated."}

    suggestions = []
    remaining_amount = available
    for meta in groups_meta:
        if remaining_amount <= Decimal("0"):
            break
        take = min(meta["remaining"], remaining_amount)
        if take <= Decimal("0"):
            continue
        suggestions.append(
            {
                "loan_group_id": meta["group"].id,
                "name": meta["group"].name,
                "counterparty": meta["group"].counterparty,
                "proposed_amount": float(take.quantize(Decimal("0.01"))),
                "summary": meta["summary"],
            }
        )
        remaining_amount -= take

    return {
        "ok": True,
        "suggestions": suggestions,
        "available_amount": float(available),
        "unused_amount": float(max(remaining_amount, Decimal("0")).quantize(Decimal("0.01"))),
        "currency": line_currency,
        "strategy": strategy,
    }
