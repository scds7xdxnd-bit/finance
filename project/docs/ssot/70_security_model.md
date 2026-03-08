# Security Model
_Last updated: 2026-03-08_

## 70.1 Scope
Authentication, authorization, CSRF, admin safety controls, audit logging, schema guard usage, endpoint sensitivity classes, and transitional exception policy.

## 70.2 Non-Negotiable Contracts
- AuthN is session-based; protected operations require `session["user_id"]` resolution via `current_user()`.
- AuthZ is user-scope first, admin override only where explicitly allowed.
- State-changing routes must enforce CSRF token checks (`X-CSRF-Token` or form `csrf_token`), except where explicitly listed in SSOT 70.5 transitional exceptions.
- Cross-user mutation of finance records is forbidden.
- Admin mutation routes require all of:
  - authenticated admin user
  - CSRF check
  - capability guard for `admin_audit`
  - typed confirmation + cooldown for destructive actions
  - audit log write to `admin_action_audit`
- Sensitive operational endpoints must fail closed when required schema capabilities are missing.
- Transitional exceptions are allowed only when listed in SSOT 70.5 with `status=open` and unexpired `expires_on_utc`.
- Expired security exceptions are release-blocking under `GATE-SECURITY-COMPLIANCE`.
- Feature work on exception routes is forbidden until the route is hardened and removed from SSOT 70.5.
- Schema-guard bypass (`SCHEMA_GUARD_ENFORCE=false`) is emergency-only and requires a reason plus an unexpired ISO timestamp no more than 7 days ahead.

## 70.3 Sensitive Endpoint Classes
- Class A (ledger/report integrity): `/upload_csv`, `/accounting/tb/reset`, `/accounting/tb/monthly`, `/accounting/statement/*`, `/accounting/tb/pdf`.
- Class B (cross-user/admin risk): `/admin/*` mutation endpoints, `/transactions/delete/<tx_id>`, journal delete/update routes.
- Class C (user profile and feedback mutations): `/profile*` post/edit/delete/change-credentials routes, `/journal_feedback`.
- Class D (legacy forecast surfaces): `/forecast`, `/api/forecast.json`, `/forecast/schedule`.
- Class E (anonymous recovery/membership): `/register`, `/forgot-username`, `/forgot-password`.
- Class F (operational CLI): `schema-status`, `backfill-transaction-links`, `ledger-reconcile`, `tb-reset-restore`, `sqlite-backup`.

## 70.4 Required Security Controls by Class
| Class | AuthN | CSRF | Scope/AuthZ | Admin | Audit | Schema Guard |
| --- | --- | --- | --- | --- | --- | --- |
| A | required | required for mutations | required | where endpoint is admin-only | required for admin mutations | required (`guard_capabilities`) |
| B | required | required | required | required | required | required when capability-mapped |
| C | required (except anonymous flows in Class E) | required | required (owner scope) | not required | recommended for sensitive writes | optional unless capability-mapped |
| D | immediate Option A policy (SSOT 70.6) | required for mutations when enabled | not user-scoped; must be fenced | required when enabled | required for mutations when enabled | required for mutations when enabled (`admin_audit`) |
| E | not required | required | N/A | N/A | N/A | N/A |
| F | CLI auth context | N/A | operator scope | as command requires | command-specific | command-specific |

## 70.5 Transitional Security Exceptions (Time-Boxed Register)
Register format is machine-parsed by `GATE-SECURITY-COMPLIANCE`.

Rules:
- `expires_on_utc` must be ISO date (`YYYY-MM-DD`).
- `status` must be `open` or `closed`.
- Any `open` row with `today_utc > expires_on_utc` is release-blocking.
- New exceptions require Architect SSOT PR and must set expiry no later than 60 days from introduction.

| exception_id | method | path | missing_controls | required_end_state | expires_on_utc | status |
| --- | --- | --- | --- | --- | --- | --- |
| SEC-EX-001 | POST | `/login` | `csrf` | POST enforces CSRF token validation | 2026-05-01 | open |
| SEC-EX-002 | POST | `/register` | `csrf` | POST enforces CSRF token validation | 2026-05-01 | open |
| SEC-EX-003 | POST | `/forgot-username` | `csrf` | POST enforces CSRF token validation | 2026-05-01 | open |
| SEC-EX-004 | POST | `/forgot-password` | `csrf` | POST enforces CSRF token validation | 2026-05-01 | open |
| SEC-EX-014 | GET | `/logout` | `csrf,method_safety` | POST /logout exists with CSRF; GET /logout must not mutate session (405 or safe). | 2026-05-01 | closed |
| SEC-EX-005 | POST | `/profile` | `csrf` | POST enforces CSRF token validation | 2026-05-01 | open |
| SEC-EX-006 | POST | `/profile/post` | `csrf` | POST enforces CSRF token validation | 2026-05-01 | open |
| SEC-EX-007 | POST | `/profile/post/edit/<int:post_id>` | `csrf` | POST enforces CSRF token validation | 2026-05-01 | open |
| SEC-EX-008 | POST | `/profile/change_credentials` | `csrf` | POST enforces CSRF token validation | 2026-05-01 | open |
| SEC-EX-009 | POST | `/profile/post/delete/<int:post_id>` | `csrf` | POST enforces CSRF token validation | 2026-05-01 | open |
| SEC-EX-010 | POST | `/journal_feedback` | `auth,csrf,scope` | Authenticated + CSRF + current-user scope enforced | 2026-05-01 | open |
| SEC-EX-011 | GET | `/forecast` | `auth,admin_fence` | Disabled by flag or admin-auth fenced | 2026-05-01 | open |
| SEC-EX-012 | GET | `/api/forecast.json` | `auth,admin_fence` | Disabled by flag or admin-auth fenced | 2026-05-01 | open |
| SEC-EX-013 | POST | `/forecast/schedule` | `auth,csrf,admin,audit,schema_guard` | Disabled by flag or admin+CSRF+audit+guard enforced | 2026-05-01 | open |

## 70.6 Legacy Forecast Security Classification (Class D)
Forecast endpoints are legacy Class D surfaces until user-scoped forecast tables exist.

Immediate policy (Option A, mandatory):
- Preferred default mode: `FORECAST_LEGACY_ENABLED=false` and all forecast endpoints return `404`.
- If forecast is enabled (`FORECAST_LEGACY_ENABLED=true`), all forecast routes must be fenced:
  - `GET /forecast` and `GET /api/forecast.json`: authenticated admin only (`401` unauthenticated, `403` non-admin).
  - `POST /forecast/schedule`: authenticated admin + CSRF + admin audit write + schema capability guard for `admin_audit`.
- Mixed user-scoped forecast access is forbidden until forecast storage is user-scoped.

## 70.7 Gate/Test Pointers
- Security compliance gate module (mandatory): `tests/test_security_compliance_gate.py`
- Sensitive endpoint hard-fail/CSRF/admin tests: `tests/test_security_sensitive_endpoints.py`
- Cross-user and scope canary checks: `tests/test_vnext_gate.py`
- Auth/login behavior tests: `tests/test_auth_login.py`
- Transaction service authorization behavior: `tests/test_transaction_service.py`

## 70.8 Implementation Truth Pointers
- Session + CSRF helpers: `finance_app/lib/auth.py`
- Auth routes/session handling: `blueprints/auth.py`
- User/profile mutation routes: `blueprints/user.py`
- Journal feedback route: `blueprints/journal.py`
- Forecast routes: `routes/forecast.py`
- Admin mutation guard, confirmation, and audit: `blueprints/admin.py`
- Accounting CSRF checks and scoped writes: `blueprints/accounting.py`
- Schema guard integration and bypass validation: `finance_app/services/schema_guard_service.py`
