# Ledger Convergence Contract
_Last updated: 2026-03-07_

## Scope
Rules for linking legacy `Transaction` rows to canonical journal entries and proving coverage/reconcile correctness.

## Non-Negotiable Contracts
- Confidence tiers are fixed: `exact`, `strong`, `weak_ambiguous`.
- Auto-linking is allowed only for `exact` and `strong`.
- `weak_ambiguous` candidates are never auto-linked; they are persisted for review only.
- `exact` link path uses explicit stable reference (`JournalEntry.reference == TX:<transaction_id>`) with unique match.
- `strong` link path requires stable provenance identity and strict 1:1 cardinality across debit/credit row keys.
- Stable provenance for strong linking is currently `row_dedupe_key`-compatible identity from CSV provenance rows.
- Backfill must be idempotent: reruns do not create extra links for already-linked rows.
- Reconcile pass requires all of: `missing_links_count == 0`, `mismatched_totals == 0`, `unbalanced_journals_count == 0`.
- Coverage gates require thresholds from `ledger-reconcile`: count >= 0.99, amount >= 0.995, unlinked_recent_90d_count <= 0 (default values).

## Reconcile and Coverage Metrics Schema
- Reconcile payload keys: `pass`, `missing_links_count`, `mismatched_totals`, `unbalanced_journals_count`.
- Coverage payload keys: `total_legacy_tx`, `linked_legacy_tx`, `linked_exact`, `linked_strong`, `total_legacy_amount`, `linked_legacy_amount`, `coverage_count`, `coverage_amount`, `unlinked_recent_90d_count`.

## Implementation Truth Pointers
- Policy enums and auto-link guard: `finance_app/services/ledger_convergence_policy.py`
- Backfill and reconcile implementation: `finance_app/services/ledger_convergence_service.py`
- CLI entry points and thresholds: `finance_app/cli/management.py`
- SQL reconciliation reference queries: `scripts/reconcile_ledger_convergence.sql`

## Gate/Test Pointers
- Convergence behavior/unit tests: `tests/test_ledger_convergence.py`
- Release gate coverage and reconcile assertions: `tests/test_vnext_gate.py`
- Gate catalog: `project/docs/qa_gate_invariants.md`
