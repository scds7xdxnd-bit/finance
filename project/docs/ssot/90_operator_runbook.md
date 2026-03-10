# Operator Runbook (Canonical)
_Last updated: 2026-03-09_

## 90.1 Scope
Canonical procedure for backup/restore, migrations, backfill, reconcile, cutover, and rollback.

## 90.2 Non-Negotiable Contracts
- Do not run import/backfill/reset/cutover operations until `schema-status` passes.
- Do not run import/backfill/reset/cutover operations when schema verifier parity fails (`total_checks != required_artifact_count`).
- Do not run release/cutover operations when invariant catalog parity fails (`missing_ids` or `extra_asserted_ids` non-empty).
- Do not run release/cutover operations when statement export parity fails (`GATE-STATEMENT-EXPORT-PARITY`).
- Do not run release/cutover operations when security compliance gate fails (`GATE-SECURITY-COMPLIANCE`).
- Do not run release/cutover operations when startup/migration contract gate fails (`GATE-STARTUP-MIGRATION-CONTRACT`).
- Do not run release/cutover operations when DB integrity gate fails (`GATE-DB-INTEGRITY`).
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
- required DB integrity precheck before migration:
  - `sqlite3 instance/finance_app.db "SELECT COUNT(*) AS invalid_dc_rows FROM journal_line WHERE dc IS NULL OR dc NOT IN ('D','C');"`
  - `sqlite3 instance/finance_app.db "SELECT COUNT(*) AS unbalanced_finalized_rows FROM (SELECT j.id FROM journal_entry j LEFT JOIN journal_line l ON l.journal_id=j.id WHERE j.posted_at IS NOT NULL GROUP BY j.id HAVING ROUND(COALESCE(SUM(CASE WHEN l.dc='D' THEN l.amount_base ELSE 0 END),0),2) != ROUND(COALESCE(SUM(CASE WHEN l.dc='C' THEN l.amount_base ELSE 0 END),0),2));"`
  - required: both counts are `0`; otherwise stop and remediate before migration.
- `alembic upgrade head`
- `python3 -m flask --app finance_app schema-status`
- `sqlite3 instance/finance_app.db < scripts/verify_schema_capabilities.sql`
- required smoke: `python3 scripts/migration_smoke_vnext.py`
- confirm all:
  - migration smoke exits `0`
  - payload `ok=true`
  - `parity_ok=true`
  - `total_checks == required_artifact_count`
  - `schema_status.capabilities.capabilities.journal_integrity == true`
  - stdout contains `parity_ok=true total_checks=<int> required_artifact_count=<int>`
- if parity fails, stop and do not continue to backfill/reconcile/cutover.
- required DB integrity gate: `python3 -m pytest -q tests/test_db_integrity_gate.py`
- confirm all:
  - command exits `0`
  - no `DB integrity gate failed:` output
- if DB integrity gate fails, stop and do not continue to release/cutover.
- required invariant parity check: `python3 scripts/check_invariant_catalog_parity.py`
- confirm all:
  - command exits `0`
  - payload `ok=true`
  - `missing_ids=[]`
  - `extra_asserted_ids=[]`
- if invariant parity fails, stop and do not continue to release/cutover.
- required statement export parity check: `python3 -m pytest -q tests/test_statement_export_contract.py`
- confirm all:
  - command exits `0`
  - no parity mismatches reported for totals/source/coverage rules
- if statement export parity fails, stop and do not continue to release/cutover.
- required security compliance gate: `python3 -m pytest -q tests/test_security_compliance_gate.py tests/test_security_sensitive_endpoints.py`
- confirm all:
  - command exits `0`
  - no `Security compliance gate failed:` output
  - no expired exceptions from SSOT 70.5
- if security compliance gate fails, stop and do not continue to release/cutover.

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
- expected:
  - top-level `ok=true`
  - `failed_checks=[]`
  - `parity_ok=true`
  - `total_checks == required_artifact_count`
  - summary line `parity_ok=true total_checks=<int> required_artifact_count=<int>`
  - on mismatch: release is blocked; do not proceed.
3. Invariant catalog parity:
- `python3 scripts/check_invariant_catalog_parity.py`
- expected:
  - top-level `ok=true`
  - `missing_ids=[]`
  - `extra_asserted_ids=[]`
  - on mismatch: release is blocked; do not proceed.
4. Statement export parity:
- `python3 -m pytest -q tests/test_statement_export_contract.py`
- expected:
  - module passes
  - no `Statement export parity mismatch:` failures
  - on mismatch: release is blocked; do not proceed.
5. Security compliance gate:
- `python3 -m pytest -q tests/test_security_compliance_gate.py tests/test_security_sensitive_endpoints.py`
- expected:
  - modules pass
  - no `Security compliance gate failed:` failures
  - no expired exceptions in SSOT 70.5
  - on mismatch: release is blocked; do not proceed.
6. Startup/migration contract gate:
- `python3 -m pytest -q tests/test_startup_migration_contract.py`
- expected:
  - module passes
  - no `Startup/migration contract failed:` failures
  - non-ready DB drill and DB URL mismatch drill both covered by the suite
  - on mismatch: release is blocked; do not proceed.
7. DB integrity gate:
- `python3 -m pytest -q tests/test_db_integrity_gate.py`
- expected:
  - module passes
  - no `DB integrity gate failed:` failures
  - invalid `dc` writes are rejected
  - unbalanced finalization writes are rejected
  - on mismatch: release is blocked; do not proceed.
8. Reconcile gate:
- `python3 -m flask --app finance_app ledger-reconcile`
- required pass thresholds:
  - `missing_links_count == 0`
  - `mismatched_totals == 0`
  - `unbalanced_journals_count == 0`
  - `coverage_count >= 0.99`
  - `coverage_amount >= 0.995`
  - `unlinked_recent_90d_count <= 0`
9. Required test gates:
- `pytest -q tests/test_transaction_import_idempotency.py`
- `pytest -q tests/test_ledger_convergence.py`
- `pytest -q tests/test_ranked_reporting_cutover.py`
- `pytest -q tests/test_vnext_gate.py`
10. Policy lock:
- reporting fallback may be `legacy` only, never `mixed`
- fallback duration must be time-boxed and documented in incident notes

Branch protection must require checks mapped in `project/docs/ssot/80_quality_gates.md`.

## 90.6 Implementation Truth Pointers
- CLI runbook commands: `finance_app/cli/management.py`
- TB snapshot implementation: `finance_app/services/trial_balance_service.py`
- Schema verification SQL: `scripts/verify_schema_capabilities.sql`
- Verifier parity playbook: `project/docs/ssot/61_schema_verifier_parity_playbook.md`
- Invariant parity playbook: `project/docs/ssot/81_invariant_catalog_parity_playbook.md`
- Statement export parity contract: `project/docs/ssot/50_reporting_contracts.md` (SSOT 50.7)
- Security model and exception register: `project/docs/ssot/70_security_model.md`
- DB integrity contract: `project/docs/ssot/20_domain_model.md` (SSOT 20.6), `project/docs/ssot/60_schema_capabilities.md` (SSOT 60.9)
- DB integrity gate suite: `tests/test_db_integrity_gate.py`
- Existing operator reference: `project/docs/operator_runbook.md`

## 90.7 Startup and Migration Standard Procedure
This subsection is authoritative for fresh setup, upgrades, and startup troubleshooting.

### 90.7.1 Fresh Install / New Database
1. Set DB URLs for the same target DB:
- `export FINANCE_DATABASE_URL=<db_url>`
- `export ALEMBIC_DATABASE_URL=<db_url>`
2. Run migrations:
- `alembic upgrade head`
3. Verify readiness:
- `python3 -m flask --app finance_app schema-status`
- `python3 scripts/migration_smoke_vnext.py`
- `python3 -m pytest -q tests/test_startup_migration_contract.py`
4. Pass criteria:
- migration smoke exits `0` with `ok=true`
- startup/migration contract suite exits `0`
- no `Startup/migration contract failed:` output

### 90.7.2 Existing Database Upgrade
1. Create backup:
- `python3 -m flask --app finance_app sqlite-backup`
2. Apply migrations:
- `alembic upgrade head`
3. Validate contract:
- `python3 -m flask --app finance_app schema-status`
- `python3 scripts/migration_smoke_vnext.py`
- `python3 -m pytest -q tests/test_startup_migration_contract.py`
4. Stop conditions:
- any command exits non-zero
- any output includes `Startup/migration contract failed:`

### 90.7.3 Backup Rule Before Destructive Operations
- Do not run reset/restore/backfill/cutover operations without a fresh backup.
- Minimum required command:
  - `python3 -m flask --app finance_app sqlite-backup`

### 90.7.4 Troubleshooting Missing-Schema 503
If runtime returns 503 with schema-not-ready semantics (for example missing `user` table):
1. Confirm DB URL alignment:
- resolved runtime DB URL must equal Alembic DB URL in non-test environments.
2. Confirm migration state:
- `alembic current`
- `alembic heads`
3. Apply migrations if needed:
- `alembic upgrade head`
4. Re-run readiness checks:
- `python3 -m flask --app finance_app schema-status`
- `python3 scripts/migration_smoke_vnext.py`
5. Do not proceed to release/cutover until both checks pass.

## 90.8 DB Integrity Preflight and Remediation Procedure
This subsection is authoritative for `journal_integrity` rollout and ongoing operations.

### 90.8.1 Pre-migration Detection (Blocking)
- Run before applying DB integrity migration:
  - `sqlite3 instance/finance_app.db "SELECT id, journal_id, dc FROM journal_line WHERE dc IS NULL OR dc NOT IN ('D','C');"`
  - `sqlite3 instance/finance_app.db "SELECT j.id FROM journal_entry j LEFT JOIN journal_line l ON l.journal_id=j.id WHERE j.posted_at IS NOT NULL GROUP BY j.id HAVING ROUND(COALESCE(SUM(CASE WHEN l.dc='D' THEN l.amount_base ELSE 0 END),0),2) != ROUND(COALESCE(SUM(CASE WHEN l.dc='C' THEN l.amount_base ELSE 0 END),0),2);"`
- If any row is returned by either query, migration is blocked.

### 90.8.2 Remediation Policy
- Required policy is detect-and-block; do not auto-repair silently inside migration.
- Remediation must produce:
  - explicit list of repaired row IDs
  - operator-approved SQL/script in change log
  - post-repair proof that detection queries return zero rows

### 90.8.3 Post-remediation Verification
- Required sequence after repair and migration:
  - `alembic upgrade head`
  - `python3 scripts/migration_smoke_vnext.py`
  - `python3 -m pytest -q tests/test_db_integrity_gate.py`
- Release/cutover remains blocked until all commands above pass.
