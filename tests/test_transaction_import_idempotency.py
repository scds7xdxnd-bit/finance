from __future__ import annotations

import os
from pathlib import Path

import pytest
from finance_app import User, create_app, db
from finance_app.models.accounting_models import CsvImportBatch, JournalEntry, Transaction, TransactionJournalLink
from finance_app.services.transaction_create_service import save_transaction_payload
from finance_app.services.transaction_import_service import import_csv_transactions

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "csv_import"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


@pytest.fixture()
def app_ctx(tmp_path):
    db_path = tmp_path / "import_test.db"
    old_db_url = os.environ.get("FINANCE_DATABASE_URL")
    os.environ["FINANCE_DATABASE_URL"] = f"sqlite:///{db_path}"
    app = create_app()
    app.config["TESTING"] = True
    app.config["LEDGER_WRITE_MODE"] = "journal"
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
        db.create_all()
        user = User(username="import_user", password_hash="pw")
        db.session.add(user)
        db.session.commit()
        try:
            yield app, user.id
        finally:
            db.session.remove()
            db.drop_all()
            if old_db_url is None:
                os.environ.pop("FINANCE_DATABASE_URL", None)
            else:
                os.environ["FINANCE_DATABASE_URL"] = old_db_url


def test_csv_import_file_hash_idempotency(app_ctx):
    app, user_id = app_ctx
    raw_csv = _fixture("reupload_base.csv")
    with app.app_context():
        first = import_csv_transactions(raw_csv, user_id, filename="a.csv", write_mode="journal", idempotency_enabled=True)
        assert first["skipped_duplicate_batch"] is False
        assert first["count_journal"] == 1

        second = import_csv_transactions(raw_csv, user_id, filename="a.csv", write_mode="journal", idempotency_enabled=True)
        assert second["skipped_duplicate_batch"] is True
        assert second["duplicate_reasons"]["duplicate_batch_file_sha256"] == 1

        assert JournalEntry.query.count() == 1
        assert CsvImportBatch.query.count() == 1


def test_csv_import_force_reupload_processes_and_row_dedupes(app_ctx):
    app, user_id = app_ctx
    raw_csv = _fixture("reupload_base.csv")
    with app.app_context():
        first = import_csv_transactions(raw_csv, user_id, filename="a.csv", write_mode="journal", idempotency_enabled=True)
        assert first["skipped_duplicate_batch"] is False
        assert first["rows_new"] == 1

        forced = import_csv_transactions(
            raw_csv,
            user_id,
            filename="a.csv",
            write_mode="journal",
            idempotency_enabled=True,
            force=True,
        )
        assert forced["skipped_duplicate_batch"] is False
        assert forced["rows_new"] == 0
        assert forced["rows_duplicate"] == 1
        assert forced["duplicate_reasons"]["duplicate_row_dedupe_key"] == 1

        assert JournalEntry.query.count() == 1
        assert CsvImportBatch.query.count() == 1


def test_csv_import_overlapping_exports_row_level_dedupe(app_ctx):
    app, user_id = app_ctx
    csv_a = _fixture("overlap_export_a.csv")
    csv_b = _fixture("overlap_export_b.csv")
    with app.app_context():
        first = import_csv_transactions(csv_a, user_id, filename="a.csv", write_mode="journal", idempotency_enabled=True)
        assert first["rows_new"] == 2
        assert first["rows_duplicate"] == 0
        assert first["count_journal"] == 2

        second = import_csv_transactions(csv_b, user_id, filename="b.csv", write_mode="journal", idempotency_enabled=True)
        assert second["rows_new"] == 1
        assert second["rows_duplicate"] == 1
        assert second["rows_error"] == 0
        assert second["count_journal"] == 1
        assert second["duplicate_reasons"]["duplicate_row_dedupe_key"] == 1
        assert JournalEntry.query.count() == 3


def test_csv_import_partial_duplicate_group_reports_error_reason(app_ctx):
    app, user_id = app_ctx
    csv_a = _fixture("partial_dup_a.csv")
    # Same transaction_id and debit line, but changed credit side -> mixed duplicate group.
    csv_b = _fixture("partial_dup_b.csv")
    with app.app_context():
        first = import_csv_transactions(csv_a, user_id, filename="a.csv", write_mode="journal", idempotency_enabled=True)
        assert first["rows_new"] == 1

        second = import_csv_transactions(csv_b, user_id, filename="b.csv", write_mode="journal", idempotency_enabled=True)
        assert second["rows_new"] == 0
        assert second["rows_duplicate"] == 0
        assert second["rows_error"] == 1
        assert second["error_reasons"]["partial_duplicate_group"] == 1
        assert JournalEntry.query.count() == 1


def test_dual_write_mode_creates_link(app_ctx):
    app, user_id = app_ctx
    with app.app_context():
        app.config["LEDGER_WRITE_MODE"] = "dual"
        ok, payload, status = save_transaction_payload(
            user_id,
            {
                "date": "2026-02-01",
                "description": "Dual mode check",
                "lines": [
                    {"dc": "D", "account": "Cash", "amount": 50},
                    {"dc": "C", "account": "Revenue", "amount": 50},
                ],
            },
        )
        assert ok is True
        assert status == 200
        assert payload["mode"] == "dual"
        assert JournalEntry.query.count() == 1
        assert Transaction.query.count() == 1
        assert TransactionJournalLink.query.count() == 1
