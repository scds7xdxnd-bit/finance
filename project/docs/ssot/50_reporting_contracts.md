# Reporting Contracts
_Last updated: 2026-03-07_

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
- Release gate report invariants: `tests/test_vnext_gate.py`
