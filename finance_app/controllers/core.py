"""Core app routes (index, documents, ML suggestion endpoints, health)."""
import datetime
import os
import time

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from finance_app.lib.auth import current_user
from finance_app.models.accounting_models import (
    TrialBalanceSetting,
)
from finance_app.services.ml_gateway_service import (
    call_ml_api,
    compute_suggestions,
    fallback_hint,
    handle_ml_response,
    log_suggestions,
    try_user_model,
)
from finance_app.services.rate_limit_service import is_rate_limited

core_bp = Blueprint("core_bp", __name__)
# ML model cache (loaded lazily at import time)
_DISABLE_ML = os.environ.get("DISABLE_ML", "").lower() in ("1", "true", "yes")
try:
    import joblib  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    joblib = None

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))

# Load models once; tolerate missing files (feature remains optional)
core_bp.debit_model = None
core_bp.debit_le = None
core_bp.debit_tfidf = None
core_bp.credit_model = None
core_bp.credit_le = None
core_bp.joblib = joblib
core_bp.base_path = _PROJECT_ROOT
core_bp.disable_ml = _DISABLE_ML
_RATE_LIMITS = {
    "ml_suggestions": {"window": 60, "limit": 60},  # 60 requests/min per user
    "ml_logs": {"window": 60, "limit": 120},  # 120 logs/min per user
}


if not _DISABLE_ML and joblib is not None:
    try:
        core_bp.debit_model = joblib.load(os.path.join(_PROJECT_ROOT, "debit_account_suggester.joblib"))
        core_bp.debit_le = joblib.load(os.path.join(_PROJECT_ROOT, "debit_account_label_encoder.joblib"))
        core_bp.debit_tfidf = joblib.load(os.path.join(_PROJECT_ROOT, "debit_account_tfidf.joblib"))
    except Exception:
        core_bp.debit_model = None
        core_bp.debit_le = None
        core_bp.debit_tfidf = None
    try:
        core_bp.credit_model = joblib.load(os.path.join(_PROJECT_ROOT, "credit_account_suggester.joblib"))
        core_bp.credit_le = joblib.load(os.path.join(_PROJECT_ROOT, "credit_account_label_encoder.joblib"))
    except Exception:
        core_bp.credit_model = None
        core_bp.credit_le = None


@core_bp.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("transactions_bp.transactions"))
    return redirect(url_for("auth_bp.login"))


@core_bp.route("/documents", methods=["GET", "POST"])
def documents():
    user = current_user()
    if not user:
        flash("Login required.")
        return redirect(url_for("auth_bp.login"))
    doc_type = request.form.get("doc_type") if request.method == "POST" else None
    try:
        tbs = TrialBalanceSetting.query.filter_by(user_id=user.id).first()
        tb_initialized_on = tbs.initialized_on if tbs else None
    except Exception:
        tb_initialized_on = None
    return render_template("documents.html", doc_type=doc_type, tb_initialized_on=tb_initialized_on)


@core_bp.route("/api/ml_suggestions", methods=["POST"])
def ml_suggestions():
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    if is_rate_limited(user.id, "ml_suggestions", _RATE_LIMITS):
        return {"ok": False, "error": "Rate limit exceeded"}, 429

    data = request.get_json(silent=True) or {}
    lines = data.get("lines") or []
    target_line_id = data.get("target_line_id")
    if not lines or not target_line_id:
        return {"ok": False, "error": "lines and target_line_id are required"}, 400
    description = (data.get("description") or "").strip()
    currency = (data.get("currency") or core_bp.app.config["MLSUGGESTER_DEFAULT_CURRENCY"]).upper()
    date_str = data.get("date") or datetime.date.today().isoformat()
    try:
        top_k = int(data.get("top_k") or core_bp.app.config["MLSUGGESTER_TOPK"])
    except Exception:
        top_k = core_bp.app.config["MLSUGGESTER_TOPK"]
    top_k = max(1, min(10, top_k))
    # Basic validation
    for ln in lines:
        try:
            amt = float(ln.get("amount", 0) or 0)
            if amt < 0:
                return {"ok": False, "error": "Amounts must be non-negative"}, 400
        except Exception:
            return {"ok": False, "error": "Invalid amount"}, 400
        if (ln.get("dc") or "").upper() not in ("D", "C"):
            return {"ok": False, "error": "Line dc must be D or C"}, 400

    # Prepare features/payload
    try:
        features, context, ctx = compute_suggestions(
            user_id=user.id,
            lines=lines,
            target_line_id=target_line_id,
            description=description,
            currency=currency,
            date_str=date_str,
            core_cfg={"top_k": top_k},
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}, 400
    except Exception:
        return {"ok": False, "error": "Unable to prepare features"}, 400

    started_ts = ctx["meta"]["started_ts"]
    request_id = ctx["meta"]["request_id"]
    ml_payload = ctx["payload"]
    ml_payload["top_k"] = top_k

    prefer_user_model = core_bp.app.config.get("MLSUGGESTER_PREFER_USER_MODEL", False)
    user_only = core_bp.app.config.get("MLSUGGESTER_USER_ONLY", False)
    if prefer_user_model or user_only:
        user_preds, user_meta = try_user_model(user.id, features["Line_Type"], description, top_k=top_k)
        if user_preds:
            responded_at = datetime.datetime.utcnow().isoformat() + "Z"
            latency_ms = int((time.perf_counter() - started_ts) * 1000)
            model_hash = (user_meta or {}).get("model_hash")
            model_version = (user_meta or {}).get("model_version")
            return {
                "ok": True,
                "currency": features["Currency"],
                "top_k": top_k,
                "model_version": model_version,
                "model_version_hash": model_hash,
                "model_hash": model_hash,
                "model_path": "user_model",
                "transaction_id": features["Transaction_ID"],
                "line_id": features["Line_ID"],
                "line_type": features["Line_Type"],
                "predictions": user_preds,
                "features": features,
                "context": context,
                "responded_at": responded_at,
                "latency_ms": latency_ms,
                "request_id": request_id,
                "fallback": False,
                "error": None,
                "status": "user_model",
                "source": "user_model",
            }
        if user_only:
            fallback_pred = fallback_hint(user.id, features["Line_Type"], description)
            return (
                {
                    "ok": True,
                    "currency": features["Currency"],
                    "top_k": top_k,
                    "transaction_id": features["Transaction_ID"],
                    "line_id": features["Line_ID"],
                    "line_type": features["Line_Type"],
                    "predictions": fallback_pred,
                    "features": features,
                    "context": context,
                    "responded_at": datetime.datetime.utcnow().isoformat() + "Z",
                    "latency_ms": int((time.perf_counter() - started_ts) * 1000),
                    "request_id": request_id,
                    "status": "user_model_fallback",
                    "fallback": True,
                    "error": "user_model_unavailable",
                    "error_code": "user_model_missing",
                },
                200,
            )

    api_url = core_bp.app.config["MLSUGGESTER_API_URL"].rstrip("/") + "/predict"
    ml_response, last_exc = call_ml_api(api_url, ml_payload, core_bp.app.config["MLSUGGESTER_TIMEOUT"])
    if ml_response is None:
        fallback_pred = fallback_hint(user.id, features["Line_Type"], description)
        return (
            {
                "ok": True,
                "currency": features["Currency"],
                "top_k": top_k,
                "transaction_id": features["Transaction_ID"],
                "line_id": features["Line_ID"],
                "line_type": features["Line_Type"],
                "predictions": fallback_pred,
                "features": features,
                "context": context,
                "responded_at": datetime.datetime.utcnow().isoformat() + "Z",
                "latency_ms": int((time.perf_counter() - started_ts) * 1000),
                "request_id": request_id,
                "status": "fallback",
                "fallback": True,
                "error": str(last_exc) if last_exc else "ML service unavailable",
                "error_code": last_exc.__class__.__name__ if last_exc else "ml_unavailable",
            },
            200,
        )

    return handle_ml_response(
        features=features,
        context=context,
        ml_response=ml_response,
        started_ts=started_ts,
        request_id=request_id,
        top_k=top_k,
        model_meta=None,
    )


@core_bp.route("/api/suggestions/log", methods=["POST"])
def ml_suggestion_log():
    user = current_user()
    if not user:
        return ("Unauthorized", 401)
    if is_rate_limited(user.id, "ml_logs", _RATE_LIMITS):
        return {"ok": False, "error": "Rate limit exceeded"}, 429
    data = request.get_json(silent=True) or {}
    logs = data.get("logs")
    if not isinstance(logs, list) or not logs:
        return {"ok": False, "error": "logs must be a non-empty list"}, 400

    saved = log_suggestions(
        user_id=user.id,
        entries=logs,
        default_currency=core_bp.app.config["MLSUGGESTER_DEFAULT_CURRENCY"],
        auto_train=core_bp.app.config.get("MLSUGGESTER_AUTO_TRAIN_USER_MODEL", False),
        min_rows=core_bp.app.config.get("MLSUGGESTER_USER_MODEL_MIN_ROWS", 5),
    )
    return {"ok": True, "saved": saved}


@core_bp.route("/suggest/debit", methods=["POST"])
def suggest_debit():
    if not current_user():
        return ("Unauthorized", 401)
    return (
        {
            "ok": False,
            "deprecated": True,
            "message": "This endpoint is deprecated. Use /api/ml_suggestions instead.",
        },
        410,
    )


@core_bp.route("/suggest/credit", methods=["POST"])
def suggest_credit():
    if not current_user():
        return ("Unauthorized", 401)
    return (
        {
            "ok": False,
            "deprecated": True,
            "message": "This endpoint is deprecated. Use /api/ml_suggestions instead.",
        },
        410,
    )


@core_bp.route("/healthz", methods=["GET"])
def healthz():
    status = {"status": "ok"}
    ml_status = "ok"
    code = 200
    try:
        ml_resp = requests.get(core_bp.app.config["MLSUGGESTER_API_URL"].rstrip("/") + "/healthz", timeout=0.5)
        if ml_resp.ok:
            payload = ml_resp.json()
            ml_status = payload.get("status", "ok")
            if ml_status != "ok":
                status["status"] = "degraded"
                code = 503
        else:
            ml_status = f"http_{ml_resp.status_code}"
            status["status"] = "degraded"
            code = 503
    except Exception:
        ml_status = "error"
        status["status"] = "degraded"
        code = 503
    status["ml_suggester"] = ml_status
    return status, code
