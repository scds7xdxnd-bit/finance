# App Brief v1 (Team 0 Intake)
_Generated from repository inspection on 2026-03-06 (Asia/Seoul)._

## 1) App Brief v1 (One Page)

### Purpose
- Flask-based personal finance and bookkeeping app for authenticated users.
- Supports ledger-style tracking and reporting across:
  - transactions (legacy `Transaction` + journal entries),
  - chart of accounts and categories,
  - trial balance initialization/monthly views,
  - receivables/debt tracking and loan grouping,
  - cash forecasting via Money Schedule and legacy Forecast modules,
  - ML-assisted account suggestions.

### User Types
- Regular user:
  - manages profile, transactions/journals, accounts/categories, TB, receivables, money schedule.
- Admin user (`is_admin`, historically `Admin1`):
  - user management, jobs, diagnostics, model training/status, suggestion metrics, exports.

### Core Workflows (Current-State)
- Authentication/session:
  - register/login/logout + recovery flows.
- Transaction capture:
  - `/add_transaction` JSON creates balanced `JournalEntry` + `JournalLine`.
  - `/upload_csv` imports CSV into either journal entries (grouped by `transaction_id`) or legacy `Transaction`.
- Accounting setup:
  - `/accounting` manages categories/folders, accounts, account codes, group assignments.
- Trial balance:
  - initialize/reset TB, set opening balances and first month.
  - monthly aggregation via `/accounting/tb/monthly`.
- Statements/reporting:
  - `/accounting/statement/data|export|pdf`, `/accounting/tb/pdf`, documents page.
- Receivables/loans:
  - manual receivable/debt creation, linking, contact timelines, loan groups/allocation suggestions.
- Cash forecasting:
  - New Money Schedule (`/money-schedule/*`) with baseline assets, recurring events, scenarios, variance.
  - Legacy Forecast (`/forecast`, `/api/forecast.json`) using `money_schedule_accounts` + scheduled tx.
- ML suggestions:
  - `/api/ml_suggestions` with rate limits, remote API path, per-user model preference/fallback, logging.

### Non-Goals (Observed in this repo state)
- No explicit budgeting module (no dedicated budget models/routes/UI found).
- No investment/portfolio tracking module (no holdings/positions/market data domain found).
- No multi-tenant organization model; system is user-scoped, session-auth web app.
- No hardened external API auth model beyond session/CSRF for web flows.

### Constraints
- Data model transitional state:
  - dual ledger reality (`Transaction` legacy + `JournalEntry/JournalLine` target source-of-truth).
- Routing/layout debt:
  - active routes split across `blueprints/`, `routes/`, and `finance_app/controllers/`.
  - duplicated `/transactions` route handlers in `blueprints/transactions.py`.
- Runtime defaults:
  - default SQLite DB at `instance/finance_app.db`; Alembic migrations required.
  - timezone assumptions include Asia/Seoul in Money Schedule UI logic.
- Security posture:
  - session auth + custom CSRF; admin role in same app.
  - some admin/account flows are operationally sensitive.
- ML coupling:
  - runtime depends on gateway to external service and/or local model artifacts and user model files.
- Worktree/doc drift:
  - repo contains legacy/duplicate modules and docs that may not fully match runtime wiring.

### Current Stack
- Backend: Python, Flask, Flask-SQLAlchemy, SQLAlchemy.
- DB: SQLite default; Alembic migrations.
- Templates/UI: Jinja templates + static JS/CSS.
- Reports: PDF generation (`weasyprint`, report scripts).
- ML:
  - app-local suggestion services + user-specific lightweight models (`instance/user_models/`),
  - optional external FastAPI suggester (`ml-suggester-repo`),
  - additional ML/training projects present in-repo (`ml_journal_suggester`, `project/`).
- Tests: pytest suites under `tests/` plus additional test suites in `project/`.

## 2) Known Unknowns (Blocking Better Decisions)
- Canonical source-of-truth cutover plan status:
  - how far production data has moved from legacy `Transaction` to journal-only.
- Production deployment topology:
  - single instance vs multiple workers; SQLite vs Postgres in actual use.
- Data volume + performance envelope:
  - user/row counts, import sizes, statement generation SLAs.
- Recovery/backup policy:
  - RPO/RTO expectations and restore drills for `instance/` data.
- Permission model details:
  - admin operational boundaries and audit logging requirements.
- Currency and FX policy:
  - base currency governance, historical rate source, correction policy.
- Reconciliation operations:
  - who performs monthly close/reconciliation and current pain points.
- Expected feature scope:
  - whether budgets/investments are intentionally absent or pending.
- External ML contract ownership:
  - who owns `MLSUGGESTER` API compatibility/versioning.
- Production observability posture:
  - metrics/alerts/log retention currently in effect (vs planned docs).

## 3) Risk Register (Top 10 Failure Modes)
1. Ledger divergence between `Transaction` and `JournalEntry` causes inconsistent reports.
2. CSV import creates mixed storage paths (journal vs legacy) leading to double counting.
3. Money Schedule baseline account selection drift produces misleading predicted vs actual variance.
4. Trial balance initialization/reset misuse wipes or invalidates opening-balance assumptions.
5. Cross-user data leakage risk if user scoping is missed in a route/query.
6. Loan/receivable linking errors misstate remaining balances and repayment status.
7. FX conversion/rate data staleness distorts statement totals and cross-currency comparisons.
8. Admin actions (delete/revoke/train jobs) without strong guardrails can cause operational/data harm.
9. ML fallback behavior or stale user-model artifacts degrade suggestion quality silently.
10. Route/module duplication (legacy + current) increases regression risk during refactors.

## 4) Next Artifact Requests (Exact, High-Leverage)
- Runtime truth snapshot:
  - `printenv | rg "APP_ENV|FINANCE_DATABASE_URL|DATABASE_URL|ALEMBIC_DATABASE_URL|MLSUGGESTER|DISABLE_ML|SESSION_|UPLOAD_|STATIC_CACHE_MAX_AGE"`
- Production-like schema + volume facts:
  - output of:
    - `alembic current`
    - `sqlite3 instance/finance_app.db ".tables"`
    - row counts for key tables (`transaction`, `journal_entry`, `journal_line`, `money_schedule_rows`, `loan_group`, `receivable_manual_entry`).
- UI ground truth screenshots (current real app state):
  - `transactions`, `accounting` (folders + TB panel), `money-schedule`, `admin/tools`.
- Reconciliation evidence:
  - result of `scripts/reconcile_ledger_convergence.sql` (or equivalent query output).
- Pain-point log:
  - top 5 current defects with concrete examples (IDs/date ranges).

## 5) Suggested Definition of Done for vNext
- Architecture consistency:
  - all new endpoints/services follow one canonical location (`finance_app/*` target layout).
- Ledger reliability:
  - journal is verified source-of-truth for reporting paths; compatibility layer is explicit and tested.
- Reconciliation safety:
  - automated checks for balance parity and duplicate counting pass in CI and pre-release.
- Money schedule trust:
  - baseline account mapping and recompute behavior are deterministic and test-covered.
- Security baseline:
  - CSRF/user-scope/admin checks verified on all mutating/account-sensitive endpoints.
- Observability:
  - endpoint error/latency metrics and job status visibility available for core workflows.
- Data migration readiness:
  - Alembic head clean; backfills idempotent; rollback path documented.
- Quality gates:
  - smoke + targeted domain tests pass (transactions/journal, TB, receivables/loans, money schedule, ML fallback).
- Documentation:
  - endpoint inventory, architecture, and operator runbook updated to match runtime.
