# Phase 2.0 Month Close Foundation Contract
_Last updated: 2026-03-11_

## 60.1 Scope
Phase 2.0 introduces a Month Close checklist UI and a minimal snapshot foundation:
- a month-close UI that surfaces readiness signals for a given `ym`
- optional snapshot storage is allowed, but immutability is not required for this personal app
- this phase locks UI contracts, query selectors, and minimal status semantics
- no PDF generation contract is introduced in Phase 2.0

## 60.2 Non-Goals
- No new immutable-ledger requirement.
- No new reporting-math invariants (totals correctness remains owned by existing gates).
- No new export/PDF endpoints in this phase.
- No new DB schema/migrations required in Phase 2.0 (snapshot persistence may be deferred).
- No weakening of SSOT 55/56/57/58-series/59-series, SSOT 60_schema_capabilities 60.8, SSOT 70, SSOT 20.6, SSOT 80, or SSOT 90 contracts.

## 60.3 Locked Decisions
- Month selector key is `ym` in `YYYY-MM` format.
- Month Close UI is advisory and does not block app usage unless a future SSOT gate explicitly makes it blocking.
- Readiness signals must reuse existing endpoint surfaces where possible:
  - `GET /accounting/tb/monthly` (JSON, SSOT 55)
  - `GET /accounting/statement/data` (JSON, SSOT 55)
  - `GET /accounting/journal/list` (JSON, SSOT 55), when counts are derived from existing list payload behavior
- If a new summary endpoint is needed, it requires a separate Architect SSOT PR (not in Phase 2.0 docs-only scope).

## 60.4 Month Close Checklist Items (User-Visible)
For a given `ym`, checklist UI must display these sections.

### 60.4.1 Coverage/Linking Health
- Source: `coverage` objects when present from statement/TB endpoints.
- Required display states:
  - coverage present or absent
  - `coverage_count`, `coverage_amount` when present
  - `unlinked_recent_90d_count` when present
- This section is advisory and does not block closing in Phase 2.0.

### 60.4.2 Unbalanced Drafts Count
- Definition:
  - draft = journal entry with `posted_at IS NULL` or not finalized by current workflow
  - unbalanced draft = `delta != 0.00` in base currency
- Phase 2.0 allows either:
  - backend-computed count in a future surface, or
  - client-side count for currently loaded list slice (advisory only)
- Contract requirement: checklist UI must show a numeric badge or `unknown` when not computable.

### 60.4.3 Report Generation Buttons (Hook Only)
- Buttons may exist for:
  - TB PDF
  - statement export/PDF
- In Phase 2.0, these are links to existing endpoints only; no contract expansion is introduced.
- If a button cannot run due to capability/startup gates, UI must show deterministic user-visible error.

### 60.4.4 Close Month Snapshot (Optional)
- Phase 2.0 introduces concept + UI affordance only; DB persistence is optional.
- Snapshot storage may be:
  - DB record (future)
  - file artifact (future)
  - soft snapshot (recorded actions + cached JSON/session state) for personal-use posture
- Snapshot is not required to be immutable.
- Snapshot must not bypass DB integrity or reporting source-policy rules.

## 60.5 Month Close Page Contracts

### 60.5.1 Route and Selector Contract
- Preferred dedicated route, when implemented: `GET /accounting/month_close`.
- Phase 2.0 does not require a new route; checklist UI may be hosted in existing accounting page surfaces.
- Query parameter:
  - `ym` required (`YYYY-MM`) for month-close context.
- Default behavior:
  - if `ym` missing, UI uses current month as default selector
  - UI must keep `ym` visible and round-trippable in URL/state.

### 60.5.2 Stable DOM Contract (Month Close UI)
- Root: `#month-close-page`
- Month selector: `[data-role="month-close-ym"]`
- Checklist root: `[data-role="month-close-checklist"]`
- Checklist item containers:
  - coverage: `[data-role="mc-coverage"]`
  - drafts: `[data-role="mc-unbalanced-drafts"]`
  - reports: `[data-role="mc-reports"]`
  - snapshot: `[data-role="mc-snapshot"]`
- Status marker convention:
  - each checklist item must expose `data-state="ok|warn|fail|unknown"`.
- UI must not be console-only on failures.

### 60.5.3 Snapshot Controls (UI)
- Snapshot action button: `[data-action="mc-create-snapshot"]`
- Snapshot status region: `[data-role="mc-snapshot-status"]`
- Snapshot list container (if shown): `[data-role="mc-snapshot-list"]`
- Phase 2.0 allows deterministic disabled/coming-soon behavior when persistence is not implemented.

## 60.6 API and Contract Touchpoints (No New Endpoints Required)
- Month Close UI should reuse:
  - `window.FINANCE_ENDPOINTS.accounting.tbMonthly`
  - `window.FINANCE_ENDPOINTS.accounting.statements.data`
- No new JSON endpoint lock is required for Phase 2.0.
- If a new registry key is needed later, it requires explicit SSOT 55 update in a separate Architect PR.

## 60.7 Minimal QA Evidence (Contract Shape Only)
- Extend `tests/test_frontend_contracts.py` with month-close contract-shape assertions.
- Required assertions:
  1. Month-close UI surface includes stable DOM markers (`#month-close-page`, checklist root, and all checklist item selectors).
  2. Each checklist section exposes `data-state` with value in `{ok,warn,fail,unknown}`.
  3. Month selector marker exists and carries/reflects `ym` context.
- Required failure prefix:
  - `Month close contract failed:`

## 60.8 Compatibility and Gate Dependencies
Phase 2.0 must not weaken:
- startup/migration contract: SSOT 60_schema_capabilities 60.8 and SSOT 80.13
- security compliance gate: SSOT 70 and SSOT 80.12
- DB integrity gate: SSOT 20.6, SSOT 60_schema_capabilities 60.9, and SSOT 80.14
- frontend contract lock: SSOT 55
- Phase 1 contracts: SSOT 56/57/58-series/59-series

## 60.9 Phase 2.5 Companion (Reports + Documents Integration)
- Phase 2.5 Month Close integration details are defined in `SSOT 63_month_close_documents_integration`.
- Phase 2.0 month selector and checklist foundation in this file remain authoritative and unchanged.
- Phase 2.5 introduces no new endpoint or registry-key requirement and does not alter advisory Month Close posture.

## 60.10 Phase 2.5.1 Companion (Documents State Derivation, Non-Contradiction)
- Phase 2.5.1 Month Close documents-state derivation details are defined in `SSOT 63_1_month_close_documents_state`.
- Phase 2.0 month selector/checklist foundation and advisory posture in this file remain authoritative and unchanged.
- Phase 2.5.1 introduces no new endpoint requirement, no new registry-key requirement, and no JSON contract expansion.

## 60.11 Phase 2.6 Companion (Coverage + Unbalanced Drafts Derivation)
- Phase 2.6 derivation rules and additive selectors are defined in `SSOT 63_2_month_close_coverage_unbalanced_state`.
- Phase 2.0 advisory posture remains unchanged; no blocking month close is introduced.

## 60.12 Phase 2.7 Companion (Resolution Actions, Non-Contradiction)
- Phase 2.7 Month Close resolution-action rules are defined in `SSOT 63_3_month_close_resolution_actions`.
- Phase 2.0 advisory posture and checklist-state model remain unchanged.
- Phase 2.7 introduces no endpoint expansion, no registry-key expansion, and no JSON contract expansion.

## 60.13 Phase 2.8 Companion (Readiness Summary, Non-Contradiction)
- Phase 2.8 readiness roll-up and next-action guidance are defined in `SSOT 63_4_month_close_readiness_summary`.
- Month Close remains advisory; no blocking posture or new gate is introduced.
- No endpoint/registry expansion or JSON expansion is introduced by Phase 2.8.

## 60.14 Phase 2.8.1 Companion (Readiness Linkage Hardening, Non-Contradiction)
- Phase 2.8.1 readiness next-action linkage hardening is defined in `SSOT 63_4_1_month_close_readiness_linkage`.
- Month Close remains advisory and non-blocking.
- No endpoint/registry expansion or JSON expansion is introduced by Phase 2.8.1.
