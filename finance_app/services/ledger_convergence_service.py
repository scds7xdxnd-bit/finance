"""Ledger convergence metrics, backfill, and reconciliation helpers."""

from __future__ import annotations

import datetime as _dt
import hashlib
from decimal import Decimal
from typing import Dict, List

from sqlalchemy import case, func

from finance_app.extensions import db
from finance_app.models.accounting_models import (
    CsvImportRow,
    JournalEntry,
    JournalLine,
    Transaction,
    TransactionJournalLink,
    TransactionLinkCandidate,
)


def _norm_text(value: str | None) -> str:
    txt = (value or "").strip().lower()
    return " ".join(txt.split())


def _row_key(
    *,
    date_raw: str | None,
    amount: Decimal,
    currency: str | None,
    counterparty: str | None,
    account_id: int,
    direction: str,
) -> str:
    key = "|".join(
        [
            (date_raw or "").strip(),
            f"{amount:.2f}",
            (currency or "KRW").upper(),
            _norm_text(counterparty),
            str(account_id),
            direction,
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def compute_convergence_metrics(user_id: int | None = None, recent_days: int = 90) -> Dict[str, object]:
    tx_q = Transaction.query
    link_q = TransactionJournalLink.query
    if user_id is not None:
        tx_q = tx_q.filter(Transaction.user_id == int(user_id))
        link_q = link_q.filter(TransactionJournalLink.user_id == int(user_id))

    total_legacy_tx = tx_q.count()
    linked_legacy_tx = (
        db.session.query(func.count(Transaction.id))
        .select_from(Transaction)
        .join(
            TransactionJournalLink,
            (TransactionJournalLink.transaction_id == Transaction.id)
            & (TransactionJournalLink.user_id == Transaction.user_id),
        )
    )
    if user_id is not None:
        linked_legacy_tx = linked_legacy_tx.filter(Transaction.user_id == int(user_id))
    linked_legacy_tx = int(linked_legacy_tx.scalar() or 0)

    total_amt_q = db.session.query(
        func.coalesce(func.sum(func.abs(Transaction.debit_amount)), 0.0)
        + func.coalesce(func.sum(func.abs(Transaction.credit_amount)), 0.0)
    )
    linked_amt_q = db.session.query(
        func.coalesce(func.sum(func.abs(Transaction.debit_amount)), 0.0)
        + func.coalesce(func.sum(func.abs(Transaction.credit_amount)), 0.0)
    ).join(
        TransactionJournalLink,
        (TransactionJournalLink.transaction_id == Transaction.id)
        & (TransactionJournalLink.user_id == Transaction.user_id),
    )
    if user_id is not None:
        total_amt_q = total_amt_q.filter(Transaction.user_id == int(user_id))
        linked_amt_q = linked_amt_q.filter(Transaction.user_id == int(user_id))
    total_legacy_amount = float(total_amt_q.scalar() or 0.0)
    linked_legacy_amount = float(linked_amt_q.scalar() or 0.0)

    cutoff = _dt.date.today() - _dt.timedelta(days=max(1, int(recent_days)))
    unlinked_recent_q = (
        db.session.query(func.count(Transaction.id))
        .select_from(Transaction)
        .outerjoin(
            TransactionJournalLink,
            (TransactionJournalLink.transaction_id == Transaction.id)
            & (TransactionJournalLink.user_id == Transaction.user_id),
        )
        .filter(TransactionJournalLink.id == None)
        .filter(Transaction.date_parsed != None)
        .filter(Transaction.date_parsed >= cutoff)
    )
    if user_id is not None:
        unlinked_recent_q = unlinked_recent_q.filter(Transaction.user_id == int(user_id))
    unlinked_recent_90d_count = int(unlinked_recent_q.scalar() or 0)

    source_counts_q = db.session.query(
        func.coalesce(
            func.sum(case((TransactionJournalLink.source.like("exact%"), 1), else_=0)), 0
        ),
        func.coalesce(
            func.sum(case((TransactionJournalLink.source.like("strong%"), 1), else_=0)), 0
        ),
    )
    if user_id is not None:
        source_counts_q = source_counts_q.filter(TransactionJournalLink.user_id == int(user_id))
    exact_count, strong_count = source_counts_q.one()

    coverage_count = 1.0 if total_legacy_tx == 0 else (linked_legacy_tx / total_legacy_tx)
    coverage_amount = 1.0 if total_legacy_amount == 0 else (linked_legacy_amount / total_legacy_amount)

    return {
        "total_legacy_tx": int(total_legacy_tx),
        "linked_legacy_tx": linked_legacy_tx,
        "linked_exact": int(exact_count or 0),
        "linked_strong": int(strong_count or 0),
        "total_legacy_amount": round(total_legacy_amount, 2),
        "linked_legacy_amount": round(linked_legacy_amount, 2),
        "coverage_count": round(coverage_count, 6),
        "coverage_amount": round(coverage_amount, 6),
        "unlinked_recent_90d_count": unlinked_recent_90d_count,
    }


def _upsert_candidate(
    *,
    user_id: int,
    transaction_id: int,
    journal_entry_id: int | None,
    confidence: str,
    reason: str,
    score: float | None,
    source: str,
    status: str = "pending_review",
) -> None:
    existing = (
        TransactionLinkCandidate.query.filter_by(user_id=user_id, transaction_id=transaction_id, reason=reason)
        .order_by(TransactionLinkCandidate.created_at.desc())
        .first()
    )
    if existing:
        existing.journal_entry_id = journal_entry_id
        existing.confidence = confidence
        existing.score = score
        existing.status = status
        existing.source = source
        return

    db.session.add(
        TransactionLinkCandidate(
            user_id=user_id,
            transaction_id=transaction_id,
            journal_entry_id=journal_entry_id,
            confidence=confidence,
            reason=reason,
            score=score,
            status=status,
            source=source,
        )
    )


def _strong_journal_for_transaction(tx: Transaction) -> tuple[int | None, str]:
    # Strong criterion uses stable row-level dedupe keys and exact 1:1 cardinality.
    if not tx.debit_account_id or not tx.credit_account_id:
        return None, "weak_unlinked"
    try:
        debit_amt = Decimal(str(tx.debit_amount or 0)).quantize(Decimal("0.01"))
        credit_amt = Decimal(str(tx.credit_amount or 0)).quantize(Decimal("0.01"))
    except Exception:
        return None, "weak_unlinked"
    if debit_amt <= 0 or credit_amt <= 0:
        return None, "weak_unlinked"

    currency = "KRW"
    date_raw = tx.date or (tx.date_parsed.isoformat() if tx.date_parsed else "")
    counterparty = tx.description or ""
    d_key = _row_key(
        date_raw=date_raw,
        amount=debit_amt,
        currency=currency,
        counterparty=counterparty,
        account_id=int(tx.debit_account_id),
        direction="D",
    )
    c_key = _row_key(
        date_raw=date_raw,
        amount=credit_amt,
        currency=currency,
        counterparty=counterparty,
        account_id=int(tx.credit_account_id),
        direction="C",
    )

    d_rows = CsvImportRow.query.filter_by(
        user_id=tx.user_id,
        account_id=int(tx.debit_account_id),
        direction="D",
        row_dedupe_key=d_key,
        status="imported",
    ).all()
    c_rows = CsvImportRow.query.filter_by(
        user_id=tx.user_id,
        account_id=int(tx.credit_account_id),
        direction="C",
        row_dedupe_key=c_key,
        status="imported",
    ).all()

    d_entries = {int(r.journal_entry_id) for r in d_rows if r.journal_entry_id}
    c_entries = {int(r.journal_entry_id) for r in c_rows if r.journal_entry_id}
    intersection = d_entries.intersection(c_entries)
    if len(intersection) == 1:
        return next(iter(intersection)), "strong_row_key"
    if len(intersection) > 1 or len(d_entries) > 1 or len(c_entries) > 1:
        return None, "weak_ambiguous"
    return None, "weak_unlinked"


def backfill_links(
    *,
    user_id: int | None = None,
    dry_run: bool = True,
    max_rows: int | None = None,
) -> Dict[str, object]:
    q = Transaction.query
    if user_id is not None:
        q = q.filter(Transaction.user_id == int(user_id))
    q = q.order_by(Transaction.id.asc())

    if max_rows is not None:
        q = q.limit(max(1, int(max_rows)))

    scanned = 0
    created_exact = 0
    created_strong = 0
    weak_candidates = 0
    already_linked = 0

    for tx in q.all():
        scanned += 1
        existing = TransactionJournalLink.query.filter_by(user_id=tx.user_id, transaction_id=tx.id).first()
        if existing:
            already_linked += 1
            continue

        # exact by explicit reference
        exact_entry = JournalEntry.query.filter_by(user_id=tx.user_id, reference=f"TX:{tx.id}").first()
        if exact_entry:
            if not dry_run:
                db.session.add(
                    TransactionJournalLink(
                        user_id=tx.user_id,
                        transaction_id=tx.id,
                        journal_entry_id=exact_entry.id,
                        source="exact_ref",
                    )
                )
            created_exact += 1
            continue

        # strong by stable row-level dedupe provenance
        strong_entry_id, weak_reason = _strong_journal_for_transaction(tx)
        if strong_entry_id:
            if not dry_run:
                db.session.add(
                    TransactionJournalLink(
                        user_id=tx.user_id,
                        transaction_id=tx.id,
                        journal_entry_id=strong_entry_id,
                        source="strong_row_key",
                    )
                )
            created_strong += 1
            continue

        weak_candidates += 1
        if not dry_run:
            _upsert_candidate(
                user_id=tx.user_id,
                transaction_id=tx.id,
                journal_entry_id=None,
                confidence="weak",
                reason=weak_reason,
                score=0.0,
                source="backfill",
                status="pending_review",
            )

    if not dry_run:
        db.session.commit()

    return {
        "scanned": scanned,
        "already_linked": already_linked,
        "created_exact": created_exact,
        "created_strong": created_strong,
        "weak_candidates": weak_candidates,
        "dry_run": bool(dry_run),
    }


def reconcile_ledger(user_id: int | None = None) -> Dict[str, object]:
    unmapped_q = (
        db.session.query(func.count(Transaction.id))
        .select_from(Transaction)
        .outerjoin(
            TransactionJournalLink,
            (TransactionJournalLink.transaction_id == Transaction.id)
            & (TransactionJournalLink.user_id == Transaction.user_id),
        )
        .filter(TransactionJournalLink.id == None)
    )
    if user_id is not None:
        unmapped_q = unmapped_q.filter(Transaction.user_id == int(user_id))
    unmapped_transactions = int(unmapped_q.scalar() or 0)

    # linked journal totals mismatch checks
    journal_totals = (
        db.session.query(
            TransactionJournalLink.transaction_id.label("transaction_id"),
            TransactionJournalLink.user_id.label("user_id"),
            func.coalesce(func.sum(case((JournalLine.dc == "D", JournalLine.amount_base), else_=0)), 0).label(
                "journal_debit_total"
            ),
            func.coalesce(func.sum(case((JournalLine.dc == "C", JournalLine.amount_base), else_=0)), 0).label(
                "journal_credit_total"
            ),
        )
        .join(JournalEntry, JournalEntry.id == TransactionJournalLink.journal_entry_id)
        .join(JournalLine, JournalLine.journal_id == JournalEntry.id)
        .group_by(TransactionJournalLink.transaction_id, TransactionJournalLink.user_id)
        .subquery()
    )

    mismatch_q = (
        db.session.query(func.count(Transaction.id))
        .join(
            journal_totals,
            (journal_totals.c.transaction_id == Transaction.id)
            & (journal_totals.c.user_id == Transaction.user_id),
        )
        .filter(
            (func.abs(func.coalesce(Transaction.debit_amount, 0) - func.coalesce(journal_totals.c.journal_debit_total, 0)) > 0.01)
            | (func.abs(func.coalesce(Transaction.credit_amount, 0) - func.coalesce(journal_totals.c.journal_credit_total, 0)) > 0.01)
        )
    )
    if user_id is not None:
        mismatch_q = mismatch_q.filter(Transaction.user_id == int(user_id))
    mismatched_links = int(mismatch_q.scalar() or 0)

    unbalanced_q = (
        db.session.query(JournalLine.journal_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_id)
        .group_by(JournalLine.journal_id)
        .having(
            func.abs(
                func.coalesce(func.sum(case((JournalLine.dc == "D", JournalLine.amount_base), else_=0)), 0)
                - func.coalesce(func.sum(case((JournalLine.dc == "C", JournalLine.amount_base), else_=0)), 0)
            )
            > 0.01
        )
    )
    if user_id is not None:
        unbalanced_q = unbalanced_q.filter(JournalEntry.user_id == int(user_id))
    unbalanced_journal_entries = int(unbalanced_q.count())

    checks = {
        "unmapped_transactions": unmapped_transactions,
        "mismatched_links": mismatched_links,
        "unbalanced_journal_entries": unbalanced_journal_entries,
    }
    return {
        "ok": all(v == 0 for v in checks.values()),
        "checks": checks,
    }
