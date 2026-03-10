# Phase 1.3 CSV Import UX Contract (No JSON)
_Last updated: 2026-03-10_

## 59.1 Scope
- Phase 1.3 defines user-visible CSV import UX behavior on transactions surfaces without introducing new APIs.
- Contract covers session summary payload, panel rendering surface, dismissal semantics, and redirect round-trip behavior.
- This phase is UX contract hardening only; existing import correctness and gate behavior remain authoritative from SSOT 40/60/80.

## 59.2 Non-Goals
- No JSON response contract for `POST /upload_csv`.
- No new endpoints for upload or import-summary retrieval.
- No migrations or index changes.
- No weakening of SSOT 20/55/56/57/58/60/70/80/90 gates or contracts.

## 59.3 Locked Decisions
- Canonical summary storage remains session-backed key: `session["last_import_result_v1"]`.
- Dismiss action is authoritative as `POST /transactions/import_result/dismiss` (existing route contract; no new route creation).
- Panel precedence vs flash:
  - Last Import Result panel is persistent (session-backed).
  - flash messages may coexist but are transient and not a replacement for the panel.
- `/upload_csv` remains redirect/flash behavior; no JSON success/failure payload is introduced.

## 59.4 Last Import Result Payload Contract (v1)

### 59.4.1 Required Keys and Types
- `imported_count`: integer, `>= 0`
- `duplicate_count`: integer, `>= 0`
- `failed_count`: integer, `>= 0`
- `summary_text`: string, non-empty after trim
- `source_filename`: string or `null`
- `recorded_at`: ISO-8601 datetime string

### 59.4.2 Optional Allowed Keys
- `failure_samples`: array of objects with shape:
  - `line_number`: integer, `>= 1`
  - `message`: string, non-empty
- `write_mode`: string
- `warnings`: array of strings

### 59.4.3 Contract Stability
- Required keys in `59.4.1` are stable and must not be removed or renamed without SSOT update and QA evidence.
- Optional keys may be absent; when present, type/shape constraints remain stable.

## 59.5 Panel Render Contract
- Panel root: `#last-import-result-panel`
- Severity slot: `[data-role="import-severity"]`
- Summary region: `[data-role="import-summary"]`
- Counts region: `[data-role="import-counts"]`
- Timestamp region: `[data-role="import-recorded-at"]`
- Filename region: `[data-role="import-filename"]`
- Dismiss action: `[data-action="dismiss-import-result"]`
- Optional details toggle: `[data-action="toggle-import-details"]`
- Optional details container: `[data-role="import-details"]`

## 59.6 Lifecycle and Visibility Rules
- Panel is rendered on `GET /transactions` when `session["last_import_result_v1"]` exists.
- Panel remains visible across refresh/navigation until one of the following occurs:
  - next import result overwrites session key
  - explicit dismiss clears session key
  - session expires
- Dismiss behavior contract:
  - method/path: `POST /transactions/import_result/dismiss`
  - requires authenticated session and CSRF validation
  - must clear `session["last_import_result_v1"]`
  - must redirect back to `/transactions` while preserving active filter query params from SSOT 57

## 59.7 Outcome Semantics (Derived `result_kind`)
- `result_kind` is derived from counts; backend is not required to store it as a separate key.
- Deterministic classification:
  - `success` when `failed_count == 0` and `imported_count > 0`
  - `no_op` when `imported_count == 0` and `duplicate_count > 0` and `failed_count == 0`
  - `partial` when `failed_count > 0` and `imported_count > 0`
  - `failed` when `imported_count == 0` and `failed_count > 0`
- UI severity requirement:
  - all kinds must render a deterministic severity indicator in `[data-role="import-severity"]`
  - `partial` and `failed` must expose a details affordance when `failure_samples` or `warnings` data exists

## 59.8 Compatibility Locks
- Phase 1.3 must not change SSOT 55 JSON endpoint contracts.
- Phase 1.3 must not change SSOT 56/57/58 query and UX contracts.
- Phase 1.3 must not introduce `/upload_csv` JSON behavior.

## 59.9 Minimal QA Evidence (Contract Shape Only)
- QA test surface:
  - primary: `tests/test_frontend_contracts.py`
  - optional dedicated suite: `tests/test_csv_import_ux_contract.py`
- Required assertions:
  - when session contains `last_import_result_v1`, HTML includes `#last-import-result-panel`
  - dismiss form/action is present, uses `POST`, and includes CSRF token in rendered HTML
  - rendered HTML includes required `data-role`/`data-action` selectors from `59.5`
  - dismiss redirect target preserves active filter params (SSOT 57 key-presence check only)
- Required contract failure prefix:
  - `CSV import UX contract failed:`

## 59.10 Safety/Gate Dependencies
- Frontend contract lock: SSOT 55
- Phase 1 UX baseline: SSOT 56
- Filters round-trip contract: SSOT 57
- Transaction edit UX: SSOT 58
- Startup/migration: SSOT 60.8 / 80.13
- Security compliance: SSOT 70 / 80.12
- DB integrity: SSOT 20.6 / 60.9 / 80.14
