# Team Boundaries and Change Rules
_Last updated: 2026-03-11_

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
- Phase 1.3.1 CSV import details polish contract (`SSOT 59_1`):
  - details rendering selectors and visibility-state semantics are stable
  - details toggle presence rule is stable (render toggle only when details data exists)
  - default details state is stable (`data-state="collapsed"` when details container exists)
  - no endpoint/registry expansion is allowed in this phase
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
- Phase 2.0 Month Close Foundation (`SSOT 60_month_close_foundation`):
  - checklist DOM selector surface and `data-state` semantics are stable
  - month selector `ym` round-trip behavior is stable
  - snapshot controls are hook-only and deterministic (immutability not required in Phase 2.0)
  - Phase 2.0 reuses existing endpoint contracts and introduces no new JSON lock surface
- Phase 2.3 Documents contract (`SSOT 61_documents_contracts`):
  - PDF selector parsing semantics are stable
  - deterministic filename contract is stable
  - PDF response/failure status behavior is stable
  - no new endpoint or registry-key requirement is introduced by this phase
- Phase 2.4 Documents UX and proof posture (`SSOT 62_documents_ux_proof_posture`):
  - documents selector UX + URL round-trip behavior are stable
  - visible validation/error messaging posture is stable
  - proof/disclaimer posture is stable (immutability still not required)
  - no new endpoint or registry-key requirement is introduced by this phase
- Phase 2.5 Month Close reports/documents integration (`SSOT 63_month_close_documents_integration`):
  - Month Close reports/documents action-selector surface is stable
  - `ym` round-trip in action URLs is stable
  - loan-receipt action render rule is stable (render only with deterministic selector source)
  - no new endpoint or registry-key requirement is introduced by this phase
- Phase 2.5.1 Month Close documents state derivation (`SSOT 63_1_month_close_documents_state`):
  - `mc-documents` state derivation rules (`ok|warn|unknown`) are stable
  - `fail` state is reserved/unused in this phase
  - additive count selectors (`mc-documents-open-count`, `mc-documents-total-count`) are stable
  - no new endpoint or registry-key requirement is introduced by this phase
- Phase 2.6 Month Close state derivation (`SSOT 63_2_month_close_coverage_unbalanced_state`):
  - deterministic coverage + unbalanced drafts derivation rules
  - additive selector surface for counts/notes
  - no endpoint/registry expansion
- Phase 2.7 Month Close resolution actions (`SSOT 63_3_month_close_resolution_actions`):
  - resolution actions are navigation-only
  - `ym` preservation in resolution URLs is stable
  - no endpoint/registry expansion is introduced by this phase
- Phase 2.8 Month Close readiness summary (`SSOT 63_4_month_close_readiness_summary`):
  - readiness roll-up state (`ready|attention|unknown`) is stable
  - additive selectors for message/next-action are stable
  - next-action guidance maps to existing Phase 2.7 navigation-only actions where applicable
  - no endpoint/registry expansion is introduced
- Phase 2.8.1 Month Close readiness next-action linkage hardening (`SSOT 63_4_1_month_close_readiness_linkage`):
  - next-action mapping/enabled/linkage semantics are stable
  - readiness link presence/absence rules are stable
  - no endpoint/registry expansion is introduced
- Phase 2.10.1 Month Close documents deep-link lock (`SSOT 63_6_month_close_documents_deeplink_lock`):
  - month-close documents action deep-links to `/accounting` with `ym` preserved
  - self-link to `/accounting/month_close` for documents resolution is forbidden
  - target-page documents hydration entry posture is stable
  - no endpoint/registry expansion is introduced

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

### 99.3.8 Phase 1.3.1 Ownership
- Architect owns `project/docs/ssot/59_1_phase1_3_csv_import_details_polish.md`.
- Backend owns:
  - session summary optional details-key population when data exists
  - dismiss redirect parameter preservation semantics on existing dismiss endpoint.
- Frontend owns details toggle/render behavior and SSOT 59/59_1 selector stability.
- QA owns contract-shape checks for details selector presence/absence rules and dismiss preservation checks.

### 99.3.9 Phase 2.0 Month Close Foundation Ownership
- Architect owns `project/docs/ssot/60_month_close_foundation.md`.
- Frontend owns checklist rendering and deterministic item-state UI behavior.
- Backend owns any future computed month-close summaries without changing existing reporting endpoint contracts in Phase 2.0.
- QA owns contract-shape checks for month-close DOM markers and item-state attributes.

### 99.3.10 Phase 2.3 Documents Ownership
- Architect owns `project/docs/ssot/61_documents_contracts.md`.
- Backend owns selector parsing, deterministic PDF response behavior, and filename stability.
- Frontend owns selector controls and URL round-trip behavior for document downloads.
- QA owns contract tests in `tests/test_documents_contract.py` and failure-prefix enforcement.
- DevOps owns merge-blocking CI wiring for documents contract tests.

### 99.3.11 Phase 2.4 Documents UX/Proof Posture Ownership
- Architect owns `project/docs/ssot/62_documents_ux_proof_posture.md`.
- Frontend owns selector UX, URL round-trip, visible validation, and download affordance behavior.
- Backend owns endpoint stability under SSOT 61; no new endpoints in this phase.
- QA owns:
  - primary contract assertions in `tests/test_documents_contract.py`
  - optional selector-surface assertions in `tests/test_frontend_contracts.py`.
- DevOps keeps documents contract checks merge-blocking without adding a new gate family.

### 99.3.12 Phase 2.5 Month Close Reports/Documents Integration Ownership
- Architect owns `project/docs/ssot/63_month_close_documents_integration.md`.
- Frontend owns Month Close checklist action rendering and URL builder behavior for reports/documents.
- Backend owns server-rendered Month Close context behavior only; no new endpoint requirement in this phase.
- QA owns contract-shape checks for Month Close reports/documents selectors and state markers.
- DevOps keeps merge-blocking coverage for impacted frontend contract tests.

### 99.3.13 Phase 2.5.1 Month Close Documents State Ownership
- Architect owns `project/docs/ssot/63_1_month_close_documents_state.md`.
- Frontend owns Month Close documents state rendering and additive count-selector stability.
- Backend owns deterministic documents-state derivation behavior using existing sources only; no endpoint expansion.
- QA owns contract-shape checks for state/count selectors and deterministic state outcomes (`warn`/`ok` seeded scenarios).
- DevOps keeps merge-blocking coverage for impacted frontend contract tests.

### 99.3.14 Phase 2.7 Month Close Resolution Actions Ownership
- Architect owns `project/docs/ssot/63_3_month_close_resolution_actions.md`.
- Frontend owns resolution-action selector rendering and URL construction.
- Backend owns reuse-only navigation targets and month-close context emission without endpoint expansion.
- QA owns contract-shape checks for selector presence and `ym` URL preservation.
- DevOps keeps merge-blocking coverage under existing required checks.

### 99.3.15 Phase 2.8 Month Close Readiness Ownership
- Architect owns `project/docs/ssot/63_4_month_close_readiness_summary.md`.
- Backend owns deterministic readiness derivation emission in month-close render context (reuse-only).
- Frontend owns selector rendering and non-blocking interaction behavior.
- QA owns contract-shape checks for readiness selector surface and seeded deterministic outcomes.
- DevOps keeps merge-blocking coverage under existing required checks.

### 99.3.16 Phase 2.8.1 Month Close Readiness Linkage Ownership
- Architect owns `project/docs/ssot/63_4_1_month_close_readiness_linkage.md`.
- Backend owns deterministic next-action linkage metadata emission in month-close render context (reuse-only).
- Frontend owns mapping/rendering of readiness action-key to existing navigation controls and enabled semantics.
- QA owns contract-shape checks for linkage mapping, enabled semantics, and `ym` preservation.
- DevOps keeps merge-blocking coverage under existing required checks.

### 99.3.17 Phase 2.10.1 Month Close Documents Deep-Link Ownership
- Architect owns `project/docs/ssot/63_6_month_close_documents_deeplink_lock.md`.
- Backend owns month-close documents URL emission and `ym` propagation in deep-link targets.
- Frontend owns `/accounting?ym` first-load documents hydration behavior and selector stability.
- QA owns contract-shape checks for deep-link path/ym/self-link prohibition and target selector surface.
- DevOps keeps merge-blocking coverage under existing required checks.

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
- Backend and Frontend must not remove/rename SSOT 59_1 details selectors (`[data-role="import-details-failures"]`, `[data-role="import-details-warnings"]`, `[data-role="import-details-meta"]`) or details `data-state="collapsed|expanded"` semantics without SSOT update and QA evidence.
- Frontend must not render details toggle when both `failure_samples` and `warnings` are absent/empty; this visibility rule is locked by SSOT 59_1.
- Backend and Frontend must not introduce new edit/list endpoints or new registry keys for Phase 1.2.1 without SSOT update and QA evidence.
- Backend and Frontend must not break query-param preservation (`page`/`per_page`) on post-save list refresh in Phase 1.2.1 flows.
- Backend and Frontend must not introduce new preload read endpoints for Phase 1.2.2 without SSOT update and QA evidence.
- Frontend must not remove or rename preload-state marker contract (`[data-role="preload-state"]` with allowed `data-state` values) without SSOT update and QA evidence.
- Backend and Frontend must not remove or rename Phase 1.2.3 refresh-safety markers (`[data-role="edit-session"]`, `[data-role="stale-warning"]`, `data-buffer-authority="local"`) without SSOT update and QA evidence.
- Backend and Frontend must not drop `page`/`per_page` preservation on edit-list refresh flows in Phase 1.2.3.
- Backend and Frontend must not introduce new endpoints, new registry keys, or row-level embedded JSON blobs for Phase 1.2.4 without SSOT update and QA evidence.
- Frontend must not remove or rename SSOT 58_4 locked usability selectors (when implemented) without SSOT update and QA evidence.
- Backend and Frontend must not introduce new month-close JSON endpoint locks or registry-key requirements in Phase 2.0 without SSOT update and QA evidence.
- Frontend must not remove or rename SSOT 60_month_close_foundation checklist selectors or `data-state="ok|warn|fail|unknown"` contract semantics without SSOT update and QA evidence.
- Backend and Frontend must not rename SSOT 61 locked documents selectors (`ym`, `status`, `party`, `min_amount`, `max_amount`, `loan_id`, `entry_id`) without SSOT update and QA evidence.
- Backend and Frontend must not change deterministic documents filename patterns or selector error semantics without SSOT update and QA evidence.
- Backend and Frontend must not introduce per-row embedded JSON blobs for documents generation in Phase 2.3.
- Backend and Frontend must not rename SSOT 62 locked documents UX selectors (`#documents-panel`, `[data-role="docs-selectors"]`, `[data-role="docs-error"]`, download action selectors) without SSOT update and QA evidence.
- Frontend must not regress documents selector URL round-trip or shift validation failures to console-only behavior in Phase 2.4.
- Backend and Frontend must not introduce new documents endpoints or new registry-key requirements in Phase 2.4 without SSOT update and QA evidence.
- Backend and Frontend must not rename SSOT 63 Month Close reports/documents action selectors (`[data-role="mc-documents"]`, required report/document action selectors) without SSOT update and QA evidence.
- Frontend must not omit `ym` in Month Close generated report/document action URLs where SSOT 63 requires month-context propagation.
- Backend and Frontend must not render Month Close loan-receipt action without deterministic selector source in Phase 2.5.
- Backend and Frontend must not introduce new endpoint/registry-key requirements for Phase 2.5 without SSOT update and QA evidence.
- Backend and Frontend must not change SSOT 63_1 documents-state derivation rules or remove/rename `[data-role="mc-documents-open-count"]` / `[data-role="mc-documents-total-count"]` without SSOT update and QA evidence.
- Backend and Frontend must not introduce new endpoint/registry-key requirements for Phase 2.7 Month Close resolution actions without SSOT update and QA evidence.
- Backend and Frontend must not convert Phase 2.7 resolution actions from navigation-only behavior into API-call behavior without SSOT update and QA evidence.
- Backend and Frontend must not introduce new endpoint/registry-key requirements for Phase 2.8.1 readiness linkage hardening without SSOT update and QA evidence.
- Backend and Frontend must not break deterministic mapping/enabled rules between readiness action keys and existing navigation controls defined by SSOT 63_4_1.
- Backend and Frontend must not point `mc-open-documents-panel` to `/accounting/month_close`; deep-link target is locked to `/accounting` under SSOT 63_6.
- Backend and Frontend must not regress `/accounting?ym` first-load documents hydration posture defined in SSOT 63_6.

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
- Any PR that changes Phase 1.3.1 CSV import details polish contracts (`SSOT 59_1`) must include:
  - SSOT 59_1 section references
  - QA contract evidence for details toggle visibility rules, details-selector state surface, and dismiss redirect-param preservation checks
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
- Any PR that changes Phase 2.0 Month Close Foundation contracts (`SSOT 60_month_close_foundation`) must include:
  - SSOT 60_month_close_foundation section references
  - QA contract evidence for month-close selector surface and checklist state-marker semantics
- Any PR that changes Phase 2.3 Documents contracts (`SSOT 61_documents_contracts`) must include:
  - SSOT 61_documents_contracts section references
  - QA contract evidence from `tests/test_documents_contract.py`
- Any PR that changes Phase 2.4 Documents UX/proof posture contracts (`SSOT 62_documents_ux_proof_posture`) must include:
  - SSOT 62_documents_ux_proof_posture section references
  - QA contract evidence from `tests/test_documents_contract.py` and `tests/test_frontend_contracts.py` when selector checks are in scope
- Any PR that changes Phase 2.5 Month Close reports/documents integration contracts (`SSOT 63_month_close_documents_integration`) must include:
  - SSOT 63_month_close_documents_integration section references
  - QA contract evidence from `tests/test_frontend_contracts.py`
- Any PR that changes Phase 2.5.1 Month Close documents-state derivation contracts (`SSOT 63_1_month_close_documents_state`) must include:
  - SSOT 63_1_month_close_documents_state section references
  - QA contract evidence from `tests/test_frontend_contracts.py`
- Any PR that changes Phase 2.7 Month Close resolution-action contracts (`SSOT 63_3_month_close_resolution_actions`) must include:
  - SSOT 63_3_month_close_resolution_actions section references
  - QA contract evidence from `tests/test_frontend_contracts.py`
- Any PR that changes Phase 2.8 readiness contracts (`SSOT 63_4_month_close_readiness_summary`) must include:
  - SSOT 63_4_month_close_readiness_summary section references
  - QA contract evidence from `tests/test_frontend_contracts.py`
- Any PR that changes Phase 2.8.1 readiness linkage contracts (`SSOT 63_4_1_month_close_readiness_linkage`) must include:
  - SSOT 63_4_1_month_close_readiness_linkage section references
  - QA contract evidence from `tests/test_frontend_contracts.py`
- Any PR that changes Phase 2.10.1 month-close documents deep-link/hydration contracts (`SSOT 63_6_month_close_documents_deeplink_lock`) must include:
  - SSOT 63_6_month_close_documents_deeplink_lock section references
  - QA contract evidence from `tests/test_frontend_contracts.py`
- If behavior is intentionally transitional, PR must include:
  - explicit temporary rule
  - expiration date
  - removal issue reference

## 99.6 Implementation Truth Pointers
- App/blueprint registration: `finance_app/controllers/__init__.py`
- Service layer roots: `finance_app/services/*`
- Model/schema roots: `finance_app/models/*`, `alembic/versions/*`
- CI gate surface: `tests/test_vnext_gate.py`, `.github/workflows/smoke.yml`
