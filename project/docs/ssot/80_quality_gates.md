# Quality Gates
_Last updated: 2026-03-08_

## 80.1 Scope
Release-blocking invariants and required CI/local gate sequence for vNext correctness.

## 80.2 Required Gate Execution
1. `python3 scripts/migration_smoke_vnext.py`
2. `python3 -m pytest -q tests/test_vnext_gate.py`
3. `python3 -m pytest -q tests/test_statement_export_contract.py`
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

If check names change, update branch protection and this SSOT section in the same PR.

## 80.4 Non-Negotiable Contracts
- Release is blocked if schema capability gate fails.
- Release is blocked if schema verifier parity fails (`total_checks != required_artifact_count`).
- Release is blocked if invariant catalog parity fails (`catalog_ids != asserted_ids`).
- Release is blocked if statement export parity fails (`/accounting/statement/export` vs `/accounting/statement/data`).
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

## 80.8 Implementation Truth Pointers
- Release gate test: `tests/test_vnext_gate.py`
- Golden fixture: `tests/fixtures/golden/vnext_gate_minimal.json`
- Gate invariant catalog: `project/docs/qa_gate_invariants.md`
- Statement export parity suite: `tests/test_statement_export_contract.py`
- Gate runbook doc: `project/docs/vnext_gate.md`
- Migration smoke: `scripts/migration_smoke_vnext.py`
- Verifier parity playbook: `project/docs/ssot/61_schema_verifier_parity_playbook.md`
- Invariant parity playbook: `project/docs/ssot/81_invariant_catalog_parity_playbook.md`
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
