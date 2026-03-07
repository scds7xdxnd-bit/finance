"""Lightweight per-user model built from that user's own suggestion logs."""
import datetime as dt
import hashlib
import json
import os
import secrets
import threading
from collections import defaultdict
from typing import Dict, List, Tuple

from flask import current_app
from sqlalchemy import func

from finance_app.extensions import db
from finance_app.models.accounting_models import AccountSuggestionLog
from finance_app.services.account_service import _BG_JOBS
from finance_app.services.ml_service import _desc_tokens


def _model_dir() -> str:
    return current_app.config.get("MLSUGGESTER_USER_MODEL_DIR")  # type: ignore[arg-type]


def _model_path(user_id: int) -> str:
    return os.path.join(_model_dir(), f"{user_id}.json")


def _hash_model(payload: dict) -> str:
    try:
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha1(raw).hexdigest()
    except Exception:
        return "unknown"


def user_model_exists(user_id: int) -> bool:
    try:
        return os.path.exists(_model_path(user_id))
    except Exception:
        return False


def load_user_model(user_id: int) -> Tuple[dict, str]:
    """Return model payload and hash for a user, empty dict if missing."""
    path = _model_path(user_id)
    if not os.path.exists(path):
        return {}, "missing"
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload, _hash_model(payload)
    except Exception:
        return {}, "error"


def train_user_model(user_id: int, min_rows: int | None = None) -> dict:
    """Train a simple token-frequency model from this user's logs."""
    min_rows = min_rows if min_rows is not None else int(current_app.config.get("MLSUGGESTER_USER_MODEL_MIN_ROWS", 5))
    q = (
        AccountSuggestionLog.query.filter(AccountSuggestionLog.user_id == user_id)
        .filter(AccountSuggestionLog.chosen_account != None)  # noqa: E711
        .filter(AccountSuggestionLog.description != None)  # noqa: E711
        .filter(AccountSuggestionLog.line_type.in_(("debit", "credit")))
    )
    rows: List[AccountSuggestionLog] = q.all()
    if len(rows) < min_rows:
        return {}

    line_type_models: Dict[str, dict] = {}
    for lt in ("debit", "credit"):
        line_type_models[lt] = {"token_counts": defaultdict(lambda: defaultdict(int)), "account_counts": defaultdict(int)}

    for row in rows:
        lt = (row.line_type or "").lower()
        if lt not in line_type_models:
            continue
        acct = (row.chosen_account or "").strip()
        if not acct:
            continue
        tokens = _desc_tokens(row.description or "")
        model = line_type_models[lt]
        model["account_counts"][acct] += 1
        for tok in tokens:
            model["token_counts"][tok][acct] += 1

    payload = {
        "user_id": user_id,
        "trained_at": dt.datetime.utcnow().isoformat() + "Z",
        "row_count": len(rows),
        "min_rows": min_rows,
        "line_types": {},
    }
    for lt, data in line_type_models.items():
        # convert defaultdicts to normal dict for JSON
        token_counts = {tok: dict(accts) for tok, accts in data["token_counts"].items()}
        account_counts = dict(data["account_counts"])
        payload["line_types"][lt] = {
            "token_counts": token_counts,
            "account_counts": account_counts,
            "row_count": sum(account_counts.values()),
        }

    os.makedirs(_model_dir(), exist_ok=True)
    with open(_model_path(user_id), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, separators=(",", ":"))
    return payload


def predict_user_model(user_id: int, line_type: str, description: str, top_k: int = 3) -> Tuple[List[dict], dict | None]:
    """Generate ranked accounts from the user-specific model."""
    payload, model_hash = load_user_model(user_id)
    lt_key = (line_type or "").lower()
    lt_data = (payload.get("line_types") or {}).get(lt_key) if payload else None
    if not lt_data:
        return [], None
    tokens = _desc_tokens(description or "")
    if not tokens:
        return [], None
    scores = defaultdict(float)
    token_counts: Dict[str, Dict[str, int]] = lt_data.get("token_counts", {})
    account_counts: Dict[str, int] = lt_data.get("account_counts", {})
    for tok in tokens:
        for acc, cnt in (token_counts.get(tok) or {}).items():
            scores[acc] += float(cnt)
    # small popularity prior to break ties and reward frequently chosen accounts
    for acc, cnt in account_counts.items():
        scores[acc] += 0.25 * float(cnt)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[: max(1, min(10, top_k))]
    predictions = [{"account_name": acc, "score": float(score)} for acc, score in ranked if acc]
    meta = {
        "model_hash": model_hash,
        "model_version": payload.get("trained_at"),
        "row_count": payload.get("row_count", 0),
        "min_rows": payload.get("min_rows", 0),
        "status": "user_model",
    }
    return predictions, meta


def user_model_status(user_id: int, min_rows: int | None = None) -> dict:
    min_rows = min_rows if min_rows is not None else int(current_app.config.get("MLSUGGESTER_USER_MODEL_MIN_ROWS", 5))
    log_count = (
        db.session.query(func.count(AccountSuggestionLog.id))
        .filter(AccountSuggestionLog.user_id == user_id)
        .filter(AccountSuggestionLog.chosen_account != None)  # noqa: E711
        .filter(AccountSuggestionLog.description != None)  # noqa: E711
        .filter(AccountSuggestionLog.line_type.in_(("debit", "credit")))
        .scalar()
        or 0
    )
    payload, model_hash = load_user_model(user_id)
    row_count = payload.get("row_count") if payload else 0
    trained_at = payload.get("trained_at") if payload else None
    needs_train = log_count >= min_rows and (not payload or (row_count or 0) < log_count)
    return {
        "user_id": user_id,
        "log_count": int(log_count),
        "model_exists": bool(payload),
        "model_hash": model_hash,
        "trained_at": trained_at,
        "row_count": row_count or 0,
        "min_rows": min_rows,
        "needs_train": bool(needs_train),
    }


def list_user_model_statuses(user_ids: List[int] | None = None, min_rows: int | None = None) -> List[dict]:
    ids = user_ids or []
    results = []
    if not ids:
        ids = [row[0] for row in db.session.query(AccountSuggestionLog.user_id).distinct().all()]
    for uid in ids:
        try:
            results.append(user_model_status(int(uid), min_rows=min_rows))
        except Exception:
            continue
    return results


def start_background_user_model_training(user_id: int | None = None, min_rows: int | None = None):
    """Train user models in the background for eligible users."""
    app = current_app._get_current_object()
    min_rows = min_rows if min_rows is not None else int(app.config.get("MLSUGGESTER_USER_MODEL_MIN_ROWS", 5))
    job_id = f"user-model-{secrets.token_hex(6)}"
    _BG_JOBS[job_id] = {"status": "running", "processed": 0, "total": 0, "kind": "train_user_models"}

    def worker():
        try:
            with app.app_context():
                q = (
                    db.session.query(AccountSuggestionLog.user_id, func.count(AccountSuggestionLog.id))
                    .filter(AccountSuggestionLog.chosen_account != None)  # noqa: E711
                    .filter(AccountSuggestionLog.description != None)  # noqa: E711
                    .filter(AccountSuggestionLog.line_type.in_(("debit", "credit")))
                )
                if user_id is not None:
                    q = q.filter(AccountSuggestionLog.user_id == int(user_id))
                q = q.group_by(AccountSuggestionLog.user_id)
                eligible = []
                for uid, cnt in q.all():
                    try:
                        uid_int = int(uid)
                    except Exception:
                        continue
                    status = user_model_status(uid_int, min_rows=min_rows)
                    if status["needs_train"]:
                        eligible.append(uid_int)
                _BG_JOBS[job_id]["total"] = len(eligible)
                processed = 0
                for uid in eligible:
                    try:
                        train_user_model(uid, min_rows=min_rows)
                    except Exception:
                        pass
                    processed += 1
                    _BG_JOBS[job_id]["processed"] = processed
                _BG_JOBS[job_id]["status"] = "completed"
        except Exception as exc:
            _BG_JOBS[job_id]["status"] = "failed"
            _BG_JOBS[job_id]["error"] = str(exc)

    threading.Thread(target=worker, daemon=True).start()
    return job_id
