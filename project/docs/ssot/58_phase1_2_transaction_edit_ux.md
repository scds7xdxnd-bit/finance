# Phase 1.2 Transaction Edit UX Contract
_Last updated: 2026-03-10_

## 58.1 Scope
- Phase 1.2 defines Transaction Edit UX for existing journal entries.
- Primary surface is Accounting journal UI; Transactions view may link into the same editor when journal-backed entries are present.
- This phase locks UX and contract behavior; ledger correctness remains enforced by existing integrity contracts.

## 58.2 Non-Goals
- No new edit endpoints.
- No mixed reporting mode changes.
- No `/upload_csv` JSON behavior changes.
- No migration/index work in this phase.
- No new immutability policy; posted-ledger mutability is allowed for this personal app, while DB integrity constraints remain mandatory.

## 58.3 Locked Decisions
- Authoritative edit endpoint: `PUT /accounting/journal/<entry_id>`.
- Authoritative list refresh source: existing `GET /accounting/journal/list`.
- Unbalanced finalize must surface deterministic frontend error mapping.
- Editor UI must show live balance delta before submit.

## 58.4 User Stories and Acceptance Criteria

### 58.4.1 Open Edit UI
- User can open an edit modal from the journal list.
- Open action preloads entry header + line data for editing.

### 58.4.2 Edit Lines (Usable Editing)
- Editor supports:
  - add line
  - remove line (minimum 2 lines enforced)
  - change account/account_id
  - change amount
  - change memo
  - change direction (`dc`)
  - change header date + description

### 58.4.3 Live Balance Delta and Save Gating
- UI computes `delta = sum(D) - sum(C)` live from current line inputs.
- Save action is disabled unless:
  - `delta == 0.00`
  - required fields pass validation.

### 58.4.4 Deterministic Error UX
- If response payload is `ok=false`, editor shows `error` in stable form-level region.
- If `error_code=JOURNAL_NOT_BALANCED`, editor shows not-balanced inline error and remains open.
- Unexpected failures must map to deterministic fallback message (not console-only behavior).

### 58.4.5 Post-Save Refresh
- On success:
  - editor closes
  - journal list refreshes via `accounting.journal.list` registry key
  - active filter URL/query state remains preserved (SSOT 57 round-trip rules).

## 58.5 Shared UI Component Contract (Edit Modal)
- Editor root: `#journal-edit-modal`
- Form root: `#journal-edit-form`
- Form-level error region: `[data-role="form-error"]`
- Field error slots: `[data-field-error="<field>"]`
- Lines container: `[data-role="lines"]`
- Add line action: `[data-action="add-line"]`
- Remove line action: `[data-action="remove-line"]`
- Balance indicator: `[data-role="balance-delta"]`
- Save action: `[data-action="save-entry"]`

## 58.6 Request/Response Semantics

### 58.6.1 Request Contract
- Method/path: `PUT /accounting/journal/<entry_id>`
- Content type: JSON
- Minimum required request keys:
  - `date`
  - `description`
  - `lines` (array)
- Per-line minimum required keys:
  - `dc`
  - `account_id` or `account`
  - `amount`
- Per-line optional:
  - `memo`

### 58.6.2 Success Contract
- HTTP `200`
- Payload minimum:
  - `ok=true`
  - `entry` object present

### 58.6.3 Failure Contract
- Payload minimum:
  - `ok=false`
  - `error` (string)
- Unbalanced finalize case must return:
  - `error_code=JOURNAL_NOT_BALANCED`
- Status classes:
  - `4xx` for validation/integrity/authorization rejections
  - `503` for capability/startup gate failures

## 58.7 Integrity Sequencing Alignment
- This phase aligns to:
  - SSOT 20.6 (finalization signal + base-amount balance invariant)
  - SSOT 60.9 (`journal_integrity` capability contract)
- Required sequencing remains:
  1. backend may set `posted_at=NULL` while rebuilding line set
  2. backend finalizes only when balanced
- DB guard abort prefix `journal_entry_not_balanced` must map to UI-facing `error_code=JOURNAL_NOT_BALANCED`.

## 58.8 Endpoint Registry Contract Touchpoints
- Frontend must use:
  - `window.FINANCE_ENDPOINTS.accounting.journal.list`
  - `window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate` with `__ENTRY_ID__` replacement token
- Phase 1.2 does not require a separate registry key for opening edit UI.
- Hardcoded update/list URLs are forbidden when registry keys exist.

## 58.9 Minimal QA Evidence (Contract Shape)
- QA extends `tests/test_frontend_contracts.py` only.
- Required additions:
  - unbalanced update attempt yields `ok=false` and `error_code=JOURNAL_NOT_BALANCED` with `4xx`
  - registry key presence check for:
    - `accounting.journal.list`
    - `accounting.journal.updateTemplate`
    - `__ENTRY_ID__` placeholder token
- No full accounting totals assertions required in Phase 1.2.

## 58.10 Safety/Gate Dependencies
- Startup/migration contract: SSOT 60.8 / 80.13
- Security compliance: SSOT 70 / 80.12
- DB integrity: SSOT 20.6 / 60.9 / 80.14
- Frontend contract lock: SSOT 55
- Phase 1 baseline: SSOT 56
- Phase 1.1 filters round-trip: SSOT 57

## 58.11 Phase 1.2.1 Companion (Hardening, Non-Contradiction)
- Phase 1.2.1 hardening details are defined in `SSOT 58_1`.
- Phase 1.2 endpoint decisions in this file remain authoritative:
  - `PUT /accounting/journal/<entry_id>` for updates
  - `GET /accounting/journal/list` for list refresh.
- Phase 1.2.1 introduces no new endpoint, no CSV JSON behavior, and no DB/migration requirement.
