# Phase 2.5.1 Month Close Documents State Derivation Contract
_Last updated: 2026-03-11_

## 63.1.1 Scope
- This document defines deterministic derivation rules for Month Close `mc-documents` state for a selected month `ym`.
- Phase 2.5.1 is advisory-only and does not create a blocking close posture.
- This phase introduces no new endpoint requirement and no new registry-key requirement.

## 63.1.2 Non-Goals
- No new endpoints.
- No new endpoint-registry keys.
- No JSON contract expansion (documents remain PDF/navigation behavior under SSOT 61/62).
- No DB schema/index/migration requirements in this phase.
- No weakening of SSOT 60/61/62/63 or SSOT 55/57 contracts.

## 63.1.3 Locked Decisions
- Month Close documents state remains computed from existing month-close/reporting/documents context for the active `ym`.
- Computation is deterministic from existing data sources only; no new "details" endpoint is permitted in this phase.
- `mc-documents` state remains a checklist-state signal only; it is not a release gate and does not block app usage.

## 63.1.4 Deterministic Inputs (Reuse-Only)
- Required derived counters for selected `ym`:
  - `open_receivables_count`
  - `open_payables_count`
  - `total_receivables_count`
  - `total_payables_count`
- Counter inputs must come from existing receivables/payables sources already used by current accounting/documents flows.
- Input-source expansion (new endpoint or dedicated state API) is out of scope for Phase 2.5.1.

## 63.1.5 Deterministic State Derivation Rules
Define:
- `open_documents_count = open_receivables_count + open_payables_count`
- `total_documents_count = total_receivables_count + total_payables_count`

State rule for `[data-role="mc-documents"]`:
1. `unknown` when month-close cannot compute counts for selected `ym` due to schema/capability/startup not-ready posture or safely handled query errors.
2. `warn` when counts are computable and `open_documents_count > 0`.
3. `ok` when counts are computable and `open_documents_count == 0`.
4. `fail` is intentionally unused in Phase 2.5.1 and is reserved for future invariant-breach rules defined in a separate SSOT PR.

## 63.1.6 Additive UI Selector Contract (Machine-Checkable)
Within Month Close documents checklist surface:
- Keep existing state marker surface:
  - `[data-role="mc-documents"]` with `data-state="ok|warn|fail|unknown"`
- Add required count slots:
  - `[data-role="mc-documents-open-count"]`
  - `[data-role="mc-documents-total-count"]`
- Optional navigation helper action:
  - `[data-action="mc-open-documents-panel"]`
  - when implemented, action must be navigation-only and must not introduce new API behavior.

## 63.1.7 Query Parameter and Round-Trip Rules
- Month Close URL context remains canonical:
  - `/accounting/month_close?ym=YYYY-MM`
- Any Month Close documents action/link in this phase must preserve `ym`.
- Any optional helper navigation action must remain compatible with SSOT 57 URL round-trip posture.

## 63.1.8 Minimal QA Evidence (Contract Shape Only)
- QA extends `tests/test_frontend_contracts.py` only.
- Required assertions:
  1. Month Close page includes required selectors:
     - `[data-role="mc-documents"]`
     - `[data-role="mc-documents-open-count"]`
     - `[data-role="mc-documents-total-count"]`
  2. `mc-documents` `data-state` derivation is deterministic in seeded scenarios for at least:
     - `warn` (open count > 0)
     - `ok` (open count == 0 and counts computable)
  3. `ym` is preserved in month-close documents action URLs when those actions are rendered.
- Required failure prefix:
  - `Month close documents state contract failed:`

## 63.1.9 Ownership
- Architect owns SSOT definitions in this file.
- Frontend owns month-close documents state rendering and selector stability.
- Backend owns deterministic count derivation behavior using existing data sources only.
- QA owns contract-shape checks in `tests/test_frontend_contracts.py`.
- DevOps keeps merge-blocking coverage for impacted frontend contract tests.

## 63.1.10 Safety and Compatibility Dependencies
- Must not weaken:
  - SSOT 55 frontend contract lock
  - SSOT 57 filter/query round-trip behavior
  - SSOT 60 month-close foundation contract
  - SSOT 61 documents route/selector/PDF contract
  - SSOT 62 documents UX/proof posture
  - SSOT 63 month-close reports/documents integration
  - startup/migration, security, and DB integrity gates (SSOT 80.12/80.13/80.14)

## 63.1.11 Phase 2.8 Companion (Readiness Roll-up)
- Phase 2.8 readiness summary consumes `mc-documents` state and open/total counts as inputs.
- No change to documents state derivation rules is introduced by Phase 2.8.
