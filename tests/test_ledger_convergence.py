from __future__ import annotations

import datetime
import hashlib
import json
import os
from decimal import Decimal

import pytest

from finance_app import User, create_app, db
from finance_app.models.accounting_models import (
    CsvImportBatch,
    CsvImportRow,
    JournalEntry,
    JournalLine,
    Transaction,
    TransactionJournalLink,
    TransactionLinkCandidate,
)
from finance_app.services.account_service import ensure_account
from finance_app.services.ledger_convergence_policy import (
    LinkCandidateStatus,
    LinkConfidence,
    LinkReason,
)
from finance_app.services.ledger_convergence_service import (
    _row_key,
    backfill_links,
)


@pytest.fixture()
def app_ctx(tmp_path):
    db_path = tmp_path / "ledger_convergence_test.db"
    old_db_url = os.environ.get("FINANCE_DATABASE_URL")
    old_guard = os.environ.get("SCHEMA_GUARD_ENFORCE")

    os.environ["FINANCE_DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["SCHEMA_GUARD_ENFORCE"] = "false"

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
        db.create_all()
        user = User(username="ledger_user", password_hash="pw")
        db.session.add(user)
        db.session.commit()
        try:
            yield app, int(user.id)
        finally:
            db.session.remove()
            db.drop_all()

    if old_db_url is None:
        os.environ.pop("FINANCE_DATABASE_URL", None)
    else:
        os.environ["FINANCE_DATABASE_URL"] = old_db_url

    if old_guard is None:
        os.environ.pop("SCHEMA_GUARD_ENFORCE", None)
    else:
        os.environ["SCHEMA_GUARD_ENFORCE"] = old_guard


def _create_tx(*, user_id: int, amount: Decimal = Decimal("100.00"), description: str = "Row key base") -> Transaction:
    cash = ensure_account(user_id, "Cash")
    revenue = ensure_account(user_id, "Revenue")
    tx = Transaction(
        user_id=user_id,
        date="2026/01/15",
        date_parsed=datetime.date(2026, 1, 15),
        description=description,
        debit_account=cash.name,
        debit_amount=float(amount),
        credit_account=revenue.name,
        credit_amount=float(amount),
        debit_account_id=int(cash.id),
        credit_account_id=int(revenue.id),
    )
    db.session.add(tx)
    db.session.flush()
    return tx


def _create_journal(*, user_id: int, amount: Decimal, description: str, reference: str | None = None) -> JournalEntry:
    cash = ensure_account(user_id, "Cash")
    revenue = ensure_account(user_id, "Revenue")
    entry = JournalEntry(
        user_id=user_id,
        date="2026/01/15",
        date_parsed=datetime.date(2026, 1, 15),
        description=description,
        reference=reference,
    )
    db.session.add(entry)
    db.session.flush()
    db.session.add(
        JournalLine(
            journal_id=entry.id,
            account_id=cash.id,
            dc="D",
            amount_base=amount,
            line_no=1,
        )
    )
    db.session.add(
        JournalLine(
            journal_id=entry.id,
            account_id=revenue.id,
            dc="C",
            amount_base=amount,
            line_no=2,
        )
    )
    return entry


def _create_batch(*, user_id: int) -> CsvImportBatch:
    digest = hashlib.sha256(f"batch:{user_id}".encode("utf-8")).hexdigest()
    batch = CsvImportBatch(
        user_id=user_id,
        file_sha256=digest,
        filename="test.csv",
        row_count=2,
        status="applied",
    )
    db.session.add(batch)
    db.session.flush()
    return batch


def _add_row(
    *,
    batch_id: str,
    user_id: int,
    row_number: int,
    dedupe_key: str,
    account_id: int,
    direction: str,
    amount: Decimal,
    journal_entry_id: int,
) -> None:
    db.session.add(
        CsvImportRow(
            batch_id=batch_id,
            user_id=user_id,
            row_number=row_number,
            row_sha256=hashlib.sha256(f"row:{row_number}:{direction}".encode("utf-8")).hexdigest(),
            row_dedupe_key=dedupe_key,
            external_txn_id=None,
            account_id=account_id,
            direction=direction,
            amount=amount,
            currency="KRW",
            effective_date=datetime.date(2026, 1, 15),
            counterparty_norm="row key base",
            status="imported",
            journal_entry_id=journal_entry_id,
        )
    )


def test_backfill_weak_candidates_never_auto_link(app_ctx):
    app, user_id = app_ctx
    with app.app_context():
        tx = _create_tx(user_id=user_id, description="No stable provenance")
        db.session.commit()

        summary = backfill_links(user_id=user_id, dry_run=False)

        assert summary["created_exact"] == 0
        assert summary["created_strong"] == 0
        assert summary["weak_candidates"] == 1
        assert TransactionJournalLink.query.filter_by(user_id=user_id, transaction_id=tx.id).count() == 0

        cand = TransactionLinkCandidate.query.filter_by(user_id=user_id, transaction_id=tx.id).one()
        assert cand.confidence == LinkConfidence.WEAK_AMBIGUOUS.value
        assert cand.reason == LinkReason.WEAK_NO_STABLE_ID.value
        assert cand.status == LinkCandidateStatus.PENDING_REVIEW.value


def test_backfill_strong_requires_stable_id_and_unique_cardinality(app_ctx):
    app, user_id = app_ctx
    with app.app_context():
        tx = _create_tx(user_id=user_id)
        strong_entry = _create_journal(user_id=user_id, amount=Decimal("100.00"), description="Strong match")
        batch = _create_batch(user_id=user_id)

        d_key = _row_key(
            date_raw=tx.date,
            amount=Decimal("100.00"),
            currency="KRW",
            counterparty=tx.description,
            account_id=int(tx.debit_account_id),
            direction="D",
        )
        c_key = _row_key(
            date_raw=tx.date,
            amount=Decimal("100.00"),
            currency="KRW",
            counterparty=tx.description,
            account_id=int(tx.credit_account_id),
            direction="C",
        )

        _add_row(
            batch_id=batch.id,
            user_id=user_id,
            row_number=1,
            dedupe_key=d_key,
            account_id=int(tx.debit_account_id),
            direction="D",
            amount=Decimal("100.00"),
            journal_entry_id=int(strong_entry.id),
        )
        _add_row(
            batch_id=batch.id,
            user_id=user_id,
            row_number=2,
            dedupe_key=c_key,
            account_id=int(tx.credit_account_id),
            direction="C",
            amount=Decimal("100.00"),
            journal_entry_id=int(strong_entry.id),
        )

        db.session.commit()

        summary = backfill_links(user_id=user_id, dry_run=False)
        assert summary["created_strong"] == 1

        link = TransactionJournalLink.query.filter_by(user_id=user_id, transaction_id=tx.id).one()
        assert int(link.journal_entry_id) == int(strong_entry.id)
        assert link.source == LinkReason.STRONG_ROW_KEY_UNIQUE.value

        cand = TransactionLinkCandidate.query.filter_by(user_id=user_id, transaction_id=tx.id).order_by(TransactionLinkCandidate.created_at.desc()).first()
        assert cand is not None
        assert cand.confidence == LinkConfidence.STRONG.value
        assert cand.reason == LinkReason.STRONG_ROW_KEY_UNIQUE.value
        assert cand.status == LinkCandidateStatus.AUTO_LINKED.value


def test_backfill_non_unique_candidate_set_becomes_weak_ambiguous(app_ctx):
    app, user_id = app_ctx
    with app.app_context():
        tx = _create_tx(user_id=user_id)
        entry_debit = _create_journal(user_id=user_id, amount=Decimal("100.00"), description="Debit candidate")
        entry_credit = _create_journal(user_id=user_id, amount=Decimal("100.00"), description="Credit candidate")
        batch = _create_batch(user_id=user_id)

        d_key = _row_key(
            date_raw=tx.date,
            amount=Decimal("100.00"),
            currency="KRW",
            counterparty=tx.description,
            account_id=int(tx.debit_account_id),
            direction="D",
        )
        c_key = _row_key(
            date_raw=tx.date,
            amount=Decimal("100.00"),
            currency="KRW",
            counterparty=tx.description,
            account_id=int(tx.credit_account_id),
            direction="C",
        )

        _add_row(
            batch_id=batch.id,
            user_id=user_id,
            row_number=1,
            dedupe_key=d_key,
            account_id=int(tx.debit_account_id),
            direction="D",
            amount=Decimal("100.00"),
            journal_entry_id=int(entry_debit.id),
        )
        _add_row(
            batch_id=batch.id,
            user_id=user_id,
            row_number=2,
            dedupe_key=c_key,
            account_id=int(tx.credit_account_id),
            direction="C",
            amount=Decimal("100.00"),
            journal_entry_id=int(entry_credit.id),
        )

        db.session.commit()

        summary = backfill_links(user_id=user_id, dry_run=False)
        assert summary["created_strong"] == 0
        assert summary["weak_candidates"] == 1

        assert TransactionJournalLink.query.filter_by(user_id=user_id, transaction_id=tx.id).count() == 0
        cand = TransactionLinkCandidate.query.filter_by(user_id=user_id, transaction_id=tx.id).one()
        assert cand.confidence == LinkConfidence.WEAK_AMBIGUOUS.value
        assert cand.reason == LinkReason.WEAK_AMBIGUOUS_CARDINALITY.value


def test_backfill_rerun_is_idempotent(app_ctx):
    app, user_id = app_ctx
    with app.app_context():
        tx = _create_tx(user_id=user_id)
        _create_journal(
            user_id=user_id,
            amount=Decimal("100.00"),
            description="Exact match",
            reference=f"TX:{tx.id}",
        )
        db.session.commit()

        first = backfill_links(user_id=user_id, dry_run=False)
        second = backfill_links(user_id=user_id, dry_run=False)

        assert first["created_exact"] == 1
        assert second["created_exact"] == 0
        assert second["already_linked"] == 1
        assert TransactionJournalLink.query.filter_by(user_id=user_id, transaction_id=tx.id).count() == 1


def test_ledger_reconcile_fails_on_mismatch(app_ctx):
    app, user_id = app_ctx
    with app.app_context():
        tx = _create_tx(user_id=user_id, amount=Decimal("100.00"), description="Mismatch source")
        entry = _create_journal(user_id=user_id, amount=Decimal("90.00"), description="Mismatch target")
        db.session.add(
            TransactionJournalLink(
                user_id=user_id,
                transaction_id=tx.id,
                journal_entry_id=entry.id,
                source="exact_tx_ref",
            )
        )
        db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(args=["ledger-reconcile", "--user-id", str(user_id)])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["pass"] is False
    assert payload["mismatched_totals"] == 1
    assert payload["missing_links_count"] == 0
    assert payload["unbalanced_journals_count"] == 0
    assert "coverage_count" in payload
    assert "coverage_amount" in payload
    assert "unlinked_recent_90d_count" in payload
