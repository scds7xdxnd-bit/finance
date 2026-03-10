# Phase 1.2.2 Transaction Edit UX State Drift Contract
_Last updated: 2026-03-10_

## 58.2.1 Scope
- Phase 1.2.2 hardens transaction edit preload and state-drift behavior for Accounting journal editor.
- Contract is limited to editor preload source, editor preload-status UX, and list-refresh/state reconciliation behavior.
- This phase preserves existing endpoint and registry surfaces from SSOT 55/58/58_1.

## 58.2.2 Non-Goals
- No new endpoints.
- No new registry keys.
- No new JSON contracts beyond SSOT 55/58/58_1.
- No `/upload_csv` JSON behavior changes.
- No DB schema/migration/index work.
- No weakening of startup, security, DB integrity, or gate contracts.

## 58.2.3 Locked Decisions
- Preload source for editor open is JS state only:
  - `JOURNAL_STATE.byId[entry_id]`
  - state is derived from `GET /accounting/journal/list`.
- No additional read endpoint is allowed for preload in Phase 1.2.2.
- If requested `entry_id` is missing from `JOURNAL_STATE.byId` at open time:
  - editor enters visible missing-state error mode
  - save stays disabled
  - error must not be console-only.
- After successful save:
  - list refresh is triggered through `window.FINANCE_ENDPOINTS.accounting.journal.list`
  - `JOURNAL_STATE.byId[entry_id]` is reconciled using:
    - response `entry` object when present, else
    - next list refresh payload.
- Active query params (`page`, `per_page`, and all SSOT 57 selectors) must remain preserved on list refresh.

## 58.2.4 UI Contract Additions (Machine-Checkable)

### 58.2.4.1 Row Open Action Surface
- Edit action selector remains required:
  - `[data-action="edit-entry"]`
- Entry identifier source is required:
  - `data-entry-id` attribute with deterministic journal `entry_id` value.

### 58.2.4.2 Preload Status Marker
- Editor root remains `#journal-edit-modal`.
- Editor root must contain preload marker:
  - `[data-role="preload-state"]`
- Allowed marker states only:
  - `data-state="ready"`
  - `data-state="missing"`
  - `data-state="stale"`
  - `data-state="loading"`

### 58.2.4.3 Non-Ready Behavior
- When preload state is not `ready`:
  - `[data-role="form-error"]` must contain visible user-facing message
  - `[data-action="save-entry"]` must be disabled
  - modal must not auto-close due to preload failure.

## 58.2.5 State Drift Rules

### 58.2.5.1 Deterministic Stale Definition
- Editor state is `stale` when list context signature differs between:
  - signature captured at editor preload time, and
  - current active list signature.
- Required list signature inputs:
  - SSOT 57 query params, including `page` and `per_page`.
- Signature may be represented as `state_epoch` or canonical `list_signature` string; one stable representation must be used by implementation.

### 58.2.5.2 Stale Handling Policy (Locked)
- Policy: non-blocking warning, no forced modal close.
- On stale detection while modal is open:
  - editor sets preload marker to `data-state="stale"`
  - visible warning is rendered in editor UI
  - local edit buffer remains intact
  - save remains available if all save-gating rules from SSOT 58/58_1 are satisfied.

### 58.2.5.3 Concurrent Refresh Safety
- List refresh must not overwrite the currently edited local buffer before save completes.
- If refresh updates backing state for the same `entry_id` during active edit session:
  - editor must keep local buffer authoritative for current modal session
  - stale warning must remain visible until save success, cancel, or manual reload action.

## 58.2.6 Round-Trip and Reconciliation
- After save success:
  - modal closes
  - list refresh is executed via registry key
  - active query params are preserved exactly (SSOT 57)
  - `JOURNAL_STATE.byId[entry_id]` reconciliation applies using response `entry` first, then list refresh fallback.
- After save failure:
  - modal remains open
  - local buffer remains intact
  - deterministic error mapping from SSOT 58/58_1 remains in effect.

## 58.2.7 Minimal QA Evidence (Contract Shape Only)
- Primary QA surface:
  - `tests/test_frontend_contracts.py`
- Required assertions:
  1. `#journal-edit-modal` contains `[data-role="preload-state"]`.
  2. Open action surface exists:
     - `[data-action="edit-entry"]` with `data-entry-id`.
  3. Missing-state scenario (simulated) renders:
     - preload marker `data-state="missing"`
     - visible `[data-role="form-error"]` message
     - disabled `[data-action="save-entry"]`.
- Required failure prefix:
  - `Transaction edit state contract failed:`

## 58.2.8 Ownership and Forbidden Changes
- Architect owns SSOT definition in this file.
- Frontend owns preload/state lifecycle and preload-status UX behavior.
- Backend owns existing endpoint behavior only (`PUT`/`GET` paths unchanged).
- QA owns contract-shape verification.
- Forbidden in Phase 1.2.2 without SSOT update and QA evidence:
  - adding new preload read endpoints
  - adding new registry keys for edit/list flows
  - removing preload-state marker or renaming allowed preload state values.

## 58.2.9 Safety/Gate Dependencies
- Frontend contract lock: SSOT 55
- Phase 1 baseline: SSOT 56
- Filters round-trip: SSOT 57
- Phase 1.2 edit contract: SSOT 58
- Phase 1.2.1 hardening: SSOT 58_1
- Startup/migration: SSOT 60.8 / 80.13
- Security compliance: SSOT 70 / 80.12
- DB integrity: SSOT 20.6 / 60.9 / 80.14

## 58.2.10 Phase 1.2.3 Companion (Refresh Safety Hardening)
- Phase 1.2.3 refresh-safety contract details are defined in `SSOT 58_3`.
- Phase 1.2.2 preload-state and stale-detection rules remain authoritative unless explicitly tightened by SSOT 58_3.
- Phase 1.2.3 introduces no new endpoint, no new registry key, and no JSON contract expansion.
