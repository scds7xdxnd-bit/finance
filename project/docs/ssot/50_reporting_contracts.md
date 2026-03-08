# Reporting Contracts
_Last updated: 2026-03-08_

## 50.1 Scope
Canonical reporting query surface, ranked endpoint mapping, and journal-only totals policy.

## 50.2 Canonical Query API (Stable Signatures)
- `trial_balance_month(user_id, ym, currency=None, include_coverage=True)`
- `statement_period(user_id, start_date, end_date, currency=None, cash_folder_ids=None, include_coverage=True)`
- `account_balance_as_of(user_id, account_id, as_of, currency=None, include_coverage=True)`

## 50.3 Endpoint Mapping (Ranked Reports)
- `/accounting/tb/monthly` -> `ledger_query_service.trial_balance_month`
- `/accounting/statement/data` -> `ledger_query_service.statement_period`
- `/accounting/statement/export` -> reuses `/accounting/statement/data` payload contract
- `/accounting/statement/pdf` -> canonical statement payload + PDF renderers
- `/accounting/tb/pdf` -> canonical TB payload + TB PDF renderer

## 50.4 Non-Negotiable Contracts
- Ranked report totals are journal-only.
- Legacy-only rows are never merged into ranked totals.
- Mixed source mode is forbidden; `source=mixed` must return `400`.
- Canonical source payload is stable: `{"mode":"journal","mixed_mode_allowed":false,"legacy_rows_included_in_totals":false}`.
- Coverage metadata is exposed as metadata (`coverage_*` fields), not as mixed aggregation.
- Statement JSON, statement export, and statement PDF must derive from the same canonical statement payload shape.
- TB JSON and TB PDF must derive from the same canonical monthly payload shape.

## 50.5 Implementation Truth Pointers
- Canonical query API: `finance_app/services/ledger_query_service.py`
- Ranked endpoint adapters and source policy checks: `blueprints/accounting.py`
- TB computations: `finance_app/services/trial_balance_service.py`
- Statement builders and PDF adapters: `statements_pdf.py`, `trial_balance_pdf.py`
- Supporting policy doc: `project/docs/report_sources_and_invariants.md`

## 50.6 Gate/Test Pointers
- Ranked reporting parity tests: `tests/test_ranked_reporting_cutover.py`
- Statement endpoint behavior tests: `tests/test_statement_data.py`
- Statement export parity tests (mandatory): `tests/test_statement_export_contract.py`
- Release gate report invariants: `tests/test_vnext_gate.py`

## 50.7 Statement Export Contract Parity (Release-Blocking)
`/accounting/statement/export` and `/accounting/statement/data` must remain parity-consistent for the same request selectors.

### 50.7.1 Input Selector Parity
Shared selectors (must be interpreted identically by both endpoints):
- `ym` (required)
- `ym_compare` (optional)
- `ccy` (optional)
- `cash_folders` (optional; same parsing semantics)
- `source` (optional; same source-policy enforcement)

Export-only selectors:
- `kind` in `income|balance|cashflow`
- `format` in `csv|xlsx`

Parity test requests must use identical shared selectors for `/data` and `/export`.

### 50.7.2 Source Policy Parity
For identical selectors:
- `source=mixed` must return `400` for both `/data` and `/export`.
- Non-journal source attempts must follow the same policy and status classes as `/data`:
  - `400` when legacy fallback is disabled.
  - `503` when fallback is enabled but not implemented.
- Export totals must remain journal-only with legacy-only rows excluded from ranked totals.

### 50.7.3 Totals Parity (Machine-Checkable)
Canonical totals are read from `/accounting/statement/data` payload:
- income totals keys: `revenue`, `expense`, `net_income`
- balance totals keys: `assets`, `liabilities`, `equity`, `le_sum`
- cashflow totals keys: `opening`, `closing`, `change`, `operating`, `investing`, `financing`, `net`

Export artifact contract (CSV and XLSX):
- Must include parity rows with reserved marker `Section="__TOTAL__"`.
- Each parity row must include:
  - `Label=<totals_key>`
  - `amount_base=<numeric decimal string>`

Parity comparison rule:
- Parse `/data` canonical totals as decimals quantized to `0.01`.
- Parse export `amount_base` totals as decimals quantized to `0.01`.
- Required equality is exact cents (`abs(delta) == 0.00`).

### 50.7.4 Metadata Parity
Export artifact must include metadata rows with reserved marker `Section="__META__"`:
- `source.mode`
- `source.mixed_mode_allowed`
- `source.legacy_rows_included_in_totals`

Coverage parity rule:
- If `/data` payload includes `coverage`, export must include:
  - `coverage.present=true`
  - `coverage.coverage_count`, `coverage.coverage_amount`, `coverage.unlinked_recent_90d_count` when present in `/data`.
- If `/data` payload does not include `coverage`, export must include `coverage.present=false` and no numeric coverage rows.

### 50.7.5 Allowed Differences
Allowed:
- file format (`csv` vs `xlsx`)
- row ordering
- presentation columns / localized labels / formatted display strings

Not allowed:
- totals parity drift from 50.7.3
- source metadata drift from 50.7.4
- mixed-mode policy drift from 50.7.2
