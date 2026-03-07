# Operator Runbook (Canonical)
_Last updated: 2026-03-07_

## 90.1 Scope
Canonical procedure for backup/restore, migrations, backfill, reconcile, cutover, and rollback.

## 90.2 Non-Negotiable Contracts
- Do not run import/backfill/reset/cutover operations until `schema-status` passes.
- Always create a backup/snapshot before migrations or destructive operations.
- Run backfill as dry-run before apply.
- Do not cut over while `ledger-reconcile` fails or coverage thresholds are below defaults.
- Ranked reporting fallback must not use mixed mode.
- Schema-guard bypass is emergency-only and must include a documented reason plus expiry no more than 7 days ahead.

## 90.3 Standard Procedure
1. Preflight
- `python3 -m flask --app finance_app schema-status`
- if `SCHEMA_GUARD_ENFORCE=false`, verify:
  - `SCHEMA_GUARD_BYPASS_REASON` is set
  - `SCHEMA_GUARD_BYPASS_UNTIL` is valid ISO time, unexpired, and <= 7 days from now

2. Backup
- `python3 -m flask --app finance_app sqlite-backup`
- optional: `python3 -m flask --app finance_app sqlite-backup --out-path <path>`

3. Migrate + verify
- `alembic upgrade head`
- `python3 -m flask --app finance_app schema-status`
- `sqlite3 instance/finance_app.db < scripts/verify_schema_capabilities.sql`
- optional smoke: `python3 scripts/migration_smoke_vnext.py`

4. Convergence baseline + backfill
- `python3 -m flask --app finance_app ledger-convergence-metrics`
- `python3 -m flask --app finance_app backfill-transaction-links --dry-run`
- `python3 -m flask --app finance_app backfill-transaction-links --apply`

5. Reconcile and threshold gate
- `python3 -m flask --app finance_app ledger-reconcile`
- required pass metrics:
  - `missing_links_count == 0`
  - `mismatched_totals == 0`
  - `unbalanced_journals_count == 0`
  - `coverage_count >= 0.99`
  - `coverage_amount >= 0.995`
  - `unlinked_recent_90d_count <= 0`

6. Cutover
- enforce `LEDGER_WRITE_MODE=journal`
- keep `ALLOW_LEGACY_REPORT_FALLBACK=false` for normal operation

## 90.4 Restore and Rollback
- Validate snapshot first:
  - `python3 -m flask --app finance_app tb-reset-restore --snapshot-id <id> --dry-run`
- Restore snapshot:
  - `python3 -m flask --app finance_app tb-reset-restore --snapshot-id <id>`
- Post-restore verify:
  - `python3 -m flask --app finance_app schema-status`
  - `python3 -m flask --app finance_app ledger-reconcile`

## 90.5 Release Checklist (Aligned with SSOT 80)
Run these in order for release readiness:

1. Schema capability preflight:
- `python3 -m flask --app finance_app schema-status`
- must exit non-zero on missing required capability
2. Migration smoke:
- `python3 scripts/migration_smoke_vnext.py`
- expected: top-level `ok=true` and `failed_checks=[]`
3. Reconcile gate:
- `python3 -m flask --app finance_app ledger-reconcile`
- required pass thresholds:
  - `missing_links_count == 0`
  - `mismatched_totals == 0`
  - `unbalanced_journals_count == 0`
  - `coverage_count >= 0.99`
  - `coverage_amount >= 0.995`
  - `unlinked_recent_90d_count <= 0`
4. Required test gates:
- `pytest -q tests/test_transaction_import_idempotency.py`
- `pytest -q tests/test_ledger_convergence.py`
- `pytest -q tests/test_ranked_reporting_cutover.py`
- `pytest -q tests/test_vnext_gate.py`
5. Policy lock:
- reporting fallback may be `legacy` only, never `mixed`
- fallback duration must be time-boxed and documented in incident notes

Branch protection must require checks mapped in `project/docs/ssot/80_quality_gates.md`.

## 90.6 Implementation Truth Pointers
- CLI runbook commands: `finance_app/cli/management.py`
- TB snapshot implementation: `finance_app/services/trial_balance_service.py`
- Schema verification SQL: `scripts/verify_schema_capabilities.sql`
- Existing operator reference: `project/docs/operator_runbook.md`
