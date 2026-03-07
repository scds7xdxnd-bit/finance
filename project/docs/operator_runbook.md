# Operator Runbook (Ledger Convergence)

## 1) Preflight
- Check schema capabilities and migration state:
  - `python3 -m flask --app finance_app schema-status`
- If command exits non-zero, do not run import/backfill/reset/reconcile operations.

## 2) Backup
- Always create a DB snapshot before migrations or reset operations.
- SQLite backup primitives:
  - `python3 -m flask --app finance_app sqlite-backup`
  - `python3 -m flask --app finance_app sqlite-backup --out-path instance/backups/sqlite/pre_migration.db`
  - Returned payload includes `backup_path`, `sha256`, and `file_size_bytes`.
- TB reset snapshot verification:
  - `python3 -m flask --app finance_app tb-reset-restore --snapshot-id <id> --dry-run`

## 3) Migrate
- Apply schema migrations:
  - `alembic upgrade head`
- Verify:
  - `python3 -m flask --app finance_app schema-status`
  - `sqlite3 instance/finance_app.db < scripts/verify_schema_capabilities.sql`

## 3.1) Migration Smoke (Ephemeral SQLite)
- Standard smoke path:
  - `python3 scripts/migration_smoke_vnext.py`
- This command performs:
  - Alembic upgrade on a temporary SQLite file.
  - `schema-status` capability report check.
  - SQL verification query suite from `scripts/verify_schema_capabilities.sql`.

## 4) Convergence Metrics
- Collect baseline:
  - `python3 -m flask --app finance_app ledger-convergence-metrics`
- Record `coverage_count`, `coverage_amount`, and `unlinked_recent_90d_count`.

## 5) Backfill Links
- Dry run first:
  - `python3 -m flask --app finance_app backfill-transaction-links --dry-run`
- Apply:
  - `python3 -m flask --app finance_app backfill-transaction-links --apply`

## 6) Reconcile
- Execute reconciliation gate:
  - `python3 -m flask --app finance_app ledger-reconcile --fail-on-mismatch`
- Default cutover thresholds enforced by `ledger-reconcile`:
  - `coverage_count >= 0.99`
  - `coverage_amount >= 0.995`
  - `unlinked_recent_90d_count <= 0`
- Do not cut over report paths if this command fails.

## 7) Cutover
- Set write mode:
  - `LEDGER_WRITE_MODE=journal`
- Keep `ALLOW_LEGACY_REPORT_FALLBACK=false` except temporary incident response.
- Legacy fallback is emergency-only and time-boxed to 7 days maximum.

## 8) TB Reset Procedure
- Require typed confirm phrase `RESET TB`, `confirm_at_ms`, and reason.
- Ensure snapshot was created before reset.

## 9) Restore
- Restore from snapshot metadata:
  - `python3 -m flask --app finance_app tb-reset-restore --snapshot-id <id>`
- Re-run `schema-status` and `ledger-reconcile`.
