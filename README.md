# Flask Finance App (vNext Baseline)

## Prerequisites
- Python 3.10+
- `pip`
- SQLite (default local DB)

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest
```

## Configuration
```bash
cp .env.example .env
```
Then edit `.env` for your local environment.

## Run App
```bash
python wsgi.py
```
Default URL: `http://127.0.0.1:5000`

## Database Migrations
```bash
alembic upgrade head
```

## vNext Migration Smoke
```bash
python scripts/migration_smoke_vnext.py
```

## Key Tests
```bash
pytest -q tests/test_schema_guard_service.py
pytest -q tests/test_transaction_import_idempotency.py
pytest -q tests/test_trial_balance_service.py tests/test_statement_data.py tests/test_ranked_reporting_cutover.py
```

## Operator / Program Docs
- `project/docs/operator_runbook.md`
- `project/docs/qa_gate_invariants.md`
- `project/docs/decisions.md`
- `project/docs/schema_capability_matrix_vnext.md`
