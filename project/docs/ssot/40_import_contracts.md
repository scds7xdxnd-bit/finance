# CSV Import Contracts
_Last updated: 2026-03-07_

## 40.1 Scope
Journal-first CSV ingestion contract, including normalization, dedupe identity, provenance writes, and deterministic summary output.

## 40.2 Non-Negotiable Contracts
- Import pipeline order is fixed: parse -> normalize -> dedupe -> post -> summarize.
- Write mode matrix is fixed: `journal|dual|legacy`; unknown mode falls back to `journal`.
- File-level idempotency key is `(user_id, file_sha256)` in `csv_import_batch`.
- Row-level dedupe key is `(user_id, account_id, direction, row_dedupe_key)` in `csv_import_row`.
- `row_dedupe_key` must remain deterministic and versioned (`v1`), hashed from canonical fields.
- Group behavior is fixed:
  - all lines duplicate -> duplicate group (no post)
  - partial duplicate group -> error `partial_duplicate_group` (no post)
  - no postable lines -> error `no_postable_lines`
- Journal mode posts journal entries only.
- Dual mode posts journal first, then mirrors simple 2-line legacy transaction and writes link source `strong_dual_write`.
- Legacy mode posts only simple 2-line legacy transactions.
- Provenance writes (`CsvImportRow`) are mandatory for newly imported lines; no bypass path is allowed.
- Import summary payload keys and reason maps are stable contract fields.

## 40.3 Import Summary Contract Fields (Required)
- Top-level keys: `batch_id`, `file_sha256`, `write_mode`, `skipped_duplicate_batch`, `totals`, `duplicate_reasons`, `error_reasons`, `count_simple`, `count_journal`, `rows_new`, `rows_duplicate`, `rows_error`.
- Totals keys: `rows_total`, `rows_new`, `rows_duplicate`, `rows_error`, `journal_entries_created`, `legacy_transactions_created`, `normalized_dates`, `unparsable_dates`.

## 40.4 Implementation Truth Pointers
- Import orchestration and hashing: `finance_app/services/transaction_import_service.py`
- Import route + capability guard: `blueprints/transactions.py`
- Persistence constraints: `finance_app/models/accounting_models.py` (`CsvImportBatch`, `CsvImportRow`)
- Summary JSON schema: `project/docs/import/csv_import_summary.schema.json`
- Pipeline spec: `project/docs/import/csv_import_pipeline_spec.md`
- Clause-to-code mapping: `project/docs/import/ssot40_clause_map.md`

## 40.5 Gate/Test Pointers
- Idempotency and dedupe tests: `tests/test_transaction_import_idempotency.py`
- Release gate dedupe assertions: `tests/test_vnext_gate.py`
