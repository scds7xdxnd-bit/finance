"""Training entrypoint for the Account Risk classifier baseline model."""
from __future__ import annotations

import json
import os
import random
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

from ..common import settings
from ..data import preprocess, schema, split
from ..data.features import build_features as feature_module
from ..data.loaders import load_csv
from . import registry


def _current_git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):  # pragma: no cover - git optional
        return None
    return result.stdout.strip()


def _ensure_artifact_dir(run_id: str) -> Path:
    root = Path(os.getenv("ARTIFACT_DIR", "./src/models/artifacts"))
    path = root / settings.MODEL_NAME / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _compute_classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_prob: np.ndarray,
    prefix: str,
) -> Dict[str, float]:
    return {
        f"{prefix}_accuracy": accuracy_score(y_true, y_pred),
        f"{prefix}_precision": precision_score(y_true, y_pred, zero_division=0),
        f"{prefix}_recall": recall_score(y_true, y_pred, zero_division=0),
        f"{prefix}_f1": f1_score(y_true, y_pred, zero_division=0),
        f"{prefix}_roc_auc": roc_auc_score(y_true, y_prob),
    }


def main() -> None:
    seed = int(os.getenv("SEED", "42"))
    random.seed(seed)
    np.random.seed(seed)

    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    data_path = data_dir / settings.DEFAULT_DATA_FILENAME

    df, invalid_rows = load_csv(data_path, require_label=True, drop_invalid=True)
    if df.empty:
        raise RuntimeError("Training aborted: no valid rows in training dataset")

    cleaned = preprocess.clean_dataframe(df, require_label=True)
    train_df, val_df, test_df = split.stratified_split(cleaned, seed=seed)

    feature_columns = list(schema.FEATURE_COLUMNS)
    X_train = train_df[feature_columns]
    y_train = train_df[schema.TARGET_COLUMN].to_numpy()
    X_val = val_df[feature_columns]
    y_val = val_df[schema.TARGET_COLUMN].to_numpy()
    X_test = test_df[feature_columns]
    y_test = test_df[schema.TARGET_COLUMN].to_numpy()

    transformer = feature_module.build_feature_transformer()
    X_train_transformed, transformer = feature_module.fit_transformer(transformer, X_train)
    X_val_transformed = feature_module.apply_transformer(transformer, X_val)
    X_test_transformed = feature_module.apply_transformer(transformer, X_test)

    model = LogisticRegression(
        random_state=seed,
        max_iter=500,
        class_weight="balanced",
        solver="lbfgs",
    )

    start_time = time.time()
    model.fit(X_train_transformed, y_train)
    training_duration = time.time() - start_time

    val_predictions = model.predict(X_val_transformed)
    val_probabilities = model.predict_proba(X_val_transformed)[:, 1]
    test_predictions = model.predict(X_test_transformed)
    test_probabilities = model.predict_proba(X_test_transformed)[:, 1]

    metrics = {}
    metrics.update(_compute_classification_metrics(y_val, val_predictions, val_probabilities, "val"))
    metrics.update(_compute_classification_metrics(y_test, test_predictions, test_probabilities, "test"))

    run_id = datetime.utcnow().strftime("run_%Y%m%d_%H%M%S")
    artifact_dir = _ensure_artifact_dir(run_id)

    joblib.dump(model, artifact_dir / "model.joblib")
    joblib.dump(transformer, artifact_dir / "transformer.joblib")

    metrics_path = artifact_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))

    git_sha = _current_git_sha()

    metadata = {
        "model_name": settings.MODEL_NAME,
        "run_id": run_id,
        "seed": seed,
        "git_sha": git_sha,
        "data_path": str(data_path.resolve()),
        "feature_columns": feature_columns,
        "invalid_row_count": len(invalid_rows),
        "primary_metric_name": settings.PRIMARY_METRIC_NAME,
        "training_duration_seconds": training_duration,
    }

    model_card = {
        "model_name": settings.MODEL_NAME,
        "version": None,
        "run_id": run_id,
        "data_window": "synthetic-sample",
        "metrics": metrics,
        "training_time_seconds": training_duration,
        "git_sha": git_sha,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    (artifact_dir / "model_card.json").write_text(json.dumps(model_card, indent=2))

    version = registry.register(str(artifact_dir), metrics, metadata)

    model_card["version"] = version
    model_card["model_name"] = settings.MODEL_NAME
    (artifact_dir / "model_card.json").write_text(json.dumps(model_card, indent=2))

    summary = {
        "model_name": settings.MODEL_NAME,
        "version": version,
        "run_id": run_id,
        "artifact_dir": str(artifact_dir),
        "metrics": metrics,
        "invalid_row_count": len(invalid_rows),
        "primary_metric_name": settings.PRIMARY_METRIC_NAME,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
