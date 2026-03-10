# Phase 1.2.4 Transaction Edit Usability Polish Contract
_Last updated: 2026-03-10_

## 58.4.1 Scope
- Phase 1.2.4 defines usability polish for Accounting journal edit modal:
  - keyboard flow
  - focus management
  - line manipulation affordances
  - balance-delta clarity
  - inline validation clarity
  - stale-warning usability affordance.
- This phase does not change correctness model; draft/finalize sequencing and DB integrity remain enforced by SSOT 20.6, 60.9, and 80.14.
- Architecture constraint is explicit and unchanged:
  - journal list row HTML remains minimal (`data-entry-id` + display fields + action markers only)
  - full entry objects remain in JS state (`JOURNAL_STATE.byId`) from `GET /accounting/journal/list`.

## 58.4.2 Non-Goals
- No new endpoints.
- No new registry keys.
- No new `get entry details` endpoint for preload.
- No conversion of list rows to embedded per-row JSON blobs.
- No JSON contract expansion beyond SSOT 55/58/58_1/58_2/58_3.
- No `/upload_csv` JSON changes.
- No DB/schema/migration/index work.

## 58.4.3 Locked Decisions
- Preload source remains JS-state only:
  - `JOURNAL_STATE.byId[entry_id]` from existing list endpoint payloads.
- Update path remains:
  - `PUT /accounting/journal/<entry_id>`.
- List refresh path remains:
  - `GET /accounting/journal/list` through existing registry key.
- Refresh-safety markers from SSOT 58_3 remain mandatory.
- Existing selectors/contracts from SSOT 58/58_1/58_2/58_3 remain stable; Phase 1.2.4 may add selectors only additively.

## 58.4.4 Keyboard and Focus Management Contract
- Modal root remains `#journal-edit-modal`.
- Required selectors:
  - first-focus target: `[data-role="first-focus"]`
  - focus trap marker: `[data-role="focus-trap"]`
  - close action: `[data-action="close-editor"]`
  - cancel action: `[data-action="cancel-editor"]`
- Behavior lock:
  - on open with preload-state `ready`, focus moves to `[data-role="first-focus"]`
  - `Esc` triggers cancel/close only when save is not in progress
  - `Ctrl+Enter`/`Cmd+Enter` triggers save only when save action is enabled
  - after save success, focus returns to originating row action (`[data-action="edit-entry"][data-entry-id="..."]`) when present; otherwise deterministic fallback focus target is used.

## 58.4.5 Line Manipulation Affordance Contract
- Existing required selectors remain:
  - `[data-role="lines"]`
  - `[data-action="add-line"]`
  - `[data-action="remove-line"]`
- Optional additive selectors (if implemented):
  - duplicate line: `[data-action="duplicate-line"]`
  - move line up: `[data-action="move-line-up"]`
  - move line down: `[data-action="move-line-down"]`
- Behavior lock:
  - minimum 2 lines enforced
  - remove action disabled when line count is 2
  - duplicate line copies `dc`, `account_id`, `amount`, and `memo` from source line
  - any line manipulation action recomputes balance delta and re-applies save-gating rules from SSOT 58_1.

## 58.4.6 Live Delta Clarity Contract
- Existing selector remains:
  - `[data-role="balance-delta"]` with `data-state="balanced|not_balanced"`.
- New required additive slots:
  - amount slot: `[data-role="balance-delta-amount"]`
  - label slot: `[data-role="balance-delta-label"]`
- Behavior lock:
  - label text remains exact: `Balanced` or `Not balanced`
  - amount is displayed as signed decimal with 2dp (`+0.00`, `-10.00`, etc.)
  - save remains disabled unless delta is exactly `0.00` and required fields are valid.

## 58.4.7 Inline Validation Messaging Polish Contract
- Existing selectors remain:
  - `[data-role="form-error"]`
  - `[data-field-error="<field>"]`
- Field-map convention lock:
  - header:
    - `[data-field-error="date"]`
    - `[data-field-error="description"]`
    - `[data-field-error="reference"]` (optional)
  - lines:
    - `[data-field-error="lines[i].dc"]`
    - `[data-field-error="lines[i].account_id"]`
    - `[data-field-error="lines[i].amount"]`
- Error behavior lock:
  - mappable field errors render near mapped field slot
  - non-mappable errors render in form-level region
  - `error_code=JOURNAL_NOT_BALANCED` renders:
    - form-level error
    - deterministic inline callout at `[data-role="not-balanced-callout"]`
  - network/unexpected failures render deterministic visible fallback message (never console-only).

## 58.4.8 Stale Warning Usability Contract
- Existing stale selector remains required:
  - `[data-role="stale-warning"]`.
- Optional additive stale CTA selector (if implemented):
  - `[data-action="reload-latest"]`.
- Behavior lock for `reload-latest` when implemented:
  - triggers list refresh via existing registry key
  - does not automatically overwrite local editor buffer
  - clears stale warning only when list signature/backing entry reconciliation succeeds
  - does not force-close modal.

## 58.4.9 Save-In-Progress and Double-Submit Protection Contract
- New required selector:
  - `[data-role="save-status"]`
- Required state attribute on save-status node:
  - `data-state="idle|saving|saved|error"`
- Behavior lock:
  - `saving`: save action disabled, line actions disabled, saving status visible
  - `error`: return to `idle` semantics with local editor buffer preserved.

## 58.4.10 Minimal QA Evidence (Contract Shape Only)
- QA extends `tests/test_frontend_contracts.py` (no full browser E2E requirement).
- Required assertions on `/accounting` HTML within `#journal-edit-modal`:
  - existing required markers:
    - `[data-role="edit-session"]`
    - `[data-role="stale-warning"]`
    - `[data-role="preload-state"]`
    - `data-buffer-authority="local"`
  - new required selectors:
    - `[data-role="balance-delta-amount"]`
    - `[data-role="balance-delta-label"]`
    - `[data-role="first-focus"]`
    - `[data-action="close-editor"]`
    - `[data-role="save-status"]` with `data-state` attribute
  - conditional selectors (assert only if feature implemented in this phase):
    - `[data-action="duplicate-line"]`
    - `[data-action="reload-latest"]`
- Registry stability assertion remains required:
  - no edit/list registry-key drift relative to SSOT 55.
- Required failure prefix:
  - `Transaction edit usability contract failed:`

## 58.4.11 Compatibility Locks
- No endpoint or registry-key additions are allowed in Phase 1.2.4.
- JS-state preload remains authoritative (`JOURNAL_STATE.byId`).
- Phase 1.2.4 is additive UI polish only; it must not weaken SSOT 58/58_1/58_2/58_3 contracts.

## 58.4.12 Ownership and Gate Dependencies
- Architect owns this SSOT file.
- Frontend owns implementation of additive selector and usability behavior.
- Backend endpoint surface remains unchanged in this phase.
- QA owns contract-shape verification in `tests/test_frontend_contracts.py`.
- Gate dependencies remain mandatory:
  - frontend contract lock: SSOT 55
  - startup/migration: SSOT 60.8 / 80.13
  - security compliance: SSOT 70 / 80.12
  - DB integrity: SSOT 20.6 / 60.9 / 80.14.
