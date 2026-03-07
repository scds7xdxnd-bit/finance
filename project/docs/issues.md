# Known Issues & Follow-ups

- Automate PSI and data quality checks inside a scheduled monitoring notebook or pipeline (currently manual placeholder).
- Implement secure secrets management for future DB/API loaders; `.env.sample` only covers local usage.
- Add authentication/authorization for the FastAPI service before exposing externally.
- Extend streaming consumer with an actual queue connector (Kafka / PubSub) and dead-letter persistence instead of stderr.
- Evaluate LightGBM and neural baselines once more data becomes available; update registry metadata with calibration metrics.
