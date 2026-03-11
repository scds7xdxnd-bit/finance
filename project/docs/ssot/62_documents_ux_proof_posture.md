# Phase 2.4 Documents UX & Proof Posture
_Last updated: 2026-03-11_

## 62.1 Scope
- Applies to documents UX on accounting surfaces (download controls + selectors + receipts).
- Covers selector UX, URL round-trip behavior, validation messaging, download affordances, and receipt proof posture.
- Covers existing document flows for:
  - receivables PDF
  - payables PDF
  - loan receipt PDF
- Explicitly out of scope:
  - no new endpoints
  - no new registry keys
  - no JSON contract expansion
  - no DB schema/migration work

## 62.2 Locked Decisions
- Endpoint surface remains exactly SSOT 61:
  - `GET /accounting/receivables/pdf`
  - `GET /accounting/payables/pdf`
  - `GET /accounting/loan_receipt/pdf`
- Selector UX must be URL-round-trippable (aligned with SSOT 57).
- Minimal row HTML posture remains (no per-row embedded JSON blobs).
- Receipt posture is proof-of-transaction document semantics for personal use; immutability is not required.
- Phase 2.4 requires no new endpoint and no new registry key.

## 62.3 Receivables/Payables PDF UX Contract

### 62.3.1 Required Input Controls
- `ym` (`YYYY-MM`)
- `status` (`open|closed|all`)
- `party` (free text)
- `min_amount`
- `max_amount`

### 62.3.2 Apply/Clear Behavior
- Apply writes selectors to URL deterministically (`replaceState` or equivalent deterministic URL update).
- Clear resets to base state and removes selectors from URL/state.

### 62.3.3 Visible Validation Rules
- Validation failures must be visible in UI (not console-only).
- Invalid `ym` format must be blocked client-side when possible.
- `min_amount`/`max_amount` must pass numeric validation.
- `min_amount > max_amount` must show visible inline error and block navigation.

### 62.3.4 Download Affordances
- Explicit download affordances must exist for:
  - receivables PDF
  - payables PDF
- Download URL must include current selector state (only selectors that are set).

### 62.3.5 Stable DOM Contract (Additive)
- Root: `#documents-panel`
- Selector region: `[data-role="docs-selectors"]`
- Validation/error region: `[data-role="docs-error"]`
- Buttons:
  - `[data-action="download-receivables-pdf"]`
  - `[data-action="download-payables-pdf"]`

## 62.4 Loan Receipt UX Contract
- Receipt generation uses exactly one selector:
  - `entry_id` xor `loan_id`
- UI may prefer `entry_id` where current surface posture already does so.
- Required row-level affordance in relevant tables/views:
  - `[data-action="download-loan-receipt"]`
  - must carry exactly one deterministic id source:
    - `data-entry-id` or
    - `data-loan-id`

### 62.4.1 Proof Fields (Document Content Posture)
The generated receipt should expose these proof fields when available:
- `doc_id` (deterministic)
- `generated_at` timestamp
- payer/payee/counterparty label
- amount/currency
- optional notes (not required in this phase)
- disclaimer line per `62.6`

## 62.5 Download Behavior Contract
- Download remains navigation/file-response behavior (no JSON required).
- On server error responses (`400`, `404`, `503`), UI must show visible message in `[data-role="docs-error"]`.
- Console-only error behavior is not allowed for user-facing documents UX.

## 62.6 Proof Posture and Disclaimer
- Receipt is a record/acknowledgment of a transaction.
- Receipt may be regenerated; regeneration is allowed and does not imply immutability.
- Receipt reflects data as of generation time.
- This posture is for personal-use documentation and does not guarantee legal validity across jurisdictions.

## 62.7 Minimal QA Evidence (Contract Shape Only)
- Primary documents contract remains:
  - `tests/test_documents_contract.py` (SSOT 61 route/selector/PDF header/filename contract)
- Optional additive UI selector checks may be added in:
  - `tests/test_frontend_contracts.py`
- Required failure prefix for new UI selector checks:
  - `Documents UX contract failed:`

## 62.8 Ownership
- Architect owns SSOT 62.
- Frontend owns selector UX + URL round-trip + validation + download affordances.
- Backend owns endpoint behavior stability per SSOT 61 (no new endpoints).
- QA owns:
  - `tests/test_documents_contract.py` as primary documents contract gate
  - optional UI selector checks in `tests/test_frontend_contracts.py`
- DevOps owns merge-blocking CI wiring for documents contract tests.

## 62.9 Safety/Gate Dependencies
- Must not weaken:
  - SSOT 55 frontend contract lock
  - SSOT 57 URL/filter round-trip posture
  - SSOT 61 documents route/selector/PDF contract lock
  - SSOT 60_schema_capabilities 60.8 / SSOT 80.13 startup-migration contract
  - SSOT 70 / SSOT 80.12 security compliance
  - SSOT 20.6 / SSOT 60_schema_capabilities 60.9 / SSOT 80.14 DB integrity

## 62.10 Phase 2.5 Companion (Month Close Integration)
- Phase 2.5 integration details are defined in `SSOT 63_month_close_documents_integration`.
- UX/proof posture in this file remains authoritative for documents surfaces and must be reused by Month Close integration copy.
- Phase 2.5 introduces no new endpoint or registry-key requirement.

## 62.11 Phase 2.10.1 Companion (Month Close Documents Deep-Link Entry Posture)
- Phase 2.10.1 deep-link lock details are defined in `SSOT 63_6_month_close_documents_deeplink_lock`.
- `/accounting?ym=YYYY-MM` entry via Month Close documents action must hydrate documents surface deterministically on first load.
- Phase 2.10.1 introduces no new endpoint or registry-key requirement.
