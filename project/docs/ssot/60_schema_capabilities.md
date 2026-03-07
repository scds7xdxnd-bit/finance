# Schema Capabilities Contract
_Last updated: 2026-03-07_

## Scope
Capability-based schema guard contract for sensitive operations.

## Capability Matrix
| Capability | Required artifacts (summary) |
| --- | --- |
| `tx_linking` | `transaction_journal_link` table, source check, required indexes/uniques |
| `link_candidates` | `transaction_link_candidate` table, required columns/indexes/check |
| `csv_idempotency` | `csv_import_batch` + `csv_import_row` tables, required uniques/checks/index |
| `tb_snapshot` | `tb_reset_snapshot` table, restore/checksum fields, required uniques/checks/index |
| `admin_audit` | `admin_action_audit` table + actor/created index |
| `journal_report_perf` | Journal report indexes on `journal_entry` and `journal_line` |

## Non-Negotiable Contracts
- Schema guard verdict is capability-based and artifact-based; migration revision string alone is insufficient.
- `schema-status` must report all required capabilities and exit non-zero when capability checks fail.
- Guarded operations must hard-fail (`503`) when required capabilities are missing and enforcement is enabled.
- Required capability names are stable: `tx_linking`, `link_candidates`, `csv_idempotency`, `tb_snapshot`, `admin_audit`, `journal_report_perf`.

## Hard-Fail Operation Map
- `/upload_csv` requires `csv_idempotency`.
- `/accounting/tb/reset` requires `tb_snapshot` and `admin_audit`.
- `backfill-transaction-links` requires `tx_linking`, `link_candidates`, `csv_idempotency`.
- `ledger-reconcile` requires `tx_linking`.
- Admin mutation routes require `admin_audit`.

## Implementation Truth Pointers
- Capability requirements and guard logic: `finance_app/services/schema_guard_service.py`
- CLI schema command and guarded CLI operations: `finance_app/cli/management.py`
- Guarded import route: `blueprints/transactions.py`
- Guarded TB reset and admin routes: `blueprints/accounting.py`, `blueprints/admin.py`
- Verification SQL: `scripts/verify_schema_capabilities.sql`
- Capability matrix reference: `project/docs/schema_capability_matrix_vnext.md`

## Gate/Test Pointers
- Capability tests: `tests/test_schema_guard_service.py`
- Release gate schema checks: `tests/test_vnext_gate.py`
- Migration smoke runner: `scripts/migration_smoke_vnext.py`
