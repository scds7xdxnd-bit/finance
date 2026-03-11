# Phase 2.6 Month Close Coverage + Unbalanced Drafts State Derivation Contract
_Last updated: 2026-03-11_

## 63.2.1 Scope
- Defines deterministic derivation rules for Month Close checklist states:
  - `[data-role="mc-coverage"]`
  - `[data-role="mc-unbalanced-drafts"]`
- Phase 2.6 remains advisory-only: no blocking “close month” enforcement is introduced here.
- Reuse-only posture: derive from existing data sources/endpoints/services; no new endpoint or registry-key requirement.

## 63.2.2 Non-Goals
- No new endpoints.
- No new endpoint-registry keys.
- No JSON contract expansion.
- No DB schema/index/migration requirements in this phase.
- No weakening of SSOT 55/57/60/61/62/63/63_1 or safety gates.

## 63.2.3 Locked Decisions
- Month Close checklist state is computed for selected `ym` using existing sources only.
- `fail` state is permitted in Phase 2.6 only for explicit invariant breaches defined below.
- State computation must be deterministic and safe-fail (unknown) under capability/startup/schema-not-ready conditions.

## 63.2.4 Deterministic Inputs (Reuse-Only)

### 63.2.4.1 Coverage Inputs
Coverage posture is derived from existing reporting primitives already used by the app:
- Trial Balance monthly surface (existing):
  - `GET /accounting/tb/monthly?ym=YYYY-MM` (JSON)
- Statement surface (existing):
  - `GET /accounting/statement/data?ym=YYYY-MM` (JSON)

If either surface cannot be computed due to schema/capability/startup not-ready, coverage state is `unknown`.

### 63.2.4.2 Unbalanced Draft Inputs
Unbalanced drafts posture is derived from existing journal sources:
- Existing journal list surface:
  - `GET /accounting/journal/list` (JSON)
- Draft definition is stable:
  - `posted_at IS NULL` indicates draft entry.
- Unbalanced definition is stable:
  - Draft entry where SUM(D.amount_base) != SUM(C.amount_base) for its lines.

No new “drafts count” endpoint is allowed in Phase 2.6.

## 63.2.5 Deterministic State Derivation Rules

### 63.2.5.1 Coverage State (`mc-coverage`)
Define `coverage_ok` as:
- TB monthly request succeeded and returned `ok=true` for selected `ym`, AND
- Statement data request succeeded and returned `ok=true` for selected `ym`.

State for `[data-role="mc-coverage"]`:
1. `unknown` when either TB or statement cannot be computed safely due to schema/capability/startup not-ready, or safely handled fetch/query error.
2. `ok` when `coverage_ok` is true.
3. `warn` when both are computable but one returns `ok=false` (non-fatal) or coverage metadata indicates partial coverage.
4. `fail` is reserved and not used for coverage in Phase 2.6 (future invariants may define fail).

### 63.2.5.2 Unbalanced Drafts State (`mc-unbalanced-drafts`)
Define:
- `draft_count`: number of draft entries for selected `ym`.
- `unbalanced_draft_count`: number of drafts for selected `ym` that are unbalanced.

State for `[data-role="mc-unbalanced-drafts"]`:
1. `unknown` when count cannot be computed safely due to schema/capability/startup not-ready, or safely handled query error.
2. `ok` when `unbalanced_draft_count == 0`.
3. `warn` when `unbalanced_draft_count > 0`.
4. `fail` is intentionally unused in Phase 2.6.

## 63.2.6 Additive UI Selector Contract (Machine-Checkable)

### 63.2.6.1 Coverage Slots
Within Month Close checklist:
- `[data-role="mc-coverage"]` (already exists) with `data-state="ok|warn|fail|unknown"`
- Add required slots:
  - `[data-role="mc-coverage-source"]` (text: `tb+statement` or `unknown`)
  - `[data-role="mc-coverage-note"]` (optional text; empty allowed)

### 63.2.6.2 Unbalanced Draft Slots
Within Month Close checklist:
- `[data-role="mc-unbalanced-drafts"]` (already exists) with `data-state="ok|warn|fail|unknown"`
- Add required slots:
  - `[data-role="mc-drafts-count"]`
  - `[data-role="mc-unbalanced-drafts-count"]`

Optional navigation helper actions (allowed, not required):
- `[data-action="mc-open-journal-drafts"]` (navigation-only)
- `[data-action="mc-open-statements"]` (navigation-only)
- `[data-action="mc-open-tb"]` (navigation-only)

## 63.2.7 Round-Trip Rules
- Month Close context remains canonical:
  - `/accounting/month_close?ym=YYYY-MM`
- Any links/actions emitted in Month Close must preserve `ym` when applicable.
- Optional navigation actions must remain URL/navigation-only and must not introduce new API behavior.

## 63.2.8 Minimal QA Evidence (Contract Shape Only)
- QA extends `tests/test_frontend_contracts.py` only.
- Required failure prefix:
  - `Month close coverage contract failed:`

Required assertions:
1. Month Close HTML includes required selectors:
- `[data-role="mc-coverage-source"]`
- `[data-role="mc-coverage-note"]`
- `[data-role="mc-drafts-count"]`
- `[data-role="mc-unbalanced-drafts-count"]`

2. Deterministic seeded scenarios:
- Unbalanced drafts WARN scenario: unbalanced_draft_count > 0 => `mc-unbalanced-drafts` data-state == "warn"
- Unbalanced drafts OK scenario: unbalanced_draft_count == 0 => data-state == "ok"

Coverage scenario tests are contract-shape only:
- If TB/statement are available in fixture, assert `mc-coverage` is not `unknown`.
- If schema-not-ready is simulated, assert `mc-coverage` is `unknown`.

## 63.2.9 Ownership
- Architect owns SSOT definitions in this file.
- Backend owns deterministic count/state derivation using existing sources only.
- Frontend owns selector rendering and optional navigation links (no new API).
- QA owns contract-shape verification.
- DevOps keeps merge-blocking coverage under existing required checks.

## 63.2.10 Safety and Compatibility Dependencies
Must not weaken:
- SSOT 55 frontend contract lock
- SSOT 57 URL round-trip behavior
- SSOT 60 month-close foundation
- SSOT 61/62 documents contracts and proof posture
- SSOT 63 / SSOT 63_1 month-close documents integration/state
- startup/migration, security, and DB integrity gates (SSOT 80.12/80.13/80.14)

## 63.2.11 Phase 2.8 Companion (Readiness Roll-up)
- Phase 2.8 readiness summary consumes coverage and unbalanced-drafts states/counts as inputs.
- No change to 63_2 derivation rules is introduced by Phase 2.8.
