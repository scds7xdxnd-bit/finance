# Schema Capabilities Contract
_Last updated: 2026-03-09_

## 60.1 Scope
Capability-based schema guard contract for sensitive operations.

## 60.2 Capability Matrix
| Capability | Required artifacts (summary) |
| --- | --- |
| `tx_linking` | `transaction_journal_link` table, source check, required indexes/uniques |
| `link_candidates` | `transaction_link_candidate` table, required columns/indexes/check |
| `csv_idempotency` | `csv_import_batch` + `csv_import_row` tables, required uniques/checks/index |
| `tb_snapshot` | `tb_reset_snapshot` table, restore/checksum fields, required uniques/checks/index |
| `admin_audit` | `admin_action_audit` table + actor/created index |
| `journal_report_perf` | Journal report indexes on `journal_entry` and `journal_line` |
| `journal_integrity` | `journal_line.dc` check + DB-level balance enforcement for finalized journal entries |

## 60.3 Non-Negotiable Contracts
- Schema guard verdict is capability-based and artifact-based; migration revision string alone is insufficient.
- `schema-status` must report all required capabilities and exit non-zero when capability checks fail.
- Guarded operations must hard-fail (`503`) when required capabilities are missing and enforcement is enabled.
- Required capability names are stable: `tx_linking`, `link_candidates`, `csv_idempotency`, `tb_snapshot`, `admin_audit`, `journal_report_perf`, `journal_integrity`.
- Emergency schema-guard bypass is time-boxed to 7 days maximum and requires both `SCHEMA_GUARD_BYPASS_REASON` and `SCHEMA_GUARD_BYPASS_UNTIL`.

## 60.4 Hard-Fail Operation Map
- `/upload_csv` requires `csv_idempotency` and `journal_integrity`.
- `/add_transaction` requires `journal_integrity`.
- Journal mutation endpoints under `/accounting/journal/*` require `journal_integrity`.
- `/accounting/tb/reset` requires `tb_snapshot` and `admin_audit`.
- `/accounting/tb/monthly` requires `journal_report_perf`.
- `/accounting/statement/data` requires `journal_report_perf`.
- `/accounting/statement/pdf` requires `journal_report_perf`.
- `/accounting/tb/pdf` requires `journal_report_perf`.
- `backfill-transaction-links` requires `tx_linking`, `link_candidates`, `csv_idempotency`.
- `ledger-reconcile` requires `tx_linking`.
- Admin mutation routes require `admin_audit`.

## 60.5 Implementation Truth Pointers
- Capability requirements and guard logic: `finance_app/services/schema_guard_service.py`
- CLI schema command and guarded CLI operations: `finance_app/cli/management.py`
- Guarded import route: `blueprints/transactions.py`
- Guarded TB/report/admin routes: `blueprints/accounting.py`, `blueprints/admin.py`
- Bypass configuration keys: `finance_app/__init__.py`
- Verification SQL: `scripts/verify_schema_capabilities.sql`
- Capability matrix reference: `project/docs/schema_capability_matrix_vnext.md`
- Verifier parity playbook: `project/docs/ssot/61_schema_verifier_parity_playbook.md`

## 60.6 Gate/Test Pointers
- Capability tests: `tests/test_schema_guard_service.py`
- Release gate schema checks: `tests/test_vnext_gate.py`
- Sensitive-route guard tests: `tests/test_security_sensitive_endpoints.py`
- Migration smoke runner: `scripts/migration_smoke_vnext.py`
- DB integrity gate tests: `tests/test_db_integrity_gate.py`

## 60.7 Verifier Parity (Release-Blocking)
- `scripts/verify_schema_capabilities.sql` must assert exactly one check row per artifact in the deduplicated global `required_artifact_set` defined in `SSOT 61.3`.
- `scripts/migration_smoke_vnext.py` must report both:
  - `required_artifact_count`: derived from `_CAPABILITY_REQUIREMENTS` via deduplicated `required_artifact_set` (SSOT 61.3)
  - `total_checks`: derived from SQL verifier output rows
- Release parity condition is strict equality: `total_checks == required_artifact_count`.
- Any parity mismatch is a `GATE-SCHEMA` failure and blocks release.
- `GATE-SCHEMA` failure payload must include:
  - `ok=false`
  - non-empty `failed_checks` when artifact checks fail
  - `failed_checks` may be empty for parity-only failures
  - explicit parity mismatch metadata when counts differ (`total_checks`, `required_artifact_count`, `parity_ok=false`, `parity_message`, `parity_delta`).
  - `parity_message` must start with `Schema verifier parity mismatch:`.

## 60.8 Startup/Migration Contract (Authoritative)

### 60.8.1 Canonical Schema Creation Path
- Alembic-first is mandatory for runtime schema creation:
  - `alembic upgrade head`
- In non-test runtime, automatic schema creation via `db.create_all()` is forbidden.
- `AUTO_CREATE_SCHEMA` may be used only in isolated test harnesses that do not provide release evidence.
- Any production/dev runtime path that creates or mutates schema outside Alembic migrations is a contract violation.

### 60.8.2 Runtime Readiness Rule
- Runtime DB readiness requires both:
  1. required schema capabilities pass (`schema_status.ok=true`)
  2. DB revision is at Alembic head (`at_head=true`)
- If either condition is false, runtime state is `schema_not_ready`.

### 60.8.3 Not-Ready Endpoint Contract
- `/healthz` is the only endpoint allowed to respond while `schema_not_ready`.
- Every non-health business endpoint (at minimum `/`, `/login`, `/transactions`, `/accounting/*`, `/upload_csv`, `/add_transaction`, `/admin/*`, `/money-schedule/*`) must fail closed with HTTP `503`.
- Required `503` JSON payload keys:
  - `ok=false`
  - `error_code` (stable enum): `SCHEMA_NOT_READY` | `ALEMBIC_NOT_AT_HEAD` | `SCHEMA_CAPABILITY_MISSING` | `DB_URL_MISMATCH`
  - `message`
  - `required_action`
- Optional diagnostics keys:
  - `at_head`
  - `current_revision`
  - `head_revision`
  - `missing_tables`
  - `missing_capabilities`
- Required failure/log prefix for tests and diagnostics:
  - `Startup/migration contract failed:`

### 60.8.4 Environment Variable Precedence and Match Rule
- Runtime DB URL precedence:
  1. `FINANCE_DATABASE_URL`
  2. `DATABASE_URL` (local development fallback only)
  3. sqlite instance fallback (local development fallback only)
- Alembic DB URL precedence:
  1. `ALEMBIC_DATABASE_URL`
  2. `alembic.ini` configured URL
- In non-test environments, resolved runtime DB URL and Alembic DB URL must target the same database.
- Any non-test mismatch is release-blocking and must emit `error_code=DB_URL_MISMATCH`.

### 60.8.5 Verification Contract
- Required release checks:
  - `python3 scripts/migration_smoke_vnext.py`
  - `python3 -m pytest -q tests/test_startup_migration_contract.py`
- Pass condition:
  - migration smoke exits `0` with `ok=true`
  - startup/migration contract suite exits `0`

## 60.9 `journal_integrity` Capability Definition (SQLite Authoritative)

### 60.9.1 Enforcement Strategy
- Strategy is trigger-backed integrity enforcement with finalized-entry guard (`SSOT 20.6`):
  - `journal_entry.posted_at` is the finalization signal.
  - Draft entries (`posted_at IS NULL`) may be incrementally built.
  - Finalized entries (`posted_at IS NOT NULL`) must be balanced on `amount_base`.

### 60.9.2 Required Artifacts
- DB check constraint:
  - `ck_journal_line_dc` enforcing `journal_line.dc IN ('D','C')`.
- Aggregate table:
  - `journal_entry_balance` keyed by `journal_entry_id` with persisted `debit_total` and `credit_total` (base amount totals).
- Required trigger set:
  - `trg_journal_line_ai_balance` (insert maintenance)
  - `trg_journal_line_au_balance` (update maintenance)
  - `trg_journal_line_ad_balance` (delete maintenance)
  - `trg_journal_entry_bi_post_balance_guard` (insert guard for finalized rows)
  - `trg_journal_entry_bu_post_balance_guard` (update guard when finalizing)

### 60.9.3 Capability-Present Verdict (SQLite)
- `journal_integrity=true` only when all required artifacts in `60.9.2` exist.
- Guard triggers must abort unbalanced finalization with stable message prefix:
  - `journal_entry_not_balanced`
- Any missing artifact or missing guard behavior yields `journal_integrity=false`.

### 60.9.4 Verifier Parity Integration
- `journal_integrity` artifacts are part of `_CAPABILITY_REQUIREMENTS`.
- SQL verifier must emit canonical rows for all `journal_integrity` artifacts.
- `required_artifact_count`/`total_checks` parity from `SSOT 60.7` includes this capability.
