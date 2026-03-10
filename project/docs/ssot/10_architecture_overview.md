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
