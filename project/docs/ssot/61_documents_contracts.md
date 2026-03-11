# Phase 2.3 Documents UX + Contract Lock
_Last updated: 2026-03-11_

## 61.1 Scope
- Locks user-facing contract surfaces for PDF documents introduced in Phase 2.2:
  - Receivables PDF
  - Payables PDF
  - Loan receipt PDF
- Locks selector parsing semantics, deterministic filename rules, and UI affordances for downloads.
- Documents remain server-generated PDFs (no JSON response contract).

## 61.2 Non-Goals
- No new document types.
- No new endpoints required by this SSOT.
- No new registry keys required by this SSOT.
- No JSON contract lock expansion (documents are `application/pdf`).
- No immutability requirement for ledgers or snapshots.
- No DB schema work in this phase.
- No per-row embedded JSON blob requirement for document generation.

## 61.3 Locked Endpoint Surfaces (Existing Routes)
These routes are authoritative and must not be renamed without SSOT update + QA evidence:
- `GET /accounting/receivables/pdf`
- `GET /accounting/payables/pdf`
- `GET /accounting/loan_receipt/pdf`

## 61.4 Selector Contract (Stable Query Parameters)

### 61.4.1 Receivables/Payables PDF Selectors
Stable query params:
- `ym` (required): `YYYY-MM`
- `status` (optional): `open|closed|all` (default `all`)
- `party` (optional): string (substring match; empty treated as absent)
- `min_amount` (optional): decimal
- `max_amount` (optional): decimal

Parsing semantics:
- Invalid selector values must fail deterministically with HTTP `400` (HTML error page is acceptable).
- `min_amount > max_amount` must fail with deterministic `400`.

### 61.4.2 Loan Receipt PDF Selectors
Stable query params:
- exactly one of:
  - `loan_id` (preferred), or
  - `entry_id`
- optional:
  - `ym` (optional; used only for contextual labeling when present)

Parsing semantics:
- If both `loan_id` and `entry_id` are provided: deterministic `400`.
- If neither is provided: deterministic `400`.

## 61.5 PDF Response Contract (Non-JSON)
Required for all document PDFs:
- HTTP `200` on success.
- `Content-Type` is `application/pdf`.
- Response body begins with `%PDF` (contract-level).
- Failure modes:
  - `400` for selector errors (HTML allowed).
  - `401/403` for auth/forbidden (HTML allowed).
  - `404` when target entity not found (HTML allowed).
  - `503` when startup/schema/capability gates block (must fail closed).

## 61.6 Deterministic Filename Contract
- PDF responses must include a deterministic filename via `Content-Disposition`.
- Minimum filename patterns:
  - Receivables: `receivables_<ym>_<status>.pdf` (additional tokens allowed but must be stable)
  - Payables: `payables_<ym>_<status>.pdf`
  - Loan receipt: `loan_receipt_<doc_id>.pdf`
- `<doc_id>` must be deterministic from `(loan_id or entry_id)` + normalized date context (implementation-defined, but must be stable).

## 61.7 UI Contract (Download Affordances)
- Phase 2.3 locks the presence of a download affordance (button/link) for:
  - Receivables PDF
  - Payables PDF
  - Loan receipt PDF (on loan/journal-backed view where applicable)
- This SSOT does not lock exact placement/styling; it locks that the download is buildable from stable selector inputs and is URL-round-trippable.
- Minimal row HTML posture remains unchanged (no per-row embedded JSON blobs).

## 61.8 QA Evidence (Contract Shape)
- Contract tests must exist and remain green:
  - `tests/test_documents_contract.py`
- Required failure prefix:
  - `Documents contract failed:`

## 61.9 Ownership
- Architect owns SSOT definitions in this file.
- Backend owns selector parsing + PDF response behavior + deterministic filenames.
- Frontend owns UI selector controls and URL round-trip behavior.
- QA owns contract tests and failure-prefix enforcement.
- DevOps owns merge-blocking CI wiring for documents contracts.

## 61.10 Safety/Gate Dependencies
- Must not weaken:
  - SSOT 55 frontend contract lock
  - SSOT 60_schema_capabilities 60.8 startup/migration contract
  - SSOT 70 security compliance
  - SSOT 20.6 / SSOT 60_schema_capabilities 60.9 DB integrity

## 61.11 Phase 2.5 Companion (Month Close Integration)
- Phase 2.5 integration details are defined in `SSOT 63_month_close_documents_integration`.
- Endpoint, selector, response, and filename contracts in this file remain authoritative and unchanged.
- Phase 2.5 introduces no new document endpoint requirement and no new registry-key requirement.
