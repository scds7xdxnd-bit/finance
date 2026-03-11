# Phase 2.8 Month Close Readiness Summary Contract (Advisory, No New Endpoints)
_Last updated: 2026-03-11_

## 63.4.1 Scope
- Defines an advisory "Close Readiness" summary for Month Close page for a selected `ym=YYYY-MM`.
- Summary is derived from existing Month Close checklist item states and counts:
  - coverage (SSOT 63_2)
  - unbalanced drafts (SSOT 63_2)
  - documents state + open/total counts (SSOT 63_1)
  - snapshot section presence/status (SSOT 60/Phase 2.1)
- This phase adds a stable DOM selector surface and deterministic derivation rules.
- No blocking posture is introduced; Month Close remains advisory.

## 63.4.2 Non-Goals
- No new endpoints.
- No new `window.FINANCE_ENDPOINTS` keys.
- No JSON contract expansion.
- No new gating/check family; readiness summary is not a release gate.
- No snapshot immutability requirement.
- No schema/index/migration work.

## 63.4.3 Locked Decisions
- Readiness summary is derived from Month Close page context only.
- Derivation must not depend on a new “summary API” or a new “details endpoint”.
- Summary must be deterministic for the same `ym` and same underlying derived states/counts.
- Summary must not override existing checklist states; it is a roll-up and guidance surface only.

## 63.4.4 Inputs (Reuse-Only)
Inputs are the already-derived Month Close checklist values:
- Coverage:
  - `mc-coverage` state in `{ok,warn,unknown}` (SSOT 63_2)
  - `mc-coverage-source` text (SSOT 63_2)
  - `mc-coverage-note` text (SSOT 63_2)
- Drafts:
  - `mc-unbalanced-drafts` state in `{ok,warn,unknown}` (SSOT 63_2)
  - `mc-drafts-count` integer text (SSOT 63_2)
  - `mc-unbalanced-drafts-count` integer text (SSOT 63_2)
- Documents:
  - `mc-documents` state in `{ok,warn,unknown}` (SSOT 63_1)
  - `mc-documents-open-count` integer text (SSOT 63_1)
  - `mc-documents-total-count` integer text (SSOT 63_1)
- Snapshot:
  - snapshot section selector surface from Phase 2.1 (`mc-snapshot`, `mc-snapshot-status`)
  - snapshot list presence is advisory signal only; it does not gate readiness.

No new raw data sources are introduced by SSOT 63_4.

## 63.4.5 Deterministic Readiness Derivation Rules

Define a roll-up state `mc-readiness` with enum:
- `ready`
- `attention`
- `unknown`

Rules (in precedence order):
1) `unknown` if ANY of the following are `unknown`:
   - `mc-coverage` is `unknown`
   - `mc-unbalanced-drafts` is `unknown`
   - `mc-documents` is `unknown`
2) `attention` if ANY of the following are true:
   - `mc-coverage` is `warn`
   - `mc-unbalanced-drafts` is `warn`
   - `mc-documents` is `warn`
3) `ready` only when all are computable and none are warn:
   - `mc-coverage` == `ok`
   - `mc-unbalanced-drafts` == `ok`
   - `mc-documents` == `ok`

Reserved:
- No `fail` state for readiness in Phase 2.8. Any future `fail` semantics must be introduced in a separate SSOT.

## 63.4.6 Deterministic Primary Message + Next Action Derivation

### 63.4.6.1 Primary Message (`mc-readiness-message`)
Message must be deterministic based on `mc-readiness`:
- `ready`: "Ready to close month (advisory)."
- `attention`: "Needs attention before closing (advisory)."
- `unknown`: "Readiness unknown (insufficient data)."

### 63.4.6.2 Primary Next Action (`mc-readiness-next-action`)
Derived from the highest-priority actionable non-ok signal:

Priority order:
1) If `mc-unbalanced-drafts` == `warn`:
   - next action key: `open_journal_drafts`
   - must map to existing resolution action selector `mc-open-journal-drafts` (SSOT 63_3)
2) Else if `mc-documents` == `warn`:
   - next action key: `open_documents`
   - must map to optional resolution selector `mc-open-documents-panel` when implemented (SSOT 63_3)
   - if not implemented, next action remains present but uses a neutral label and no click target
3) Else if `mc-coverage` == `warn`:
   - next action key: `open_statements`
   - must map to existing resolution selector `mc-open-statements` (SSOT 63_3)
4) Else if `mc-readiness` == `unknown`:
   - next action key: `retry_refresh`
   - optional navigation-only behavior; no new endpoint required
5) Else (ready):
   - next action key: `create_snapshot`
   - must map to existing snapshot create action when present (`mc-create-snapshot`) and remain advisory.

The “next action” is guidance only; it must not introduce blocking behavior.

## 63.4.7 Required DOM/Selector Contract (Machine-Checkable)

Under `#month-close-page` the following selectors must exist:

### 63.4.7.1 Readiness Summary Root
- `[data-role="mc-readiness"]` with attribute:
  - `data-state="ready|attention|unknown"`

### 63.4.7.2 Summary Fields
- `[data-role="mc-readiness-message"]` (text)
- `[data-role="mc-readiness-next-action"]` with attributes:
  - `data-action-key="open_journal_drafts|open_documents|open_statements|retry_refresh|create_snapshot"`
  - `data-enabled="true|false"`

### 63.4.7.3 Optional linkage markers (do not add new endpoints)
- `[data-role="mc-readiness-next-action-link"]` (optional):
  - when present, must link to an existing navigation target only.
  - must preserve `ym` context.

## 63.4.8 URL and Round-Trip Rules
- Month Close canonical context remains:
  - `/accounting/month_close?ym=YYYY-MM`
- If `mc-readiness-next-action-link` exists, its URL must include the active `ym`.
- No new query params are required by this phase.

## 63.4.9 Minimal QA Evidence (Contract Shape Only)
- QA extends `tests/test_frontend_contracts.py` only.
- Required assertions for `/accounting/month_close?ym=YYYY-MM`:
  1) Selector presence:
     - `[data-role="mc-readiness"]`
     - `[data-role="mc-readiness-message"]`
     - `[data-role="mc-readiness-next-action"]`
  2) Enum checks:
     - `mc-readiness` `data-state` is in `{ready,attention,unknown}`
     - `mc-readiness-next-action` `data-action-key` is in allowed set
     - `data-enabled` is `true|false`
  3) Deterministic outcome in seeded scenarios:
     - scenario A: drafts warn => readiness `attention`, next action key `open_journal_drafts`
     - scenario B: all ok => readiness `ready`, next action key `create_snapshot` (or `none` is forbidden; must be present)
     - scenario C: any unknown => readiness `unknown`, next action key `retry_refresh`
- Required failure prefix:
  - `Month close readiness contract failed:`

## 63.4.10 Ownership
- Architect owns this SSOT file.
- Backend owns readiness derivation values emitted into server-rendered month-close context.
- Frontend owns selector rendering and non-blocking interaction (navigation-only where applicable).
- QA owns contract-shape checks in `tests/test_frontend_contracts.py`.
- DevOps keeps merge-blocking coverage under existing required checks.

## 63.4.11 Safety and Compatibility Dependencies
Must remain compatible with:
- SSOT 55 frontend contract lock
- SSOT 57 URL round-trip behavior
- SSOT 60 month-close foundation
- SSOT 63/63_1/63_2/63_3 month-close integration/state/resolution contracts
- SSOT 61/62 documents contracts/proof posture
Must not weaken startup/security/DB-integrity gates (SSOT 80.12/80.13/80.14).

## 63.4.12 Phase 2.8.1 Companion (Next-Action Linkage Hardening)
- Phase 2.8.1 deterministic next-action linkage/enabled semantics are defined in `SSOT 63_4_1_month_close_readiness_linkage`.
- No change to readiness roll-up state derivation or primary message rules is introduced by Phase 2.8.1.
