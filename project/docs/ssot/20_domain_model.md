# Canonical Domain Model
_Last updated: 2026-03-07_

## 20.1 Scope
Canonical finance domain model for ledger correctness, import provenance, reporting totals, and convergence compatibility.

## 20.2 Canonical Entities
- `AccountCategory` and `Account`: chart-of-accounts structure and TB grouping.
- `JournalEntry` and `JournalLine`: canonical double-entry ledger.
- `Transaction`: legacy compatibility record only.
- `TransactionJournalLink`: explicit compatibility link between legacy transaction and journal entry.
- `TransactionLinkCandidate`: reviewable convergence candidates and confidence/status metadata.
- `CsvImportBatch` and `CsvImportRow`: file-level and row-level import provenance/idempotency records.
- `TrialBalanceSetting`, `AccountOpeningBalance`, `AccountMonthlyBalance`: TB initialization/opening/period snapshots.
- `ReceivableTracker`, `ReceivableManualEntry`, `LoanGroup`, `LoanGroupLink`: receivable/debt overlays on journal lines.

## 20.3 Non-Negotiable Contracts
- Canonical ledger truth is `JournalEntry` + `JournalLine`; ranked reporting totals are derived from them.
- Every posted journal entry must be balanced; unbalanced entries are rejected at write time.
- Legacy `Transaction` may exist only for compatibility (`dual` or `legacy` modes) and emergency operations.
- `TransactionJournalLink` is user-scoped and enforces 1:1 uniqueness by transaction and by journal entry.
- `CsvImportRow` idempotency identity is user/account/direction/row_dedupe_key; duplicate rows are not reposted.
- TB group polarity is credit-nature for `liability|equity|income`, debit-nature otherwise.
- Receivable/loan overlays must resolve through user-scoped journal lines; cross-user linkage is forbidden.
- Money schedule and forecast data are out of vNext ledger truth scope; they do not define ranked report totals.

## 20.4 Implementation Truth Pointers
- Models: `finance_app/models/accounting_models.py`
- Journal validation/write: `finance_app/services/journal_service.py`
- Transaction write modes: `finance_app/services/transaction_create_service.py`
- TB computation: `finance_app/services/trial_balance_service.py`
- Canonical reporting source: `finance_app/services/ledger_query_service.py`
- Receivable and loan overlays: `finance_app/services/receivable_service.py`, `finance_app/services/loan_group_service.py`

## 20.5 Gate/Test Pointers
- Journal balance checks: `tests/test_journal_service.py`, `tests/test_transactions_journal.py`
- Reporting parity expectations: `tests/test_statement_data.py`, `tests/test_ranked_reporting_cutover.py`
- Release-level invariants: `tests/test_vnext_gate.py`
