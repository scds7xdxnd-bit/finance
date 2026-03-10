# Team Boundaries and Change Rules
_Last updated: 2026-03-10_

## 99.1 Scope
Ownership boundaries, stable interfaces, and forbidden changes for vNext correctness work.

## 99.2 Ownership by Convention
| Team | Owns (primary write authority) |
| --- | --- |
| Ledger | `finance_app/services/journal_service.py`, `finance_app/services/transaction_create_service.py`, `finance_app/services/ledger_convergence_service.py`, `finance_app/services/ledger_convergence_policy.py`, ledger models in `finance_app/models/accounting_models.py` |
| Import | `finance_app/services/transaction_import_service.py`, `/upload_csv` route in `blueprints/transactions.py`, import specs in `project/docs/import/*` |
| DB | `alembic/versions/*`, `finance_app/services/schema_guard_service.py`, `scripts/verify_schema_capabilities.sql`, schema capability docs |
| Reporting | `finance_app/services/ledger_query_service.py`, ranked report routes in `blueprints/accounting.py`, `statements_pdf.py`, `trial_balance_pdf.py` |
| QA | `tests/test_vnext_gate.py`, `tests/test_transaction_import_idempotency.py`, `tests/test_ledger_convergence.py`, `tests/test_ranked_reporting_cutover.py`, `tests/test_security_sensitive_endpoints.py`, golden fixtures under `tests/fixtures/golden/*` |
| Sec | `finance_app/lib/auth.py`, `blueprints/auth.py`, `blueprints/admin.py`, authz/CSRF checks in sensitive blueprints |
| Frontend | `templates/*`, `static/js/*`, `static/css/*`, UI-side use of `window.FINANCE_ENDPOINTS` |
| PM | `project/docs/ssot/*`, release policy docs, acceptance and rollout checklists |

## 99.3 Stable Interfaces (Architect Signoff Required)
- Canonical reporting API signatures in `finance_app/services/ledger_query_service.py`.
- Import summary payload contract and required keys in `transaction_import_service.py` and `project/docs/import/csv_import_summary.schema.json`.
- `row_dedupe_key` canonical composition and uniqueness tuple (`user_id`, `account_id`, `direction`, `row_dedupe_key`).
- Convergence confidence enums and auto-link policy (`exact|strong|weak_ambiguous`).
- Schema capability names and required artifacts in `schema_guard_service.py`.
- Schema-guard bypass metadata contract (`SCHEMA_GUARD_BYPASS_REASON`, `SCHEMA_GUARD_BYPASS_UNTIL`, 7-day max window).
- Release gate invariant IDs and pass/fail semantics in `tests/test_vnext_gate.py`.
- Frontend Contract Surface (`SSOT 55`):
  - locked endpoint contracts:
    - `POST /add_transaction`
    - `POST /api/ml_suggestions`
    - `POST /api/suggestions/log`
    - `GET /accounting/tb/monthly`
    - `GET /accounting/statement/data`
    - `GET /accounting/journal/list`
    - `PUT /accounting/journal/<entry_id>`
  - locked endpoint-registry keys in `window.FINANCE_ENDPOINTS`:
    - `transactions.list`
    - `transactions.add`
    - `ml.suggestions`
    - `ml.suggestionLog`
    - `accounting.tbMonthly`
    - `accounting.statements.data`
    - `accounting.journal.list`
    - `accounting.journal.updateTemplate`
- Phase 1 UI interaction contract (`SSOT 56`):
  - Quick Add modal DOM selectors and validation behavior
  - Last Import Result panel persistence/render contract
  - Search/filter query parameter names and defaults
  - Journal edit sequencing and deterministic error mapping
- Phase 1.1 filters round-trip contract (`SSOT 57`):
  - stable filter parameter names
  - transactions and journal round-trip/pagination preservation rules
  - measurement-first performance posture trigger
- Phase 1.2 transaction edit UX contract (`SSOT 58`):
  - edit UX uses `PUT /accounting/journal/<entry_id>` only (no new edit endpoint)
  - deterministic unbalanced mapping (`error_code=JOURNAL_NOT_BALANCED`)
  - locked edit UI DOM selectors and save-gating behavior
  - mandatory registry-key usage for journal list/update paths
- Phase 1.3 CSV import UX contract (`SSOT 59`):
  - session summary key is stable (`last_import_result_v1`)
  - panel selector/data-role surface is stable
  - dismiss semantics are stable (`POST /transactions/import_result/dismiss`, auth+CSRF, redirect param preservation)
  - `/upload_csv` remains no-JSON contract surface
- Phase 1.2.1 transaction edit UX hardening (`SSOT 58_1`):
  - deterministic preload/render behavior for edit modal
  - deterministic balance-state and save-gating behavior
  - deterministic field-level vs form-level error placement rules
  - post-save list refresh must preserve active query params (`page`/`per_page` included)
- Phase 1.2.2 transaction edit state drift hardening (`SSOT 58_2`):
  - preload source is JS state (`JOURNAL_STATE.byId`) from existing list endpoint
  - preload-state marker and state values are stable (`ready|missing|stale|loading`)
  - missing/stale state handling remains deterministic and visible
  - no new preload endpoint or registry key is allowed in this phase
- Phase 1.2.3 transaction edit refresh-safety hardening (`SSOT 58_3`):
  - edit-session marker and stale-warning selector are stable interfaces
  - local-buffer authority under active modal session is mandatory
  - background refresh must preserve active query params and must not overwrite local editor buffer
  - no new endpoint or registry key is allowed in this phase
- Phase 1.2.4 transaction edit usability polish (`SSOT 58_4`):
  - additive usability selectors are stable where declared
  - keyboard/focus, balance clarity, and save-status semantics are deterministic
  - JS-state preload posture remains unchanged (`JOURNAL_STATE.byId`, no row JSON blobs)
  - no endpoint or registry-key expansion is allowed in this phase

### 99.3.1 Frontend Contract Surface Ownership
- Architect owns SSOT definitions in `project/docs/ssot/55_frontend_contracts.md`.
- QA owns contract tests in `tests/test_frontend_contracts.py`.
- Backend owns endpoint conformity with locked request/response keys and status semantics.
- Frontend owns UI consumption of locked contracts and registry keys.

### 99.3.2 Phase 1.2 Ownership
- Architect owns `project/docs/ssot/58_phase1_2_transaction_edit_ux.md`.
- Backend owns conformity for:
  - `PUT /accounting/journal/<entry_id>` request/response shape
  - deterministic `JOURNAL_NOT_BALANCED` mapping.
- Frontend owns editor implementation and required registry-key consumption.
- QA owns contract-shape checks for edit failure mapping and registry token presence.

### 99.3.3 Phase 1.3 Ownership
- Architect owns `project/docs/ssot/59_phase1_3_csv_import_ux_no_json.md`.
- Backend owns:
  - session summary write semantics for `/upload_csv`
  - dismiss endpoint semantics (`POST /transactions/import_result/dismiss`) including auth+CSRF and redirect param preservation.
- Frontend owns panel rendering and deterministic selector usage from SSOT 59.
- QA owns contract-shape checks for panel presence, dismiss form semantics, and filter-param preservation.

### 99.3.4 Phase 1.2.1 Ownership
- Architect owns `project/docs/ssot/58_1_phase1_2_1_transaction_edit_ux_hardening.md`.
- Backend owns endpoint conformity and deterministic error mapping for existing edit/list endpoints:
  - `PUT /accounting/journal/<entry_id>`
  - `GET /accounting/journal/list`
- Frontend owns deterministic preload/render UX, balance-state gating UX, and visible fallback errors.
- QA owns contract-shape checks for selector surface, error mapping, and query-param preservation.

### 99.3.5 Phase 1.2.2 Ownership
- Architect owns `project/docs/ssot/58_2_phase1_2_2_transaction_edit_state_drift.md`.
- Frontend owns preload/state lifecycle behavior and preload-state UI semantics.
- Backend owns existing endpoint behavior only; no new endpoint introduction.
- QA owns contract-shape checks for preload-state markers, missing-state handling, and entry-id action surface.

### 99.3.6 Phase 1.2.3 Ownership
- Architect owns `project/docs/ssot/58_3_phase1_2_3_transaction_edit_refresh_safety.md`.
- Frontend owns edit-session marker, stale-warning rendering, and buffer-authority semantics.
- Backend owns existing endpoint behavior only; no endpoint expansion.
- QA owns contract-shape checks for refresh-safety markers and registry stability.

### 99.3.7 Phase 1.2.4 Ownership
- Architect owns `project/docs/ssot/58_4_phase1_2_4_transaction_edit_usability_polish.md`.
- Frontend owns additive usability selector implementation and deterministic behavior.
- Backend owns existing endpoint behavior only; no endpoint expansion.
- QA owns selector-surface and registry-stability contract checks.

## 99.4 Forbidden Changes
- Reporting code must not compute ranked totals from legacy `Transaction` rows.
- Reporting code must not enable or silently emulate mixed mode aggregation.
- Import code must not bypass `CsvImportBatch`/`CsvImportRow` provenance writes.
- Import code must not weaken file/row idempotency constraints.
- Convergence code must not auto-link `weak_ambiguous` candidates.
- Ledger posting code must not bypass balance validation.
- Sensitive routes must not bypass schema guard when capability checks are required.
- Admin mutation flows must not bypass CSRF, confirmation cooldown, or audit logging.
- Backend and Frontend must not remove or rename required frontend-contract keys (`SSOT 55`) without SSOT update and QA contract-test update.
- Backend and Frontend must not remove or rename required `window.FINANCE_ENDPOINTS` keys (`SSOT 55.5`) without SSOT update and QA contract-test update.
- Frontend must not hardcode locked endpoint paths when a registry key exists in `window.FINANCE_ENDPOINTS`.
- Backend and Frontend must not rename or repurpose locked filter query parameter names from SSOT 57 without SSOT update and QA evidence.
- Frontend must not drop active filter params during pagination or `per_page` changes when SSOT 57 requires round-trip preservation.
- Backend and Frontend must not remove/rename/repurpose `error_code=JOURNAL_NOT_BALANCED` contract semantics without SSOT update and QA evidence.
- Frontend must not bypass `window.FINANCE_ENDPOINTS.accounting.journal.list` and `window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate` in Phase 1.2 flows.
- Backend and Frontend must not introduce `/upload_csv` JSON response contracts without SSOT update and QA evidence.
- Backend and Frontend must not rename `session["last_import_result_v1"]` or SSOT 59 locked panel selectors/data-role markers without SSOT update and QA evidence.
- Backend and Frontend must not introduce new edit/list endpoints or new registry keys for Phase 1.2.1 without SSOT update and QA evidence.
- Backend and Frontend must not break query-param preservation (`page`/`per_page`) on post-save list refresh in Phase 1.2.1 flows.
- Backend and Frontend must not introduce new preload read endpoints for Phase 1.2.2 without SSOT update and QA evidence.
- Frontend must not remove or rename preload-state marker contract (`[data-role="preload-state"]` with allowed `data-state` values) without SSOT update and QA evidence.
- Backend and Frontend must not remove or rename Phase 1.2.3 refresh-safety markers (`[data-role="edit-session"]`, `[data-role="stale-warning"]`, `data-buffer-authority="local"`) without SSOT update and QA evidence.
- Backend and Frontend must not drop `page`/`per_page` preservation on edit-list refresh flows in Phase 1.2.3.
- Backend and Frontend must not introduce new endpoints, new registry keys, or row-level embedded JSON blobs for Phase 1.2.4 without SSOT update and QA evidence.
- Frontend must not remove or rename SSOT 58_4 locked usability selectors (when implemented) without SSOT update and QA evidence.

## 99.5 SSOT Change Protocol (Mandatory)
- Any PR that changes a stable interface or forbidden-change area must:
  - update relevant SSOT file(s)
  - update tests/gates in the same PR
  - include architect signoff before merge
- Any PR that changes frontend contract surface (`SSOT 55`) must include:
  - SSOT 55 section references
  - QA contract evidence from `tests/test_frontend_contracts.py` (once implemented)
- Any PR that changes Phase 1 UX contract behavior (`SSOT 56`) must include:
  - SSOT 56 section references
  - QA contract evidence for key-presence/status handling
- Any PR that changes Phase 1.1 filter contracts (`SSOT 57`) must include:
  - SSOT 57 section references
  - QA contract evidence for round-trip parameter preservation/status handling
- Any PR that changes Phase 1.2 edit UX contracts (`SSOT 58`) must include:
  - SSOT 58 section references
  - QA contract evidence for deterministic error mapping and registry-key usage checks
- Any PR that changes Phase 1.3 CSV import UX contracts (`SSOT 59`) must include:
  - SSOT 59 section references
  - QA contract evidence for panel selectors, dismiss semantics, and filter-param preservation checks
- Any PR that changes Phase 1.2.1 edit hardening contracts (`SSOT 58_1`) must include:
  - SSOT 58_1 section references
  - QA contract evidence for preload/render selectors, error mapping, and post-save query-param preservation checks
- Any PR that changes Phase 1.2.2 edit preload/state-drift contracts (`SSOT 58_2`) must include:
  - SSOT 58_2 section references
  - QA contract evidence for preload-state markers, missing-state behavior, and action-surface entry-id checks
- Any PR that changes Phase 1.2.3 edit refresh-safety contracts (`SSOT 58_3`) must include:
  - SSOT 58_3 section references
  - QA contract evidence for edit-session marker, stale-warning selector, buffer-authority marker, and refresh-param preservation checks
- Any PR that changes Phase 1.2.4 edit usability-polish contracts (`SSOT 58_4`) must include:
  - SSOT 58_4 section references
  - QA contract evidence for additive selector surface and registry-stability checks
- If behavior is intentionally transitional, PR must include:
  - explicit temporary rule
  - expiration date
  - removal issue reference

## 99.6 Implementation Truth Pointers
- App/blueprint registration: `finance_app/controllers/__init__.py`
- Service layer roots: `finance_app/services/*`
- Model/schema roots: `finance_app/models/*`, `alembic/versions/*`
- CI gate surface: `tests/test_vnext_gate.py`, `.github/workflows/smoke.yml`
