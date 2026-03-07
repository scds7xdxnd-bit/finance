"""Streaming inference stub for online or queue-based processing."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

import joblib
import pandas as pd

from ..common import settings
from ..data import schema
from ..data.features import build_features as feature_module
from ..data.preprocess import clean_dataframe
from . import registry


def _load_artifacts(model_selector: str) -> Tuple[Any, Any, Dict[str, Any]]:
    entry = registry.select_entry(settings.MODEL_NAME, selector=model_selector)
    artifact_dir = Path(entry["artifact_path"])
    model = joblib.load(artifact_dir / "model.joblib")
    transformer = joblib.load(artifact_dir / "transformer.joblib")
    return model, transformer, entry


def _process_batch(
    buffer: List[Dict[str, Any]],
    model,
    transformer,
    model_version: int,
) -> None:
    df = pd.DataFrame(buffer)
    invalid = schema.validate_dataframe(df, require_label=False)
    if invalid:
        sys.stderr.write(json.dumps({"invalid": invalid}, indent=2) + "\n")
        return
    cleaned = clean_dataframe(df, require_label=False)
    feature_columns = list(schema.FEATURE_COLUMNS)
    transformed = feature_module.apply_transformer(transformer, cleaned[feature_columns])
    probs = model.predict_proba(transformed)[:, 1]
    preds = model.predict(transformed)
    for original, pred, prob in zip(buffer, preds, probs):
        response = {
            "transaction_id": original.get("transaction_id"),
            "account_id": original.get("account_id"),
            "prediction": int(pred),
            "probability": float(prob),
            "model_version": model_version,
            "request_id": str(uuid.uuid4()),
        }
        print(json.dumps(response))


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Streaming inference stub")
    parser.add_argument(
        "--model",
        dest="model_selector",
        default="best",
        help="Model version to load (default: best)",
    )
    parser.add_argument(
        "--batch-size",
        dest="batch_size",
        type=int,
        default=32,
        help="Micro-batch size for processing",
    )
    args = parser.parse_args(argv)

    model, transformer, entry = _load_artifacts(args.model_selector)
    buffer: List[Dict[str, Any]] = []

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            sys.stderr.write(json.dumps({"error": "invalid_json", "line": line}) + "\n")
            continue
        buffer.append(record)
        if len(buffer) >= args.batch_size:
            _process_batch(buffer, model, transformer, entry["version"])
            buffer = []

    if buffer:
        _process_batch(buffer, model, transformer, entry["version"])

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
