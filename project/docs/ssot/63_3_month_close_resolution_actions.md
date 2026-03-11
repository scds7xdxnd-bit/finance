# Phase 2.7 Month Close Resolution Actions (Navigation-Only) Contract
_Last updated: 2026-03-11_

## 63.3.1 Scope
- Defines Month Close checklist resolution actions for `warn` and `unknown` states as navigation-only affordances.
- Applies to checklist surfaces under `#month-close-page` without introducing blocking close behavior.
- Resolution actions reuse existing pages/endpoints; no new endpoint or registry-key requirement is introduced.

## 63.3.2 Non-Goals
- No new APIs/endpoints.
- No new `window.FINANCE_ENDPOINTS` keys.
- No JSON contract expansion.
- No new gate family or blocking month-close posture.
- No snapshot immutability requirement.

## 63.3.3 Locked Decisions
- Resolution actions are links/forms that navigate to existing pages or existing endpoints only.
- All resolution actions preserve `ym` month context.
- Where pagination context exists (for example journal list navigation), actions preserve `page` and `per_page` when applicable.
- This phase introduces no new checklist states; existing enum remains authoritative.

## 63.3.4 Required UI Selector Contract (Machine-Checkable)
Under `#month-close-page`, required resolution selectors:

### 63.3.4.1 Coverage Resolution Actions
- `[data-action="mc-open-tb"]`
- `[data-action="mc-open-statements"]`

### 63.3.4.2 Draft Resolution Action
- `[data-action="mc-open-journal-drafts"]`

### 63.3.4.3 Documents Resolution Action
- `[data-action="mc-open-documents-panel"]` is required under current contract set (see SSOT 63_6 deep-link lock).
- Action remains navigation-only.

## 63.3.5 URL Construction and Round-Trip Rules
- Month Close canonical context remains:
  - `/accounting/month_close?ym=YYYY-MM`
- Every rendered resolution action URL must include `ym`.
- Actions that target paginated list contexts must preserve `page` and `per_page` where those values exist.
- Actions remain navigation-only; no asynchronous API behavior is required by this contract.

## 63.3.6 State Compatibility
- No new state values are introduced in Phase 2.7.
- Checklist items continue to use:
  - `ok|warn|fail|unknown`
- State semantics remain governed by SSOT 60, SSOT 63, and SSOT 63_2.

## 63.3.7 Minimal QA Evidence (Contract Shape Only)
- QA extends `tests/test_frontend_contracts.py` only.
- Required assertions:
  1. `/accounting/month_close?ym=YYYY-MM` includes required action selectors:
     - `[data-action="mc-open-tb"]`
     - `[data-action="mc-open-statements"]`
     - `[data-action="mc-open-journal-drafts"]`
     - `[data-action="mc-open-documents-panel"]`
  2. Extracted action URLs include `ym` query parameter.
  3. Where paginated targets are rendered with known context, URLs preserve `page` and `per_page`.
- Required failure prefix:
  - `Month close resolution contract failed:`

## 63.3.8 Ownership
- Architect owns SSOT definitions in this file.
- Frontend owns selector rendering and URL construction for navigation actions.
- Backend owns reuse-only navigation targets and month-close context emission without endpoint expansion.
- QA owns contract-shape verification.
- DevOps keeps merge-blocking coverage under existing required checks.

## 63.3.9 Safety and Compatibility Dependencies
- Must remain compatible with:
  - SSOT 55 frontend contract lock
  - SSOT 57 URL round-trip behavior
  - SSOT 60 month-close foundation
  - SSOT 61/62 documents contracts/proof posture
  - SSOT 63/63_1/63_2 month-close integration/state derivation contracts
- Must not weaken startup/security/DB-integrity gates (SSOT 80.12/80.13/80.14).

## 63.3.10 Phase 2.8 Companion (Next-Action Mapping)
- Phase 2.8 next-action guidance must map to Phase 2.7 resolution actions where applicable (navigation-only).
- No new resolution-action selectors are required by Phase 2.8.

## 63.3.11 Phase 2.8.1 Companion (Readiness Linkage Hardening)
- Phase 2.8.1 hardens deterministic readiness-linkage rules against this file's resolution selectors.
- No new resolution-action selectors are required by Phase 2.8.1.

## 63.3.12 Phase 2.10.1 Companion (Documents Deep-Link Lock)
- Phase 2.10.1 tightens `[data-action="mc-open-documents-panel"]` from optional to required on month-close surfaces.
- Documents resolution target contract is locked to `/accounting?ym=...`; self-linking to `/accounting/month_close` is forbidden.
