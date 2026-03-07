# CSV Import Pipeline Spec (Journal-First, Deterministic)

## Scope
This spec defines the application-layer behavior for `/upload_csv` import in `LEDGER_WRITE_MODE=journal|dual|legacy` with deterministic idempotency and provenance.

## Pipeline
1. Parse
- Read CSV via `csv.DictReader`.
- Normalize header keys to lowercase/trimmed aliases.
- Build `ParsedCsvRow` records per source row.

2. Normalize
- `date_str/date_parsed`: parsed to `YYYY/MM/DD` when possible.
- `date_token`: `YYYY/MM/DD` when parsed; otherwise trimmed raw date with `-` -> `/` and whitespace removed.
- `description/memo`: whitespace-collapsed strings.
- `currency`: uppercase, default `KRW`.
- `external_txn_id`: trimmed text or null.
- `amount`: `Decimal(18,2)` half-up quantization.

3. Dedupe
- File-level idempotency: `csv_import_batch(user_id, file_sha256)` unique.
- Row-level dedupe across files: `csv_import_row(user_id, account_id, direction, row_dedupe_key)` unique.
- Grouping key for posting:
  - `external_txn_id` when present.
  - otherwise per-source-row key `ROW:{row_number}`.
- Group outcomes:
  - all lines duplicate -> duplicate (no post)
  - mixed duplicate/new lines -> error `partial_duplicate_group` (no post)
  - no lines -> error `no_postable_lines`

4. Post (Journal-first)
- `journal` mode: create balanced `JournalEntry` + `JournalLine` only.
- `dual` mode: journal post first, then mirror simple 2-line record to legacy `Transaction` + `TransactionJournalLink`.
- `legacy` mode: only simple 2-line legacy record (compatibility mode).
- Every imported line writes `csv_import_row` with provenance (`row_sha256`, `row_dedupe_key`, `journal_entry_id`, optional `external_txn_id`).

5. Summarize
- Return deterministic audit summary with:
  - counts: `rows_new`, `rows_duplicate`, `rows_error`
  - reason maps: `duplicate_reasons`, `error_reasons`
  - compat counters: `count_journal`, `count_simple`, date normalization counts.

## Dedupe Key Spec (`row_dedupe_key`)
- Version: `v1`
- Canonical payload fields (ordered):
  - `date_token`
  - `amount` (2dp)
  - `currency`
  - `account_id`
  - `direction` (`D|C`)
  - if `external_txn_id` exists: `external_txn_id`
  - else: `counterparty_norm` (`lower(description|memo)` with collapsed whitespace)
- Storage value: `sha256("|".join(canonical_fields))` hex digest.

## Provenance Spec (`row_sha256`)
- Versioned canonical hash (`v1`) of normalized row-level fields:
  - `date_token`, `description_norm`, `memo_norm`,
  - normalized debit/credit account names,
  - debit/credit amounts (2dp), currency, external_txn_id.
- Storage value: `sha256(canonical_row_string)` hex digest.

## Error Taxonomy
- Duplicate reasons:
  - `duplicate_batch_file_sha256`
  - `duplicate_row_dedupe_key`
- Error reasons:
  - `no_postable_lines`
  - `partial_duplicate_group`
  - `unbalanced_journal`
  - `legacy_unsupported_shape`
