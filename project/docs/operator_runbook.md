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
  - `python3 -m flask --app finance_app ledger-reconcile`
- Default cutover thresholds enforced by `ledger-reconcile`:
  - `coverage_count >= 0.99`
  - `coverage_amount >= 0.995`
  - `unlinked_recent_90d_count <= 0`
- CLI output schema (machine-readable, deterministic):
  - `pass`
  - `unbalanced_journals_count`
  - `missing_links_count`
  - `mismatched_totals`
  - `coverage_count`
  - `coverage_amount`
  - `unlinked_recent_90d_count`
- Override flag (non-default, incident/debug only):
  - `python3 -m flask --app finance_app ledger-reconcile --no-fail-on-mismatch`
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

## 10) Release Checklist (Merge Train Gate)
Run in order and do not proceed on failures.

1. Schema capability gate:
   - `python3 -m flask --app finance_app schema-status`
   - Pass criteria:
     - exit code `0`
     - `ok=true`
     - required capabilities present (`tx_linking`, `link_candidates`, `csv_idempotency`, `tb_snapshot`, `admin_audit`, `journal_report_perf`)
2. Migration smoke:
   - `python3 scripts/migration_smoke_vnext.py`
   - Pass criteria:
     - top-level `ok=true`
     - `failed_checks=[]`
3. Reconcile release gate:
   - `python3 -m flask --app finance_app ledger-reconcile`
   - Pass criteria:
     - exit code `0`
     - `pass=true`
     - `unbalanced_journals_count=0`
     - `missing_links_count=0`
     - `mismatched_totals=0`
     - `coverage_count >= 0.99`
     - `coverage_amount >= 0.995`
     - `unlinked_recent_90d_count <= 0`
4. Test gates:
   - `pytest -q tests/test_transaction_import_idempotency.py`
   - `pytest -q tests/test_ledger_convergence.py`
   - `pytest -q tests/test_ranked_reporting_cutover.py`
   - Pass criteria:
     - all commands exit `0`
5. Incident fallback policy:
   - if reporting fallback is used, it must be `legacy` only, never `mixed`
   - fallback window must be time-boxed to 7 days maximum
