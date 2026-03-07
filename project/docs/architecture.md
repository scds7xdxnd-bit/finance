# Finance App Architecture Constitution
_Last updated: 2025-12-24_

## Purpose & Scope
Finance App is a Flask-based bookkeeping system centered on a single user tenant. This document is the normative source for boundaries, foldering, events, naming, and migration strategy. Controllers stay thin; services own business rules; models own persistence.

## Architectural Principles
- Controllers and blueprints validate/authz and delegate to services.
- Services hold business rules and orchestration; models are persistence-only.
- Every domain table is user-scoped unless explicitly global (e.g., settings).
- Cross-boundary changes require explicit interfaces or events; no ad-hoc imports.

## Domain Boundaries (authoritative list)
- Core Platform: app factory, config, extensions, auth/session, CSRF, rate limiting, CLI.
- Identity & Admin: user, profile, admin dashboard, access control.
- Accounting Core: chart of accounts, categories, account codes, opening balances, monthly balances.
- Transactions (legacy single-entry) and Imports: transactions table, CSV import, filters.
- Journal & Posting (double-entry): journal entries/lines, posting, transaction links.
- Trial Balance & Period Close: trial balance settings, opening balances, month rollups.
- Money Schedule (cash forecast): schedule rows, recurring events, scenarios, baseline accounts, snapshots.
- Receivables & Loans: receivable trackers, manual entries, loan groups, allocations.
- ML Suggestions: hint logs, feedback, model gateway, per-user models.
- Reporting & Documents: PDF statements, trial balance exports.

## Layering & Folder Map
### Current (tolerated)
- App package root: `finance_app/`
  - App factory/config: `finance_app/__init__.py`
  - Extensions: `finance_app/extensions.py` (root `extensions.py` is a compatibility shim)
  - Controllers/registration: `finance_app/controllers/` (register_blueprints + `core.py` routes)
  - Blueprints (HTTP handlers): `blueprints/`
  - Legacy route module: `routes/` (legacy only; no new endpoints)
  - Services: `finance_app/services/`
  - Models: `finance_app/models/`
  - Shared helpers: `finance_app/lib/`
  - CLI commands: `finance_app/cli/`
  - Domain placeholder: `finance_app/domain/` (unused)
- Templates: `templates/` (Jinja)
- Static: `static/`
- Migrations: `alembic/` + `alembic.ini`
- Scripts: `scripts/` (backfills, seeders, ad-hoc data fixes)
- Instance data: `instance/` (db, uploads, backups, per-user ML models)
- ML/training assets: `ml/`, `ml-suggester-repo/`, `ml_journal_suggester/`

### Target (post-refactor, mandatory for new work)
- App package root: `finance_app/`
  - App factory/config: `finance_app/__init__.py`
  - Extensions: `finance_app/extensions.py` only (remove root shim after Phase 1)
  - Controllers/registration: `finance_app/controllers/` (registration only)
  - Blueprints (HTTP handlers): `finance_app/blueprints/` (single source of truth)
  - Domains: `finance_app/domains/<domain>/{blueprints,services,models,schemas,tasks}`
  - Shared helpers: `finance_app/lib/`
  - CLI commands: `finance_app/cli/`
  - Platform adapters: `finance_app/platform/{clients,bus,outbox,worker}` when introduced
- Templates: `templates/` (Jinja)
- Static: `static/`
- Migrations: `alembic/` + `alembic.ini`
- Scripts: `scripts/`
- Instance data: `instance/`
- ML/runtime assets: `finance_app/ml/` or external repo; no training artifacts in runtime root

## Dependency Rules
- Blueprints/controllers -> services -> models; controllers never access models directly.
- Services may call other services but only across defined boundaries with explicit interfaces.
- Models stay persistence-only; no cross-domain business logic.
- ML access only via `finance_app/services/ml_*` gateway/services; controllers do not call ML directly.

## Structural Weaknesses (current state)
- Split routing and packaging across `finance_app/controllers/`, `blueprints/`, and `routes/` blurs ownership and complicates imports.
- Domain boundaries are not encoded in the filesystem; `finance_app/services/` and `finance_app/models/` mix unrelated domains.
- Legacy shims and duplicates (`extensions.py`, `models/`, `finance_app/domain/`) hide the true source of truth for imports.
- Dual accounting systems (legacy `Transaction` vs journal entries/lines) create ambiguous source-of-record semantics.
- Parallel account systems (`account` vs `money_schedule_accounts`) duplicate concepts without an explicit boundary contract.
- ML runtime and training assets live in the repo root, making deployable runtime footprint unclear.

## Refactor Roadmap (phased)
### Phase 0: Alignment and guardrails (no behavior change)
- Freeze new endpoints in `routes/` and `blueprints/`; new work targets the target layout only.
- Inventory services and map each to a domain; document ownership.
- Decide authoritative source-of-record for `Transaction` vs `JournalEntry` and for money schedule accounts.

### Phase 1: Routing and package consolidation
- Move all route modules into `finance_app/blueprints/` and keep `finance_app/controllers/` for registration only.
- Migrate `routes/forecast.py` into the new blueprint package; remove `routes/` usage.
- Remove root `extensions.py` shim once imports are updated.

### Phase 2: Domain modularization
- Create `finance_app/domains/<domain>` and move models/services/blueprints under each domain.
- Introduce per-domain `schemas.py` and `mappers.py` for DTO mapping.
- Update tests to mirror the new domain layout.

### Phase 3: Ledger convergence and schema hygiene
- Make double-entry journal the source of truth; treat legacy `Transaction` as a view/compat layer.
- If consolidating money schedule accounts, add mapping tables and backfill scripts; otherwise document strict boundary.
- Use Alembic for schema changes; backfills live in `scripts/`.

### Phase 4: ML boundary and platformization
- Separate training artifacts into `finance_app/ml/` or an external repo; keep runtime client under `finance_app/platform/clients`.
- Standardize ML contract enforcement via `project/docs/interfaces.md` and events in the catalog.

## Coding Style Standards (target)
- One domain per module tree; avoid cross-domain imports outside service interfaces.
- `*_service.py` files expose orchestration functions; controllers only compose responses.
- DTO validation and mapping live in `schemas.py` and `mappers.py` per domain.
- No global state in route modules beyond configuration constants; use app config for runtime settings.

## ERD (textual summary)
- User 1..N AccountCategory; AccountCategory 1..N Account.
- User 1..N AccountOpeningBalance; Account 1..N AccountOpeningBalance.
- User 1..N Transaction with optional debit_account_id/credit_account_id -> Account.
- User 1..1 TrialBalanceSetting; User 1..N AccountMonthlyBalance (unique by user/account/year/month).
- JournalEntry 1..N JournalLine; JournalLine -> Account.
- ReceivableTracker -> JournalEntry + JournalLine + Account; ReceivableManualEntry -> Account.
- LoanGroup 1..N LoanGroupLink; LoanGroupLink -> JournalLine.
- MoneyScheduleAccount 1..N ScheduledTransaction; MoneyScheduleAccount 1..N AccountSnapshot.
- User 1..N MoneyScheduleRow; User 1..N MoneyScheduleDailyBalance; User 1..N MoneyScheduleRecurringEvent.
- MoneyScheduleScenario 1..N MoneyScheduleScenarioRow.
- User 1..N AccountSuggestionHint/AccountSuggestionLog/SuggestionFeedback.
- User 1..N RateLimitBucket; User 1..1 UserProfile; UserProfile 1..N UserPost.

## Event Catalog (name -> payload contract)
Events are logical contracts; if/when an event bus/outbox is introduced under `finance_app/platform`, these are the authoritative names and payloads.

- finance.transaction.created -> {transaction_id, user_id, date, description?, debit_account_id?, credit_account_id?, debit_amount?, credit_amount?}
- finance.transaction.updated -> {transaction_id, user_id, fields:[...], updated_at}
- finance.transaction.deleted -> {transaction_id, user_id, deleted_at}
- finance.journal.posted -> {entry_id, user_id, debit_total, credit_total, line_count, posted_at}
- finance.trial_balance.initialized -> {user_id, initialized_on, first_month}
- finance.trial_balance.opening_balance.updated -> {user_id, account_id, amount, as_of_date}
- finance.money_schedule.row.updated -> {row_id, user_id, date, inflow, outflow, is_auto_generated}
- finance.money_schedule.recomputed -> {user_id, start_date, end_date}
- finance.receivable.created -> {tracker_id, user_id, account_id, category, transaction_value, due_date?}
- finance.receivable.payment.recorded -> {tracker_id, user_id, amount, payment_date}
- finance.loan_group.created -> {loan_group_id, user_id, direction, principal_amount, start_date}
- finance.loan_group.linked -> {loan_group_id, user_id, journal_line_id, linked_amount}
- ml.suggestion.requested -> {user_id, request_id, line_type, currency, description?}
- ml.suggestion.responded -> {user_id, request_id, model_version?, latency_ms, status}

## Data Model Inventory (current tables)
- Core/Identity: user, user_profile, user_post, login_session, rate_limit_bucket.
- Accounting: account_category, account, account_opening_balance, account_monthly_balance, trial_balance_setting, transaction.
- Journal: journal_entry, journal_line.
- Receivables/Loans: receivable_tracker, receivable_manual_entry, loan_group, loan_group_link.
- Money Schedule: money_schedule_accounts, money_schedule_transactions, money_schedule_rows, money_schedule_asset_includes, money_schedule_daily_balances, account_snapshots, money_schedule_recurring_events, money_schedule_scenarios, money_schedule_scenario_rows, settings.
- ML/Feedback: account_suggestion_hint, account_suggestion_log, suggestion_feedback.

## Integration Points
- ML suggestions: HTTP JSON to `MLSUGGESTER_API_URL` using `project/docs/interfaces.md`; fallback to local joblib models when disabled/unavailable.
- File I/O: CSV import/export; PDFs generated by `statements_pdf.py` and `trial_balance_pdf.py`; uploads stored under `instance/uploads`.
- Data exports and reports flow through services; controllers never query models directly.

## CIE Design (Change Impact & Evolution)
CIE = Change Impact & Evolution. Any change that touches a contract surface requires a CIE review.
Contract surfaces: DB schema, HTTP routes, ML request/response contracts, event catalog, file formats (CSV/PDF).
CIE workflow: design note -> update this architecture doc -> update `project/docs/decisions.md` if a decision changes -> implementation -> tests -> rollout note.

## Schema Evolution & Migrations
- Single Alembic home at `alembic/`; use `alembic.ini` for DB URL overrides.
- Naming: `<timestamp>_finance_<short_action>.py` (example `20251224_finance_add_receivable_indexes.py`).
- Default additive; destructive changes require two-phase (shadow + backfill + swap).
- Backfills belong in `scripts/` or CLI commands, never long-running Alembic steps.
- Indexes: always include `user_id` plus primary query dimension (date, account_id, status, etc.).

## Background Jobs & Scripts
- Long-running or repeatable jobs live in `scripts/` or `finance_app/cli`; they call services only.
- In-process background threads are allowed only for small maintenance tasks; heavy jobs should move to a worker when introduced.

## Security & Auth
- Session-based auth with CSRF protection; admin access gated by `is_admin`.
- Rate limits enforced via `rate_limit_bucket` for ML endpoints and other high-volume routes.
- Sensitive files stored under `instance/` with max upload size enforced by config.

## Testing
- Mirror module structure under `tests/`.
- Required coverage: services, money schedule workflows, migrations, ML fallback behavior.
