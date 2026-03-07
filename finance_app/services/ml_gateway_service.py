"""Service layer for ML suggestions and logging."""
import datetime
import secrets
import time
from typing import Any, Dict, List, Tuple

import requests
from sqlalchemy import func

from finance_app.extensions import db
from finance_app.models.accounting_models import Account, AccountSuggestionLog, SuggestionFeedback
from finance_app.services.ml_service import (
    _compute_ml_line_features,
    best_hint_suggestion,
    record_suggestion_hint,
)
from finance_app.services.user_model_service import predict_user_model, train_user_model


class MlGatewayError(Exception):
    """Base exception for ML gateway issues."""


def _normalize_weight(value, default=1, minimum=1):
    try:
        w = int(round(float(value)))
    except Exception:
        w = default
    if w < minimum:
        return minimum
    return w


def compute_suggestions(
    user_id: int,
    lines: List[Dict[str, Any]],
    target_line_id: str,
    description: str,
    currency: str,
    date_str: str,
    core_cfg: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Prepare features/context/payload and select model path (user-model, fallback to service, or hints)."""
    started_ts = time.perf_counter()
    transaction_id = f"temp-{user_id}-{int(time.time() * 1000)}-{secrets.token_hex(4)}"
    features, context = _compute_ml_line_features(
        date_str, description, currency, transaction_id, lines, target_line_id, user_id=user_id
    )
    request_id = f"{features['Transaction_ID']}:{features['Line_ID']}"
    line_payload = {
        "transaction_id": features["Transaction_ID"],
        "line_id": features["Line_ID"],
        "date": features["Date"],
        "description": features["Description"],
        "line_type": features["Line_Type"],
        "amount": features["Amount"],
        "transaction_total_debit": features["Transaction_Total_Debit"],
        "transaction_total_credit": features["Transaction_Total_Credit"],
        "relative_amount": features["Relative_Amount"],
        "is_max_line": features["Is_Max_Line"],
        "num_debit_lines": features["Num_Debit_Lines"],
        "num_credit_lines": features["Num_Credit_Lines"],
    }
    ml_payload = {
        "currency": features["Currency"],
        "top_k": core_cfg.get("top_k"),
        "lines": [line_payload],
    }
    meta = {
        "started_ts": started_ts,
        "request_id": request_id,
        "transaction_id": features["Transaction_ID"],
        "line_id": features["Line_ID"],
        "line_type": features["Line_Type"],
    }
    return features, context, {"payload": ml_payload, "meta": meta}


def try_user_model(user_id: int, line_type: str, description: str, top_k: int):
    """Return predictions from the per-user model if available."""
    try:
        preds, meta = predict_user_model(user_id, line_type, description, top_k=top_k)
        return preds, meta
    except Exception:
        return [], None


def call_ml_api(api_url: str, payload: Dict[str, Any], timeout: float, max_attempts: int = 2):
    """Call external ML API with basic retry."""
    attempts = 0
    last_exc = None
    while attempts < max_attempts:
        attempts += 1
        try:
            resp = requests.post(api_url, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json(), None
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            time.sleep(0.2 * attempts)
        except Exception as exc:
            last_exc = exc
            break
    return None, last_exc


def fallback_hint(user_id: int, line_type: str, description: str):
    """Return a hint-based suggestion payload."""
    suggestion = best_hint_suggestion(user_id, line_type, description)
    return [{"account_name": suggestion, "score": 0.0}] if suggestion else []


def handle_ml_response(features, context, ml_response, started_ts, request_id, top_k, model_meta=None):
    """Normalize ML response into API shape."""
    responded_at_dt = datetime.datetime.utcnow()
    latency_ms = int((time.perf_counter() - started_ts) * 1000)
    results = ml_response.get("results") or []
    first = results[0] if results else {}
    predictions = first.get("predictions") or []
    model_path = ml_response.get("model_path")
    model_version = ml_response.get("model_version")
    model_hash = ml_response.get("model_hash") or ml_response.get("model_version_hash")
    return {
        "ok": True,
        "currency": ml_response.get("currency", features["Currency"]),
        "top_k": ml_response.get("top_k", top_k),
        "model_version": model_version,
        "model_version_hash": model_hash,
        "model_hash": model_hash,
        "model_path": model_path,
        "transaction_id": features["Transaction_ID"],
        "line_id": features["Line_ID"],
        "line_type": features["Line_Type"],
        "predictions": predictions,
        "features": features,
        "context": context,
        "responded_at": responded_at_dt.isoformat() + "Z",
        "latency_ms": latency_ms,
        "request_id": request_id,
        "fallback": False,
        "error": None,
        "status": "ok",
    }


def log_suggestions(user_id: int, entries: List[Dict[str, Any]], default_currency: str, auto_train: bool, min_rows: int):
    """Persist suggestion logs, feedback, and hint updates. Returns saved count."""
    saved = 0
    for entry in entries:
        try:
            probability = entry.get("probability")
            probability_float = float(probability) if probability is not None else None
        except Exception:
            probability_float = None
        responded_at_raw = entry.get("responded_at") or entry.get("model_timestamp")
        responded_at = None
        if responded_at_raw:
            try:
                normalized = responded_at_raw.replace("Z", "+00:00")
                responded_at = datetime.datetime.fromisoformat(normalized)
                if responded_at.tzinfo is not None:
                    responded_at = responded_at.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            except Exception:
                responded_at = None
        raw_features = entry.get("features")
        if isinstance(raw_features, dict):
            raw_features = dict(raw_features)
        elif raw_features is None:
            raw_features = {}
        else:
            raw_features = {"value": raw_features}
        predictions = entry.get("predictions") or []
        chosen_account = (entry.get("chosen_account") or "").strip()
        chosen_rank = None
        for idx, pred in enumerate(predictions):
            pred_name = (pred.get("account_name") or "").strip()
            if pred_name and chosen_account and pred_name.lower() == chosen_account.lower():
                chosen_rank = idx + 1
                break
        reward_table = {1: 1.0, 2: 0.5, 3: 0.2}
        manual_reward = -1.0
        if chosen_rank:
            reward = reward_table.get(chosen_rank, 0.0)
            mrr = 1.0 / chosen_rank
        else:
            reward = manual_reward
            mrr = 0.0
        model_hash = entry.get("model_hash") or entry.get("model_version_hash")
        pred_rewards = []
        for idx, pred in enumerate(predictions[:3]):
            pred_name = (pred.get("account_name") or "").strip()
            pr_rank = idx + 1
            if chosen_rank and chosen_rank == pr_rank:
                pr_reward = reward
            else:
                pr_reward = {-1: 0.0, 1: -0.3, 2: -0.2, 3: -0.1}.get(pr_rank, -0.05)
            pred_rewards.append({"account_name": pred_name, "rank": pr_rank, "reward": pr_reward})
        status_value = entry.get("status") or ("fallback" if entry.get("fallback") else "ok")
        raw_features.update(
            {
                "final_amount": entry.get("final_amount"),
                "manual_override": bool(entry.get("manual_override")),
                "feedback_weight": entry.get("feedback_weight"),
                "lines_snapshot": entry.get("lines_snapshot"),
                "fallback": bool(entry.get("fallback")),
                "error": entry.get("error"),
                "error_code": entry.get("error_code"),
                "latency_ms": entry.get("latency_ms"),
                "client_latency_ms": entry.get("client_latency_ms"),
                "request_id": entry.get("request_id"),
                "logged_at": entry.get("logged_at"),
                "status": status_value,
                "model_version_hash": model_hash,
                "model_hash": model_hash,
                "model_version": entry.get("model_version"),
                "chosen_rank": chosen_rank,
                "reward": reward,
                "mrr": mrr,
                "prediction_rewards": pred_rewards,
            }
        )
        log = AccountSuggestionLog(
            user_id=user_id,
            currency=(entry.get("currency") or default_currency).upper(),
            transaction_id=entry.get("transaction_id"),
            line_id=entry.get("line_id"),
            line_type=(entry.get("line_type") or "").lower() or None,
            chosen_account=entry.get("chosen_account"),
            model_version=entry.get("model_version") or model_hash,
            model_path=entry.get("model_path"),
            probability=probability_float,
            raw_features=raw_features,
            predictions=entry.get("predictions"),
            description=entry.get("description"),
            entry_date=entry.get("date") or entry.get("entry_date"),
            responded_at=responded_at,
        )
        chosen_name = (entry.get("chosen_account") or "").strip()
        if chosen_name:
            try:
                matched = (
                    Account.query.filter(Account.user_id == user_id)
                    .filter(func.lower(Account.name) == chosen_name.lower())
                    .first()
                )
                if matched:
                    log.account_id = matched.id
            except Exception:
                pass
        db.session.add(log)
        saved += 1

        line_type = (entry.get("line_type") or "").strip().lower()
        description = entry.get("description") or ""
        if chosen_name and line_type in ("debit", "credit"):
            weight = _normalize_weight(entry.get("feedback_weight"), default=1, minimum=1)
            try:
                record_suggestion_hint(user_id, line_type, description, chosen_name, weight=weight)
            except Exception:
                pass

        if chosen_name and line_type in ("debit", "credit"):
            top_pred = (predictions[0].get("account_name") or "").strip() if predictions else ""
            is_correct = reward > 0
            try:
                fb = SuggestionFeedback(
                    user_id=user_id,
                    kind=line_type,
                    description=description,
                    suggested=top_pred or None,
                    actual=chosen_name,
                    is_correct=is_correct,
                )
                db.session.add(fb)
            except Exception:
                pass

        if entry.get("manual_override") and line_type in ("debit", "credit"):
            for pred in predictions[:3]:
                pred_name = (pred.get("account_name") or "").strip()
                if not pred_name or pred_name.lower() == chosen_name.lower():
                    continue
                try:
                    record_suggestion_hint(user_id, line_type, description, pred_name, weight=-1)
                except Exception:
                    continue

    if saved:
        db.session.commit()
        try:
            if auto_train:
                train_user_model(user_id, min_rows=min_rows)
        except Exception:
            pass
    return saved
