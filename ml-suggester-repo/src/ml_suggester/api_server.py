"""FastAPI service for the ml-suggester account prediction models."""
from __future__ import annotations

import datetime
import hashlib
import os
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, validator

from .features import feature_target_split, prepare_dataframe


def _default_model_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


MODEL_ROOT = Path(os.getenv("MLSUGGESTER_MODEL_ROOT", _default_model_root()))
MODEL_LOCK = Lock()
MODEL_CACHE: Dict[str, Dict[str, object]] = {}


def _scan_default_models(root: Path) -> Dict[str, Path]:
    registry: Dict[str, Path] = {}
    for candidate in root.glob("models_*/model.joblib"):
        currency = candidate.parent.name.split("_", 1)[1].upper()
        registry[currency] = candidate
    models_dir = root / "models"
    if models_dir.exists():
        for child in models_dir.iterdir():
            if child.is_dir():
                currency = child.name.upper()
                candidate = child / "model.joblib"
                if candidate.exists():
                    registry[currency] = candidate
    return registry


MODEL_PATHS = _scan_default_models(MODEL_ROOT)


def _resolve_model_path(currency: str) -> Path:
    currency = currency.upper()
    if currency in MODEL_PATHS:
        return MODEL_PATHS[currency]
    # fall back to conventional directory names
    candidates = [
        MODEL_ROOT / f"models_{currency.lower()}" / "model.joblib",
        MODEL_ROOT / "models" / currency.lower() / "model.joblib",
        MODEL_ROOT / "models" / currency.upper() / "model.joblib",
    ]
    for path in candidates:
        if path.exists():
            MODEL_PATHS[currency] = path
            return path
    raise FileNotFoundError(f"No model.joblib found for currency '{currency}'.")


def _load_model(currency: str):
    currency = currency.upper()
    if currency in MODEL_CACHE:
        return MODEL_CACHE[currency]
    with MODEL_LOCK:
        if currency in MODEL_CACHE:
            return MODEL_CACHE[currency]
        path = _resolve_model_path(currency)
        model = joblib.load(path)
        classes = getattr(model, "_classes", None)
        if classes is None:
            clf = getattr(model, "named_steps", {}).get("clf") if hasattr(model, "named_steps") else None
            classes = getattr(clf, "classes_", None)
        if classes is None:
            raise RuntimeError(f"Model at {path} does not expose class labels.")
        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()[:12]
        MODEL_CACHE[currency] = {
            "model": model,
            "classes": np.array(classes),
            "version": digest,
            "path": path,
        }
        return MODEL_CACHE[currency]


class TransactionLine(BaseModel):
    date: datetime.date = Field(..., description="ISO date of the transaction line")
    description: str = Field(..., description="Free-text memo or narration")
    line_type: str = Field(..., description="debit or credit")
    amount: float = Field(..., description="Signed amount for the line")
    transaction_total_debit: Optional[float] = Field(None, description="Total debit for the parent transaction")
    transaction_total_credit: Optional[float] = Field(None, description="Total credit for the parent transaction")
    relative_amount: float = Field(..., description="Amount divided by the transaction total")
    is_max_line: Optional[bool] = Field(False, description="Whether this line is the largest within its transaction")
    num_debit_lines: int = Field(..., ge=0, description="Number of debit lines in the transaction")
    num_credit_lines: int = Field(..., ge=0, description="Number of credit lines in the transaction")
    transaction_id: Optional[str] = Field(None, description="Optional upstream transaction identifier")
    line_id: Optional[str] = Field(None, description="Optional upstream line identifier")

    @validator("line_type")
    def _validate_line_type(cls, value: str) -> str:
        if value is None:
            raise ValueError("line_type is required")
        value = value.strip().lower()
        if value not in {"debit", "credit", "total", "unknown"}:
            raise ValueError("line_type must be one of: debit, credit, total, unknown")
        return value


class PredictRequest(BaseModel):
    currency: str = Field(..., description="Three-letter ISO currency code")
    top_k: int = Field(3, ge=1, le=10, description="Number of account suggestions to return")
    lines: List[TransactionLine]

    @validator("currency")
    def _validate_currency(cls, value: str) -> str:
        if len(value.strip()) != 3:
            raise ValueError("currency must be a 3-letter ISO code")
        return value.strip().upper()


class Prediction(BaseModel):
    account_name: str
    probability: float


class LinePrediction(BaseModel):
    input_index: int
    transaction_id: str
    line_id: str
    predictions: List[Prediction]


class PredictResponse(BaseModel):
    currency: str
    top_k: int
    model_version: str
    model_path: str
    results: List[LinePrediction]


app = FastAPI(title="ml-suggester API", version="1.0.0")


@app.get("/healthz")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/predict", response_model=PredictResponse)
def predict(payload: PredictRequest) -> PredictResponse:
    if not payload.lines:
        raise HTTPException(status_code=400, detail="lines cannot be empty")
    model_bundle = _load_model(payload.currency)
    model = model_bundle["model"]
    classes = model_bundle["classes"]
    top_k = min(payload.top_k, len(classes))

    records = []
    meta: List[tuple[int, str, str]] = []
    for idx, line in enumerate(payload.lines):
        transaction_id = line.transaction_id or f"txn-{idx}"
        line_id = line.line_id or f"{transaction_id}-line-{idx}"
        record = {
            "Transaction_ID": transaction_id,
            "Line_ID": line_id,
            "Date": line.date.isoformat(),
            "Description": line.description,
            "Account_Name": "__PREDICT__",
            "Currency": payload.currency,
            "Line_Type": line.line_type,
            "Amount": line.amount,
            "Transaction_Total_Debit": line.transaction_total_debit if line.transaction_total_debit is not None else 0.0,
            "Transaction_Total_Credit": line.transaction_total_credit if line.transaction_total_credit is not None else 0.0,
            "Relative_Amount": line.relative_amount,
            "Is_Max_Line": bool(line.is_max_line),
            "Num_Debit_Lines": line.num_debit_lines,
            "Num_Credit_Lines": line.num_credit_lines,
        }
        records.append(record)
        meta.append((idx, transaction_id, line_id))

    df = pd.DataFrame(records)
    try:
        prepared = prepare_dataframe(df)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Feature preparation failed: {exc}")

    if prepared.empty:
        raise HTTPException(status_code=400, detail="No usable rows after preprocessing.")

    try:
        X, _ = feature_target_split(prepared)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Feature split failed: {exc}")

    try:
        proba = model.predict_proba(X)
    except Exception:
        decision = model.decision_function(X)
        exp = np.exp(decision - decision.max(axis=1, keepdims=True))
        proba = exp / exp.sum(axis=1, keepdims=True)

    proba = np.asarray(proba)
    if proba.ndim != 2 or proba.shape[1] != len(classes):
        raise HTTPException(status_code=500, detail="Model probability output mismatches class labels")

    top_indices = np.argsort(-proba, axis=1)[:, :top_k]
    top_scores = np.take_along_axis(proba, top_indices, axis=1)
    top_labels = classes[top_indices]

    results: List[LinePrediction] = []
    for i, (input_index, transaction_id, line_id) in enumerate(meta):
        preds = [
            Prediction(account_name=str(top_labels[i, j]), probability=float(top_scores[i, j]))
            for j in range(top_k)
        ]
        results.append(
            LinePrediction(
                input_index=input_index,
                transaction_id=transaction_id,
                line_id=line_id,
                predictions=preds,
            )
        )

    return PredictResponse(
        currency=payload.currency,
        top_k=top_k,
        model_version=model_bundle["version"],
        model_path=str(model_bundle["path"]),
        results=results,
    )
