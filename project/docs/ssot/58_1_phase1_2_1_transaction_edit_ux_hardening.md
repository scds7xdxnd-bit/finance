# Phase 1.2.1 Transaction Edit UX Hardening Contract
_Last updated: 2026-03-10_

## 58.1.1 Scope
- Phase 1.2.1 hardens transaction edit UX for Accounting journal list as the primary surface.
- This phase standardizes preload/render behavior, balance-state UX, error placement, and post-save round-trip behavior.
- This phase is UX and contract hardening only; correctness remains governed by SSOT 20.6, 60.9, and 80.14.

## 58.1.2 Non-Goals
- No new endpoints.
- No new JSON contracts beyond SSOT 55 and SSOT 58.
- No `/upload_csv` JSON behavior changes.
- No DB schema/migration/index work.
- No weakening of startup, security, DB integrity, or existing quality gates.

## 58.1.3 Locked Decisions
- Edit update endpoint remains `PUT /accounting/journal/<entry_id>`.
- List refresh endpoint remains `GET /accounting/journal/list`.
- Registry-key usage remains mandatory:
  - `window.FINANCE_ENDPOINTS.accounting.journal.list`
  - `window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate` with `__ENTRY_ID__`
- Unbalanced finalize mapping remains deterministic:
  - `error_code=JOURNAL_NOT_BALANCED`
  - modal remains open.

## 58.1.4 UX Acceptance Criteria (Machine-Checkable)

### 58.1.4.1 Open and Preload Behavior
- Row action selector must exist: `[data-action="edit-entry"]` on each editable journal row.
- Open action must resolve a deterministic `entry_id` source from row context.
- Modal selectors from SSOT 58.5 remain required and unchanged.
- Preload contract:
  - header fields preload: `date`, `description` (and `reference` when available)
  - lines preload with `dc`, `account_id|account`, `amount`, `memo` (optional)
- Preload failure contract:
  - modal stays open only in error state or remains closed; either path must render visible message in `[data-role="form-error"]`
  - save action must stay disabled on preload failure
  - failure must not be console-only.

### 58.1.4.2 Lines Editing Behavior
- Lines container is `[data-role="lines"]`.
- Add/remove actions remain:
  - `[data-action="add-line"]`
  - `[data-action="remove-line"]`
- Minimum line count is `2`; remove action is blocked when line count is `2`.
- Editable line fields:
  - `dc`
  - `account_id` (or `account`)
  - `amount`
  - `memo` (optional)
- Editable header fields:
  - `date`
  - `description`
  - `reference` (optional).

### 58.1.4.3 Live Balance Delta and Save Gating
- Balance indicator selector remains `[data-role="balance-delta"]`.
- Balance state must be explicit and deterministic:
  - `data-state="balanced"` when `delta == 0.00`
  - `data-state="not_balanced"` when `delta != 0.00`
- Visible label must be deterministic:
  - `"Balanced"` for balanced state
  - `"Not balanced"` for non-balanced state
- Save action selector remains `[data-action="save-entry"]`.
- Save action must be disabled unless:
  - `delta == 0.00`
  - required fields are valid.

### 58.1.4.4 Error UX Rules
- Response envelope handling remains per SSOT 55/58:
  - `ok=false` must include visible `error`.
- Field-level error placement (when mappable) uses:
  - `[data-field-error="date"]`
  - `[data-field-error="description"]`
  - `[data-field-error="lines[i].amount"]`
  - `[data-field-error="lines[i].dc"]`
  - `[data-field-error="lines[i].account_id"]`
- Non-mappable errors must render in `[data-role="form-error"]`.
- `JOURNAL_NOT_BALANCED` must render inline not-balanced error and keep modal open.
- Unexpected/network errors must render deterministic fallback message in visible UI (never console-only).

## 58.1.5 Round-Trip Behavior (SSOT 57 Preservation)
- After successful save:
  - modal closes
  - list refresh uses `accounting.journal.list` registry key
  - active query params are preserved exactly, including `page` and `per_page`
- After failed save:
  - modal remains open
  - user input values remain intact
  - errors are rendered by rules in `58.1.4.4`.

## 58.1.6 Contract Lock Touchpoints
- This phase introduces no new endpoint and no new registry key requirements.
- New registry keys are forbidden in Phase 1.2.1 unless an Architect SSOT PR updates SSOT 55.5.
- Hardcoded list/update paths remain forbidden when registry keys exist.

## 58.1.7 Minimal QA Evidence (Contract Shape Only)
- Preferred QA surface: extend `tests/test_frontend_contracts.py`.
- Allowed alternative: add focused suite only when needed; baseline remains contract-shape checks.
- Required assertions:
  - required edit modal selectors and balance selector exist
  - update failure mapping includes `ok=false`, `error`, `error_code=JOURNAL_NOT_BALANCED`
  - registry keys/token still present:
    - `accounting.journal.list`
    - `accounting.journal.updateTemplate`
    - `__ENTRY_ID__`
  - post-save refresh target preserves active query params (`page`/`per_page` included)
- Required failure prefix:
  - `Transaction edit UX contract failed:`

## 58.1.8 Safety/Gate Dependencies
- Frontend contract lock: SSOT 55
- Phase 1 baseline: SSOT 56
- Filters round-trip: SSOT 57
- Phase 1.2 edit contract: SSOT 58
- Startup/migration gate: SSOT 60.8 / 80.13
- Security compliance gate: SSOT 70 / 80.12
- DB integrity gate: SSOT 20.6 / 60.9 / 80.14

## 58.1.9 Phase 1.2.2 Companion (State Drift Hardening)
- Phase 1.2.2 preload/state-drift contract details are defined in `SSOT 58_2`.
- Phase 1.2.1 selector, save-gating, and error placement rules remain authoritative unless explicitly tightened by SSOT 58_2.
- Phase 1.2.2 introduces no new endpoint, no new registry key, and no CSV JSON behavior.

## 58.1.10 Phase 1.2.4 Companion (Usability Polish)
- Phase 1.2.4 usability polish details are defined in `SSOT 58_4`.
- Phase 1.2.1 selector, save-gating, and error-placement rules remain authoritative unless explicitly tightened additively by SSOT 58_4.
- Phase 1.2.4 introduces no new endpoint, no new registry key, no JSON expansion, and no CSV JSON behavior.
