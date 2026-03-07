# Account Risk Classifier Starter

**Assumptions:** Project name `Account Risk Classifier`, problem type `classification`, primary metric `F1`, data source `CSV/Parquet in ./data`, feature scope `numeric + categorical`, model family `sklearn-baseline`, latency goal `p95 < 150ms`, batch SLA `1M rows under 20 min`, security constraint `transaction_id/account_id masked before export`.

Goal: deliver a reproducible, production-friendly ML system skeleton for scoring account transactions.

## Scope

**In scope**: schema-checked data ingestion, deterministic training/evaluation, local registry, batch + FastAPI services, strict JSON contracts, smoke/contract/unit tests.

**Out of scope**: real data connectors, authn/z, advanced monitoring stack, infra-as-code.

## System at a Glance

```
[Data assets]
   ↓ loaders (schema + validation)
   ↓ preprocess (clean + mask)
   ↓ features (ColumnTransformer)
   ↓ train (LogReg) ──→ registry (JSON/MLflow)
                              ↓
      ┌────────────── batch service (CLI)
      └────────────── online service (FastAPI)
```

## Getting Started

```bash
python -m venv .venv && source .venv/bin/activate
make setup && python scripts/download_sample_data.py
make train && make eval && make smoke
make serve &
curl -X POST localhost:8000/predict \
  -H 'Content-Type: application/json' \
  -d '{"request_id":"demo","records":[{"transaction_id":"txn_demo","account_id":"acct_1","amount":123.4,"merchant_type":"utilities","transaction_hour":10}]}'
```

### Data Assumptions

- Synthetic sample data lives under `./data/transactions.csv`. Replace with your own by dropping a file with matching schema or by pointing `DATA_DIR` to an alternative folder.
- For external sources (DB/API), add loaders in `src/data/loaders.py` and make sure they emit the same column contract.

### Make Targets

- `make train` / `make eval` / `make batch` / `make serve` follow the documented artifact locations.
- `make smoke` spins up the synthetic dataset, trains, evaluates, runs the HTTP endpoint test suite.

### Configuration

- Copy `.env.sample` to `.env` and adjust `DATA_DIR`, `ARTIFACT_DIR`, or registry flags as needed.
- Set `HOT_RELOAD_MODEL=1` in dev to refresh the loaded model before each request.

## Repository Layout

- `docs/` — architecture, interfaces, standards, open issues.
- `src/data/` — schema, loaders, preprocessing, feature engineering.
- `src/models/` — training, evaluation, registry, inference runners.
- `src/service_online/` — FastAPI service with validation contracts.
- `src/service_batch/` — CLI for scheduled inference.
- `tests/` — smoke, contract, and unit suites ensuring regressions are caught early.
- `pipelines/` — declarative pipeline specs for automation.
