from __future__ import annotations

import datetime as dt
import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from finance_app import Account, JournalEntry, User, create_app, db
from helpers.db_integrity_gate import (
    ROOT,
    FAILURE_PREFIX,
    add_mismatch,
    assert_no_mismatches,
    json_from_text,
    load_audit_queries,
    make_mismatch_sets,
    run_alembic_upgrade,
    run_verifier_sql,
    sqlite_url,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

VERIFY_SQL_PATH = ROOT / "scripts" / "verify_schema_capabilities.sql"
AUDIT_SQL_PATH = ROOT / "scripts" / "sql" / "journal_integrity_audit.sql"

EXPECTED_JOURNAL_INTEGRITY_ARTIFACT_IDS = {
    "check:journal_line.ck_journal_line_dc",
    "column:journal_entry.posted_at",
    "table:journal_entry_balance",
    "trigger:trg_journal_entry_bi_post_balance_guard",
    "trigger:trg_journal_entry_bu_post_balance_guard",
    "trigger:trg_journal_line_ad_balance",
    "trigger:trg_journal_line_ai_balance",
    "trigger:trg_journal_line_au_balance",
}


@pytest.fixture()
def integrity_app(tmp_path, monkeypatch):
    db_path = tmp_path / "db_integrity_gate.db"
    db_url = sqlite_url(db_path)
    monkeypatch.setenv("FINANCE_DATABASE_URL", db_url)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", db_url)
    monkeypatch.setenv("AUTO_CREATE_SCHEMA", "false")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    run_alembic_upgrade(db_url=db_url, target_revision="head")

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        try:
            yield app, db_path
        finally:
            db.session.remove()
            db.engine.dispose()


def _seed_user_account_and_draft_entry() -> tuple[int, int, int]:
    user = User(
        username=f"qa_db_integrity_{uuid4().hex[:10]}",
        password_hash="pw",
        email=f"qa_{uuid4().hex[:8]}@example.com",
    )
    db.session.add(user)
    db.session.flush()

    account = Account(user_id=user.id, name="Cash", side="both", currency_code="KRW")
    db.session.add(account)
    db.session.flush()

    entry = JournalEntry(
        user_id=user.id,
        date="2026-03-09",
        date_parsed=dt.date(2026, 3, 9),
        description="qa integrity drill",
        posted_at=None,
    )
    db.session.add(entry)
    db.session.commit()
    return int(user.id), int(account.id), int(entry.id)


def _extract_error_message(exc: BaseException) -> str:
    if hasattr(exc, "orig") and getattr(exc, "orig") is not None:
        return str(getattr(exc, "orig"))
    return str(exc)


def test_db_integrity_capability_presence(integrity_app):
    app, _ = integrity_app
    mismatch_sets = make_mismatch_sets()

    runner = app.test_cli_runner()
    result = runner.invoke(args=["schema-status"])
    payload = json_from_text(result.output)
    caps = ((payload.get("capabilities") or {}).get("capabilities") or {})
    if not bool(caps.get("journal_integrity")):
        add_mismatch(
            mismatch_sets,
            "missing_journal_integrity_capability",
            f"schema_status_journal_integrity={caps.get('journal_integrity')}",
        )

    assert_no_mismatches(
        context={"gate": "capability_presence"},
        mismatch_sets=mismatch_sets,
    )


def test_db_integrity_invalid_dc_rejection(integrity_app):
    app, _ = integrity_app
    mismatch_sets = make_mismatch_sets()

    with app.app_context():
        _, account_id, entry_id = _seed_user_account_and_draft_entry()
        # Ensure draft semantics regardless of model default behavior.
        db.session.execute(
            text("UPDATE journal_entry SET posted_at=NULL WHERE id=:entry_id"),
            {"entry_id": entry_id},
        )
        db.session.commit()

        # Insert with invalid dc='X'
        try:
            db.session.execute(
                text(
                    "INSERT INTO journal_line (journal_id, account_id, dc, amount_base, line_no) "
                    "VALUES (:journal_id, :account_id, :dc, :amount_base, :line_no)"
                ),
                {
                    "journal_id": entry_id,
                    "account_id": account_id,
                    "dc": "X",
                    "amount_base": 10,
                    "line_no": 1,
                },
            )
            db.session.commit()
            add_mismatch(
                mismatch_sets,
                "invalid_dc_insert_not_rejected",
                "insert_dc_X_succeeded",
            )
        except (IntegrityError, OperationalError):
            db.session.rollback()

        # Insert with dc=NULL
        try:
            db.session.execute(
                text(
                    "INSERT INTO journal_line (journal_id, account_id, dc, amount_base, line_no) "
                    "VALUES (:journal_id, :account_id, :dc, :amount_base, :line_no)"
                ),
                {
                    "journal_id": entry_id,
                    "account_id": account_id,
                    "dc": None,
                    "amount_base": 11,
                    "line_no": 2,
                },
            )
            db.session.commit()
            add_mismatch(
                mismatch_sets,
                "invalid_dc_insert_not_rejected",
                "insert_dc_null_succeeded",
            )
        except (IntegrityError, OperationalError):
            db.session.rollback()

        # Seed valid row then ensure invalid updates are rejected.
        db.session.execute(
            text(
                "INSERT INTO journal_line (journal_id, account_id, dc, amount_base, line_no) "
                "VALUES (:journal_id, :account_id, :dc, :amount_base, :line_no)"
            ),
            {
                "journal_id": entry_id,
                "account_id": account_id,
                "dc": "D",
                "amount_base": 12,
                "line_no": 3,
            },
        )
        db.session.commit()
        line_id = int(
            db.session.execute(
                text(
                    "SELECT id FROM journal_line WHERE journal_id=:journal_id AND line_no=3 LIMIT 1"
                ),
                {"journal_id": entry_id},
            ).scalar_one()
        )

        for dc_value, label in (("X", "update_to_X"), (None, "update_to_null")):
            try:
                db.session.execute(
                    text("UPDATE journal_line SET dc=:dc WHERE id=:line_id"),
                    {"dc": dc_value, "line_id": line_id},
                )
                db.session.commit()
                add_mismatch(
                    mismatch_sets,
                    "invalid_dc_insert_not_rejected",
                    f"{label}_succeeded",
                )
            except (IntegrityError, OperationalError):
                db.session.rollback()

        invalid_count = int(
            db.session.execute(
                text("SELECT COUNT(*) FROM journal_line WHERE dc IS NULL OR dc NOT IN ('D','C')")
            ).scalar()
            or 0
        )
        if invalid_count != 0:
            add_mismatch(
                mismatch_sets,
                "invalid_dc_insert_not_rejected",
                f"invalid_dc_rows_persisted={invalid_count}",
            )

        journal_line_sql = str(
            db.session.execute(
                text("SELECT sql FROM sqlite_master WHERE type='table' AND name='journal_line'")
            ).scalar()
            or ""
        ).lower()
        if "ck_journal_line_dc" not in journal_line_sql:
            add_mismatch(
                mismatch_sets,
                "missing_dc_constraint",
                "ck_journal_line_dc_not_found_in_sqlite_master",
            )

    assert_no_mismatches(
        context={"gate": "invalid_dc_rejection"},
        mismatch_sets=mismatch_sets,
    )


def test_db_integrity_unbalanced_finalization_rejection(integrity_app):
    app, _ = integrity_app
    mismatch_sets = make_mismatch_sets()

    with app.app_context():
        _, account_id, entry_id = _seed_user_account_and_draft_entry()
        # Ensure draft semantics regardless of model default behavior.
        db.session.execute(
            text("UPDATE journal_entry SET posted_at=NULL WHERE id=:entry_id"),
            {"entry_id": entry_id},
        )
        db.session.commit()

        # Intentionally unbalanced draft lines: D=10, C=5.
        db.session.execute(
            text(
                "INSERT INTO journal_line (journal_id, account_id, dc, amount_base, line_no) "
                "VALUES (:journal_id, :account_id, 'D', 10.00, 1)"
            ),
            {"journal_id": entry_id, "account_id": account_id},
        )
        db.session.execute(
            text(
                "INSERT INTO journal_line (journal_id, account_id, dc, amount_base, line_no) "
                "VALUES (:journal_id, :account_id, 'C', 5.00, 2)"
            ),
            {"journal_id": entry_id, "account_id": account_id},
        )
        db.session.commit()

        try:
            db.session.execute(
                text("UPDATE journal_entry SET posted_at=CURRENT_TIMESTAMP WHERE id=:entry_id"),
                {"entry_id": entry_id},
            )
            db.session.commit()
            add_mismatch(
                mismatch_sets,
                "unbalanced_finalize_not_rejected",
                "finalize_unbalanced_entry_succeeded",
            )
        except (IntegrityError, OperationalError) as exc:
            db.session.rollback()
            message = _extract_error_message(exc)
            if not message.startswith("journal_entry_not_balanced"):
                add_mismatch(
                    mismatch_sets,
                    "unbalanced_finalize_not_rejected",
                    f"unexpected_error_message={message}",
                )

        posted_at = db.session.execute(
            text("SELECT posted_at FROM journal_entry WHERE id=:entry_id"),
            {"entry_id": entry_id},
        ).scalar()
        if posted_at is not None:
            add_mismatch(
                mismatch_sets,
                "unbalanced_finalize_not_rejected",
                "posted_at_persisted_after_failed_finalize",
            )

    assert_no_mismatches(
        context={"gate": "unbalanced_finalization_rejection"},
        mismatch_sets=mismatch_sets,
    )


def test_db_integrity_preexisting_invalid_row_detection(integrity_app):
    _, db_path = integrity_app
    mismatch_sets = make_mismatch_sets()

    queries = load_audit_queries(AUDIT_SQL_PATH)
    with sqlite3.connect(str(db_path)) as conn:
        for idx, query in enumerate(queries, start=1):
            rows = conn.execute(query).fetchall()
            if rows:
                add_mismatch(
                    mismatch_sets,
                    "preexisting_invalid_rows_detected",
                    f"audit_query_{idx}_row_count={len(rows)}",
                )

    assert_no_mismatches(
        context={"gate": "preexisting_invalid_row_detection"},
        mismatch_sets=mismatch_sets,
    )


def test_db_integrity_verifier_parity_includes_journal_integrity_artifacts(integrity_app):
    _, db_path = integrity_app
    mismatch_sets = make_mismatch_sets()

    smoke = subprocess.run(
        ["python3", "scripts/migration_smoke_vnext.py"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    smoke_payload = json_from_text(smoke.stdout)

    if smoke.returncode != 0:
        add_mismatch(
            mismatch_sets,
            "verifier_parity_missing_artifacts",
            f"migration_smoke_exit={smoke.returncode}",
        )
    if smoke_payload.get("parity_ok") is not True:
        add_mismatch(
            mismatch_sets,
            "verifier_parity_missing_artifacts",
            f"parity_ok={smoke_payload.get('parity_ok')}",
        )

    total_checks = int(smoke_payload.get("total_checks") or -1)
    required_artifact_count = int(smoke_payload.get("required_artifact_count") or -1)
    if total_checks != required_artifact_count:
        add_mismatch(
            mismatch_sets,
            "verifier_parity_missing_artifacts",
            f"count_mismatch total_checks={total_checks} required_artifact_count={required_artifact_count}",
        )
    if required_artifact_count < 55:
        add_mismatch(
            mismatch_sets,
            "verifier_parity_missing_artifacts",
            f"required_artifact_count_too_small={required_artifact_count}",
        )

    verifier_rows = run_verifier_sql(db_path, VERIFY_SQL_PATH)
    observed_by_id = {row["artifact_id"]: row for row in verifier_rows}
    missing_ids = sorted(EXPECTED_JOURNAL_INTEGRITY_ARTIFACT_IDS - set(observed_by_id))
    if missing_ids:
        add_mismatch(
            mismatch_sets,
            "verifier_parity_missing_artifacts",
            f"missing_artifact_ids={missing_ids}",
        )
    for artifact_id in sorted(EXPECTED_JOURNAL_INTEGRITY_ARTIFACT_IDS & set(observed_by_id)):
        if str(observed_by_id[artifact_id].get("ok")) != "1":
            add_mismatch(
                mismatch_sets,
                "verifier_parity_missing_artifacts",
                f"artifact_not_ok={artifact_id}:{observed_by_id[artifact_id].get('message')}",
            )

    assert_no_mismatches(
        context={"gate": "verifier_parity"},
        mismatch_sets=mismatch_sets,
    )


def test_db_integrity_failure_prefix_contract():
    with pytest.raises(AssertionError) as exc:
        mismatch_sets = make_mismatch_sets()
        add_mismatch(
            mismatch_sets,
            "missing_journal_integrity_capability",
            "simulated_missing_capability",
        )
        assert_no_mismatches(
            context={"gate": "failure_prefix_contract"},
            mismatch_sets=mismatch_sets,
        )

    assert str(exc.value).startswith(FAILURE_PREFIX)
