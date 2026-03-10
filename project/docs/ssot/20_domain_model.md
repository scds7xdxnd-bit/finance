# Canonical Domain Model
_Last updated: 2026-03-09_

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
- DB integrity gate: `tests/test_db_integrity_gate.py`

## 20.6 DB-level Ledger Integrity (Non-Negotiable)

### 20.6.1 Direction Constraint
- `journal_line.dc` must be constrained at DB level to `D` or `C` only.
- Null or any value outside `{D,C}` is invalid and must be rejected by the database.

### 20.6.2 Finalization Signal and Balance Invariant
- `journal_entry.posted_at` is the finalization signal:
  - `posted_at IS NULL` means draft/in-progress entry.
  - `posted_at IS NOT NULL` means finalized entry.
- For every finalized journal entry, DB-level invariant is strict:
  - `SUM(amount_base WHERE dc='D') == SUM(amount_base WHERE dc='C')`.
- If a mutation would finalize an unbalanced entry, the database must reject it.

### 20.6.3 Currency Rule for Balance
- Mixed transaction currencies on journal lines are allowed.
- Balance enforcement is computed on `journal_line.amount_base` only.
- Therefore, currency-specific line fields (`currency_code`, `amount_tx`, `fx_rate_to_base`) do not override base-amount balancing.

### 20.6.4 Enforcement Boundary
- Ledger integrity is a persistence-layer contract, not application best effort.
- App-level validation may fail fast, but DB constraints/triggers are authoritative and mandatory.

### 20.6.5 Existing Data Remediation Posture
- Migration introducing DB integrity enforcement is blocked if preflight detects invalid existing rows.
- Required posture is detect-and-block, not silent auto-repair.
- Repair workflow must run under operator control with audit trail before constraints are applied.
