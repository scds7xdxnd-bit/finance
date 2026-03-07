# Service Domain Inventory
_Last updated: 2025-12-24_

## Why
- Capture explicit service ownership to prevent cross-domain imports.
- Provide a Phase 0 baseline for refactors and guardrails.

## Inventory
| Service | Domain | Owner | Notes |
| --- | --- | --- | --- |
| finance_app/services/account_service.py | Accounting Core | Finance Backend | Chart of accounts, account codes, background jobs. |
| finance_app/services/exchange_rate_service.py | Accounting Core | Finance Backend | Exchange rate helpers. |
| finance_app/services/transaction_service.py | Transactions & Imports | Finance Backend | Legacy single-entry transactions. |
| finance_app/services/transaction_create_service.py | Transactions & Imports | Finance Backend | Transaction creation helpers. |
| finance_app/services/transaction_import_service.py | Transactions & Imports | Finance Backend | CSV import orchestration. |
| finance_app/services/journal_service.py | Journal & Posting | Finance Backend | Journal entry/line orchestration. |
| finance_app/services/trial_balance_service.py | Trial Balance & Period Close | Finance Backend | Trial balance settings and rollups. |
| finance_app/services/money_schedule_service.py | Money Schedule | Finance Backend | Money schedule core logic. |
| finance_app/services/forecast.py | Money Schedule | Finance Backend | Cash forecast projections. |
| finance_app/services/receivable_service.py | Receivables & Loans | Finance Backend | Receivable tracking and helpers. |
| finance_app/services/loan_group_service.py | Receivables & Loans | Finance Backend | Loan group orchestration. |
| finance_app/services/ml_gateway_service.py | ML Suggestions | Finance Backend | ML gateway + fallback orchestration. |
| finance_app/services/ml_service.py | ML Suggestions | Finance Backend | Suggestion feature computation. |
| finance_app/services/user_model_service.py | ML Suggestions | Finance Backend | Per-user ML model training and lookup. |
| finance_app/services/rate_limit_service.py | Core Platform | Finance Backend | Rate limit buckets. |
