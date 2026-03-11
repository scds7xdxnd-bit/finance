# Phase 2.10.1 Month Close Documents Deep-Link Lock + Target Hydration Contract
_Last updated: 2026-03-11_

## 63.6.1 Scope
- Locks Month Close documents resolution deep-link behavior and target-page hydration behavior.
- Applies to:
  - Month Close action selector `[data-action="mc-open-documents-panel"]`
  - Accounting target page loaded with `/accounting?ym=YYYY-MM`
- This phase is navigation-only contract hardening with no new endpoint or registry-key requirement.

## 63.6.2 Non-Goals
- No new endpoints.
- No new `window.FINANCE_ENDPOINTS` keys.
- No JSON contract expansion.
- No new gate family.
- No change to existing documents PDF endpoint surfaces (SSOT 61).

## 63.6.3 Locked Decisions
- `mc-open-documents-panel` MUST deep-link to `/accounting` with `ym` preserved.
- Self-linking Month Close to `/accounting/month_close` for documents resolution is forbidden.
- Target hydration is deterministic:
  - when `/accounting` loads with valid `ym`, first-load entry context is documents/receivables-payables surface.
  - unrelated localStorage view restores must not override this first-load `ym` entry context.
- Behavior remains navigation-only; no new API surfaces are introduced.

## 63.6.4 Deep-Link Contract
For `[data-action="mc-open-documents-panel"]` URL:
- Path MUST be `/accounting`.
- Query MUST include `ym=YYYY-MM`.
- URL MUST NOT target `/accounting/month_close`.
- If `page`/`per_page` are preserved for list contexts, they are additive only and must not remove `ym`.

## 63.6.5 Target-Page Hydration Contract (`/accounting?ym=YYYY-MM`)
When accounting page loads with valid `ym`:
- Initial visible context MUST be documents/receivables-payables surface.
- Documents selector controls MUST hydrate from `ym`.
- Documents PDF URL builders MUST include the active selector `ym`.
- Hydration remains navigation-only; no fetch endpoint additions are required by this contract.

## 63.6.6 Readiness Linkage Consistency
- If readiness next-action key is `open_documents` with `data-enabled="true"`:
  - readiness next-action link URL MUST equal the URL from `[data-action="mc-open-documents-panel"]`.
- If documents panel action selector is absent:
  - readiness `open_documents` MUST be `data-enabled="false"`.
  - readiness next-action link MUST be omitted.

## 63.6.7 Machine-Checkable Selector Surface

### 63.6.7.1 Month Close Source Page
- Required:
  - `[data-action="mc-open-documents-panel"]`

### 63.6.7.2 Accounting Target Page
- Required:
  - `#documents-panel`
  - `[data-role="docs-selectors"]`
  - `[data-role="docs-error"]`
- Optional clarity marker (recommended):
  - `[data-role="docs-entry-context"]` with `data-ym="YYYY-MM"`

## 63.6.8 QA Evidence (Contract Shape Only)
- QA extends `tests/test_frontend_contracts.py` only.
- Required failure prefix:
  - `Month close resolution contract failed:`
- Required assertions:
  1. `mc-open-documents-panel` URL path is `/accounting` and includes `ym`.
  2. Self-link to `/accounting/month_close` is forbidden.
  3. When readiness action-key is `open_documents` and enabled, readiness link URL equals documents-panel action URL.
  4. Target accounting page loaded with `ym` includes required documents selector surface (`#documents-panel`, docs selectors/error).

## 63.6.9 Ownership
- Architect owns SSOT definitions in this file.
- Backend owns Month Close URL emission and `ym` propagation in render context.
- Frontend owns target-page hydration and deterministic entry-context behavior.
- QA owns contract-shape verification.
- DevOps keeps merge-blocking coverage in existing required checks.

## 63.6.10 Safety and Compatibility Dependencies
- Must remain compatible with SSOT 55/57/60/61/62/63/63_3/63_4/63_4_1.
- Must not weaken startup/security/DB-integrity gates (SSOT 80.12/80.13/80.14).
