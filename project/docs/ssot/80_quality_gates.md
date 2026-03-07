# Quality Gates
_Last updated: 2026-03-07_

## Scope
Release-blocking invariants and required CI/local gate sequence for vNext correctness.

## Required Gate Execution
1. `python3 scripts/migration_smoke_vnext.py`
2. `python3 -m pytest -q tests/test_vnext_gate.py`

## Non-Negotiable Contracts
- Release is blocked if schema capability gate fails.
- Release is blocked if import idempotency or dedupe invariants fail.
- Release is blocked if convergence reconcile or coverage gates fail.
- Release is blocked if ranked report parity invariants fail.
- Release is blocked if scope/security smoke probes fail.
- Mixed source rejection (`source=mixed` -> `400`) is mandatory.

## Threshold Defaults
- `coverage_count_min`: `0.99`
- `coverage_amount_min`: `0.995`
- `unlinked_recent_max`: `0`
- `pytest_coverage_min`: `85` (when enforced in CI workflow)

## Invariant Families (Authoritative)
- `GATE-SCHEMA`
- `GATE-DEDUPE`
- `GATE-LINKING`
- `GATE-REPORT-PARITY`
- `GATE-SCOPE`
- `GATE-MODE`

## How To Intentionally Test Failures
- Schema failure drill:
  - run `schema-status` against a DB missing required artifacts and confirm non-zero exit.
- Reconcile mismatch drill:
  - run `pytest -q tests/test_ledger_convergence.py::test_ledger_reconcile_fails_on_mismatch` and confirm reconcile exit code `1`.
- Mixed source rejection drill:
  - run `pytest -q tests/test_ranked_reporting_cutover.py::test_ranked_reporting_rejects_mixed_source_mode` and confirm `400` responses.
- Dedupe contract drill:
  - run `pytest -q tests/test_transaction_import_idempotency.py` and confirm duplicate/partial-duplicate behavior.

## Implementation Truth Pointers
- Release gate test: `tests/test_vnext_gate.py`
- Golden fixture: `tests/fixtures/golden/vnext_gate_minimal.json`
- Gate invariant catalog: `project/docs/qa_gate_invariants.md`
- Gate runbook doc: `project/docs/vnext_gate.md`
- Migration smoke: `scripts/migration_smoke_vnext.py`
