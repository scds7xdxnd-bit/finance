# Security Model
_Last updated: 2026-03-07_

## 70.1 Scope
Authentication, authorization, CSRF, admin safety controls, audit logging, and sensitive endpoint classification for vNext correctness surfaces.

## 70.2 Non-Negotiable Contracts
- AuthN is session-based; protected operations require `session["user_id"]` resolution via `current_user()`.
- AuthZ is user-scope first, admin override only where explicitly allowed.
- State-changing routes must enforce CSRF token checks (`X-CSRF-Token` or form `csrf_token`).
- Cross-user mutation of finance records is forbidden.
- Admin mutation routes require all of:
  - authenticated admin user
  - CSRF check
  - capability guard for `admin_audit`
  - typed confirmation + cooldown for destructive actions
  - audit log write to `admin_action_audit`
- Sensitive operational endpoints must fail closed when schema capabilities are missing.
- Schema-guard bypass (`SCHEMA_GUARD_ENFORCE=false`) is emergency-only and requires a reason plus an unexpired ISO timestamp no more than 7 days ahead.

## 70.3 Sensitive Endpoint Classes
- Class A (ledger/report integrity): `/upload_csv`, `/accounting/tb/reset`, `/accounting/tb/monthly`, `/accounting/statement/*`, `/accounting/tb/pdf`.
- Class B (cross-user/admin risk): `/admin/*` mutation endpoints, `/transactions/delete/<tx_id>`, journal delete/update routes.
- Class C (operational CLI): `schema-status`, `backfill-transaction-links`, `ledger-reconcile`, `tb-reset-restore`, `sqlite-backup`.

## 70.4 Implementation Truth Pointers
- Session + CSRF helpers: `finance_app/lib/auth.py`
- Auth routes/session handling: `blueprints/auth.py`
- Admin mutation guard, confirmation, and audit: `blueprints/admin.py`
- Accounting CSRF checks and scoped writes: `blueprints/accounting.py`
- Transaction delete scope enforcement: `finance_app/services/transaction_service.py`, `blueprints/transactions.py`
- Schema guard integration and bypass validation: `finance_app/services/schema_guard_service.py`

## 70.5 Gate/Test Pointers
- Auth/login CSRF path coverage: `tests/test_auth_login.py`
- Cross-user delete/forecast canary checks: `tests/test_vnext_gate.py`
- Transaction service authorization behavior: `tests/test_transaction_service.py`
- Sensitive endpoint hard-fail/CSRF/admin tests: `tests/test_security_sensitive_endpoints.py`
