# Phase 1.1 Search & Filters Round-Trip Contract
_Last updated: 2026-03-10_

## 57.1 Scope
- This document locks Phase 1.1 query-parameter contracts, UI round-trip behavior, and minimal acceptance criteria.
- Scope includes:
  - transactions filters on `/transactions` and `/transactions/list`
  - accounting journal filters on existing `GET /accounting/journal/list`
  - measurement-first performance posture for filter/list behavior

## 57.2 Non-Goals (Explicit)
- No new endpoints in Phase 1.1.
- No new JSON list endpoint for transactions.
- No DB indexes in this PR.
- No `/upload_csv` JSON contract change.

## 57.3 Transactions Filter Contract (Server-Rendered)

### 57.3.1 Stable Query Parameters
- `q`
- `account`
- `category`
- `min_amount`
- `max_amount`
- `start_date`
- `end_date`
- `page`
- `per_page`

### 57.3.2 Parsing Semantics
- `q`: case-insensitive substring match against merchant/description text.
- `account` and `category`:
  - empty string or `all` means no filter.
- `min_amount` and `max_amount`:
  - valid decimal values only.
  - invalid values are frontend validation errors; request must not be submitted.
- `start_date` and `end_date`:
  - required format `YYYY-MM-DD`.
  - invalid values are frontend validation errors; request must not be submitted.

### 57.3.3 Round-Trip Rules
- Filter submit must persist filter params in URL.
- Pagination links must preserve all active filter params.
- `per_page` must persist across pagination.
- Clear action must navigate to base `/transactions` with no filter params.

## 57.4 Transactions Progressive Enhancement Contract (`/transactions/list`)
- Endpoint accepts identical query parameters as `/transactions` (`57.3.1`).
- Response contract is HTML fragment (not JSON) for list replacement.
- Client callers must pass query params through unchanged from current UI filter state.

## 57.5 Accounting Journal Filter Contract (Existing JSON Endpoint)

### 57.5.1 Stable Query Parameters
- `q`
- `account_id`
- `category_id`
- `min_amount`
- `max_amount`
- `start`
- `end`
- `page`
- `per_page`

### 57.5.2 Round-Trip Rules
- UI control state must always mirror active query params.
- Pagination must preserve all active query params.
- `per_page` must persist across pagination.

## 57.6 User-Visible Acceptance Criteria
- Transactions filter UI must expose controls for:
  - `q`, `account`, `category`, `min_amount`, `max_amount`, `start_date`, `end_date`, `per_page`
- Accounting journal filter UI must expose controls for:
  - `q`, `account_id`, `category_id`, `min_amount`, `max_amount`, `start`, `end`, `per_page`
- Empty and error states must follow standardized behavior from SSOT 56.4.2.

## 57.7 Minimal Contract Evidence (QA)
- QA extends `tests/test_frontend_contracts.py` only (contract-shape scope).
- Required test method for transactions round-trip:
  - assert pagination link `href` values preserve active filter params, including `per_page`.
- Required test method for journal list:
  - assert endpoint accepts params and returns `ok=true` with stable keys (`entries`, `page`, `pages`, `total`).
- Phase 1.1 does not add totals correctness assertions.

## 57.8 Performance Posture (Measurement-First)
- Rule: no new indexes unless slowness is evidenced.
- Measurement path:
  - collect request timings for filtered `/transactions` and `/accounting/journal/list` calls in local verification notes.
  - evaluate p95 latency over at least 30 requests on a local dataset around 10k rows.
- Follow-up trigger for DB/index PR:
  - p95 observed > 500ms for either filtered list path.
- Any index work must be in a separate DB-focused PR with evidence attached.

## 57.9 Gate/Safety Dependencies
- Startup/migration contract remains mandatory: SSOT 60.8 / 80.13.
- Security compliance remains mandatory: SSOT 70 / 80.12.
- DB integrity contract remains mandatory: SSOT 20.6 / 60.9 / 80.14.
- Frontend contract lock remains mandatory: SSOT 55.
- Phase 1 UX baseline remains mandatory: SSOT 56.
