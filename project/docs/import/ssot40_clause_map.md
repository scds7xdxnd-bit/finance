# SSOT 40 Clause-to-Implementation Map (Import Team)

This file maps `project/docs/ssot/40_import_contracts.md` clauses to implementation and gates.

## Clause Mapping

| SSOT 40 Clause | Implementation (Exact Function/File) | Notes |
| --- | --- | --- |
| Pipeline order fixed: parse -> normalize -> dedupe -> post -> summarize | `import_csv_transactions()` in `finance_app/services/transaction_import_service.py` | Parse/normalize loop, dedupe/group checks, post branches, `_build_summary()` return sequence. |
| Write mode matrix fixed with unknown -> `journal` | `_valid_write_mode()` in `finance_app/services/transaction_import_service.py` | Accepts only `journal|dual|legacy`; otherwise returns `journal`. |
| File-level idempotency `(user_id, file_sha256)` in `csv_import_batch` | `CsvImportBatch` model unique + `existing_batch` branch in `import_csv_transactions()` | Model: `finance_app/models/accounting_models.py`; branch uses `file_sha256` hash short-circuit unless `force=true`. |
| Row-level dedupe `(user_id, account_id, direction, row_dedupe_key)` | `CsvImportRow` model unique + per-line lookup in `import_csv_transactions()` | Model unique constraint enforced in DB; service checks before post. |
| `row_dedupe_key` deterministic and versioned (`v1`) | `DEDUPE_VERSION = "v1"` + `_row_dedupe_key()` in `finance_app/services/transaction_import_service.py` | Canonical ordered field hashing (`sha256`). |
| Group behavior: all duplicate -> duplicate; partial -> `partial_duplicate_group`; no lines -> `no_postable_lines` | Duplicate/no-line logic in `import_csv_transactions()` | Uses `ROW_DUPLICATE_KEY`, `ROW_ERROR_PARTIAL_DUPLICATE_GROUP`, `ROW_ERROR_NO_POSTABLE_LINES`. |
| Journal mode posts journal only | Journal branch in `import_csv_transactions()` | `create_journal_entry()` is used; no legacy mirror in `journal` mode. |
| Dual mode posts journal first, then simple 2-line legacy + link `strong_dual_write` | Dual branch in `import_csv_transactions()` | Creates `Transaction` and `TransactionJournalLink(source="strong_dual_write")` after journal post. |
| Legacy mode posts only simple 2-line legacy | Legacy branch in `import_csv_transactions()` | Rejects non-2-line with `legacy_unsupported_shape`. |
| Provenance writes mandatory for newly imported lines | `CsvImportRow(...)` inserts in journal and legacy branches | Row provenance fields include `row_sha256`, `row_dedupe_key`, `external_txn_id`, account/direction/amount, optional `journal_entry_id`. |
| Import summary payload keys and reason maps stable | `_build_summary()` + schema file `project/docs/import/csv_import_summary.schema.json` | Required top-level/totals keys and reason maps are emitted consistently. |
| Route + capability guard truth pointer | `/upload_csv` in `blueprints/transactions.py` | Calls `guard_capabilities(["csv_idempotency"])` then `import_csv_transactions(...)`. |

## SSOT 20 Provenance/Balance Invariants Mapping

- Canonical balanced journal invariant:
  - `create_journal_entry()` -> `JournalBalanceError` in `finance_app/services/journal_service.py`.
  - Import path catches unbalanced and records `unbalanced_journal` reason.
- Import dedupe identity invariant:
  - `CsvImportRow` uniqueness + importer dedupe checks.

## SSOT 80 Dedupe Gate Mapping

- Dedupe contract tests:
  - `tests/test_transaction_import_idempotency.py`
- Release gate assertions for summary keys/reasons and overlap/partial duplicate scenarios:
  - `tests/test_vnext_gate.py` (`INV-DEDUPE-*` family)
