# Operator Runbook (Canonical)
_Last updated: 2026-03-07_

## Scope
Canonical procedure for backup/restore, migrations, backfill, reconcile, cutover, and rollback.

## Non-Negotiable Contracts
- Do not run import/backfill/reset/cutover operations until `schema-status` passes.
- Always create a backup/snapshot before migrations or destructive operations.
- Run backfill as dry-run before apply.
- Do not cut over while `ledger-reconcile` fails or coverage thresholds are below defaults.
- Ranked reporting fallback must not use mixed mode.

## Standard Procedure
1. Preflight
- `python3 -m flask --app finance_app schema-status`

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

## Restore and Rollback
- Validate snapshot first:
  - `python3 -m flask --app finance_app tb-reset-restore --snapshot-id <id> --dry-run`
- Restore snapshot:
  - `python3 -m flask --app finance_app tb-reset-restore --snapshot-id <id>`
- Post-restore verify:
  - `python3 -m flask --app finance_app schema-status`
  - `python3 -m flask --app finance_app ledger-reconcile`

## Implementation Truth Pointers
- CLI runbook commands: `finance_app/cli/management.py`
- TB snapshot implementation: `finance_app/services/trial_balance_service.py`
- Schema verification SQL: `scripts/verify_schema_capabilities.sql`
- Existing operator reference: `project/docs/operator_runbook.md`
