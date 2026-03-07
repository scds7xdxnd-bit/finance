from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from finance_app import create_app, db
from finance_app.models.accounting_models import JournalEntry, Transaction, TransactionJournalLink
from finance_app.services.transaction_create_service import save_transaction_payload
from finance_app.services.transaction_import_service import import_csv_transactions

from helpers.golden_loader import load_csv_fixture_text, load_golden_case, seed_golden_case

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CAPABILITIES = (
    "tx_linking",
    "link_candidates",
    "csv_idempotency",
    "tb_snapshot",
    "admin_audit",
    "journal_report_perf",
)


def _assert_inv(
    inv_id: str,
    condition: bool,
    *,
    observed: Any = None,
    expected: Any = None,
    context: dict[str, Any] | None = None,
) -> None:
    if condition:
        return
    payload = {
        "invariant": inv_id,
        "observed": observed,
        "expected": expected,
        "context": context or {},
    }
    raise AssertionError(f"{inv_id} failed\n{json.dumps(payload, indent=2, sort_keys=True, default=str)}")


def _json_from_text(text: str) -> dict[str, Any]:
    body = (text or "").strip()
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        start = body.find("{")
        end = body.rfind("}")
        if start >= 0 and end > start:
            return json.loads(body[start : end + 1])
        raise


def _metric(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _schema_parity_failure_message(payload: dict[str, Any]) -> str:
    return (
        "Schema parity gate failed: "
        f"parity_ok={payload.get('parity_ok')} "
        f"total_checks={payload.get('total_checks')} "
        f"required_artifact_count={payload.get('required_artifact_count')} "
        f"parity_message={payload.get('parity_message') or ''}"
    )


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["csrf_token"] = "test-token"


def _user_counts(user_id: int) -> dict[str, int]:
    return {
        "journal_entries": int(JournalEntry.query.filter_by(user_id=user_id).count()),
        "transactions": int(Transaction.query.filter_by(user_id=user_id).count()),
        "links": int(TransactionJournalLink.query.filter_by(user_id=user_id).count()),
    }


def _run_write_mode_case(
    app,
    *,
    user_id: int,
    case: dict[str, Any],
) -> tuple[bool, dict[str, Any], int]:
    expected = case["expected"]
    app.config["LEDGER_WRITE_MODE"] = case["mode"]

    before = _user_counts(user_id)
    ok, payload, status = save_transaction_payload(user_id, case["payload"])
    after = _user_counts(user_id)
    delta = {
        "delta_journal_entries": after["journal_entries"] - before["journal_entries"],
        "delta_transactions": after["transactions"] - before["transactions"],
        "delta_links": after["links"] - before["links"],
    }

    _assert_inv(
        "INV-MODE-001",
        status == int(expected["status_code"]),
        observed={"status": status, "payload": payload},
        expected={"status_code": int(expected["status_code"])},
        context={"mode_case": case["name"], "mode": case["mode"]},
    )
    for key in ("delta_journal_entries", "delta_transactions", "delta_links"):
        _assert_inv(
            "INV-MODE-002",
            int(delta[key]) == int(expected[key]),
            observed=delta,
            expected=expected,
            context={"mode_case": case["name"], "mode": case["mode"]},
        )

    if expected.get("link_source") and int(expected.get("delta_links") or 0) > 0:
        latest = (
            TransactionJournalLink.query.filter_by(user_id=user_id)
            .order_by(TransactionJournalLink.id.desc())
            .first()
        )
        _assert_inv(
            "INV-MODE-003",
            bool(latest and (latest.source or "") == expected["link_source"]),
            observed={"link_source": (latest.source if latest else None)},
            expected={"link_source": expected["link_source"]},
            context={"mode_case": case["name"], "mode": case["mode"]},
        )

    if expected.get("error_contains") and status >= 400:
        message = str((payload or {}).get("error") or "").lower()
        _assert_inv(
            "INV-MODE-004",
            str(expected["error_contains"]).lower() in message,
            observed={"error": message},
            expected={"contains": expected["error_contains"]},
            context={"mode_case": case["name"], "mode": case["mode"]},
        )

    return ok, payload, status


@pytest.fixture()
def gate_app(tmp_path, monkeypatch):
    db_path = tmp_path / "vnext_gate.db"
    db_url = f"sqlite:///{db_path}"

    monkeypatch.setenv("FINANCE_DATABASE_URL", db_url)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", db_url)
    monkeypatch.setenv("AUTO_CREATE_SCHEMA", "false")
    monkeypatch.setenv("SCHEMA_GUARD_ENFORCE", "true")
    monkeypatch.setenv("ALLOW_LEGACY_REPORT_FALLBACK", "false")

    env = dict(os.environ)
    env["ALEMBIC_DATABASE_URL"] = db_url
    completed = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Failed to run alembic upgrade head for vNext gate fixture setup:\n"
            f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
        )

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        try:
            yield app
        finally:
            db.session.remove()
            db.engine.dispose()

    for suffix in ("", "-shm", "-wal"):
        try:
            (Path(str(db_path) + suffix)).unlink(missing_ok=True)
        except Exception:
            pass


def test_vnext_gate(gate_app, monkeypatch):
    case = load_golden_case("vnext_gate_minimal.json")
    runner = gate_app.test_cli_runner()

    # A) Schema capability gate
    migration_smoke = subprocess.run(
        ["python3", "scripts/migration_smoke_vnext.py"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )
    _assert_inv(
        "INV-SCHEMA-001",
        migration_smoke.returncode == 0,
        observed={
            "exit_code": migration_smoke.returncode,
            "stdout": migration_smoke.stdout,
            "stderr": migration_smoke.stderr,
        },
        expected={"exit_code": 0},
        context={"gate": "migration_smoke_vnext"},
    )
    migration_payload = _json_from_text(migration_smoke.stdout)
    total_checks = migration_payload.get("total_checks")
    required_artifact_count = migration_payload.get("required_artifact_count")
    parity_ok = migration_payload.get("parity_ok")
    parity_is_true = parity_ok is True
    counts_match = (
        total_checks is not None
        and required_artifact_count is not None
        and int(total_checks) == int(required_artifact_count)
    )
    assert parity_is_true and counts_match, _schema_parity_failure_message(migration_payload)

    schema_result = runner.invoke(args=["schema-status"])
    _assert_inv(
        "INV-SCHEMA-001",
        schema_result.exit_code == 0,
        observed={"exit_code": schema_result.exit_code, "output": schema_result.output},
        expected={"exit_code": 0},
        context={"gate": "schema-status"},
    )
    schema_payload = _json_from_text(schema_result.output)
    caps = ((schema_payload.get("capabilities") or {}).get("capabilities") or {})
    for cap in REQUIRED_CAPABILITIES:
        _assert_inv(
            "INV-SCHEMA-002",
            bool(caps.get(cap)),
            observed={"capability": cap, "capabilities": caps},
            expected={"required_true": cap},
            context={"gate": "schema-status"},
        )

    with gate_app.app_context():
        seeded = seed_golden_case(case)
        owner_id = int(seeded.user_ids["u_owner"])
        other_id = int(seeded.user_ids["u_other"])

        # Write-mode matrix behavior
        for mode_case in case.get("write_mode_matrix") or []:
            mode = str(mode_case.get("mode") or "").lower()
            user_id = other_id if mode == "legacy" else owner_id
            _run_write_mode_case(gate_app, user_id=user_id, case=mode_case)

        # B) Import idempotency gate
        required_top_level_keys = {
            "batch_id",
            "file_sha256",
            "write_mode",
            "skipped_duplicate_batch",
            "totals",
            "duplicate_reasons",
            "error_reasons",
            "count_simple",
            "count_journal",
            "rows_new",
            "rows_duplicate",
            "rows_error",
        }
        required_total_keys = {
            "rows_total",
            "rows_new",
            "rows_duplicate",
            "rows_error",
            "journal_entries_created",
            "legacy_transactions_created",
            "normalized_dates",
            "unparsable_dates",
        }

        duplicate_batch_hits = 0
        overlap_duplicate_rows = 0
        partial_duplicate_errors = 0

        for spec in case.get("csv_import_batches") or []:
            raw_csv = load_csv_fixture_text(spec["fixture_path"])
            user_id = int(seeded.user_ids[spec["user"]])
            summary = import_csv_transactions(
                raw_csv,
                user_id,
                filename=spec["filename"],
                write_mode=spec["write_mode"],
                idempotency_enabled=bool(spec["idempotency_enabled"]),
                force=bool(spec["force"]),
            )

            missing_summary_keys = sorted(required_top_level_keys.difference(summary.keys()))
            _assert_inv(
                "INV-DEDUPE-001",
                not missing_summary_keys,
                observed={"missing_summary_keys": missing_summary_keys, "summary_keys": sorted(summary.keys())},
                expected={"required_summary_keys": sorted(required_top_level_keys)},
                context={"batch_name": spec["name"]},
            )

            totals = summary.get("totals") or {}
            missing_total_keys = sorted(required_total_keys.difference(totals.keys()))
            _assert_inv(
                "INV-DEDUPE-002",
                not missing_total_keys,
                observed={"missing_total_keys": missing_total_keys, "total_keys": sorted(totals.keys())},
                expected={"required_total_keys": sorted(required_total_keys)},
                context={"batch_name": spec["name"]},
            )

            expected_summary = spec["expected_summary"]
            _assert_inv(
                "INV-DEDUPE-003",
                bool(summary.get("skipped_duplicate_batch")) == bool(expected_summary["skipped_duplicate_batch"]),
                observed={"skipped_duplicate_batch": summary.get("skipped_duplicate_batch")},
                expected={"skipped_duplicate_batch": expected_summary["skipped_duplicate_batch"]},
                context={"batch_name": spec["name"]},
            )

            for key in ("rows_new", "rows_duplicate", "rows_error", "count_journal", "count_simple"):
                _assert_inv(
                    "INV-DEDUPE-004",
                    int(summary.get(key) or 0) >= int(expected_summary.get(key) or 0),
                    observed={key: int(summary.get(key) or 0)},
                    expected={f"{key}_min": int(expected_summary.get(key) or 0)},
                    context={"batch_name": spec["name"]},
                )

            duplicate_reasons = summary.get("duplicate_reasons") or {}
            error_reasons = summary.get("error_reasons") or {}
            _assert_inv(
                "INV-DEDUPE-005",
                isinstance(duplicate_reasons, dict) and isinstance(error_reasons, dict),
                observed={
                    "duplicate_reasons_type": type(duplicate_reasons).__name__,
                    "error_reasons_type": type(error_reasons).__name__,
                },
                expected={"maps": ["duplicate_reasons", "error_reasons"]},
                context={"batch_name": spec["name"]},
            )

            for reason_key, min_count in (expected_summary.get("duplicate_reasons") or {}).items():
                _assert_inv(
                    "INV-DEDUPE-006",
                    int(duplicate_reasons.get(reason_key) or 0) >= int(min_count),
                    observed={"reason": reason_key, "count": int(duplicate_reasons.get(reason_key) or 0)},
                    expected={"min_count": int(min_count)},
                    context={"batch_name": spec["name"]},
                )
            for reason_key, min_count in (expected_summary.get("error_reasons") or {}).items():
                _assert_inv(
                    "INV-DEDUPE-007",
                    int(error_reasons.get(reason_key) or 0) >= int(min_count),
                    observed={"reason": reason_key, "count": int(error_reasons.get(reason_key) or 0)},
                    expected={"min_count": int(min_count)},
                    context={"batch_name": spec["name"]},
                )

            tags = set(spec.get("scenario_tags") or [])
            if "reupload" in tags and bool(summary.get("skipped_duplicate_batch")):
                duplicate_batch_hits += 1
            if "overlap_export" in tags:
                overlap_duplicate_rows += int(summary.get("rows_duplicate") or 0)
            if "partial_duplicate" in tags:
                partial_duplicate_errors += int(error_reasons.get("partial_duplicate_group") or 0)

        expected_dedupe = (case.get("expected") or {}).get("dedupe_gates") or {}
        _assert_inv(
            "INV-DEDUPE-008",
            duplicate_batch_hits >= int(expected_dedupe.get("duplicate_batch_hits_min") or 0),
            observed={"duplicate_batch_hits": duplicate_batch_hits},
            expected={"min": int(expected_dedupe.get("duplicate_batch_hits_min") or 0)},
            context={"gate": "import_idempotency"},
        )
        _assert_inv(
            "INV-DEDUPE-009",
            overlap_duplicate_rows >= int(expected_dedupe.get("overlap_duplicate_rows_min") or 0),
            observed={"overlap_duplicate_rows": overlap_duplicate_rows},
            expected={"min": int(expected_dedupe.get("overlap_duplicate_rows_min") or 0)},
            context={"gate": "import_idempotency"},
        )
        _assert_inv(
            "INV-DEDUPE-010",
            partial_duplicate_errors >= int(expected_dedupe.get("partial_duplicate_group_errors_min") or 0),
            observed={"partial_duplicate_errors": partial_duplicate_errors},
            expected={"min": int(expected_dedupe.get("partial_duplicate_group_errors_min") or 0)},
            context={"gate": "import_idempotency"},
        )

        # C) Ledger convergence gate
        dry_run = runner.invoke(
            args=["backfill-transaction-links", "--user-id", str(owner_id), "--dry-run"]
        )
        _assert_inv(
            "INV-LINK-001",
            dry_run.exit_code == 0,
            observed={"exit_code": dry_run.exit_code, "output": dry_run.output},
            expected={"exit_code": 0},
            context={"gate": "backfill_dry_run"},
        )
        apply_once = runner.invoke(
            args=["backfill-transaction-links", "--user-id", str(owner_id), "--apply"]
        )
        _assert_inv(
            "INV-LINK-002",
            apply_once.exit_code == 0,
            observed={"exit_code": apply_once.exit_code, "output": apply_once.output},
            expected={"exit_code": 0},
            context={"gate": "backfill_apply_first"},
        )
        apply_twice = runner.invoke(
            args=["backfill-transaction-links", "--user-id", str(owner_id), "--apply"]
        )
        _assert_inv(
            "INV-LINK-003",
            apply_twice.exit_code == 0,
            observed={"exit_code": apply_twice.exit_code, "output": apply_twice.output},
            expected={"exit_code": 0},
            context={"gate": "backfill_apply_second"},
        )

        second_summary = _json_from_text(apply_twice.output)
        created_second = int(second_summary.get("created_exact") or 0) + int(
            second_summary.get("created_strong") or 0
        )
        _assert_inv(
            "INV-LINK-004",
            created_second == 0,
            observed={"created_exact": second_summary.get("created_exact"), "created_strong": second_summary.get("created_strong")},
            expected={"created_second_run": 0},
            context={"gate": "backfill_idempotency"},
        )

        link_sources = [
            (row.source or "").lower()
            for row in TransactionJournalLink.query.filter_by(user_id=owner_id).all()
        ]
        weak_sources = [src for src in link_sources if src.startswith("weak")]
        _assert_inv(
            "INV-LINK-005",
            len(weak_sources) == 0,
            observed={"link_sources": sorted(link_sources), "weak_sources": weak_sources},
            expected={"weak_sources": []},
            context={"gate": "weak_never_autolink"},
        )

        reconcile = runner.invoke(args=["ledger-reconcile", "--user-id", str(owner_id), "--fail-on-mismatch"])
        _assert_inv(
            "INV-LINK-006",
            reconcile.exit_code == 0,
            observed={"exit_code": reconcile.exit_code, "output": reconcile.output},
            expected={"exit_code": 0},
            context={"gate": "ledger_reconcile"},
        )
        reconcile_payload = _json_from_text(reconcile.output)
        pass_flag = _metric(reconcile_payload, "pass", "ok")
        _assert_inv(
            "INV-LINK-007",
            bool(pass_flag) is True,
            observed={"pass": pass_flag, "payload": reconcile_payload},
            expected={"pass": True},
            context={"gate": "ledger_reconcile"},
        )

        checks = (reconcile_payload.get("reconcile") or {}).get("checks") or {}
        unbalanced_count = _metric(
            reconcile_payload,
            "unbalanced_journals_count",
            "unbalanced_journal_entries",
        )
        if unbalanced_count is None:
            unbalanced_count = _metric(checks, "unbalanced_journals_count", "unbalanced_journal_entries")
        missing_links_count = _metric(reconcile_payload, "missing_links_count", "unmapped_transactions")
        if missing_links_count is None:
            missing_links_count = _metric(checks, "missing_links_count", "unmapped_transactions")
        mismatch_count = _metric(reconcile_payload, "mismatched_totals", "mismatched_links_count", "mismatched_links")
        if mismatch_count is None:
            mismatch_count = _metric(checks, "mismatched_totals", "mismatched_links_count", "mismatched_links")

        _assert_inv(
            "INV-LINK-008",
            int(unbalanced_count or 0) == 0,
            observed={"unbalanced": unbalanced_count, "checks": checks},
            expected={"unbalanced": 0},
            context={"gate": "ledger_reconcile"},
        )
        _assert_inv(
            "INV-LINK-009",
            int(missing_links_count or 0) == 0,
            observed={"missing_links": missing_links_count, "checks": checks},
            expected={"missing_links": 0},
            context={"gate": "ledger_reconcile_dual_scope"},
        )
        _assert_inv(
            "INV-LINK-010",
            int(mismatch_count or 0) == 0,
            observed={"mismatched_links": mismatch_count, "checks": checks},
            expected={"mismatched_links": 0},
            context={"gate": "ledger_reconcile"},
        )

        coverage = reconcile_payload.get("coverage") or {}
        thresholds = (case.get("expected") or {}).get("coverage_gates") or {}
        total_legacy_tx_raw = coverage.get("total_legacy_tx")
        total_legacy_amount_raw = coverage.get("total_legacy_amount")
        coverage_count_raw = _metric(reconcile_payload, "coverage_count")
        coverage_amount_raw = _metric(reconcile_payload, "coverage_amount")
        unlinked_recent_raw = _metric(reconcile_payload, "unlinked_recent_90d_count")

        if coverage_count_raw is None:
            coverage_count_raw = coverage.get("coverage_count")
        if coverage_amount_raw is None:
            coverage_amount_raw = coverage.get("coverage_amount")
        if unlinked_recent_raw is None:
            unlinked_recent_raw = coverage.get("unlinked_recent_90d_count")

        total_legacy_tx = int(total_legacy_tx_raw) if total_legacy_tx_raw is not None else None
        total_legacy_amount = float(total_legacy_amount_raw) if total_legacy_amount_raw is not None else None
        coverage_count = float(coverage_count_raw or 0.0)
        coverage_amount = float(coverage_amount_raw or 0.0)
        unlinked_recent = int(unlinked_recent_raw or 0)

        if total_legacy_tx == 0:
            _assert_inv(
                "INV-LINK-011",
                coverage_count == pytest.approx(1.0),
                observed={"coverage_count": coverage_count, "total_legacy_tx": total_legacy_tx},
                expected={"coverage_count": 1.0},
                context={"gate": "coverage_count"},
            )
        else:
            _assert_inv(
                "INV-LINK-011",
                coverage_count >= float(thresholds.get("coverage_count_min") or 0.99),
                observed={"coverage_count": coverage_count},
                expected={"coverage_count_min": float(thresholds.get("coverage_count_min") or 0.99)},
                context={"gate": "coverage_count"},
            )
        if total_legacy_amount == 0.0:
            _assert_inv(
                "INV-LINK-012",
                coverage_amount == pytest.approx(1.0),
                observed={"coverage_amount": coverage_amount, "total_legacy_amount": total_legacy_amount},
                expected={"coverage_amount": 1.0},
                context={"gate": "coverage_amount"},
            )
        else:
            _assert_inv(
                "INV-LINK-012",
                coverage_amount >= float(thresholds.get("coverage_amount_min") or 0.995),
                observed={"coverage_amount": coverage_amount},
                expected={"coverage_amount_min": float(thresholds.get("coverage_amount_min") or 0.995)},
                context={"gate": "coverage_amount"},
            )
        _assert_inv(
            "INV-LINK-013",
            unlinked_recent <= int(thresholds.get("unlinked_recent_max") or 0),
            observed={"unlinked_recent_90d_count": unlinked_recent},
            expected={"unlinked_recent_max": int(thresholds.get("unlinked_recent_max") or 0)},
            context={"gate": "coverage_unlinked_recent"},
        )

        # D) Ranked report parity gate
        client = gate_app.test_client()
        _login(client, owner_id)
        ym = case["period"]["ym"]

        tb_resp = client.get(f"/accounting/tb/monthly?ym={ym}")
        _assert_inv(
            "INV-RPT-001",
            tb_resp.status_code == 200,
            observed={"status_code": tb_resp.status_code, "body": tb_resp.get_data(as_text=True)},
            expected={"status_code": 200},
            context={"endpoint": "/accounting/tb/monthly"},
        )
        tb_payload = tb_resp.get_json()
        _assert_inv(
            "INV-RPT-002",
            bool(tb_payload.get("ok")),
            observed=tb_payload,
            expected={"ok": True},
            context={"endpoint": "/accounting/tb/monthly"},
        )
        _assert_inv(
            "INV-RPT-003",
            (tb_payload.get("source") or {}).get("mode") == "journal",
            observed=tb_payload.get("source"),
            expected={"mode": "journal"},
            context={"endpoint": "/accounting/tb/monthly"},
        )

        expected_tb = (((case.get("expected") or {}).get("reports") or {}).get("tb_monthly") or {})
        _assert_inv(
            "INV-RPT-004",
            float(tb_payload["totals"]["asset"]["bd"]) == pytest.approx(float(expected_tb["asset_bd"])),
            observed={"asset_bd": tb_payload["totals"]["asset"]["bd"]},
            expected={"asset_bd": expected_tb["asset_bd"]},
            context={"endpoint": "/accounting/tb/monthly"},
        )
        _assert_inv(
            "INV-RPT-005",
            float(tb_payload["totals"]["asset"]["balance"]) == pytest.approx(float(expected_tb["asset_balance"])),
            observed={"asset_balance": tb_payload["totals"]["asset"]["balance"]},
            expected={"asset_balance": expected_tb["asset_balance"]},
            context={"endpoint": "/accounting/tb/monthly"},
        )
        _assert_inv(
            "INV-RPT-006",
            float(tb_payload["grand_totals"]["period_debit"]) == pytest.approx(float(expected_tb["grand_period_debit"])),
            observed={"period_debit": tb_payload["grand_totals"]["period_debit"]},
            expected={"period_debit": expected_tb["grand_period_debit"]},
            context={"endpoint": "/accounting/tb/monthly"},
        )
        _assert_inv(
            "INV-RPT-007",
            float(tb_payload["grand_totals"]["period_credit"]) == pytest.approx(float(expected_tb["grand_period_credit"])),
            observed={"period_credit": tb_payload["grand_totals"]["period_credit"]},
            expected={"period_credit": expected_tb["grand_period_credit"]},
            context={"endpoint": "/accounting/tb/monthly"},
        )

        statement_resp = client.get(f"/accounting/statement/data?ym={ym}")
        _assert_inv(
            "INV-RPT-008",
            statement_resp.status_code == 200,
            observed={"status_code": statement_resp.status_code, "body": statement_resp.get_data(as_text=True)},
            expected={"status_code": 200},
            context={"endpoint": "/accounting/statement/data"},
        )
        statement_payload = statement_resp.get_json()
        _assert_inv(
            "INV-RPT-009",
            bool(statement_payload.get("ok")),
            observed=statement_payload,
            expected={"ok": True},
            context={"endpoint": "/accounting/statement/data"},
        )
        _assert_inv(
            "INV-RPT-010",
            (statement_payload.get("source") or {}).get("mode") == "journal",
            observed=statement_payload.get("source"),
            expected={"mode": "journal"},
            context={"endpoint": "/accounting/statement/data"},
        )

        expected_statements = (((case.get("expected") or {}).get("reports") or {}).get("statements") or {})
        income_totals = (statement_payload.get("statements") or {}).get("income", {}).get("totals") or {}
        balance_totals = (statement_payload.get("statements") or {}).get("balance", {}).get("totals") or {}
        cashflow_totals = (statement_payload.get("statements") or {}).get("cashflow", {}).get("totals") or {}
        _assert_inv(
            "INV-RPT-011",
            float(income_totals["revenue"]) == pytest.approx(float(expected_statements["income"]["revenue"])),
            observed={"revenue": income_totals.get("revenue")},
            expected={"revenue": expected_statements["income"]["revenue"]},
            context={"endpoint": "/accounting/statement/data"},
        )
        _assert_inv(
            "INV-RPT-012",
            float(income_totals["expense"]) == pytest.approx(float(expected_statements["income"]["expense"])),
            observed={"expense": income_totals.get("expense")},
            expected={"expense": expected_statements["income"]["expense"]},
            context={"endpoint": "/accounting/statement/data"},
        )
        _assert_inv(
            "INV-RPT-013",
            float(income_totals["net_income"]) == pytest.approx(float(expected_statements["income"]["net_income"])),
            observed={"net_income": income_totals.get("net_income")},
            expected={"net_income": expected_statements["income"]["net_income"]},
            context={"endpoint": "/accounting/statement/data"},
        )
        _assert_inv(
            "INV-RPT-014",
            float(balance_totals["assets"]) == pytest.approx(float(expected_statements["balance"]["assets"])),
            observed={"assets": balance_totals.get("assets")},
            expected={"assets": expected_statements["balance"]["assets"]},
            context={"endpoint": "/accounting/statement/data"},
        )
        _assert_inv(
            "INV-RPT-015",
            float(balance_totals["le_sum"]) == pytest.approx(float(expected_statements["balance"]["le_sum"])),
            observed={"le_sum": balance_totals.get("le_sum")},
            expected={"le_sum": expected_statements["balance"]["le_sum"]},
            context={"endpoint": "/accounting/statement/data"},
        )
        _assert_inv(
            "INV-RPT-016",
            float(cashflow_totals["opening"]) == pytest.approx(float(expected_statements["cashflow"]["opening"])),
            observed={"opening": cashflow_totals.get("opening")},
            expected={"opening": expected_statements["cashflow"]["opening"]},
            context={"endpoint": "/accounting/statement/data"},
        )
        _assert_inv(
            "INV-RPT-017",
            float(cashflow_totals["closing"]) == pytest.approx(float(expected_statements["cashflow"]["closing"])),
            observed={"closing": cashflow_totals.get("closing")},
            expected={"closing": expected_statements["cashflow"]["closing"]},
            context={"endpoint": "/accounting/statement/data"},
        )

        captured_statement_pdf: dict[str, Any] = {}

        def _fake_income_pdf(data, org, start_date, end_date, out_pdf, logo=None):
            captured_statement_pdf["data"] = data
            Path(out_pdf).write_bytes(b"%PDF-1.4\n%stub\n%%EOF\n")

        monkeypatch.setattr("statements_pdf.generate_income_statement_pdf_from_data", _fake_income_pdf)
        statement_pdf_resp = client.get(f"/accounting/statement/pdf?kind=income&ym={ym}")
        _assert_inv(
            "INV-RPT-018",
            statement_pdf_resp.status_code == 200,
            observed={"status_code": statement_pdf_resp.status_code},
            expected={"status_code": 200},
            context={"endpoint": "/accounting/statement/pdf"},
        )
        statement_pdf_totals = (captured_statement_pdf.get("data") or {}).get("totals") or {}
        _assert_inv(
            "INV-RPT-019",
            float(statement_pdf_totals.get("revenue") or 0.0) == pytest.approx(float(income_totals["revenue"])),
            observed={"pdf_revenue": statement_pdf_totals.get("revenue")},
            expected={"json_revenue": income_totals["revenue"]},
            context={"endpoint": "/accounting/statement/pdf"},
        )
        _assert_inv(
            "INV-RPT-020",
            float(statement_pdf_totals.get("net_income") or 0.0) == pytest.approx(float(income_totals["net_income"])),
            observed={"pdf_net_income": statement_pdf_totals.get("net_income")},
            expected={"json_net_income": income_totals["net_income"]},
            context={"endpoint": "/accounting/statement/pdf"},
        )

        captured_tb_pdf: dict[str, Any] = {}

        def _fake_tb_pdf(data, org, start_date, end_date, out_pdf, logo=None, engine="weasy"):
            captured_tb_pdf["data"] = data
            Path(out_pdf).write_bytes(b"%PDF-1.4\n%stub\n%%EOF\n")
            return 1, "0" * 64

        monkeypatch.setattr("trial_balance_pdf.generate_trial_balance_pdf", _fake_tb_pdf)
        tb_pdf_resp = client.get(f"/accounting/tb/pdf?ym={ym}&scope=folders")
        _assert_inv(
            "INV-RPT-021",
            tb_pdf_resp.status_code == 200,
            observed={"status_code": tb_pdf_resp.status_code},
            expected={"status_code": 200},
            context={"endpoint": "/accounting/tb/pdf"},
        )
        rows = (captured_tb_pdf.get("data") or {}).get("rows") or []
        pdf_debit = sum(float(row.get("debit") or 0.0) for row in rows)
        pdf_credit = sum(float(row.get("credit") or 0.0) for row in rows)
        _assert_inv(
            "INV-RPT-022",
            pdf_debit == pytest.approx(float(tb_payload["grand_totals"]["period_debit"])),
            observed={"tb_pdf_debit": pdf_debit},
            expected={"tb_json_debit": tb_payload["grand_totals"]["period_debit"]},
            context={"endpoint": "/accounting/tb/pdf"},
        )
        _assert_inv(
            "INV-RPT-023",
            pdf_credit == pytest.approx(float(tb_payload["grand_totals"]["period_credit"])),
            observed={"tb_pdf_credit": pdf_credit},
            expected={"tb_json_credit": tb_payload["grand_totals"]["period_credit"]},
            context={"endpoint": "/accounting/tb/pdf"},
        )

        for endpoint in (
            f"/accounting/tb/monthly?ym={ym}&source=mixed",
            f"/accounting/statement/data?ym={ym}&source=mixed",
            f"/accounting/statement/pdf?kind=income&ym={ym}&source=mixed",
            f"/accounting/tb/pdf?ym={ym}&source=mixed",
        ):
            resp = client.get(endpoint)
            _assert_inv(
                "INV-RPT-024",
                resp.status_code == 400,
                observed={"endpoint": endpoint, "status_code": resp.status_code, "body": resp.get_data(as_text=True)},
                expected={"status_code": 400},
                context={"gate": "mixed_source_rejected"},
            )

        # Legacy mode assertion: ranked endpoints remain journal-only (never mixed).
        gate_app.config["LEDGER_WRITE_MODE"] = "legacy"
        legacy_tb_resp = client.get(f"/accounting/tb/monthly?ym={ym}")
        _assert_inv(
            "INV-RPT-025",
            legacy_tb_resp.status_code == 200,
            observed={"status_code": legacy_tb_resp.status_code, "body": legacy_tb_resp.get_data(as_text=True)},
            expected={"status_code": 200},
            context={"endpoint": "/accounting/tb/monthly", "write_mode": "legacy"},
        )
        legacy_tb_payload = legacy_tb_resp.get_json()
        legacy_source = legacy_tb_payload.get("source") or {}
        _assert_inv(
            "INV-RPT-026",
            legacy_source.get("mode") == "journal" and not bool(legacy_source.get("mixed_mode_allowed")),
            observed=legacy_source,
            expected={"mode": "journal", "mixed_mode_allowed": False},
            context={"endpoint": "/accounting/tb/monthly", "write_mode": "legacy"},
        )
        gate_app.config["LEDGER_WRITE_MODE"] = "journal"

        # E) Security scope smoke probe
        marker = "LEAK_MARKER_OWNER_TX"
        owner_tx = Transaction(
            user_id=owner_id,
            date="2026/03/01",
            description=marker,
            debit_account="Main Cash",
            debit_amount=12.0,
            credit_account="Product Revenue",
            credit_amount=12.0,
        )
        db.session.add(owner_tx)
        db.session.commit()
        owner_tx_id = int(owner_tx.id)

        other_client = gate_app.test_client()
        _login(other_client, other_id)
        delete_resp = other_client.post(
            f"/transactions/delete/{owner_tx_id}",
            follow_redirects=False,
            headers={"X-CSRF-Token": "test-token"},
        )
        _assert_inv(
            "INV-SCOPE-001",
            delete_resp.status_code in (302, 401, 403),
            observed={"status_code": delete_resp.status_code},
            expected={"status_code_any_of": [302, 401, 403]},
            context={"endpoint": "/transactions/delete/<tx_id>", "actor_user_id": other_id, "target_tx_id": owner_tx_id},
        )
        still_exists = db.session.get(Transaction, owner_tx_id) is not None
        _assert_inv(
            "INV-SCOPE-002",
            still_exists,
            observed={"transaction_exists_after_cross_user_delete": still_exists},
            expected={"transaction_exists_after_cross_user_delete": True},
            context={"target_tx_id": owner_tx_id, "actor_user_id": other_id, "target_user_id": owner_id},
        )

        has_forecast_route = any(rule.rule == "/api/forecast.json" for rule in gate_app.url_map.iter_rules())
        if has_forecast_route:
            forecast_resp = other_client.get(
                f"/api/forecast.json?start=2024-01-01&end=2024-01-02&currency=KRW&user_id={owner_id}"
            )
            forecast_body = forecast_resp.get_data(as_text=True)
            forecast_safe = (
                forecast_resp.status_code in (401, 403, 404)
                or marker not in forecast_body
            )
            _assert_inv(
                "INV-SCOPE-003",
                forecast_safe,
                observed={
                    "status_code": forecast_resp.status_code,
                    "contains_owner_marker": (marker in forecast_body),
                },
                expected={
                    "status_code_any_of": [401, 403, 404],
                    "or_marker_absent": True,
                },
                context={"endpoint": "/api/forecast.json", "actor_user_id": other_id, "target_user_id": owner_id},
            )
