# Phase 2.5 Month Close Reports + Documents Integration Contract
_Last updated: 2026-03-11_

## 63.1 Scope
- Phase 2.5 integrates Month Close checklist UX (SSOT 60) with reports/documents download actions (SSOT 61/62) for a selected month `ym=YYYY-MM`.
- Scope is workflow integration and contract locking only:
  - reports generated actions
  - documents generated actions
  - stable selector and round-trip behavior
- Month Close remains advisory and does not enforce immutability.

## 63.2 Non-Goals
- No new JSON endpoints.
- No new PDF endpoints (must reuse SSOT 61 route surfaces and existing report PDF routes).
- No new endpoint registry keys are required by this phase.
- No requirement to persist/store PDFs in-app; download-now posture is sufficient.
- No DB schema/migration/index work in this phase.

## 63.3 Locked Decisions
- Month selector contract remains canonical as `ym=YYYY-MM` (SSOT 60).
- Reuse-only document/report endpoint posture:
  - `GET /accounting/tb/pdf`
  - `GET /accounting/statement/pdf`
  - `GET /accounting/receivables/pdf`
  - `GET /accounting/payables/pdf`
  - `GET /accounting/loan_receipt/pdf` (`entry_id` xor `loan_id`)
- Proof posture copy must align with SSOT 62:
  - generated-as-of timestamp posture
  - regeneration allowed
  - no legal/compliance claim posture
- No new registry key is required by this phase.
  - when registry key exists, UI must use it (SSOT 55/99 rule)
  - when no registry key exists for these fixed routes, hardcoded route use is allowed in Phase 2.5

## 63.4 Month Close Checklist Expansion (Additive)
Under `#month-close-page`, expand checklist contract with reports/documents action surfaces.

### 63.4.1 Reports Section
- Existing container remains:
  - `[data-role="mc-reports"]`
- Required child actions:
  - `[data-action="mc-download-tb-pdf"]`
  - `[data-action="mc-download-statement-pdf"]`

### 63.4.2 Documents Section
- Required checklist item container:
  - `[data-role="mc-documents"]`
- Required state marker:
  - `data-state="ok|warn|fail|unknown"`
- Required child actions:
  - `[data-action="mc-download-receivables-pdf"]`
  - `[data-action="mc-download-payables-pdf"]`
- Optional child action (conditional):
  - `[data-action="mc-download-loan-receipt-pdf"]`
  - render only when deterministic selector source exists (see `63.6`)

## 63.5 Selector Round-Trip Rules
- Month Close page URL remains:
  - `/accounting/month_close?ym=YYYY-MM`
- Any report/document action generated from Month Close must include selected `ym` in the action URL.
- Download actions are navigation-based file requests; no background fetch is required.

## 63.6 Loan Receipt in Month Close (Strict Render Rule)
- Month Close may show loan receipt action only when deterministic selector source exists in current month-close context:
  - chosen `loan_id` from UI selector, or
  - selected `entry_id` from an on-page list/context.
- If deterministic selector source does not exist, do not render loan receipt action in Phase 2.5.

## 63.7 Minimal QA Evidence (Contract Shape Only)
- Preferred: extend `tests/test_frontend_contracts.py`.
- Optional: small focused suite if needed, but no new gate family is required.
- Required checks:
  - `/accounting/month_close` renders:
    - `[data-role="mc-documents"]`
    - `[data-action="mc-download-receivables-pdf"]`
    - `[data-action="mc-download-payables-pdf"]`
    - `[data-action="mc-download-tb-pdf"]`
    - `[data-action="mc-download-statement-pdf"]`
  - checklist items expose valid `data-state` enum values.
- Required failure prefix:
  - `Month close documents contract failed:`

## 63.8 Ownership
- Architect owns SSOT 63.
- Frontend owns Month Close UI wiring, selector/action presence, URL builders, and round-trip behavior.
- Backend owns server-rendered month-close page behavior and keeps SSOT 61 route behavior stable; no new endpoints required.
- QA owns contract-shape tests for selectors/state/action surfaces.
- DevOps keeps merge-blocking test coverage when new test modules are introduced.

## 63.9 Safety/Gate Dependencies
- Must not weaken:
  - startup/migration contract: SSOT 60_schema_capabilities 60.8 and SSOT 80.13
  - security compliance: SSOT 70 and SSOT 80.12
  - DB integrity: SSOT 20.6, SSOT 60_schema_capabilities 60.9, and SSOT 80.14
  - frontend contract lock: SSOT 55
  - month-close foundation: SSOT 60_month_close_foundation
  - documents route contract: SSOT 61_documents_contracts
  - documents UX/proof posture: SSOT 62_documents_ux_proof_posture

## 63.10 Phase 2.5.1 Companion (Documents State Derivation, Non-Contradiction)
- Phase 2.5.1 deterministic documents-state derivation details are defined in `SSOT 63_1_month_close_documents_state`.
- Phase 2.5 action-selector and URL round-trip contracts in this file remain authoritative and unchanged.
- Phase 2.5.1 introduces no endpoint expansion, no registry-key expansion, and no JSON contract expansion.
