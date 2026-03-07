# QA Gate Invariants
_Last updated: 2026-03-06_

This catalog defines the financial correctness invariants that must hold for protected-branch CI.

## Gate Families

### `GATE-JOURNAL` (journal correctness)

1. `INV-JRNL-001` Journal entry balance:
`sum(D) - sum(C)` per `journal_entry.id` must be within `<= 0.01`.
2. `INV-JRNL-002` No unbalanced journals in reconcile output:
`reconcile.checks.unbalanced_journal_entries == 0`.

### `GATE-LINKING` (link quality + coverage)

1. `INV-LINK-001` Weak auto-links are forbidden:
no `transaction_journal_link.source` may start with `weak`.
2. `INV-LINK-002` Reconcile mismatches are forbidden:
`reconcile.checks.mismatched_links == 0`.
3. `INV-LINK-003` Reconcile unmapped transactions are forbidden:
`reconcile.checks.unmapped_transactions == 0`.
4. `INV-LINK-004` Coverage count threshold:
`coverage.coverage_count >= coverage_count_min`.
5. `INV-LINK-005` Coverage amount threshold:
`coverage.coverage_amount >= coverage_amount_min`.
6. `INV-LINK-006` Recent unlinked threshold:
`coverage.unlinked_recent_90d_count <= unlinked_recent_max`.

### `GATE-DEDUPE` (CSV idempotency + overlap handling)

1. `INV-DEDUPE-001` File hash re-upload idempotency:
second import of same file must set `skipped_duplicate_batch=true`.
2. `INV-DEDUPE-002` Row-level dedupe for overlapping exports:
overlap import must increase `rows_duplicate` and must not double-post journals.
3. `INV-DEDUPE-003` Partial duplicate group safety:
mixed duplicate/new group must return `error_reasons.partial_duplicate_group > 0`.
4. `INV-DEDUPE-004` Row dedupe uniqueness constraint:
no duplicate (`user_id`, `account_id`, `direction`, `row_dedupe_key`) rows can exist.

### `GATE-SCOPE` (cross-user isolation)

1. `INV-SCOPE-001` Sensitive read endpoints enforce user scope:
actor must never see another user's balances, journals, receivables, or links.
2. `INV-SCOPE-002` Sensitive write endpoints enforce user scope:
actor must not mutate another user's receivable/link/journal rows.
3. `INV-SCOPE-003` Scope probes are explicit in golden data:
each probe declares actor, target, endpoint, and forbidden record keys.

### `GATE-MODE` (write-mode matrix behavior)

1. `INV-MODE-001` `journal` mode:
creates journal rows only (`tx=0`, `links=0`).
2. `INV-MODE-002` `dual` mode:
creates journal + legacy transaction + exactly one strong link.
3. `INV-MODE-003` `legacy` mode:
creates legacy transaction only (`journal=0`, `links=0`).
4. `INV-MODE-004` Invalid shape in `dual`/`legacy`:
split lines (not exactly one D + one C) must fail with `400`.
5. `INV-MODE-005` Unknown mode fallback:
unknown mode is treated as `journal`.

### `GATE-REPORT-PARITY` (ranked report numeric parity)

1. `INV-RPT-001` TB internal parity:
`grand_totals.period_debit == grand_totals.period_credit`.
2. `INV-RPT-002` TB -> income statement parity:
statement revenue/expense/net income must match TB-derived values.
3. `INV-RPT-003` TB -> balance statement parity:
assets/liabilities/equity/le_sum must match TB-derived values.
4. `INV-RPT-004` Statement JSON -> statement PDF parity:
captured PDF payload totals must equal JSON statement totals.
5. `INV-RPT-005` TB JSON -> TB PDF parity:
captured TB PDF row sums must equal TB JSON grand totals.
6. `INV-RPT-006` Ranked source policy:
`source=mixed` requests must return `400`.

### `GATE-SCHEMA` (capability contract)

1. `INV-SCHEMA-001` `schema-status` command must return `ok=true`.
2. `INV-SCHEMA-002` Required capabilities must all be present:
`tx_linking`, `link_candidates`, `csv_idempotency`, `tb_snapshot`, `admin_audit`, `journal_report_perf`.

## Required Failure Output Shape

Each gate failure message must include:

1. invariant id (`INV-*`)
2. gate family (`GATE-*`)
3. observed value(s)
4. expected threshold/value
5. minimal diff context (`user_id`, `journal_id`, `transaction_id`, `endpoint`, `fixture_case_id`)

## Release Gate Threshold Defaults

1. `coverage_count_min`: `0.99`
2. `coverage_amount_min`: `0.995`
3. `unlinked_recent_max`: `0`
4. `pytest_coverage_min`: `85` (line coverage, enforced in CI gate job)
