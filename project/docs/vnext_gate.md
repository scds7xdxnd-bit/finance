# vNext Gate
_Last updated: 2026-03-07_

Single executable release gate for Finance App vNext:

- test file: `tests/test_vnext_gate.py`
- golden fixture: `tests/fixtures/golden/vnext_gate_minimal.json`
- fixture loader: `tests/helpers/golden_loader.py`

## Local Run

1. `python3 scripts/migration_smoke_vnext.py`
2. `python3 -m pytest -q tests/test_vnext_gate.py`

## Gate Groups

1. Schema capability gate:
   - validates `schema-status` and required capabilities.
2. Import idempotency gate:
   - validates file hash dedupe, row-level overlap dedupe, and stable summary keys.
3. Ledger convergence gate:
   - validates backfill safety/idempotency and `ledger-reconcile` pass + thresholds.
4. Ranked report parity gate:
   - validates TB/statement/PDF numeric parity and mixed-source rejection.
5. Security scope smoke:
   - validates cross-user transaction delete fails and forecast canary does not leak owner markers.

## Failure Output

Each failure prints:

1. invariant id (for example `INV-LINK-009`)
2. observed payload/metric values
3. expected threshold/value
4. context (endpoint, user_id, mode case, or batch name)

This format is designed to be actionable in CI logs without rerunning locally first.

## CI Check

Workflow job name: `vnext-gate` in `.github/workflows/smoke.yml`.

Commands executed by the job:

1. `python3 scripts/migration_smoke_vnext.py`
2. `python3 -m pytest -q tests/test_vnext_gate.py`
