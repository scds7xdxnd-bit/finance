# Team Boundaries and Change Rules
_Last updated: 2026-03-07_

## Scope
Ownership boundaries, stable interfaces, and forbidden changes for vNext correctness work.

## Ownership by Convention
| Team | Owns (primary write authority) |
| --- | --- |
| Ledger | `finance_app/services/journal_service.py`, `finance_app/services/transaction_create_service.py`, `finance_app/services/ledger_convergence_service.py`, `finance_app/services/ledger_convergence_policy.py`, ledger models in `finance_app/models/accounting_models.py` |
| Import | `finance_app/services/transaction_import_service.py`, `/upload_csv` route in `blueprints/transactions.py`, import specs in `project/docs/import/*` |
| DB | `alembic/versions/*`, `finance_app/services/schema_guard_service.py`, `scripts/verify_schema_capabilities.sql`, schema capability docs |
| Reporting | `finance_app/services/ledger_query_service.py`, ranked report routes in `blueprints/accounting.py`, `statements_pdf.py`, `trial_balance_pdf.py` |
| QA | `tests/test_vnext_gate.py`, `tests/test_transaction_import_idempotency.py`, `tests/test_ledger_convergence.py`, `tests/test_ranked_reporting_cutover.py`, golden fixtures under `tests/fixtures/golden/*` |
| Sec | `finance_app/lib/auth.py`, `blueprints/auth.py`, `blueprints/admin.py`, authz/CSRF checks in sensitive blueprints |
| PM | `project/docs/ssot/*`, release policy docs, acceptance and rollout checklists |

## Stable Interfaces (Architect Signoff Required)
- Canonical reporting API signatures in `finance_app/services/ledger_query_service.py`.
- Import summary payload contract and required keys in `transaction_import_service.py` and `project/docs/import/csv_import_summary.schema.json`.
- `row_dedupe_key` canonical composition and uniqueness tuple (`user_id`, `account_id`, `direction`, `row_dedupe_key`).
- Convergence confidence enums and auto-link policy (`exact|strong|weak_ambiguous`).
- Schema capability names and required artifacts in `schema_guard_service.py`.
- Release gate invariant IDs and pass/fail semantics in `tests/test_vnext_gate.py`.

## Forbidden Changes
- Reporting code must not compute ranked totals from legacy `Transaction` rows.
- Reporting code must not enable or silently emulate mixed mode aggregation.
- Import code must not bypass `CsvImportBatch`/`CsvImportRow` provenance writes.
- Import code must not weaken file/row idempotency constraints.
- Convergence code must not auto-link `weak_ambiguous` candidates.
- Ledger posting code must not bypass balance validation.
- Sensitive routes must not bypass schema guard when capability checks are required.
- Admin mutation flows must not bypass CSRF, confirmation cooldown, or audit logging.

## SSOT Change Protocol (Mandatory)
- Any PR that changes a stable interface or forbidden-change area must:
  - update relevant SSOT file(s)
  - update tests/gates in the same PR
  - include architect signoff before merge
- If behavior is intentionally transitional, PR must include:
  - explicit temporary rule
  - expiration date
  - removal issue reference

## Implementation Truth Pointers
- App/blueprint registration: `finance_app/controllers/__init__.py`
- Service layer roots: `finance_app/services/*`
- Model/schema roots: `finance_app/models/*`, `alembic/versions/*`
- CI gate surface: `tests/test_vnext_gate.py`, `.github/workflows/smoke.yml`
