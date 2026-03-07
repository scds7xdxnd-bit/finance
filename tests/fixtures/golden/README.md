# Golden Fixture Contract

Golden fixture files for QA gate tests must validate against:

- `tests/fixtures/golden/finance_gate_case.schema.json`

## Required Scenario Coverage

`scenario_coverage` must include all of:

1. `transfer`
2. `refund`
3. `fee`
4. `split`
5. `receivable_repayment`
6. `csv_overlap_exports`

## Why This Exists

This schema is the authoritative contract for:

1. invariant test data
2. write-mode matrix test inputs
3. CSV idempotency overlap tests
4. cross-user leakage probes
5. ranked report parity expected values
6. CLI release-gate thresholds (`schema-status`, `ledger-reconcile`, coverage)
