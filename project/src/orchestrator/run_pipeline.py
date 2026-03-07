"""Orchestrator that chains training and evaluation steps."""
from __future__ import annotations

import json
from typing import Dict

from ..common import settings
from ..models import evaluate, registry, train


def main() -> int:
    pipeline_log: Dict[str, Dict] = {}

    try:
        train.main()
        pipeline_log["train"] = {"status": "completed"}
    except Exception as exc:
        pipeline_log["train"] = {"status": "failed", "message": str(exc)}
        print(json.dumps(pipeline_log, indent=2))
        return 1

    try:
        evaluate.main()
        pipeline_log["evaluate"] = {"status": "completed"}
    except Exception as exc:
        pipeline_log["evaluate"] = {"status": "failed", "message": str(exc)}
        print(json.dumps(pipeline_log, indent=2))
        return 2

    entry = registry.get_registry_entry(settings.MODEL_NAME)
    pipeline_log["register"] = {
        "status": "completed",
        "model_name": settings.MODEL_NAME,
        "version": entry["version"],
        "primary_metric": entry["metrics"].get(entry.get("primary_metric_name")),
    }

    print(json.dumps(pipeline_log, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
