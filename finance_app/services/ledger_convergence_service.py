"""Ledger convergence metrics, backfill, and reconciliation helpers."""

from __future__ import annotations

import datetime as _dt
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict

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
from finance_app.services.ledger_convergence_policy import (
    LinkCandidateStatus,
    LinkConfidence,
    LinkReason,
    is_auto_link_confidence,
)


@dataclass(frozen=True)
class _LinkDecision:
    confidence: LinkConfidence
    reason: LinkReason
    journal_entry_id: int | None = None


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
    if user_id is not None:
        tx_q = tx_q.filter(Transaction.user_id == int(user_id))

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
    confidence: LinkConfidence,
    reason: LinkReason,
    score: float | None,
    source: str,
    status: LinkCandidateStatus = LinkCandidateStatus.PENDING_REVIEW,
) -> None:
    confidence_value = confidence.value
    reason_value = reason.value
    status_value = status.value
    now = _dt.datetime.utcnow()
    existing = (
        TransactionLinkCandidate.query.filter_by(user_id=user_id, transaction_id=transaction_id, reason=reason_value)
        .order_by(TransactionLinkCandidate.created_at.desc())
        .first()
    )
    if existing:
        existing.journal_entry_id = journal_entry_id
        existing.confidence = confidence_value
        existing.score = score
        existing.status = status_value
        existing.source = source
        if status != LinkCandidateStatus.PENDING_REVIEW:
            existing.resolved_at = now
        return

    db.session.add(
        TransactionLinkCandidate(
            user_id=user_id,
            transaction_id=transaction_id,
            journal_entry_id=journal_entry_id,
            confidence=confidence_value,
            reason=reason_value,
            score=score,
            status=status_value,
            source=source,
            resolved_at=(None if status == LinkCandidateStatus.PENDING_REVIEW else now),
        )
    )


def _decide_from_row_keys(tx: Transaction) -> _LinkDecision:
    # Strong criterion uses stable row-level dedupe keys and exact 1:1 cardinality.
    if not tx.debit_account_id or not tx.credit_account_id:
        return _LinkDecision(
            confidence=LinkConfidence.WEAK_AMBIGUOUS,
            reason=LinkReason.WEAK_NO_STABLE_ID,
        )
    try:
        debit_amt = Decimal(str(tx.debit_amount or 0)).quantize(Decimal("0.01"))
        credit_amt = Decimal(str(tx.credit_amount or 0)).quantize(Decimal("0.01"))
    except Exception:
        return _LinkDecision(
            confidence=LinkConfidence.WEAK_AMBIGUOUS,
            reason=LinkReason.WEAK_NO_STABLE_ID,
        )
    if debit_amt <= 0 or credit_amt <= 0:
        return _LinkDecision(
            confidence=LinkConfidence.WEAK_AMBIGUOUS,
            reason=LinkReason.WEAK_NO_STABLE_ID,
        )

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
    if not d_entries or not c_entries:
        return _LinkDecision(
            confidence=LinkConfidence.WEAK_AMBIGUOUS,
            reason=LinkReason.WEAK_NO_STABLE_ID,
        )
    intersection = d_entries.intersection(c_entries)
    if len(intersection) == 1 and len(d_entries) == 1 and len(c_entries) == 1:
        return _LinkDecision(
            confidence=LinkConfidence.STRONG,
            reason=LinkReason.STRONG_ROW_KEY_UNIQUE,
            journal_entry_id=next(iter(intersection)),
        )
    return _LinkDecision(
        confidence=LinkConfidence.WEAK_AMBIGUOUS,
        reason=LinkReason.WEAK_AMBIGUOUS_CARDINALITY,
    )


def _create_link_with_policy_guard(
    *,
    user_id: int,
    transaction_id: int,
    journal_entry_id: int,
    source: str,
    confidence: LinkConfidence,
) -> None:
    if not is_auto_link_confidence(confidence):
        raise AssertionError("Weak candidates must never auto-link.")
    db.session.add(
        TransactionJournalLink(
            user_id=user_id,
            transaction_id=transaction_id,
            journal_entry_id=journal_entry_id,
            source=source,
        )
    )


def backfill_links(
    *,
    user_id: int | None = None,
    dry_run: bool = True,
    max_rows: int | None = None,
    source_marker: str | None = None,
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
    marker = (source_marker or f"bf_{_dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')}")[:40]

    for tx in q.all():
        scanned += 1
        existing = TransactionJournalLink.query.filter_by(user_id=tx.user_id, transaction_id=tx.id).first()
        if existing:
            already_linked += 1
            continue

        # exact by explicit reference
        exact_entry_ids = [
            int(row[0])
            for row in db.session.query(JournalEntry.id).filter_by(user_id=tx.user_id, reference=f"TX:{tx.id}").all()
        ]
        if len(exact_entry_ids) == 1:
            exact_entry_id = exact_entry_ids[0]
            if not dry_run:
                _create_link_with_policy_guard(
                    user_id=tx.user_id,
                    transaction_id=tx.id,
                    journal_entry_id=exact_entry_id,
                    source=LinkReason.EXACT_TX_REF.value,
                    confidence=LinkConfidence.EXACT,
                )
                _upsert_candidate(
                    user_id=tx.user_id,
                    transaction_id=tx.id,
                    journal_entry_id=exact_entry_id,
                    confidence=LinkConfidence.EXACT,
                    reason=LinkReason.EXACT_TX_REF,
                    score=1.0,
                    source=marker,
                    status=LinkCandidateStatus.AUTO_LINKED,
                )
            created_exact += 1
            continue
        if len(exact_entry_ids) > 1:
            weak_candidates += 1
            if not dry_run:
                _upsert_candidate(
                    user_id=tx.user_id,
                    transaction_id=tx.id,
                    journal_entry_id=None,
                    confidence=LinkConfidence.WEAK_AMBIGUOUS,
                    reason=LinkReason.WEAK_AMBIGUOUS_CARDINALITY,
                    score=0.0,
                    source=marker,
                    status=LinkCandidateStatus.PENDING_REVIEW,
                )
            continue

        # strong by stable row-level dedupe provenance
        decision = _decide_from_row_keys(tx)
        if decision.confidence == LinkConfidence.STRONG and decision.journal_entry_id:
            if not dry_run:
                _create_link_with_policy_guard(
                    user_id=tx.user_id,
                    transaction_id=tx.id,
                    journal_entry_id=int(decision.journal_entry_id),
                    source=LinkReason.STRONG_ROW_KEY_UNIQUE.value,
                    confidence=decision.confidence,
                )
                _upsert_candidate(
                    user_id=tx.user_id,
                    transaction_id=tx.id,
                    journal_entry_id=int(decision.journal_entry_id),
                    confidence=decision.confidence,
                    reason=decision.reason,
                    score=0.9,
                    source=marker,
                    status=LinkCandidateStatus.AUTO_LINKED,
                )
            created_strong += 1
            continue

        weak_candidates += 1
        if not dry_run:
            _upsert_candidate(
                user_id=tx.user_id,
                transaction_id=tx.id,
                journal_entry_id=None,
                confidence=LinkConfidence.WEAK_AMBIGUOUS,
                reason=decision.reason,
                score=0.0,
                source=marker,
                status=LinkCandidateStatus.PENDING_REVIEW,
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
        "source_marker": marker,
    }


def reconcile_ledger(user_id: int | None = None) -> Dict[str, object]:
    # Deterministic count of legacy transactions with no explicit transaction_journal_link.
    missing_links_q = (
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
        missing_links_q = missing_links_q.filter(Transaction.user_id == int(user_id))
    missing_links_count = int(missing_links_q.scalar() or 0)

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
    mismatched_totals = int(mismatch_q.scalar() or 0)

    # Deterministic count of journal entries whose summed debit and credit diverge.
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
    unbalanced_journals_count = int(unbalanced_q.count())

    passed = bool(
        missing_links_count == 0
        and mismatched_totals == 0
        and unbalanced_journals_count == 0
    )
    return {
        "pass": passed,
        "missing_links_count": missing_links_count,
        "mismatched_totals": mismatched_totals,
        "unbalanced_journals_count": unbalanced_journals_count,
    }
