# Data Schema

| Column | Type | Allowed values / range | Nullable | PII | Notes |
| --- | --- | --- | --- | --- | --- |
| `transaction_id` | string (<=64) | ASCII, no whitespace-only | no | masked (hash/last4) | Unique transaction primary key. |
| `account_id` | string (<=64) | ASCII, no whitespace-only | no | masked (hash/last4) | Customer account identifier. |
| `amount` | float64 | [-1_000_000, 1_000_000] | no | no | Normalized currency amount in account currency. |
| `merchant_type` | category | {utilities, payroll, supplies, travel, software} | no | no | Lowercase normalized categories. |
| `transaction_hour` | int32 | 0–23 | no | no | Hour of day in UTC. |
| `risk_label` | int8 | {0, 1} | no (training) | no | Fraud / anomaly label. Absent in inference payloads. |

## PII Handling

- `transaction_id` and `account_id` must be masked or hashed before data leaves secure zones. Downstream outputs echo the identifiers for traceability; consumers must enforce masking policies.
- No additional direct PII fields are present.

## Data Quality & Drift Checks (future work)

- **Population stability**: compute PSI on `amount` histogram buckets and one-hot merchant distribution; alert if PSI > 0.2.
- **Volume**: compare daily row count against trailing 7-day average; alert if outside ±15%.
- **Target leakage**: monitor label rate; alert if class balance shifts more than ±10% absolute.
- **Schema**: verify no new columns, dtype shifts, or enum expansions prior to ingestion.
- **Anomaly detection**: flag if >1% rows fail schema validation within loaders.
