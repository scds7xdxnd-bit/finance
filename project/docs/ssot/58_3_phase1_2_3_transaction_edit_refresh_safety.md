# Phase 1.2.3 Transaction Edit Refresh Safety Contract
_Last updated: 2026-03-10_

## 58.3.1 Scope
- Phase 1.2.3 hardens editor refresh safety for Accounting journal edit flow.
- Scope is limited to:
  - local editor buffer preservation under background list refresh
  - stale warning visibility behavior
  - query-parameter preservation on refresh calls.

## 58.3.2 Non-Goals
- No new endpoints.
- No new registry keys.
- No JSON contract expansion beyond SSOT 55/58/58_1/58_2.
- No `/upload_csv` JSON behavior changes.
- No DB/schema/index work.

## 58.3.3 Locked Decisions
- While modal session is active, editor local buffer is authoritative.
- Background list refresh is allowed while modal is open, but must not mutate:
  - editor input values
  - balance delta state
  - field-level or form-level error state.
- Stale warning is mandatory and non-blocking; stale state never force-closes modal.

## 58.3.4 Machine-Checkable UI Contract Additions

### 58.3.4.1 Edit Session Marker
- `#journal-edit-modal` must contain:
  - `[data-role="edit-session"]`
- Required attributes:
  - `data-entry-id="<id>"`
  - `data-session="active|inactive"`
- `data-session="active"` is required while modal is open for editing.

### 58.3.4.2 Stale Warning Surface
- `#journal-edit-modal` must contain:
  - `[data-role="stale-warning"]`
- Behavior lock:
  - visible when preload-state is `stale`
  - hidden when preload-state is not `stale`.

### 58.3.4.3 Refresh Safety Guard Marker
- Modal root `#journal-edit-modal` must carry:
  - `data-buffer-authority="local"` during active edit session.
- This marker is the explicit contract that refresh logic must not overwrite local editor buffer.

## 58.3.5 Refresh Behavior Contract
- List refresh call must preserve active query params exactly, including:
  - `q`
  - `account_id`
  - `category_id`
  - `min_amount`
  - `max_amount`
  - `start`
  - `end`
  - `page`
  - `per_page`
- If refresh occurs while edit session is active:
  - `JOURNAL_STATE.byId` may update
  - editor local buffer must not be overwritten
  - stale warning must remain visible when backing entry changes.

## 58.3.6 Reconciliation After Save
- On save success:
  - if `response.entry` exists, update `JOURNAL_STATE.byId[entry_id]` immediately from response
  - then trigger list refresh for list ordering/aggregate consistency
  - modal closes only after save success.
- Refresh events alone must not auto-close modal.

## 58.3.7 Minimal QA Evidence (Contract Shape Only)
- Extend `tests/test_frontend_contracts.py` only.
- Required assertions:
  1. `/accounting` HTML includes inside `#journal-edit-modal`:
     - `[data-role="edit-session"]`
     - `[data-role="stale-warning"]`
     - modal root has `data-buffer-authority="local"` default marker.
  2. Registry key set remains stable (no new edit/list registry keys added); required keys remain present.
- Required failure prefix:
  - `Transaction edit refresh safety contract failed:`

## 58.3.8 Ownership and Forbidden Changes
- Architect owns this SSOT file.
- Frontend owns edit-session marker, stale-warning rendering, and buffer-authority behavior.
- Backend owns existing endpoint behavior only (`PUT /accounting/journal/<entry_id>`, `GET /accounting/journal/list`).
- QA owns contract-shape checks for this phase.
- Forbidden without SSOT update and QA evidence:
  - adding preload read endpoints
  - adding new registry keys for edit/list flow
  - removing `edit-session` marker, `stale-warning` selector, or `data-buffer-authority="local"` semantics
  - dropping `page`/`per_page` and active selector preservation on refresh.

## 58.3.9 Safety/Gate Dependencies
- Frontend contract lock: SSOT 55
- Phase 1 baseline: SSOT 56
- Filters round-trip: SSOT 57
- Transaction edit contracts: SSOT 58 / 58_1 / 58_2
- Startup/migration gates: SSOT 60.8 / 80.13
- Security compliance gate: SSOT 70 / 80.12
- DB integrity gate: SSOT 20.6 / 60.9 / 80.14


## 58.3.10 Phase 1.2.4 Companion (Usability Polish)
- Phase 1.2.4 usability polish contract details are defined in `SSOT 58_4`.
- Phase 1.2.3 refresh-safety marker and local-buffer authority rules remain authoritative unless explicitly tightened additively by SSOT 58_4.
- Phase 1.2.4 introduces no new endpoint, no new registry key, and no JSON contract expansion.
