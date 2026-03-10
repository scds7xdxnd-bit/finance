# Frontend Contract Lock (vNext)
_Last updated: 2026-03-10_

## 55.1 Scope
- Frontend Contract Surface means any HTTP status, payload key, or endpoint registry key consumed directly by templates or static JavaScript.
- This document locks minimal backend contracts for frontend-critical endpoints during UI refactors.
- Non-JSON endpoints are out of scope for this contract lock.
- `/upload_csv` JSON behavior is explicitly excluded in this phase; current redirect/flash flow remains authoritative.

## 55.2 Rule of Change
- Additive response/request changes are allowed if required keys in this document remain valid.
- Breaking contract changes require all of the following in the same coordinated rollout:
  - Architect SSOT PR updating this file
  - QA contract test update
  - Frontend update consuming the new contract
- No team may remove or rename locked keys without SSOT update and QA evidence.

## 55.3 Global JSON Envelope Contract (In Scope Endpoints)

### 55.3.1 Required Envelope Keys
- Every JSON response must include `ok` with boolean type.
- Any failure JSON response must include:
  - `ok=false`
  - `error` (human-readable string)
- `error_code` is optional but strongly recommended; if present, it is a stable contract key.

### 55.3.2 Content Type
- In-scope JSON endpoints must return Flask JSON responses (`application/json` or JSON-compatible Flask response object).

### 55.3.3 Status Code Classes
- `2xx` for successful processing (normally `200`).
- `4xx` for client/auth/request errors.
- `503` for schema/capability/startup not-ready conditions.

## 55.4 Endpoint Contract Lock (Minimum Required Keys)

### 55.4.1 `POST /add_transaction`
- Auth requirement:
  - logged-in user required
  - CSRF required
- Required request keys:
  - `date`
  - `description`
  - `lines` (array)
- Required response keys:
  - always: `ok`
  - on success (`ok=true`): `mode` and at least one identifier key: `entry_id` or `transaction_id`
  - on failure (`ok=false`): `error` (optional `error_code`)
- Status classes:
  - `200` success
  - `4xx` request/auth/validation errors
  - `503` schema/capability not-ready
- Allowed differences:
  - extra keys are allowed
  - key ordering is irrelevant
- Breaking change definition:
  - removing `ok`, removing `mode` on success, removing both `entry_id` and `transaction_id` on success, or removing `error` on failure.

### 55.4.2 `POST /api/ml_suggestions`
- Auth requirement:
  - logged-in user required
- Required request keys:
  - `lines` (array)
  - selector key: `target_line_id`
  - stable selector set used by frontend (when provided by caller context): `description`, `currency`, `date`, `top_k`
- Required response keys:
  - always: `ok`
  - on success (`ok=true`):
    - `predictions` (array)
    - `currency`
    - context identifiers: `transaction_id`, `line_id`, `line_type`
    - `status`
    - `fallback`
  - prediction item minimum shape:
    - `account_name`
    - `probability`
  - on failure (`ok=false`):
    - `error` (optional `error_code`)
    - if `status`/`fallback` are present, meanings must remain stable
- Status classes:
  - `200` success
  - `4xx` request/auth/rate-limit/validation errors
  - `503` dependency/capability not-ready
- Allowed differences:
  - extra metadata fields are allowed (for example timing/model fields)
  - key ordering is irrelevant
- Breaking change definition:
  - removing required success keys, changing prediction minimum shape, or unstable semantics for `status`/`fallback`.

### 55.4.3 `POST /api/suggestions/log`
- Auth requirement:
  - logged-in user required
- Required request keys:
  - `logs` (array)
- Required response keys:
  - always: `ok`
  - on success (`ok=true`): `saved`
  - on failure (`ok=false`): `error` (optional `error_code`)
- Status classes:
  - `200` success
  - `4xx` request/auth/rate-limit/validation errors
  - `503` dependency/capability not-ready
- Allowed differences:
  - extra keys are allowed
  - key ordering is irrelevant
- Breaking change definition:
  - removing `saved` on success or removing `error` on failure.

### 55.4.4 `GET /accounting/tb/monthly`
- Auth requirement:
  - logged-in user required
- Required query selectors:
  - `ym` (frontend must send explicit month selector)
  - `ccy` optional when currency filtering is used
- Required response keys:
  - always: `ok`
  - on success (`ok=true`): `groups`, `grand_totals`, `source`
  - coverage metadata is optional; when present, it must be under `coverage`
  - on failure (`ok=false`): `error` (contract lock uses `error`, not `message`)
- Status classes:
  - `200` success
  - `4xx` request/auth/validation/source-policy errors
  - `503` schema/capability/startup not-ready
- Allowed differences:
  - extra keys are allowed (for example `totals`, `initialized_on`)
  - key ordering is irrelevant
- Breaking change definition:
  - removing any required success key, moving coverage outside `coverage`, or replacing failure `error` with an incompatible key.

### 55.4.5 `GET /accounting/statement/data`
- Auth requirement:
  - logged-in user required
- Required query selectors:
  - `ym`
  - optional selectors: `ym_compare`, `ccy`, `cash_folders`
- Required response keys:
  - always: `ok`
  - on success (`ok=true`): `period`, `generated_at`, `statements`, `source`
  - if coverage is returned, it must be a stable object at `coverage`
  - minimum coverage keys when `coverage` exists: `coverage_count`, `coverage_amount`
  - on failure (`ok=false`): `error` (contract lock uses `error`, not `message`)
- Status classes:
  - `200` success
  - `4xx` request/auth/validation/source-policy errors
  - `503` schema/capability/startup not-ready
- Allowed differences:
  - extra keys are allowed (for example `compare_period`, `cash_folder_options`)
  - key ordering is irrelevant
- Breaking change definition:
  - removing any required success key, incompatible `coverage` object shape when present, or replacing failure `error` with an incompatible key.

### 55.4.6 `GET /accounting/journal/list`
- Auth requirement:
  - logged-in user required
- Required query selectors:
  - `q` optional
  - `account_id` optional
  - `category_id` optional
  - `min_amount` optional
  - `max_amount` optional
  - `start` optional
  - `end` optional
  - `page` optional
  - `per_page` optional
- Required response keys:
  - always: `ok`
  - on success (`ok=true`): `entries`, `page`, `pages`, `total`
  - on failure (`ok=false`): `error` (optional `error_code`)
- Status classes:
  - `200` success
  - `4xx` request/auth/validation errors
  - `503` schema/capability/startup not-ready
- Allowed differences:
  - extra entry fields are allowed
  - key ordering is irrelevant
- Breaking change definition:
  - removing required pagination/list keys, or removing `error` on failure.

### 55.4.7 `PUT /accounting/journal/<entry_id>`
- Auth requirement:
  - logged-in user required
  - CSRF required
- Required request keys:
  - `date`
  - `description`
  - `lines` (array, minimum 2)
  - optional: `reference`
- Required response keys:
  - always: `ok`
  - on success (`ok=true`): `entry`
  - on failure (`ok=false`): `error` (optional `error_code`)
- Required error mapping:
  - unbalanced finalize failures must expose stable `error_code=JOURNAL_NOT_BALANCED`
- Status classes:
  - `200` success
  - `4xx` request/auth/validation/forbidden errors
  - `503` schema/capability/startup not-ready
- Allowed differences:
  - extra keys are allowed
  - key ordering is irrelevant
- Breaking change definition:
  - removing `entry` on success, removing deterministic unbalanced error mapping, or removing `error` on failure.

## 55.5 Frontend Endpoint Registry Contract (`window.FINANCE_ENDPOINTS`)
- Registry source file: `templates/partials/frontend_endpoints.html`.
- Required registry keys that must exist:
  - `window.FINANCE_ENDPOINTS.transactions.list`
  - `window.FINANCE_ENDPOINTS.transactions.add`
  - `window.FINANCE_ENDPOINTS.ml.suggestions`
  - `window.FINANCE_ENDPOINTS.ml.suggestionLog`
  - `window.FINANCE_ENDPOINTS.accounting.tbMonthly`
  - `window.FINANCE_ENDPOINTS.accounting.statements.data`
  - `window.FINANCE_ENDPOINTS.accounting.journal.list`
  - `window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate`
- Registry values must resolve to the endpoint paths/methods locked in `55.4`.
- For `accounting.journal.updateTemplate`, placeholder token `__ENTRY_ID__` is the stable replacement token for client substitution.
- Breaking registry change definition:
  - removing or renaming required keys
  - repointing required keys to incompatible endpoint contracts without SSOT/test updates.

## 55.6 Gate/Test Pointers (Follow-up Required)
- Mandatory QA contract suite pointer:
  - `tests/test_frontend_contracts.py`
- Optional shared assertion helper:
  - `tests/helpers/contract_assertions.py`
- This PR is docs-only; test implementation is follow-up work owned by QA/Backend/Frontend coordination.
- Phase 1 UX contract companion: `project/docs/ssot/56_phase1_ux_friction_removal.md`.
