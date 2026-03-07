"""Minimal model registry with optional MLflow integration."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import mlflow  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    mlflow = None

DEFAULT_ARTIFACT_DIR = Path(os.getenv("ARTIFACT_DIR", "./src/models/artifacts"))
REGISTRY_INDEX_PATH = DEFAULT_ARTIFACT_DIR / "registry.json"


def _load_registry() -> Dict[str, Any]:
    if not REGISTRY_INDEX_PATH.exists():
        return {"models": {}}
    return json.loads(REGISTRY_INDEX_PATH.read_text())


def _save_registry(registry: Dict[str, Any]) -> None:
    REGISTRY_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_INDEX_PATH.write_text(json.dumps(registry, indent=2))


def _next_version(model_entries: Dict[str, Any]) -> int:
    versions = model_entries.get("versions", [])
    return len(versions) + 1


def select_entry(
    model_name: str,
    selector: str = "best",
    criterion: str = "primary_metric",
) -> Dict[str, Any]:
    """Return the registry entry matching the selector."""

    registry = _load_registry()
    model_entries = registry["models"].get(model_name)
    if not model_entries:
        raise ValueError(f"No entries found for model '{model_name}'")

    versions = model_entries["versions"]
    if selector != "best":
        try:
            requested_version = int(selector)
        except ValueError as exc:
            raise ValueError("Model selector must be 'best' or an integer") from exc
        for entry in versions:
            if entry["version"] == requested_version:
                return entry
        raise ValueError(f"Version {requested_version} not found for model '{model_name}'")

    best_entry = None
    best_score = float("-inf")
    for entry in versions:
        if criterion == "primary_metric":
            metric_name = entry.get("primary_metric_name")
            score = entry.get("metrics", {}).get(metric_name) if metric_name else None
        else:
            score = entry.get("metrics", {}).get(criterion)
        if score is None:
            continue
        if best_entry is None or score >= best_score:
            best_entry = entry
            best_score = score

    if best_entry is None:
        raise ValueError(
            f"No suitable entry found for model '{model_name}' and criterion '{criterion}'"
        )

    return best_entry


def register(
    model_artifact_path: str,
    metrics: Dict[str, float],
    metadata: Dict[str, Any],
) -> int:
    """Register a model artifact and return the assigned version id."""

    model_name = metadata.get("model_name")
    if not model_name:
        raise ValueError("metadata.model_name is required for registration")

    registry = _load_registry()
    model_entries = registry["models"].setdefault(model_name, {"versions": []})
    version = _next_version(model_entries)

    primary_metric_name = metadata.get("primary_metric_name")
    if primary_metric_name is None and metrics:
        primary_metric_name = sorted(metrics.keys())[0]

    entry = {
        "version": version,
        "artifact_path": model_artifact_path,
        "metrics": metrics,
        "metadata": metadata,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "primary_metric_name": primary_metric_name,
        "primary_metric": metrics.get(primary_metric_name) if primary_metric_name else None,
    }

    model_entries["versions"].append(entry)
    _save_registry(registry)

    if os.getenv("USE_MLFLOW") == "1" and mlflow:  # pragma: no cover - external side-effect
        with mlflow.start_run(run_name=f"{model_name}-v{version}"):
            mlflow.log_metrics(metrics)
            for key, value in metadata.items():
                if isinstance(value, (str, int, float)):
                    mlflow.log_param(key, value)
            mlflow.log_artifacts(model_artifact_path)

    return version


def get_registry_entry(model_name: str, version: Optional[int] = None) -> Dict[str, Any]:
    registry = _load_registry()
    model_entries = registry["models"].get(model_name)
    if not model_entries:
        raise ValueError(f"No entries found for model '{model_name}'")

    versions = model_entries["versions"]
    if version is None:
        return versions[-1]

    for entry in versions:
        if entry["version"] == version:
            return entry
    raise ValueError(f"Version {version} not found for model '{model_name}'")


def get_best(model_name: str, criterion: str = "primary_metric") -> str:
    """Return the artifact path for the best model under the given criterion."""

    entry = select_entry(model_name, selector="best", criterion=criterion)
    return entry["artifact_path"]


def list_versions(model_name: str) -> Dict[str, Any]:
    registry = _load_registry()
    model_entries = registry["models"].get(model_name)
    if not model_entries:
        raise ValueError(f"No entries found for model '{model_name}'")
    return model_entries


__all__ = [
    "register",
    "get_best",
    "get_registry_entry",
    "list_versions",
    "select_entry",
]
