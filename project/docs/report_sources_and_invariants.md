# Report Sources And Invariants
_Last updated: 2026-03-06_

## Canonical Query API (PR-09 minimal scope)

`finance_app/services/ledger_query_service.py` is the only reporting query surface for ranked reports.

1. `trial_balance_month(user_id, ym, currency=None, include_coverage=True)`
2. `statement_period(user_id, start_date, end_date, currency=None, cash_folder_ids=None, include_coverage=True)`
3. `account_balance_as_of(user_id, account_id, as_of, currency=None, include_coverage=True)`

### Output contract (common)

All successful canonical responses include:
- `ok: true`
- `source`: `{mode: "journal", mixed_mode_allowed: false, legacy_rows_included_in_totals: false}`
- `coverage`: legacy-link completeness metrics (when `include_coverage=True`)

Coverage fields:
- `coverage_count`, `coverage_amount`
- `total_legacy_tx`, `linked_legacy_tx`
- `total_legacy_amount`, `linked_legacy_amount`
- `unlinked_recent_90d_count`

## Endpoint Mapping

Ranked endpoints and source adapters:

1. `/accounting/tb/monthly` -> `ledger_query_service.trial_balance_month`
2. `/accounting/statement/data` -> `ledger_query_service.statement_period` (plus `trial_balance_month` only for trend/folder UI metadata)
3. `/accounting/statement/export` -> reuses `/accounting/statement/data` payload
4. `/accounting/statement/pdf` -> `ledger_query_service.statement_period` + PDF renderers from canonical statement data
5. `/accounting/tb/pdf` -> `ledger_query_service.trial_balance_month` + TB PDF row adapter

## Invariants

1. `source=mixed` is rejected (`400`) on all ranked endpoints.
2. Ranked totals are journal-only; legacy-only rows are never merged into totals.
3. Legacy completeness is exposed through `coverage`, not by mixed aggregation.
4. Statement JSON, export, and PDF share the same canonical statement payload shape.
5. TB JSON (`/accounting/tb/monthly`) and TB PDF are generated from the same monthly canonical payload.
6. Legacy source mode remains emergency-only and intentionally unimplemented for ranked endpoints.
