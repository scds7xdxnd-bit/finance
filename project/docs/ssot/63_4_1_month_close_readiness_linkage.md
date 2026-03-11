# Phase 2.8.1 Month Close Readiness Next-Action Linkage Hardening Contract (Advisory, No New Endpoints)
_Last updated: 2026-03-11_

## 63.4.1.1 Scope
- Tightens SSOT 63_4 readiness next-action linkage so each action key deterministically maps to existing navigation-only controls.
- Linkage is reuse-only and advisory-only.
- No blocking close behavior is introduced.

## 63.4.1.2 Non-Goals
- No new endpoints.
- No new `window.FINANCE_ENDPOINTS` keys.
- No JSON contract expansion.
- No new gate/check family.
- No snapshot immutability requirement.

## 63.4.1.3 Locked Decisions
- Readiness next-action linkage must reuse existing selectors from SSOT 63_3 and snapshot controls from SSOT 60/Phase 2.1.
- Mapping is navigation-only; no async API behavior is introduced.
- Enabled/disabled semantics are deterministic and machine-checkable.
- Link surfaces must preserve active `ym`.

## 63.4.1.4 Deterministic Linkage Mapping Rules
For `[data-role="mc-readiness-next-action"]` `data-action-key`:

1) `open_journal_drafts`:
- MUST map to `[data-action="mc-open-journal-drafts"]`.

2) `open_statements`:
- MUST map to `[data-action="mc-open-statements"]`.

3) `open_documents`:
- MUST map to `[data-action="mc-open-documents-panel"]` IF that selector exists.
- If selector is absent: `data-enabled="false"` and readiness link is omitted.

4) `retry_refresh`:
- MUST map to navigation reload of `/accounting/month_close?ym=...` for active month context.
- No new endpoint is allowed.

5) `create_snapshot`:
- MUST map to existing `[data-action="mc-create-snapshot"]` IF present.
- If snapshot create control is absent: `data-enabled="false"` and readiness link is omitted.

## 63.4.1.5 Enabled Semantics (Deterministic)
- `data-enabled="true"` only when a valid existing mapping target/control exists for current `data-action-key`.
- `data-enabled="false"` when mapping target/control is absent.
- Enabled semantics must not be inferred from speculative/future routes.

## 63.4.1.6 Link Surface Contract
- `[data-role="mc-readiness-next-action-link"]` is REQUIRED when:
  - `data-enabled="true"`, and
  - mapping target is a linkable navigation URL.
- If `data-enabled="false"`, readiness link MUST be absent.
- Empty/placeholder `href` is forbidden.

`create_snapshot` special handling:
- If snapshot action is represented as an in-page POST form/control (non-link), readiness may remain `data-enabled="true"` with no readiness link element, but must reference the existing in-page snapshot control deterministically.
- If neither linkable URL nor in-page snapshot control exists, `data-enabled="false"` is required.

## 63.4.1.7 `ym` Preservation Rules
- Whenever readiness next-action link exists, URL MUST include active `ym`.
- Link `ym` MUST match visible active month-close context.
- For navigation targets that carry pagination context, preserve `page` and `per_page` where applicable.

## 63.4.1.8 Minimal QA Evidence (Contract Shape Only)
- QA extends `tests/test_frontend_contracts.py` only.
- Required checks:
  1) `open_journal_drafts` readiness key:
     - readiness link URL equals or includes URL from `[data-action="mc-open-journal-drafts"]`.
  2) `open_statements` readiness key:
     - readiness link URL equals URL from `[data-action="mc-open-statements"]`.
  3) `retry_refresh` readiness key:
     - readiness link URL includes `/accounting/month_close` and active `ym`.
  4) `create_snapshot` readiness key:
     - if snapshot form/control exists, readiness `data-enabled="true"` is allowed with no link only when explicitly bound to in-page snapshot action.
     - otherwise readiness must be `data-enabled="false"`.
- Required failure prefix:
  - `Month close readiness linkage contract failed:`

## 63.4.1.9 Ownership
- Architect owns this SSOT file.
- Backend owns deterministic readiness linkage metadata in month-close context.
- Frontend owns deterministic selector/link rendering and enabled semantics.
- QA owns contract-shape verification.
- DevOps keeps merge-blocking coverage under existing checks.

## 63.4.1.10 Safety and Compatibility Dependencies
- Must remain compatible with SSOT 55/57/60/63/63_1/63_2/63_3/63_4.
- Must not weaken startup/security/DB-integrity gates (SSOT 80.12/80.13/80.14).

## 63.4.1.11 Phase 2.10.1 Companion (Open-Documents Deep-Link Lock)
- Phase 2.10.1 locks `open_documents` mapping target to Month Close selector `[data-action="mc-open-documents-panel"]` with `/accounting?ym=...` deep-link behavior.
- If documents-panel action selector is absent, existing fallback remains: readiness `open_documents` must be `data-enabled="false"` and link omitted.
