# Quality Gates
_Last updated: 2026-03-07_

## 80.1 Scope
Release-blocking invariants and required CI/local gate sequence for vNext correctness.

## 80.2 Required Gate Execution
1. `python3 scripts/migration_smoke_vnext.py`
2. `python3 -m pytest -q tests/test_vnext_gate.py`

## 80.3 Required Checks on `main` (Branch Protection)
Required checks must be enforced in GitHub branch protection and map to SSOT gate families:

1. `Smoke Test / smoke`
- baseline route wiring smoke
2. `Smoke Test / vnext-gate`
- executes migration smoke + unified vNext gate
- currently runs:
  - `python3 scripts/migration_smoke_vnext.py`
  - `python3 -m pytest -q tests/test_vnext_gate.py`
- unified gate must cover schema, dedupe, linking/reconcile, reporting parity, mode matrix, and scope invariants.

If check names change, update branch protection and this SSOT section in the same PR.

## 80.4 Non-Negotiable Contracts
- Release is blocked if schema capability gate fails.
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

## 80.7 How To Intentionally Test Failures
- Schema failure drill:
  - run `schema-status` against a DB missing required artifacts and confirm non-zero exit.
- Reconcile mismatch drill:
  - run `pytest -q tests/test_ledger_convergence.py::test_ledger_reconcile_fails_on_mismatch` and confirm reconcile exit code `1`.
- Mixed source rejection drill:
  - run `pytest -q tests/test_ranked_reporting_cutover.py::test_ranked_reporting_rejects_mixed_source_mode` and confirm `400` responses.
- Dedupe contract drill:
  - run `pytest -q tests/test_transaction_import_idempotency.py` and confirm duplicate/partial-duplicate behavior.
- Sensitive endpoint drill:
  - run `pytest -q tests/test_security_sensitive_endpoints.py` and confirm CSRF/admin/schema-hard-fail behavior.

## 80.8 Implementation Truth Pointers
- Release gate test: `tests/test_vnext_gate.py`
- Golden fixture: `tests/fixtures/golden/vnext_gate_minimal.json`
- Gate invariant catalog: `project/docs/qa_gate_invariants.md`
- Gate runbook doc: `project/docs/vnext_gate.md`
- Migration smoke: `scripts/migration_smoke_vnext.py`
- PR checklist enforcement: `.github/pull_request_template.md`
