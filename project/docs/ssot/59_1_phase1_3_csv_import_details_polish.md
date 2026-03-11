# Phase 1.3.1 CSV Import Details UX Polish Contract (No JSON)
_Last updated: 2026-03-11_

## 59.1.1 Scope
- Phase 1.3.1 hardens details UX behavior for the existing Last Import Result panel from SSOT 59.
- Scope is limited to deterministic server-rendered details rendering, toggle behavior, selector stability, and dismiss round-trip behavior.
- Existing architecture posture remains unchanged:
  - `POST /upload_csv` stays redirect/flash.
  - Summary state stays session-backed at `session["last_import_result_v1"]`.
  - Panel rendering stays server-side on `/transactions`.

## 59.1.2 Non-Goals
- No new endpoints.
- No new registry keys.
- No `/upload_csv` JSON response contract.
- No DB-backed import-summary persistence or schema work.
- No weakening of SSOT 55/56/57/58/60/70/80/90 contracts and gates.

## 59.1.3 Locked Decisions
- Canonical summary storage key remains `session["last_import_result_v1"]`.
- Dismiss route remains `POST /transactions/import_result/dismiss` with auth + CSRF and redirect preserving SSOT 57 params.
- Details polish is additive to SSOT 59; it does not change endpoint surfaces.
- Panel + details behavior must be deterministic and must not be console-only.

## 59.1.4 Data Contract Tightening (Extends SSOT 59.4)

### 59.1.4.1 Required Keys (Unchanged)
- Required key contract remains from SSOT 59.4.1:
  - `imported_count`
  - `duplicate_count`
  - `failed_count`
  - `summary_text`
  - `source_filename`
  - `recorded_at`

### 59.1.4.2 Optional Details Keys (When Present)
- `failure_samples`: array of objects with:
  - `line_number`: integer, `>= 1`
  - `message`: string, non-empty after trim
- `warnings`: array of non-empty strings
- `write_mode`: string

### 59.1.4.3 Details Display Rules
- If `failure_samples` exists and has length `> 0`, details UI must render a Failures section.
- If `warnings` exists and has length `> 0`, details UI must render a Warnings section.
- If both `failure_samples` and `warnings` are absent or empty, details toggle must not be rendered.
- `write_mode` is optional metadata; when present, it must be rendered in details metadata section.

## 59.1.5 DOM/Selector Contract (Additive and Stable)
- Base selectors from SSOT 59.5 remain required:
  - `#last-import-result-panel`
  - `[data-role="import-severity"]`
  - `[data-role="import-summary"]`
  - `[data-role="import-counts"]`
  - `[data-role="import-recorded-at"]`
  - `[data-role="import-filename"]`
  - `[data-action="dismiss-import-result"]`
  - `[data-action="toggle-import-details"]` (conditional; required only when details data exists)
  - `[data-role="import-details"]` (conditional; required only when details data exists)
- New stable detail selectors (required when details data exists):
  - `[data-role="import-details-failures"]`
  - `[data-role="import-details-warnings"]`
  - `[data-role="import-details-meta"]`
- Details visibility state contract:
  - details container must include `data-state="collapsed|expanded"`.

## 59.1.6 Usability and Behavior Locks
- Default on page render:
  - when details container exists, it must initialize to `data-state="collapsed"`.
- Toggle behavior:
  - clicking `[data-action="toggle-import-details"]` must toggle details `data-state` between `collapsed` and `expanded`.
  - toggle action must not trigger navigation and must not refresh the page.
- Severity behavior:
  - severity label remains deterministic in `[data-role="import-severity"]` per SSOT 59.7 result-kind rules.
  - for `partial` and `failed`, UI must indicate details availability when details data exists.
- Dismiss behavior (unchanged from SSOT 59.6):
  - dismiss stays `POST` + CSRF
  - redirect preserves active SSOT 57 filter params
  - after dismiss, panel must not render because session key is cleared.

## 59.1.7 Forbidden Changes
- Do not introduce `/upload_csv` JSON response semantics.
- Do not add endpoint(s) to fetch import summary/details.
- Do not rename or repurpose `session["last_import_result_v1"]`.
- Do not remove/rename required SSOT 59 and SSOT 59.1 selectors or details `data-state` semantics without SSOT update and QA evidence.

## 59.1.8 Minimal QA Evidence (Contract Shape Only)
- Preferred QA test surface: `tests/test_frontend_contracts.py`.
- Optional dedicated suite: `tests/test_csv_import_ux_contract.py`.
- Required assertions:
  - when session includes `last_import_result_v1` with populated details keys:
    - panel renders all required base selectors
    - details toggle exists
    - details container exists with default `data-state="collapsed"`
    - failures/warnings sections render when corresponding data exists
  - when session includes summary without details keys:
    - details toggle must not render
  - dismiss semantics:
    - dismiss action uses `POST` with CSRF in rendered HTML
    - redirect preserves active SSOT 57 params
- Required failure prefix:
  - `CSV import details UX contract failed:`

## 59.1.9 Compatibility and Gate Dependencies
- Frontend contract lock: SSOT 55
- Phase 1 baseline: SSOT 56
- Filters round-trip: SSOT 57
- Startup/migration gate: SSOT 60.8 / 80.13
- Security compliance gate: SSOT 70 / 80.12
- DB integrity gate: SSOT 20.6 / 60.9 / 80.14
- SSOT 59.1 is additive polish only and must not weaken SSOT 59.
