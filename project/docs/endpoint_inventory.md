# Endpoint Inventory (Phase 0)
_Last updated: 2025-12-24_

## Why
- Provide a single list of HTTP routes with owners and consumers.
- Freeze new endpoints in legacy paths until Phase 1 consolidation.

## Notes
- Legacy paths in use: `blueprints/`, `routes/`, and `finance_app/controllers/core.py`.
- `blueprints/accounting copy.py` appears to be a duplicate and is not registered.
- `blueprints/transactions.py` defines `/transactions` twice; inventory lists it once.

## Core (finance_app/controllers/core.py)
| Endpoint | Methods | Owner | Consumers | Notes |
| --- | --- | --- | --- | --- |
| / | GET | Core Platform | Web UI | Redirects to login/transactions. |
| /documents | GET, POST | Reporting & Documents | Web UI | Documents page. |
| /api/ml_suggestions | POST | ML Suggestions | Web UI (JS) | JSON ML inference. |
| /api/suggestions/log | POST | ML Suggestions | Web UI (JS) | Suggestion feedback log. |
| /suggest/debit | POST | ML Suggestions | Web UI (legacy) | Legacy hint endpoint. |
| /suggest/credit | POST | ML Suggestions | Web UI (legacy) | Legacy hint endpoint. |
| /healthz | GET | Core Platform | Ops/Monitoring | Health check. |

## Auth (blueprints/auth.py)
| Endpoint | Methods | Owner | Consumers | Notes |
| --- | --- | --- | --- | --- |
| /login | GET, POST | Identity & Admin | Web UI | Login form. |
| /register | GET, POST | Identity & Admin | Web UI | Registration form. |
| /logout | GET | Identity & Admin | Web UI | Session logout. |
| /forgot-username | GET, POST | Identity & Admin | Web UI | Username recovery. |
| /forgot-password | GET, POST | Identity & Admin | Web UI | Password reset. |

## User (blueprints/user.py)
| Endpoint | Methods | Owner | Consumers | Notes |
| --- | --- | --- | --- | --- |
| /profile | GET, POST | Identity & Admin | Web UI | Profile view/edit. |
| /profile/post | POST | Identity & Admin | Web UI | Create profile post. |
| /profile/post/edit/<int:post_id> | POST | Identity & Admin | Web UI | Edit profile post. |
| /profile/change_credentials | GET, POST | Identity & Admin | Web UI | Change credentials. |
| /profile/post/delete/<int:post_id> | POST | Identity & Admin | Web UI | Delete profile post. |

## Admin (blueprints/admin.py)
| Endpoint | Methods | Owner | Consumers | Notes |
| --- | --- | --- | --- | --- |
| /admin | GET | Identity & Admin | Admin UI | Admin dashboard. |
| /admin/grant/<int:user_id> | POST | Identity & Admin | Admin UI | Grant admin. |
| /admin/delete/<int:user_id> | POST | Identity & Admin | Admin UI | Delete user. |
| /admin/revoke/<int:user_id> | POST | Identity & Admin | Admin UI | Revoke admin. |
| /admin/users | GET | Identity & Admin | Admin UI | User list. |
| /admin/tools | GET | Identity & Admin | Admin UI | Admin tools. |
| /admin/download_login_sessions | GET | Identity & Admin | Admin UI | CSV download. |
| /admin/download_user_list | GET | Identity & Admin | Admin UI | CSV download. |
| /admin/suggestions | GET | Identity & Admin | Admin UI | Suggestion metrics UI. |
| /admin/diagnostics/weasy | GET | Identity & Admin | Admin UI | Diagnostics JSON. |
| /admin/suggestions/train | POST | Identity & Admin | Admin UI | Train suggestion model. |
| /admin/jobs/assign-account-ids | POST | Identity & Admin | Admin UI | Start background job. |
| /admin/jobs/status | GET | Identity & Admin | Admin UI (JS) | Job status poll. |
| /admin/user-models/train | POST | Identity & Admin | Admin UI | Train per-user model. |
| /admin/jobs/train-user-models | POST | Identity & Admin | Admin UI | Start user-model job. |
| /admin/api/suggestions/metrics | GET | Identity & Admin | Admin UI (JS) | Metrics API. |
| /admin/api/user-models/status | GET | Identity & Admin | Admin UI (JS) | Status API. |
| /admin/api/tx/summary | GET | Identity & Admin | Admin UI (JS) | Transaction summary API. |

## Transactions (blueprints/transactions.py)
| Endpoint | Methods | Owner | Consumers | Notes |
| --- | --- | --- | --- | --- |
| /upload_csv | POST | Transactions & Imports | Web UI | CSV import. |
| /transactions | GET | Transactions & Imports | Web UI | Listed once (duplicate decorator exists). |
| /transactions/delete/<int:tx_id> | POST | Transactions & Imports | Web UI | Delete transaction. |
| /add_transaction | GET, POST | Transactions & Imports | Web UI | POST expects JSON. |

## Accounting (blueprints/accounting.py)
| Endpoint | Methods | Owner | Consumers | Notes |
| --- | --- | --- | --- | --- |
| /accounting | GET | Accounting Core | Web UI | Main accounting view. |
| /accounting/codes/refresh | POST | Accounting Core | Web UI | Refresh codes. |
| /accounting/category/add | POST | Accounting Core | Web UI | Add category. |
| /accounting/account/add | POST | Accounting Core | Web UI | Add account. |
| /accounting/account/move | POST | Accounting Core | Web UI | Move account. |
| /accounting/category/reorder | POST | Accounting Core | Web UI | Reorder categories. |
| /accounting/category/delete/<int:cat_id> | POST | Accounting Core | Web UI | Delete category. |
| /accounting/account/delete/<int:acc_id> | POST | Accounting Core | Web UI | Delete account. |
| /accounting/account/bulk_currency | POST | Accounting Core | Web UI | Bulk currency update. |
| /accounting/category/rename/<int:cat_id> | POST | Accounting Core | Web UI | Rename category. |
| /accounting/account/rename/<int:acc_id> | POST | Accounting Core | Web UI | Rename account. |
| /accounting/account/code/<int:acc_id> | POST | Accounting Core | Web UI | Set account code. |
| /accounting/category/set_group | POST | Accounting Core | Web UI | Set category group. |
| /accounting/tb/opening_balance | POST | Trial Balance & Period Close | Web UI | Set opening balance. |
| /accounting/tb/initialize | POST | Trial Balance & Period Close | Web UI | Initialize TB. |
| /accounting/tb/reset | POST | Trial Balance & Period Close | Web UI | Reset TB. |
| /accounting/account/bulk_move | POST | Accounting Core | Web UI | Bulk move accounts. |
| /accounting/account/bulk_unassign | POST | Accounting Core | Web UI | Bulk unassign. |
| /accounting/receivables/data | GET | Receivables & Loans | Web UI (JS) | Receivables data. |
| /accounting/receivables/save | POST | Receivables & Loans | Web UI | Save receivables. |
| /accounting/receivables/link | POST | Receivables & Loans | Web UI | Link receivable lines. |
| /accounting/receivables/delete | POST | Receivables & Loans | Web UI | Delete receivable. |
| /accounting/receivables/create | POST | Receivables & Loans | Web UI | Create receivable. |
| /accounting/loan-groups | GET | Receivables & Loans | Web UI (JS) | List loan groups. |
| /accounting/loan-groups | POST | Receivables & Loans | Web UI | Create loan group. |
| /accounting/loan-groups/<group_id> | GET | Receivables & Loans | Web UI (JS) | Loan group detail. |
| /accounting/loan-groups/<group_id> | DELETE | Receivables & Loans | Web UI (JS) | Delete loan group. |
| /accounting/loan-groups/<group_id> | PATCH | Receivables & Loans | Web UI (JS) | Update loan group. |
| /accounting/loan-groups/<group_id>/summary | GET | Receivables & Loans | Web UI (JS) | Loan group summary. |
| /accounting/loan-groups/<group_id>/entries | GET | Receivables & Loans | Web UI (JS) | Loan group entries. |
| /accounting/transaction-links | POST | Journal & Posting | Web UI | Link journal lines. |
| /accounting/transaction-links/<link_id> | DELETE | Journal & Posting | Web UI (JS) | Unlink transaction. |
| /accounting/allocation/suggest | POST | Journal & Posting | Web UI (JS) | Suggest allocation. |
| /accounting/tb/monthly | GET | Trial Balance & Period Close | Web UI (JS) | Monthly TB. |
| /accounting/tb/close | POST | Trial Balance & Period Close | Web UI | Close period. |
| /accounting/statement/data | GET | Reporting & Documents | Web UI (JS) | Statement data. |
| /accounting/statement/export | GET | Reporting & Documents | Web UI | CSV export. |
| /accounting/statement/pdf | GET | Reporting & Documents | Web UI | PDF export. |
| /accounting/tb/set_first_month | POST | Trial Balance & Period Close | Web UI | Set first month. |
| /accounting/journal/list | GET | Journal & Posting | Web UI (JS) | Journal list. |
| /accounting/journal/<int:entry_id> | PUT | Journal & Posting | Web UI (JS) | Update journal entry. |
| /accounting/tb/pdf | GET | Trial Balance & Period Close | Web UI | TB PDF. |
| /accounting/journal/delete/<int:entry_id> | POST | Journal & Posting | Web UI | Delete journal entry. |
| /first_tb_month | GET | Trial Balance & Period Close | Web UI (JS) | First TB month. |

## Journal (blueprints/journal.py)
| Endpoint | Methods | Owner | Consumers | Notes |
| --- | --- | --- | --- | --- |
| /journal_feedback | POST | ML Suggestions | Web UI (JS) | Journal model feedback. |

## Money Schedule (blueprints/money_schedule/routes.py, prefix /money-schedule)
| Endpoint | Methods | Owner | Consumers | Notes |
| --- | --- | --- | --- | --- |
| /money-schedule/ | GET | Money Schedule | Web UI | Main view. |
| /money-schedule/assets | POST | Money Schedule | Web UI | Asset include updates. |
| /money-schedule/quick_add | POST | Money Schedule | Web UI | Quick add entry. |
| /money-schedule/edit | POST | Money Schedule | Web UI | Edit row. |
| /money-schedule/events | POST | Money Schedule | Web UI | Create recurring event. |
| /money-schedule/events/<int:event_id>/edit | POST | Money Schedule | Web UI | Edit event. |
| /money-schedule/events/<int:event_id>/toggle | POST | Money Schedule | Web UI | Toggle event. |
| /money-schedule/events/<int:event_id>/delete | POST | Money Schedule | Web UI | Delete event. |
| /money-schedule/scenarios | POST | Money Schedule | Web UI | Create scenario. |
| /money-schedule/scenarios/<int:scenario_id>/edit | POST | Money Schedule | Web UI | Edit scenario. |
| /money-schedule/scenarios/<int:scenario_id>/delete | POST | Money Schedule | Web UI | Delete scenario. |

## Forecast (routes/forecast.py, legacy routes/)
| Endpoint | Methods | Owner | Consumers | Notes |
| --- | --- | --- | --- | --- |
| /forecast | GET | Money Schedule | Web UI | Forecast page. |
| /api/forecast.json | GET | Money Schedule | Web UI (JS) | Forecast data API. |
| /forecast/schedule | POST | Money Schedule | Web UI | Add schedule item. |
