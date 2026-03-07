Added Phase 3 schema scaffolding to align the database with the journal-as-source-of-truth decision while keeping Transaction compatibility, and to make money schedule account mappings explicit. This is additive-only; compat population and reconciliation remain in scripts/services.

**Changes**
- `alembic/versions/20251224_finance_add_phase3_structures.py` adds `transaction_journal_link`, `money_schedule_account_link`, and user-scoped composite indexes.
- `finance_app/models/accounting_models.py` defines `TransactionJournalLink` plus new indexes on Transaction, JournalEntry, Account, AccountCategory, and AccountOpeningBalance.
- `finance_app/models/money_account.py` defines `MoneyScheduleAccountLink` to encode explicit money schedule mappings.
- `finance_app/__init__.py` exports the new link models for metadata registration.
- `scripts/reconcile_ledger_convergence.sql` provides reconciliation checks for link coverage and balance parity.
- `project/docs/decisions.md` records the Phase 3 scaffolding decision and compat intent.

**Why**
- Phase 3 requires journal truth with legacy compatibility; link tables avoid destructive changes while enabling convergence.
- Money schedule accounts stay separate; explicit links prevent implicit cross-domain reuse.
- Composite indexes enforce the user_id + dimension rule for primary query paths.
- Additive-only schema keeps current behavior stable until backfills and compat reads are enabled.

**Next Steps**
1. Run Alembic migration `alembic/versions/20251224_finance_add_phase3_structures.py` in each environment.
2. Add backfill/CLI scripts to populate `transaction_journal_link` and `money_schedule_account_link` (no long-running Alembic data moves).
3. Execute `scripts/reconcile_ledger_convergence.sql` and resolve mismatches before enabling compat reads.
4. Add tests for link creation and reconciliation invariants once backfills exist.
