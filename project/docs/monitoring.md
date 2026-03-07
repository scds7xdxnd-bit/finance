# Monitoring Plan

## Online Service Observability

Log per-request structured records including:
- `request_id`, `model_version`, `latency_ms`, `record_count`, HTTP status code.
- Count validation failures separately (`error_code=INVALID_REQUEST`) to spot contract drift.
- Capture score distribution summaries (min/median/max) for sliding windows to feed drift detectors.

Metrics to export (e.g., Prometheus):
- Request throughput (`predict_requests_total`).
- Latency histogram (`predict_latency_seconds_bucket`).
- Success vs. error counts, keyed by `error_code`.
- Input validation error rate.

## Batch Job Monitoring

For each run of `service_batch` record:
- Row count processed vs. invalid row count.
- Runtime duration; alert if exceeding `BATCH_MAX_ROWS` SLA or time budget.
- Output parquet summary stats (mean/std of probability, class distribution) for regression to the mean detection.

## Drift & Data Quality Outline

- Daily job dumps histograms of `amount` and categorical frequencies to object storage.
- Compute PSI between latest and trailing-30-day reference; alert if PSI > 0.2 for any feature.
- Track target rate (`risk_label` mean) in training/evaluation datasets; flag deviations above ±10%.
- Integrate with registry metadata so each deployed model stores the reference distribution snapshot for comparison.
