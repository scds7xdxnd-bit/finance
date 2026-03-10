# Phase 1 UX Friction Removal Contract
_Last updated: 2026-03-10_

## 56.1 Scope
- This document defines the SSOT contract for Phase 1 UX friction removal.
- Scope is limited to frontend-visible behavior and frontend-consumed contract surfaces.
- Phase 1 must not weaken existing release/safety contracts in SSOT 20, 55, 60, 70, 80, and 90.

## 56.2 Non-Goals (Explicit)
- No new `/upload_csv` JSON API behavior in Phase 1.
- No bypass of startup/migration, security, or DB integrity gates.
- No replacement of canonical posting endpoint for Quick Add (`POST /add_transaction` remains authoritative).

## 56.3 Phase 1 Decisions (Locked)

### 56.3.1 Last Import Result Persistence
- Decision: Option B (session-backed persistence).
- Canonical storage key: `session["last_import_result_v1"]`.
- This value is written server-side after `/upload_csv` completes and redirects.
- It is rendered by the transactions page after redirect and may coexist with flash messages.
- Persistence window:
  - until replaced by next import result, explicit dismiss action, or session expiry.

### 56.3.2 Search/Filter Mechanism
- Decision: hybrid without introducing new JSON endpoints.
- Transactions view contract:
  - server-rendered query params on `/transactions` (and `/transactions/list` for progressive enhancement HTML refresh).
- Journal view contract:
  - existing JSON endpoint `GET /accounting/journal/list` remains in use (already present runtime surface).
- Phase 1 introduces no new search/filter JSON endpoint.

### 56.3.3 Transaction Edit Surface
- Decision: reuse existing `PUT /accounting/journal/<entry_id>` endpoint.
- No new edit endpoint is introduced in Phase 1.

## 56.4 User Stories and Acceptance Criteria

### 56.4.1 A. Quick Add Modal (Transactions + Accounting)
- User story:
  - As a user, I can open one shared modal from transactions and accounting pages and post a balanced entry quickly.
- Acceptance criteria:
  - single reusable modal component is used by both pages
  - submit path is only `POST /add_transaction`
  - no alternate posting endpoint is required
  - success closes modal, resets fields, and refreshes visible list data
  - failure keeps modal open and shows deterministic error text

### 56.4.2 B. Standardized Inline Validation + Error UX
- User story:
  - As a user, I see consistent field-level and form-level validation errors across Phase 1 flows.
- Acceptance criteria:
  - client validation runs before submit
  - server error envelope from SSOT 55 is consumed consistently
  - field errors map to stable inline containers
  - non-field errors map to stable form-level container

### 56.4.3 C. CSV Import UX Improvement (No JSON)
- User story:
  - As a user, I can always see the most recent import result after redirect.
- Acceptance criteria:
  - import flow remains `/upload_csv` redirect/flash compatible
  - no new CSV JSON response contract introduced
  - persistent Last Import Result panel renders from server-side session-backed summary

### 56.4.4 D. Search & Filters
- User story:
  - As a user, I can find transactions/journal entries by text, account/folder, amount, and date range.
- Acceptance criteria:
  - stable query param contract is implemented (`56.7`)
  - absent params preserve default unfiltered behavior
  - paging is deterministic
  - rendering uses existing page/fragment mechanisms (no new JSON endpoint for transactions list)

### 56.4.5 E. Transaction Edit Flow
- User story:
  - As a user, I can edit journal entries while preserving integrity guarantees.
- Acceptance criteria:
  - edit uses existing journal update endpoint
  - mutation sequence uses draft-to-finalize behavior (`posted_at=NULL` during rebuild, finalize only when balanced)
  - DB trigger block (`journal_entry_not_balanced`) is surfaced as deterministic UI error

## 56.5 Shared UI Component Contract (Quick Add Modal)

### 56.5.1 Stable DOM Surface
- Modal root: `#quick-add-modal`
- Form root: `#quick-add-form`
- Form-level error region: `[data-role="form-error"]`
- Field error slots: `[data-field-error="<field_name>"]`
- Submit button: `[data-action="quick-add-submit"]`

### 56.5.2 Required Inputs
- `date` (string, `YYYY-MM-DD`)
- `description` (string)
- `lines[]` (array, minimum 2 rows)
- per-line required: `dc`, `account` or `account_id`, `amount`
- per-line optional: `memo`

### 56.5.3 Validation Rules (Client + Server)
- date required and parseable
- description required (1..255 chars after trim)
- at least 2 lines
- each line requires valid direction (`D|C`), account/account_id, and amount > 0
- line totals must balance (`sum(D) == sum(C)`)

### 56.5.4 Submission and Result Handling
- Submit as JSON to `POST /add_transaction` with CSRF header/token.
- Success behavior:
  - close modal
  - clear form
  - refresh visible list region/page state
- Failure behavior:
  - keep modal open
  - show inline field errors when mappable
  - otherwise show form-level error from response `error` (and optional `error_code` mapping)

## 56.6 Last Import Result Panel Contract (No CSV JSON)

### 56.6.1 Storage and Shape
- Canonical source is server session key `last_import_result_v1`.
- Minimum summary keys:
  - `imported_count`
  - `duplicate_count`
  - `failed_count`
  - `summary_text`
  - `source_filename` (if available)
  - `recorded_at` (ISO string)

### 56.6.2 Render Contract
- Panel root selector: `#last-import-result-panel`.
- Panel is rendered on transactions page after redirect from `/upload_csv`.
- Flash messages remain supported; session-backed panel is authoritative for persistence.

### 56.6.3 Lifecycle
- overwrite on next import completion
- clear on explicit dismiss action
- clear on session expiration

## 56.7 Search and Filter Query Contract
- Phase 1.1 companion for parsing and round-trip semantics: `SSOT 57`.

### 56.7.1 Transactions View (`/transactions` and `/transactions/list`)
- Stable query params:
  - `q` (merchant/description contains)
  - `account`
  - `category`
  - `min_amount`
  - `max_amount`
  - `start_date`
  - `end_date`
  - `page`
  - `per_page`
- Defaults when absent:
  - no filter for optional selectors
  - `page=1`
  - `per_page` server default

### 56.7.2 Journal View (`GET /accounting/journal/list`)
- Stable query params:
  - `q`
  - `account_id`
  - `category_id`
  - `min_amount`
  - `max_amount`
  - `start`
  - `end`
  - `page`
  - `per_page`
- Defaults when absent:
  - no filter for optional selectors
  - `page=1`
  - `per_page` server default

### 56.7.3 Performance Constraint
- Phase 1 implementations must avoid unbounded full-table scans where filter selectors are present.
- If p95 filter/list latency exceeds target thresholds, add index follow-up in later DB PR (outside this SSOT-only PR).
- Measurement-first threshold and evidence method are defined in `SSOT 57.8`.

## 56.8 Transaction Edit Contract (`PUT /accounting/journal/<entry_id>`)

### 56.8.1 Allowed Edits
- editable: `date`, `description`, `reference`, `lines[]`
- line edits may:
  - change account/account_id
  - change amount
  - change memo
  - add/remove lines (minimum 2 lines required)

### 56.8.2 Integrity Sequencing
- update flow must:
  1. set `posted_at=NULL` while rebuilding line set
  2. validate/attempt balanced finalization
  3. set `posted_at` only after valid finalization
- DB integrity contract from SSOT 20.6 and 60.9 remains mandatory.

### 56.8.3 Error Mapping Requirement
- If DB guard rejects finalization with `journal_entry_not_balanced`, UI-facing failure must be deterministic:
  - `ok=false`
  - stable `error` message
  - stable `error_code` for unbalanced finalization (`JOURNAL_NOT_BALANCED`)

## 56.9 Safety/Gate Dependencies (Must Not Be Weakened)
- Startup/migration contract gate: SSOT 60.8 / 80.13
- Security compliance gate: SSOT 70 / 80.12
- DB integrity gate: SSOT 20.6 / 60.9 / 80.14
- Frontend contract lock: SSOT 55

## 56.10 Minimal QA Contract Evidence (Phase 1)
- Contract tests are key-presence and status-class checks, not full accounting totals verification.
- Mandatory follow-up test surface:
  - `tests/test_frontend_contracts.py`
- Minimum assertions:
  - required keys from SSOT 55, SSOT 56, and SSOT 57
  - stable endpoint registry keys used by Phase 1
  - deterministic error-key presence for failure paths

## 56.11 Phase 1.2 Companion (Non-Contradiction Lock)
- Phase 1.2 transaction edit UX is defined in `SSOT 58`.
- Quick Add behavior in `56.4.1` and `56.5` is unchanged by Phase 1.2.
- Any Phase 1.2 implementation must preserve all Phase 1 contracts in this document and must not weaken `56.9` safety/gate dependencies.
