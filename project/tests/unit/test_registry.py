from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.common import settings


def _create_artifact_dir(base: Path, version: int) -> Path:
    run_dir = base / f"run_v{version}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "model.joblib").write_text("stub")
    (run_dir / "transformer.joblib").write_text("stub")
    (run_dir / "metrics.json").write_text(
        json.dumps({settings.PRIMARY_METRIC_NAME: 0.5 + 0.1 * version})
    )
    return run_dir


def test_register_and_get_best(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    from src.models import registry  # import after env patch

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    registry.DEFAULT_ARTIFACT_DIR = artifact_root
    registry.REGISTRY_INDEX_PATH = artifact_root / "registry.json"

    artifact_dir = artifact_root / settings.MODEL_NAME
    first = _create_artifact_dir(artifact_dir, 1)
    second = _create_artifact_dir(artifact_dir, 2)

    metadata = {
        "model_name": settings.MODEL_NAME,
        "run_id": "run1",
        "primary_metric_name": settings.PRIMARY_METRIC_NAME,
    }
    version1 = registry.register(str(first), {settings.PRIMARY_METRIC_NAME: 0.6}, metadata)
    metadata2 = {
        "model_name": settings.MODEL_NAME,
        "run_id": "run2",
        "primary_metric_name": settings.PRIMARY_METRIC_NAME,
    }
    version2 = registry.register(str(second), {settings.PRIMARY_METRIC_NAME: 0.8}, metadata2)

    assert version1 == 1
    assert version2 == 2
    best_path = registry.get_best(settings.MODEL_NAME)
    assert best_path == str(second)


def test_get_best_raises_for_missing_model(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))
    from src.models import registry

    registry.DEFAULT_ARTIFACT_DIR = tmp_path
    registry.REGISTRY_INDEX_PATH = tmp_path / "registry.json"

    with pytest.raises(ValueError):
        registry.get_best("missing")
