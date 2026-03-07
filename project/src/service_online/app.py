"""FastAPI application exposing the online inference endpoint."""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict

import joblib
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..common import settings
from ..data import schema
from ..data.features import build_features as feature_module
from ..data.preprocess import clean_dataframe
from ..models import registry
from .validators import PredictionRequest, PredictionResponse, validate_request

logger = logging.getLogger("service_online")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Account Risk Classifier Service")


class ModelBundle:
    def __init__(self, model, transformer, entry: Dict[str, Any]):
        self.model = model
        self.transformer = transformer
        self.entry = entry


_MODEL_BUNDLE: ModelBundle | None = None


def _load_model_bundle(selector: str = "best") -> ModelBundle:
    entry = registry.select_entry(settings.MODEL_NAME, selector=selector)
    artifact_dir = Path(entry["artifact_path"])
    model = joblib.load(artifact_dir / "model.joblib")
    transformer = joblib.load(artifact_dir / "transformer.joblib")
    return ModelBundle(model=model, transformer=transformer, entry=entry)


def _get_bundle() -> ModelBundle:
    global _MODEL_BUNDLE
    if os.getenv("HOT_RELOAD_MODEL") == "1":
        _MODEL_BUNDLE = _load_model_bundle()
    if _MODEL_BUNDLE is None:
        _MODEL_BUNDLE = _load_model_bundle()
    return _MODEL_BUNDLE


@app.on_event("startup")
async def startup_event() -> None:
    bundle = _get_bundle()
    logger.info(
        "model_loaded",
        extra={"model_name": settings.MODEL_NAME, "model_version": bundle.entry["version"]},
    )


@app.get("/healthz")
async def healthz() -> Dict[str, Any]:
    bundle = _get_bundle()
    return {
        "status": "ok",
        "model_name": settings.MODEL_NAME,
        "model_version": bundle.entry["version"],
    }


@app.post("/predict")
async def predict(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
        validated: PredictionRequest = validate_request(payload)
    except ValidationError as exc:
        request_id = payload.get("request_id") if isinstance(payload, dict) else str(uuid.uuid4())
        logger.warning("validation_error", extra={"request_id": request_id, "errors": exc.errors()})
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "error_code": "INVALID_REQUEST",
                "message": exc.errors(),
                "request_id": str(request_id),
            },
        )
    except Exception as exc:
        req_id = str(uuid.uuid4())
        logger.exception("payload_parse_failure", extra={"request_id": req_id})
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "error_code": "INVALID_REQUEST",
                "message": str(exc),
                "request_id": req_id,
            },
        )

    bundle = _get_bundle()
    feature_columns = list(schema.FEATURE_COLUMNS)

    records = [record.model_dump() for record in validated.records]
    df = pd.DataFrame(records)
    invalid = schema.validate_dataframe(df, require_label=False)
    if invalid:
        logger.warning("schema_validation_failed", extra={"request_id": validated.request_id, "invalid": invalid})
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "error_code": "INVALID_REQUEST",
                "message": invalid,
                "request_id": validated.request_id,
            },
        )

    cleaned = clean_dataframe(df, require_label=False)
    transformed = feature_module.apply_transformer(bundle.transformer, cleaned[feature_columns])
    probabilities = bundle.model.predict_proba(transformed)[:, 1]
    predictions = bundle.model.predict(transformed)

    response_payload = PredictionResponse(
        request_id=validated.request_id,
        model_name=settings.MODEL_NAME,
        model_version=bundle.entry["version"],
        predictions=[
            {
                "transaction_id": record.transaction_id,
                "prediction": int(pred),
                "probability": float(prob),
                "request_id": str(uuid.uuid4()),
            }
            for record, pred, prob in zip(validated.records, predictions, probabilities)
        ],
    ).model_dump()

    logger.info(
        "prediction_completed",
        extra={
            "request_id": validated.request_id,
            "model_version": bundle.entry["version"],
            "record_count": len(validated.records),
        },
    )

    return JSONResponse(response_payload)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):  # pragma: no cover - emergency path
    req_id = str(uuid.uuid4())
    logger.exception("unhandled_error", extra={"request_id": req_id})
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error_code": "INTERNAL_ERROR",
            "message": str(exc),
            "request_id": req_id,
        },
    )
