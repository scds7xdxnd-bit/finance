"""Centralised project-wide constants to avoid duplication."""
from __future__ import annotations

MODEL_NAME = "account_risk_classifier"
DEFAULT_DATA_FILENAME = "transactions.csv"
PRIMARY_METRIC_NAME = "val_f1"

__all__ = ["MODEL_NAME", "DEFAULT_DATA_FILENAME", "PRIMARY_METRIC_NAME"]
