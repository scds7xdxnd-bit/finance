# Cross-Team Architecture Brief + Execution Plan (Phase 0)
_Last updated: 2025-12-24_

## A) Problem Statement + Success Criteria
### Problem statement (root causes)
- Routing lives in three places (`finance_app/controllers/`, `blueprints/`, `routes/`), which obscures ownership and increases import inconsistencies.
- Domain boundaries are not encoded in the filesystem; `finance_app/services/` and `finance_app/models/` mix domains.
- Legacy shims and duplicate modules (root `extensions.py`, duplicate `models/`, unused `finance_app/domain/`) obscure the source of truth.
- Two ledger systems compete (`Transaction` vs `JournalEntry`/`JournalLine`), creating ambiguous source-of-record semantics.
- Two account systems compete (`account` vs `money_schedule_accounts`) without an explicit boundary contract.
- ML runtime and training artifacts live in repo root (`ml/`, `ml-suggester-repo/`, joblib files), blurring deployable footprint.

### Success criteria (definition of done per phase)
- Phase 0: No new endpoints in legacy locations; service-to-domain ownership map published; explicit decisions recorded for ledger source-of-record and money schedule account strategy; guardrails in CI.
- Phase 1: All endpoints live under `finance_app/blueprints/`; `routes/` unused; `finance_app/controllers/` only registers blueprints; no endpoint path changes.
- Phase 2: `finance_app/domains/<domain>/{blueprints,services,models,schemas,tasks}` exists; tests mirror domain layout; import rules enforced.
- Phase 3: Journal is source of truth; `Transaction` is compatibility-only; money schedule account strategy implemented with migration/backfill where required; reconciliation checks pass.
- Phase 4: ML training artifacts separated from runtime footprint; ML client under `finance_app/platform/clients`; contract tests for `project/docs/interfaces.md` pass.

### Non-goals (Phase 0)
- No runtime behavior changes.
- No endpoint path changes.
- No database migrations.
- No domain moves of code.

### Guardrails (non-negotiables)
- Controllers/blueprints validate/authz and delegate to services only.
- Services own business rules; models are persistence-only.
- Every domain table is user-scoped unless explicitly global.
- Cross-boundary changes require explicit interfaces or events.
- ML access only via gateway service; controllers never call ML directly.

## B) Target Architecture and Folder Map
### Canonical layout (post-refactor)
- `finance_app/`
  - `__init__.py` (app factory)
  - `extensions.py` (only location; remove root shim after Phase 1)
  - `controllers/` (registration only)
  - `blueprints/` (single source of truth for HTTP handlers)
  - `domains/<domain>/{blueprints,services,models,schemas,tasks}`
  - `lib/` (shared helpers)
  - `cli/` (CLI entrypoints)
  - `platform/{clients,bus,outbox,worker}` (future infra)
- `templates/`, `static/`, `alembic/`, `alembic.ini`, `scripts/`, `instance/`

### Layering rules
- blueprint/controller -> service -> model only.
- services may call other services only through explicit interfaces.
- models import only SQLAlchemy and simple utilities.
- ML access only via services under `finance_app/services/` or `finance_app/platform/clients`.

### Allowed imports (examples)
- `finance_app/blueprints/transactions.py` -> `finance_app/services/transaction_service.py`
- `finance_app/services/transaction_service.py` -> `finance_app/models/accounting_models.py`
- `finance_app/services/ml_gateway_service.py` -> `finance_app/platform/clients/ml_client.py` (future)

### Forbidden patterns (examples)
- `finance_app/blueprints/...` importing `finance_app/models/...`
- `finance_app/models/...` importing `finance_app/services/...`
- cross-domain imports that bypass service interfaces
- controllers calling ML clients directly

## C) Phase Plan With PR Slices
### Phase 0: Alignment and guardrails (no behavior change)
**Objective**
- Prevent further drift and establish ownership/decisions.

**What must not change**
- No endpoint behavior or paths change.
- No data migrations or schema changes.

**Work items mapped to weaknesses**
- Weakness 1 (split routing): add CI guardrail to block new files in `routes/` and root `blueprints/`.
- Weakness 2 (domain mix): create service-to-domain ownership inventory.
- Weakness 3 (legacy shims/duplicates): record source-of-truth decision and deprecation plan for shims.
- Weakness 4 (dual ledger): explicit source-of-record decision and compat strategy.
- Weakness 5 (parallel accounts): explicit boundary decision and mapping plan.
- Weakness 6 (ML assets in root): decide runtime footprint and training artifact location.

**PR slices**
- PR0.1: Add CI guardrails (no new files under `routes/`; new endpoints must live under `finance_app/blueprints/`).
- PR0.2: Add `project/docs/service_domain_inventory.md` with ownership map.
- PR0.3: Add `project/docs/endpoint_inventory.md` with routes, owners, and consumers.
- PR0.4: Record decisions in `project/docs/decisions.md` for ledger source-of-record, money schedule account strategy, ML assets location.

**Acceptance criteria**
- CI fails if new files appear under `routes/`.
- Ownership inventory exists for all services under `finance_app/services/`.
- Endpoint inventory exists and is reviewed by Backend + Frontend.
- Decision records approved and referenced in architecture doc.

**Risk + rollback**
- Risk: guardrails block urgent patches; rollback by temporarily exempting a hotfix with explicit approval.

**Docs updates**
- `project/docs/architecture.md`
- `project/docs/decisions.md`
- `project/docs/service_domain_inventory.md`
- `project/docs/endpoint_inventory.md`

### Phase 1: Routing and package consolidation
**Objective**
- Single source of truth for endpoints under `finance_app/blueprints/`.

**Must not change**
- Endpoint paths and behavior.

**PR slices**
- Move `routes/forecast.py` into `finance_app/blueprints/`.
- Move root `blueprints/` modules into `finance_app/blueprints/`.
- Update `finance_app/controllers/` to register only from `finance_app/blueprints/`.
- Remove root `extensions.py` shim after import updates.

**Acceptance criteria**
- `routes/` unused by app registration.
- Endpoints unchanged and verified by endpoint inventory.

**Risk + rollback**
- Risk: missing blueprint registration; rollback by restoring previous registration module.

**Docs updates**
- `project/docs/architecture.md`, endpoint inventory.

### Phase 2: Domain modularization
**Objective**
- Encode domains into filesystem and enforce import boundaries.

**Must not change**
- Runtime behavior and endpoint paths.

**PR slices**
- Create domain folders and move services/models/blueprints into them.
- Add `schemas.py` and `mappers.py` per domain.
- Update tests to mirror `finance_app/domains/<domain>` layout.

**Acceptance criteria**
- Import guardrails pass; tests mirror domain layout.

**Risk + rollback**
- Risk: import cycles; rollback by moving one domain at a time.

**Docs updates**
- `project/docs/architecture.md`, `project/docs/decisions.md` if boundaries change.

### Phase 3: Ledger convergence and schema hygiene
**Objective**
- Journal becomes the source of truth; `Transaction` becomes compat-only.

**Must not change**
- No data loss; compatibility for legacy flows.

**PR slices**
- Add compat adapter for `Transaction` reads/writes.
- Reconcile data between `Transaction` and journal.
- Implement money schedule account decision with mapping or boundary contract.

**Acceptance criteria**
- Journal invariants pass; reconciliation checks green.

**Risk + rollback**
- Risk: data divergence; rollback to dual-write with reconciliation.

**Docs updates**
- Architecture doc, migration notes.

### Phase 4: ML boundary and platformization
**Objective**
- Separate training artifacts and standardize ML client location.

**Must not change**
- External ML contract and endpoints.

**PR slices**
- Move training artifacts out of runtime root.
- Add ML client under `finance_app/platform/clients` and access via gateway service.
- Add contract tests for `project/docs/interfaces.md`.

**Acceptance criteria**
- Runtime footprint excludes training artifacts; contract tests pass.

**Risk + rollback**
- Risk: missing assets in deploy; rollback by restoring asset paths.

**Docs updates**
- `project/docs/architecture.md`, `project/docs/interfaces.md` as needed.

## D) Contract Surfaces & CIE (Change Impact & Evolution)
### Contract surfaces
- DB schema (tables, indexes, constraints)
- HTTP routes and payloads
- ML request/response contracts
- Event catalog
- CSV/PDF formats

### CIE checklist (required for PRs touching contract surfaces)
- Identify contract surface(s) touched
- List affected consumers (backend, frontend, ML, external)
- Backward compatibility strategy
- Docs updated (architecture, interfaces, decisions)
- Tests added/updated
- Rollback plan and deprecation window
- Owner approvals recorded

### Versioning and change announcements
- Version DB changes via Alembic with naming standard.
- Version ML models and event payloads; record schema changes in docs.
- Announce breaking changes with deprecation window and migration notes.

## E) Cross-Team Handoff
### BACKEND (Flask/API)
- Refactors: enforce blueprint -> service -> model; no controller-to-model access.
- Routing consolidation: all endpoints move to `finance_app/blueprints/` and register only there.
- Domain modularization mapping (initial proposal):
  - Accounting Core: `account_service.py`, `exchange_rate_service.py`
  - Transactions & Imports: `transaction_service.py`, `transaction_create_service.py`, `transaction_import_service.py`
  - Journal & Posting: `journal_service.py`
  - Trial Balance: `trial_balance_service.py`
  - Money Schedule: `money_schedule_service.py`, `forecast.py`
  - Receivables & Loans: `receivable_service.py`, `loan_group_service.py`
  - ML Suggestions: `ml_gateway_service.py`, `ml_service.py`, `user_model_service.py`
  - Core Platform: `rate_limit_service.py`
- Interfaces: define cross-domain service calls; events used for asynchronous or decoupled consumers.
- Deliverables: endpoint migration map, import guard rules, domain folder skeletons, ownership map.

### FRONTEND
- Endpoint stability: no path changes during Phase 1; use endpoint inventory to validate.
- Contract testing: schema fixtures for JSON payloads; optional OpenAPI if adopted.
- Deliverables: endpoint inventory review, migration readiness checklist, error handling expectations.

### DB / DATA
- Ledger convergence workflow: journal as source-of-record; define compat layer behavior for `Transaction`.
- Alembic standard: `<timestamp>_finance_<short_action>.py`.
- Two-phase destructive changes: shadow + backfill + swap.
- Index policy: include `user_id` + primary query dimension.
- Deliverables: migration plan, backfill scripts plan, reconciliation queries.

### ML
- Enforce ML access only via gateway service; align with `project/docs/interfaces.md`.
- Separate training artifacts from runtime; define storage boundary.
- Telemetry: include latency/status/version fields in responses/logs.
- Deliverables: ML client adapter spec, contract tests, artifact packaging plan.

### DEVOPS
- Deployment impact: confirm entrypoint (`wsgi.py`) and update import paths post-Phase 1.
- Runtime footprint: define what ships vs what stays out (training artifacts excluded).
- Instance policy: `instance/` holds DB/uploads/per-user models.
- Deliverables: deploy path updates, packaging rules, CI checks.

### QA
- Regression plan for routing changes (Phase 1) and domain modularization (Phase 2).
- Ledger tests: double-entry invariants and reconciliation between compat `Transaction` and journal truth.
- Money schedule boundary tests: ensure semantics unchanged.
- Deliverables: per-phase test plan, golden fixtures, contract tests, smoke checklist.

## F) Decision Points (Explicit Selection Required)
### Source-of-record: Transaction vs JournalEntry (required decision)
- Option A: Journal is source-of-record; `Transaction` is a compat adapter.
  - Pros: aligns with double-entry and auditability.
  - Cons: migration work, compat layer required.
  - Recommendation: choose Option A; `Transaction` becomes read-only or adapter-only with write-through during transition.

### Money schedule account strategy
- Option A: Consolidate into accounting accounts with mapping/backfills.
  - Pros: single account universe.
  - Cons: higher migration risk.
- Option B: Keep separate with strict boundary + explicit mapping contract.
  - Pros: stability, lower risk.
  - Cons: ongoing duplication.
  - Recommendation: choose Option B through Phase 2; revisit consolidation after Phase 3.

### ML assets location
- Option A: Runtime-only assets under `finance_app/ml/`, training external.
- Option B: External training repo; runtime artifacts stored under `instance/` or build artifact store.
  - Recommendation: choose Option B for clear runtime footprint and deployment safety.

## G) Event Catalog and Future Bus/Outbox
### Authoritative event names (service layer only)
- finance.transaction.created
- finance.transaction.updated
- finance.transaction.deleted
- finance.journal.posted
- finance.trial_balance.initialized
- finance.trial_balance.opening_balance.updated
- finance.money_schedule.row.updated
- finance.money_schedule.recomputed
- finance.receivable.created
- finance.receivable.payment.recorded
- finance.loan_group.created
- finance.loan_group.linked
- ml.suggestion.requested
- ml.suggestion.responded

### Emission rule
- Services emit after durable commit; payloads follow `project/docs/architecture.md` contracts.

### Minimal event emission wrapper
- `event_service.emit(name, payload, user_id, occurred_at, source)`
- Implementation logs to an audit table now and can be swapped to outbox later.

## H) Quality Gates (Enforceable)
### CI checks
- Block new files under `routes/`.
- Block new blueprints outside `finance_app/blueprints/`.
- Import-lint: prevent blueprint->model imports and cross-domain imports.
- Ensure tests mirror domain layout once Phase 2 starts.

### PR template checklist
- Contract surface touched? (Y/N)
- CIE checklist completed? (Y/N)
- Docs updated (architecture/decisions/interfaces)? (Y/N)
- Tests added/updated? (Y/N)
- Rollback plan included? (Y/N)
- Owner approvals recorded? (Y/N)
