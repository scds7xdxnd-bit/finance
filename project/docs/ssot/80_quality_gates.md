# Quality Gates
_Last updated: 2026-03-08_

## 80.1 Scope
Release-blocking invariants and required CI/local gate sequence for vNext correctness.

## 80.2 Required Gate Execution
1. `python3 scripts/migration_smoke_vnext.py`
2. `python3 -m pytest -q tests/test_vnext_gate.py`
3. `python3 -m pytest -q tests/test_statement_export_contract.py`
4. `python3 -m pytest -q tests/test_security_compliance_gate.py tests/test_security_sensitive_endpoints.py`
5. `python3 -m pytest -q tests/test_startup_migration_contract.py`
- Command 2 is release-blocking only if unified gate assertions include invariant catalog parity per `SSOT 80.10` / `SSOT 81`.

## 80.3 Required Checks on `main` (Branch Protection)
Required checks must be enforced in GitHub branch protection and map to SSOT gate families:

1. `Smoke Test / smoke`
- baseline route wiring smoke
2. `Smoke Test / vnext-gate`
- executes migration smoke + unified vNext gate
- currently runs:
  - `python3 scripts/migration_smoke_vnext.py`
  - `python3 -m pytest -q tests/test_vnext_gate.py`
- must preserve migration smoke exit status even when output is piped for capture
- must upload migration smoke output artifact as `migration_smoke_vnext.json` on success and failure
- migration smoke output must include exactly one summary line:
  - `parity_ok=<bool> total_checks=<int> required_artifact_count=<int>`
- unified gate must cover schema, dedupe, linking/reconcile, reporting parity, mode matrix, and scope invariants.
- unified gate must also enforce invariant catalog parity (`project/docs/qa_gate_invariants.md` vs asserted IDs in unified gate code).
- release checks must execute statement export parity assertions (`tests/test_statement_export_contract.py`) directly or via unified gate.
- release checks must execute security compliance gate assertions (`tests/test_security_compliance_gate.py` + `tests/test_security_sensitive_endpoints.py`).

If check names change, update branch protection and this SSOT section in the same PR.

## 80.4 Non-Negotiable Contracts
- Release is blocked if schema capability gate fails.
- Release is blocked if schema verifier parity fails (`total_checks != required_artifact_count`).
- Release is blocked if invariant catalog parity fails (`catalog_ids != asserted_ids`).
- Release is blocked if statement export parity fails (`/accounting/statement/export` vs `/accounting/statement/data`).
- Release is blocked if security compliance gate fails (`GATE-SECURITY-COMPLIANCE`).
- Release is blocked if startup/migration contract fails (`GATE-STARTUP-MIGRATION-CONTRACT`).
- Release is blocked if import idempotency or dedupe invariants fail.
- Release is blocked if convergence reconcile or coverage gates fail.
- Release is blocked if ranked report parity invariants fail.
- Release is blocked if scope/security smoke probes fail.
- Mixed source rejection (`source=mixed` -> `400`) is mandatory.

## 80.5 Threshold Defaults
- `coverage_count_min`: `0.99`
- `coverage_amount_min`: `0.995`
- `unlinked_recent_max`: `0`
- `pytest_coverage_min`: `85` (when enforced in CI workflow)

## 80.6 Invariant Families (Authoritative)
- `GATE-SCHEMA`
- `GATE-DEDUPE`
- `GATE-LINKING`
- `GATE-REPORT-PARITY`
- `GATE-SCOPE`
- `GATE-MODE`
- `GATE-INVARIANT-PARITY`
- `GATE-STATEMENT-EXPORT-PARITY`
- `GATE-SECURITY-COMPLIANCE`
- `GATE-STARTUP-MIGRATION-CONTRACT`

## 80.7 How To Intentionally Test Failures
- Schema failure drill:
  - run `schema-status` against a DB missing required artifacts and confirm non-zero exit.
- Schema verifier parity failure drill:
  - preferred (non-destructive): run `python3 scripts/migration_smoke_vnext.py --simulate-parity-mismatch 1`.
  - fallback: temporarily remove one `SELECT` check row from `scripts/verify_schema_capabilities.sql`, then run `python3 scripts/migration_smoke_vnext.py`.
  - confirm failure signal: non-zero exit, `ok=false`, and explicit parity mismatch metadata (`parity_ok=false`, `total_checks`, `required_artifact_count`).
- Reconcile mismatch drill:
  - run `pytest -q tests/test_ledger_convergence.py::test_ledger_reconcile_fails_on_mismatch` and confirm reconcile exit code `1`.
- Mixed source rejection drill:
  - run `pytest -q tests/test_ranked_reporting_cutover.py::test_ranked_reporting_rejects_mixed_source_mode` and confirm `400` responses.
- Dedupe contract drill:
  - run `pytest -q tests/test_transaction_import_idempotency.py` and confirm duplicate/partial-duplicate behavior.
- Sensitive endpoint drill:
  - run `pytest -q tests/test_security_sensitive_endpoints.py` and confirm CSRF/admin/schema-hard-fail behavior.
- Invariant catalog parity drill:
  - run parity checker drill from `SSOT 81.7` in simulation mode (non-destructive).
  - confirm failure signal includes non-zero exit and explicit missing invariant IDs.
- Statement export parity drill:
  - preferred (non-destructive): run `python3 -m pytest -q tests/test_statement_export_contract.py::test_statement_export_parity_simulated_mismatch`.
  - fallback: run targeted mismatch test cases in `tests/test_statement_export_contract.py` that assert failure payload parsing for totals/source drift.
  - confirm failure signal includes non-zero exit and explicit mismatch payload keys.
- Security compliance drill:
  - preferred (non-destructive): run `python3 -m pytest -q tests/test_security_compliance_gate.py::test_security_exception_expiry_simulated`.
  - fallback: run `python3 -m pytest -q tests/test_security_compliance_gate.py`.
  - confirm failure signal includes non-zero exit and explicit expired exception IDs or missing control sets.
- Startup/migration contract drill:
  - preferred (non-destructive): run `python3 -m pytest -q tests/test_startup_migration_contract.py::test_startup_contract_empty_db_drill`.
  - required mismatch drill: run `python3 -m pytest -q tests/test_startup_migration_contract.py::test_startup_contract_db_url_mismatch_drill`.
  - confirm failure signal includes non-zero exit and message prefix `Startup/migration contract failed:`.

## 80.8 Implementation Truth Pointers
- Release gate test: `tests/test_vnext_gate.py`
- Golden fixture: `tests/fixtures/golden/vnext_gate_minimal.json`
- Gate invariant catalog: `project/docs/qa_gate_invariants.md`
- Statement export parity suite: `tests/test_statement_export_contract.py`
- Security compliance suite: `tests/test_security_compliance_gate.py`, `tests/test_security_sensitive_endpoints.py`
- Gate runbook doc: `project/docs/vnext_gate.md`
- Migration smoke: `scripts/migration_smoke_vnext.py`
- Verifier parity playbook: `project/docs/ssot/61_schema_verifier_parity_playbook.md`
- Invariant parity playbook: `project/docs/ssot/81_invariant_catalog_parity_playbook.md`
- Security model and exception register: `project/docs/ssot/70_security_model.md`
- Startup/migration contract: `project/docs/ssot/60_schema_capabilities.md` (SSOT 60.8)
- Startup/migration contract suite: `tests/test_startup_migration_contract.py`
- PR checklist enforcement: `.github/pull_request_template.md`

## 80.9 `GATE-SCHEMA` Acceptance Criteria (Authoritative)
`GATE-SCHEMA` passes only when all conditions below are true:
1. `python3 scripts/migration_smoke_vnext.py` exits `0`.
2. Migration smoke payload contains `ok=true`.
3. Required capabilities are all true in `schema_status.capabilities.capabilities`.
4. `total_checks == required_artifact_count`.
5. `parity_ok=true`.

`GATE-SCHEMA` fails when any condition above is false.

Required failure signal for parity failure:
1. command exits non-zero.
2. payload contains `ok=false`.
3. payload contains `parity_ok=false`.
4. payload contains both `total_checks` and `required_artifact_count`.
5. payload contains a human-readable parity mismatch message with prefix `Schema verifier parity mismatch:`.
6. `failed_checks` may be empty when failure reason is parity mismatch only.

## 80.10 `GATE-INVARIANT-PARITY` Acceptance Criteria (Authoritative)
Definitions are normative in `SSOT 81`.

`GATE-INVARIANT-PARITY` passes only when all conditions below are true:
1. `catalog_ids` are parsed from `project/docs/qa_gate_invariants.md`.
2. `asserted_ids` are parsed from unified gate assertion code in `tests/test_vnext_gate.py`.
3. Every catalog ID is asserted by unified gate code:
   - `missing_ids := catalog_ids - asserted_ids`
   - must be empty.
4. Unified gate assertion code must not declare undocumented IDs:
   - `extra_asserted_ids := asserted_ids - catalog_ids`
   - must be empty.
5. Parity checker emits required contract fields from `SSOT 81.5`.

`GATE-INVARIANT-PARITY` fails when any condition above is false.

Required failure signal:
1. checker/test command exits non-zero.
2. output includes `ok=false`.
3. output includes `missing_ids` and `extra_asserted_ids`.
4. output includes message prefix `Invariant catalog parity mismatch:`.

## 80.11 `GATE-STATEMENT-EXPORT-PARITY` Acceptance Criteria (Authoritative)
Definitions are normative in `SSOT 50.7`.

`GATE-STATEMENT-EXPORT-PARITY` passes only when all conditions below are true:
1. `tests/test_statement_export_contract.py` passes.
2. For identical shared selectors (`ym`, `ym_compare`, `ccy`, `cash_folders`, `source`):
   - `/accounting/statement/data` and `/accounting/statement/export` agree on source-policy status behavior.
3. `source=mixed` is rejected with `400` by `/accounting/statement/export`.
4. Export totals rows (`Section="__TOTAL__"`) contain all required totals keys per statement kind from `SSOT 50.7.3`.
5. Export totals match `/data` canonical totals at exact cent precision.
6. Export metadata rows (`Section="__META__"`) satisfy source and coverage parity rules from `SSOT 50.7.4`.

`GATE-STATEMENT-EXPORT-PARITY` fails when any condition above is false.

Required failure signal:
1. test command exits non-zero.
2. failure output identifies mismatched selector context (`ym`, `kind`, `ccy`, `cash_folders`, `source`).
3. failure output identifies at least one mismatch set:
   - `totals_mismatch_keys`
   - `metadata_mismatch_keys`
   - `status_mismatch_keys`
4. failure output includes message prefix `Statement export parity mismatch:`.

## 80.12 `GATE-SECURITY-COMPLIANCE` Acceptance Criteria (Authoritative)
Definitions are normative in `SSOT 70`.

`GATE-SECURITY-COMPLIANCE` passes only when all conditions below are true:
1. `tests/test_security_compliance_gate.py` passes.
2. `tests/test_security_sensitive_endpoints.py` passes.
3. All open exceptions in SSOT 70.5 are unexpired:
   - for every row with `status=open`, `today_utc <= expires_on_utc`.
4. Every route listed in SSOT 70.5 is still explicitly classified as transitional exception until closed.
5. No route outside SSOT 70.5 open exceptions is missing required controls from SSOT 70.4.
6. Forecast Class D posture satisfies SSOT 70.6 Option A:
   - disabled by feature flag, or
   - admin-fenced + CSRF/audit/guard controls when enabled.

`GATE-SECURITY-COMPLIANCE` fails when any condition above is false.

Required failure signal:
1. test command exits non-zero.
2. failure output includes message prefix `Security compliance gate failed:`.
3. failure output includes one or more mismatch sets:
   - `expired_exception_ids`
   - `missing_csrf_routes`
   - `missing_auth_routes`
   - `missing_scope_routes`
   - `method_safety_failures`
   - `forecast_fence_failures`

## 80.13 `GATE-STARTUP-MIGRATION-CONTRACT` Acceptance Criteria (Authoritative)
Definitions are normative in `SSOT 60.8` and `SSOT 10.6`.

`GATE-STARTUP-MIGRATION-CONTRACT` passes only when all conditions below are true:
1. `python3 scripts/migration_smoke_vnext.py` exits `0` and payload `ok=true`.
2. `python3 -m pytest -q tests/test_startup_migration_contract.py` exits `0`.
3. The startup/migration contract suite verifies Alembic-first policy:
   - non-test runtime schema creation does not use `db.create_all()`.
4. The suite verifies not-ready endpoint behavior on an unmigrated database:
   - `/healthz` responds with readiness diagnostics (`ok=false` + `required_action`).
   - representative business endpoints return HTTP `503` with required keys from `SSOT 60.8.3`.
5. The suite verifies readiness enforcement:
   - when `at_head=false`, startup contract fails closed on non-health endpoints.
   - when required capabilities are missing, startup contract fails closed on non-health endpoints.
6. The suite verifies DB URL match rule:
   - non-test mismatch between runtime DB URL and Alembic DB URL fails with `error_code=DB_URL_MISMATCH`.

`GATE-STARTUP-MIGRATION-CONTRACT` fails when any condition above is false.

Required failure signal:
1. command exits non-zero.
2. failure output includes message prefix `Startup/migration contract failed:`.
3. failure output includes one or more mismatch sets:
   - `missing_payload_keys`
   - `unexpected_ready_endpoint_status`
   - `at_head_violation`
   - `capability_violation`
   - `db_url_mismatch_violation`
   - `create_all_drift_violation`
