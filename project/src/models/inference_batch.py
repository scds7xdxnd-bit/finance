"""Batch inference entrypoint for the Account Risk classifier."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import joblib
import pandas as pd

from ..common import settings
from ..data import schema
from ..data.features import build_features as feature_module
from ..data.loaders import load_csv, load_parquet
from ..data.preprocess import clean_dataframe
from . import registry


class DataValidationError(Exception):
    """Raised when batch inputs fail schema validation."""

    def __init__(self, issues: Iterable[dict]):
        super().__init__("Input data failed schema validation")
        self.issues = list(issues)


def _load_artifacts(model_selector: str) -> Tuple[Any, Any, Dict[str, Any]]:
    entry = registry.select_entry(settings.MODEL_NAME, selector=model_selector)
    artifact_dir = Path(entry["artifact_path"])
    model = joblib.load(artifact_dir / "model.joblib")
    transformer = joblib.load(artifact_dir / "transformer.joblib")
    return model, transformer, entry


def _load_input(path: Path) -> Tuple[pd.DataFrame, list[dict]]:
    if path.suffix.lower() == ".csv":
        return load_csv(path, require_label=False, drop_invalid=False)
    if path.suffix.lower() in {".parquet", ".pq"}:
        return load_parquet(path, require_label=False, drop_invalid=False)
    raise ValueError("Unsupported input format. Use CSV or Parquet.")


def run_batch_inference(
    input_path: Path | str,
    output_path: Path | str,
    model_selector: str = "best",
) -> Dict[str, Any]:
    """Execute batch inference and return a summary payload."""

    input_path = Path(input_path)
    output_path = Path(output_path)

    df, invalid_rows = _load_input(input_path)
    if invalid_rows:
        raise DataValidationError(invalid_rows)

    cleaned = clean_dataframe(df, require_label=False)
    feature_columns = list(schema.FEATURE_COLUMNS)
    features = cleaned[feature_columns]

    model, transformer, entry = _load_artifacts(model_selector)
    transformed = feature_module.apply_transformer(transformer, features)
    predictions = model.predict(transformed)
    probabilities = model.predict_proba(transformed)[:, 1]

    result = cleaned[list(schema.IDENTIFIER_COLUMNS)].copy()
    result["prediction"] = predictions
    result["probability"] = probabilities
    result["model_version"] = entry["version"]
    result["request_id"] = [str(uuid.uuid4()) for _ in range(len(result))]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output_path, index=False)

    summary = {
        "rows": int(len(result)),
        "output": str(output_path),
        "model_version": entry["version"],
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run batch inference")
    parser.add_argument("--in", dest="input_path", required=True, help="Input file path")
    parser.add_argument("--out", dest="output_path", required=True, help="Output Parquet path")
    parser.add_argument(
        "--model",
        dest="model_selector",
        default="best",
        help="Model version to load (default: best)",
    )
    args = parser.parse_args(argv)

    try:
        summary = run_batch_inference(args.input_path, args.output_path, args.model_selector)
    except DataValidationError as exc:
        sys.stderr.write(json.dumps({"invalid_rows": exc.issues}, indent=2) + "\n")
        return 2
    except Exception as exc:
        sys.stderr.write(json.dumps({"error": str(exc)}) + "\n")
        return 1

    print(json.dumps(summary, indent=2))
    return 0


__all__ = ["run_batch_inference", "DataValidationError", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
