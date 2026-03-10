# vNext Architecture Overview
_Last updated: 2026-03-10_

## 10.1 Scope
This document defines the canonical runtime architecture for correctness-critical finance flows (ledger posting, CSV import, convergence, reporting, schema guard, and release gates).

## 10.2 High-Level Module Graph (Text Diagram)
```text
Clients (browser, API callers, CLI operator)
    |
    v
Flask Route Layer
  - blueprints/*.py
  - finance_app/controllers/core.py
  - routes/forecast.py (legacy)
    |
    v
Service Layer (finance_app/services/*)
  - journal/posting
  - import
  - convergence
  - reporting query
  - schema guard
  - TB/reset
  - auth/rate-limit helpers
    |
    v
Model/Schema Layer (finance_app/models/* + alembic/*)
  - SQLAlchemy models + DB constraints/indexes
    |
    v
SQLite/Postgres DB

Operational Plane
  - CLI commands: finance_app/cli/management.py
  - Verification SQL/scripts: scripts/*
  - CI gate tests: tests/test_vnext_gate.py and related suites
```

## 10.3 Canonical Data Flows

### 1) Journal Posting (Canonical Ledger Write)
`/add_transaction` or service callers -> `finance_app/services/transaction_create_service.py` -> `finance_app/services/journal_service.py` -> `JournalEntry` + `JournalLine`.

In `dual` mode only: legacy `Transaction` + `TransactionJournalLink` are mirrored atomically.

### 2) CSV Import (Journal-First + Idempotent)
`/upload_csv` -> `guard_capabilities(["csv_idempotency"])` -> `finance_app/services/transaction_import_service.py`.

Pipeline: parse -> normalize -> dedupe -> post -> summarize.

Writes:
- canonical: `JournalEntry`, `JournalLine`, `CsvImportBatch`, `CsvImportRow`
- optional compatibility (`dual`/`legacy`): `Transaction`, `TransactionJournalLink`

### 3) Ledger Convergence (Legacy Compatibility Linking)
CLI `backfill-transaction-links` -> `finance_app/services/ledger_convergence_service.py` + `ledger_convergence_policy.py`.

`exact` and `strong` may auto-link; `weak_ambiguous` generates review candidates only.

CLI `ledger-reconcile` computes pass/fail + coverage thresholds.

### 4) Ranked Reporting (Journal-Only)
`/accounting/tb/monthly`, `/accounting/statement/data`, `/accounting/statement/export`, `/accounting/statement/pdf`, `/accounting/tb/pdf`
-> `finance_app/services/ledger_query_service.py`
-> `finance_app/services/trial_balance_service.py` + statement builders in `statements_pdf.py` and `trial_balance_pdf.py`.

All ranked totals come from journal data. `source=mixed` is rejected.

### 5) Schema Capability Guard
Guarded routes/CLI call `finance_app/services/schema_guard_service.py`.

Required capabilities are checked from actual schema artifacts (tables/columns/indexes/uniques/checks), not only migration revision string.

## 10.4 Runtime Boundaries (Enforced Contract)

### Route/Blueprint Boundary
Route modules may:
- authenticate user
- validate request shape
- enforce source mode policy and CSRF
- delegate correctness logic to services

Route modules must not implement alternate ledger/reporting truth paths outside defined service contracts.

### Service Boundary
Services own business rules and contract logic:
- balance validation
- write-mode matrix
- dedupe and provenance
- convergence confidence policy
- canonical reporting payloads
- capability checks

### Model Boundary
Models and migrations own persistence contract:
- table names
- key columns
- unique/check/index constraints

Service contracts may rely on these artifacts; changing them requires DB-team process and SSOT update.

### CLI Boundary
Correctness-critical operator flows are CLI-owned:
- `schema-status`
- `backfill-transaction-links`
- `ledger-reconcile`
- `sqlite-backup`
- `tb-reset-restore`

### Test/Gate Boundary
Quality gates in `tests/test_vnext_gate.py` and related suites are release-blocking references for contract compliance.

## 10.5 Authoritative Runtime Entry Points
- App factory: `finance_app/__init__.py`
- Blueprint registration: `finance_app/controllers/__init__.py`
- Accounting/report routes: `blueprints/accounting.py`
- Import routes: `blueprints/transactions.py`
- Admin safety hooks: `blueprints/admin.py`
- Auth/session/CSRF helpers: `finance_app/lib/auth.py`
- CLI commands: `finance_app/cli/management.py`

## 10.6 Boot Sequence Contract
- Boot sequence is deterministic and must execute in this order:
  1. resolve runtime DB URL (`FINANCE_DATABASE_URL` precedence per `SSOT 60.8.4`)
  2. resolve Alembic DB URL (`ALEMBIC_DATABASE_URL` precedence per `SSOT 60.8.4`)
  3. evaluate schema readiness (`schema_status.ok` and `at_head`)
  4. apply request preflight gate based on readiness state
- Runtime is `ready` only when both are true:
  - required schema capabilities pass
  - DB is at Alembic head
- Route behavior before readiness:
  - `/healthz` may respond with readiness diagnostics (`ok=false`, `required_action`, optional revision/capability metadata).
  - non-health business endpoints must return HTTP `503` with the standard startup/migration payload from `SSOT 60.8.3`.
- Non-test runtime must never create schema at boot (`db.create_all()` forbidden; Alembic-first only).
- Any startup path that bypasses the preflight gate or emits non-standard error payloads is a contract violation.

## 10.7 Phase 1 UX Integration Points
- Quick Add modal flow:
  - transactions page and accounting page both submit to `POST /add_transaction` (no alternate posting endpoint).
- Journal edit flow:
  - UI edit operations submit to `PUT /accounting/journal/<entry_id>`.
  - mutation sequence must preserve draft-to-finalize behavior required by SSOT 20.6 and 56.8.
- Transactions search/filter flow:
  - canonical selectors use query params on `/transactions`.
  - `/transactions/list` may be used for progressive enhancement HTML refresh.
- Journal search/filter flow:
  - existing `GET /accounting/journal/list` JSON endpoint remains the list/filter source for accounting UI.
- CSV import UX flow:
  - `/upload_csv` remains redirect/flash pipeline.
  - Last Import Result panel uses server-side persistence; no new CSV JSON contract in Phase 1.

## 10.8 Phase 1.1 Filters Round-Trip Integration
- Transactions filtering:
  - canonical query params flow through `/transactions`.
  - `/transactions/list` accepts identical params for progressive HTML refresh.
  - no new JSON endpoint is introduced for transactions filtering.
- Accounting journal filtering:
  - existing `GET /accounting/journal/list` remains the filter/list JSON endpoint.
- UI round-trip behavior:
  - filter params persist through pagination and `per_page` changes.
  - clear action resets to base route with no filter params.
- Performance posture:
  - measurement-first thresholding is defined in SSOT 57; indexing changes require separate evidence-backed DB PR.

## 10.9 Phase 1.2 Transaction Edit Integration Points
- Edit submission path:
  - accounting journal editor submits to `PUT /accounting/journal/<entry_id>` only.
  - no new edit endpoint is introduced in Phase 1.2.
- List refresh path:
  - post-save refresh uses existing `GET /accounting/journal/list` endpoint.
  - refresh calls must preserve active query/filter params per SSOT 57 round-trip contract.
- Integrity sequencing:
  - edit mutation sequencing remains bound to SSOT 20.6 and SSOT 60.9 (`posted_at` draft-to-finalize with balance enforcement).
  - DB trigger guard failures (for example `journal_entry_not_balanced`) must map to deterministic UI-facing error code contract from SSOT 55/58.
- Endpoint registry:
  - UI integration must use `window.FINANCE_ENDPOINTS.accounting.journal.list` and `window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate` (token `__ENTRY_ID__`).

## 10.10 Phase 1.3 CSV Import UX Integration Points (No JSON)
- Import flow remains:
  - `POST /upload_csv` -> server computes summary -> write `session["last_import_result_v1"]` -> redirect to `/transactions`.
- Render flow remains:
  - `GET /transactions` reads session summary and renders `#last-import-result-panel` when present.
- Dismiss flow remains:
  - `POST /transactions/import_result/dismiss` clears session summary and redirects to `/transactions`.
  - redirect target must preserve active query/filter params required by SSOT 57.
- Contract boundary:
  - no JSON response contract is introduced for `/upload_csv`; Phase 1.3 is HTML/session UX only (SSOT 59).

## 10.11 Phase 1.2.1 Transaction Edit UX Hardening Integration Points
- Open/preload flow:
  - row-level edit action opens existing edit modal for a deterministic `entry_id` context.
  - preload data comes from current list context; no new read endpoint is introduced.
  - preload failures must produce visible editor error state (not console-only).
- Save flow:
  - updates submit only to `PUT /accounting/journal/<entry_id>`.
  - list refresh calls only `GET /accounting/journal/list`.
  - active query params (including `page` and `per_page`) remain preserved per SSOT 57.
- UI state contract:
  - live balance delta state is explicit (`balanced` vs `not_balanced`) and save gating is deterministic.
  - deterministic error mapping remains required (`JOURNAL_NOT_BALANCED`).
- Contract boundary:
  - no new endpoints
  - no `/upload_csv` JSON behavior changes
  - no DB/schema changes in this phase (SSOT 58_1).

## 10.12 Phase 1.2.2 Transaction Edit Preload/State Drift Integration Points
- Preload source:
  - editor preload uses in-memory state only (`JOURNAL_STATE.byId`) derived from `GET /accounting/journal/list`.
  - no new preload read endpoint is introduced.
- Preload-state UI:
  - editor exposes deterministic preload-state marker (`ready|missing|stale|loading`).
  - non-ready states must produce visible UI errors and disabled save action.
- Save and refresh:
  - save remains `PUT /accounting/journal/<entry_id>`.
  - refresh remains `GET /accounting/journal/list` via registry key.
  - refresh preserves active query params (including `page` and `per_page`) per SSOT 57.
- Reconciliation:
  - on success, editor state reconciles `JOURNAL_STATE.byId[entry_id]` from response `entry` when present, else from next list refresh payload.
- Contract boundary:
  - no new endpoints
  - no new registry keys
  - no new JSON contracts
  - no `/upload_csv` JSON behavior changes (SSOT 58_2).

## 10.13 Phase 1.2.3 Transaction Edit Refresh Safety Integration Points
- Active edit session contract:
  - modal session uses explicit marker (`edit-session`) and local-buffer authority marker.
  - local buffer is authoritative while modal session is active.
- Background refresh behavior:
  - list refresh may run while modal is open.
  - refresh may update `JOURNAL_STATE.byId` but must not overwrite modal local buffer.
  - stale warning surface remains deterministic and visible when backing entry diverges.
- Refresh param preservation:
  - refresh calls preserve active SSOT 57 selectors including `page` and `per_page`.
- Save success sequencing:
  - apply `response.entry` reconciliation when present
  - then refresh list
  - close modal only after successful save.
- Contract boundary:
  - no new endpoints
  - no new registry keys
  - no new JSON contracts
  - no `/upload_csv` JSON behavior changes (SSOT 58_3).

## 10.14 Phase 1.2.4 Transaction Edit Usability Polish Integration Points
- Data source posture remains unchanged:
  - list rows remain minimal HTML (`data-entry-id` + action markers, no per-row JSON blobs).
  - full entry payloads remain in `JOURNAL_STATE.byId` from `GET /accounting/journal/list`.
- Editor flow remains endpoint-stable:
  - update: `PUT /accounting/journal/<entry_id>`
  - refresh: `GET /accounting/journal/list` via existing registry keys only.
- Additive usability polish:
  - keyboard/focus markers and save-status markers are additive DOM contracts only.
  - line affordance actions are additive and must preserve existing save-gating rules.
  - stale-warning CTA (when implemented) remains non-blocking and local-buffer-safe.
- Contract boundary:
  - no new endpoints
  - no new registry keys
  - no new JSON contracts
  - no `/upload_csv` JSON behavior changes (SSOT 58_4).
