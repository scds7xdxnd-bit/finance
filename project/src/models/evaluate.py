"""Evaluation entrypoint for registered models."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

import joblib
import numpy as np
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

from ..common import settings
from ..data import schema, split
from ..data.features import build_features as feature_module
from ..data.loaders import load_csv
from ..data.preprocess import clean_dataframe
from . import registry


def _metric_bundle(prefix: str, y_true: np.ndarray, y_pred: np.ndarray, y_prob: np.ndarray) -> Dict[str, float]:
    return {
        f"{prefix}_accuracy": accuracy_score(y_true, y_pred),
        f"{prefix}_precision": precision_score(y_true, y_pred, zero_division=0),
        f"{prefix}_recall": recall_score(y_true, y_pred, zero_division=0),
        f"{prefix}_f1": f1_score(y_true, y_pred, zero_division=0),
        f"{prefix}_roc_auc": roc_auc_score(y_true, y_prob),
    }


def _slice_metrics(merchant_series, y_true, y_pred):
    metrics = {}
    for merchant in sorted(merchant_series.unique()):
        mask = merchant_series == merchant
        if mask.sum() == 0:
            continue
        y_true_slice = y_true[mask]
        y_pred_slice = y_pred[mask]
        metrics[merchant] = {
            "count": int(mask.sum()),
            "accuracy": accuracy_score(y_true_slice, y_pred_slice),
            "precision": precision_score(y_true_slice, y_pred_slice, zero_division=0),
            "recall": recall_score(y_true_slice, y_pred_slice, zero_division=0),
            "f1": f1_score(y_true_slice, y_pred_slice, zero_division=0),
        }
    return metrics


def main() -> None:
    seed = int(os.getenv("SEED", "42"))
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    data_path = data_dir / settings.DEFAULT_DATA_FILENAME

    entry = registry.get_registry_entry(settings.MODEL_NAME)
    artifact_dir = Path(entry["artifact_path"])
    model = joblib.load(artifact_dir / "model.joblib")
    transformer = joblib.load(artifact_dir / "transformer.joblib")

    df, _ = load_csv(data_path, require_label=True, drop_invalid=True)
    cleaned = clean_dataframe(df, require_label=True)
    _, _, test_df = split.stratified_split(cleaned, seed=seed)

    feature_columns = list(schema.FEATURE_COLUMNS)
    X_test = test_df[feature_columns]
    y_test = test_df[schema.TARGET_COLUMN].to_numpy()
    X_test_transformed = feature_module.apply_transformer(transformer, X_test)

    y_pred = model.predict(X_test_transformed)
    y_prob = model.predict_proba(X_test_transformed)[:, 1]

    metrics = _metric_bundle("test", y_test, y_pred, y_prob)
    metrics[settings.PRIMARY_METRIC_NAME] = entry["metrics"].get(settings.PRIMARY_METRIC_NAME)

    slice_metrics = _slice_metrics(test_df["merchant_type"], y_test, y_pred)

    evaluation_report = {
        "model_name": settings.MODEL_NAME,
        "version": entry["version"],
        "artifact_dir": str(artifact_dir),
        "metrics": metrics,
        "slices": slice_metrics,
    }

    output_path = artifact_dir / "evaluation.json"
    output_path.write_text(json.dumps(evaluation_report, indent=2))
    print(json.dumps(evaluation_report, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
