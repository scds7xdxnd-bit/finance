import os
from pathlib import Path
from typing import Any

from flask import Flask, request
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import OperationalError

from finance_app.cli import register_cli
from finance_app.controllers import register_blueprints
from finance_app.extensions import db
from finance_app.lib.auth import _get_csrf_token, current_user, require_csrf
from finance_app.lib.dates import _parse_date_tuple
from finance_app.services.account_service import (
    _BG_JOBS,
    _account_sort_key,
    _category_prefix,
    assign_codes_for_user,
    ensure_account,
    generate_account_code,
    start_background_assign_account_ids,
)
from finance_app.services.ml_service import (
    _compute_ml_line_features,
    best_hint_suggestion,
    record_suggestion_hint,
)
from finance_app.services.schema_guard_service import capability_report

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
INSTANCE_DIR = os.path.join(PROJECT_ROOT, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)
DEFAULT_DB_PATH = os.path.join(INSTANCE_DIR, "finance_app.db")
STARTUP_MIGRATION_FAILURE_PREFIX = "Startup/migration contract failed:"
STARTUP_CONTRACT_ERROR_CODES = {
    "SCHEMA_NOT_READY",
    "ALEMBIC_NOT_AT_HEAD",
    "SCHEMA_CAPABILITY_MISSING",
    "DB_URL_MISMATCH",
}


def _resolve_database_uri() -> str:
    """Prefer finance-specific DB URL but keep DATABASE_URL backward compatible."""
    return (
        os.environ.get("FINANCE_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or f"sqlite:///{DEFAULT_DB_PATH}"
    )


def _build_default_config() -> dict:
    return {
        "SECRET_KEY": os.environ.get("SECRET_KEY", "replace-with-a-secure-key"),
        # Prefer a finance-specific env var; keep DATABASE_URL fallback for existing local setups.
        # Use absolute path to avoid resolving relative to instance_path twice when running via flask CLI.
        "SQLALCHEMY_DATABASE_URI": _resolve_database_uri(),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {"connect_args": {"timeout": 30}},
        "AUTO_CREATE_SCHEMA": os.environ.get("AUTO_CREATE_SCHEMA", "false").lower() in ("1", "true", "yes"),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": os.environ.get("SESSION_COOKIE_SECURE", "false").lower() in ("1", "true", "yes"),
        "SESSION_COOKIE_SAMESITE": os.environ.get("SESSION_COOKIE_SAMESITE", "Lax"),
        "SESSION_COOKIE_HTTPONLY": True,
        "PERMANENT_SESSION_LIFETIME": int(os.environ.get("SESSION_TTL_SECONDS", "86400")),
        "MAX_CONTENT_LENGTH": int(os.environ.get("MAX_CONTENT_LENGTH", str(10 * 1024 * 1024))),  # 10 MB cap
        "UPLOAD_ALLOWED_EXTENSIONS": set((os.environ.get("UPLOAD_ALLOWED_EXTENSIONS") or "csv,png,jpg,jpeg,gif,pdf").split(",")),
        "UPLOAD_FOLDER": os.environ.get("UPLOAD_FOLDER", None),  # resolved to instance/uploads if not set
        "STATIC_CACHE_MAX_AGE": int(os.environ.get("STATIC_CACHE_MAX_AGE", "3600")),
        "LEDGER_WRITE_MODE": os.environ.get("LEDGER_WRITE_MODE", "journal").strip().lower() or "journal",
        "SCHEMA_GUARD_ENFORCE": os.environ.get("SCHEMA_GUARD_ENFORCE", "true").lower() in ("1", "true", "yes"),
        "ALLOW_LEGACY_REPORT_FALLBACK": os.environ.get("ALLOW_LEGACY_REPORT_FALLBACK", "false").lower() in ("1", "true", "yes"),
        "FORECAST_LEGACY_ENABLED": os.environ.get("FORECAST_LEGACY_ENABLED", "false").lower() in ("1", "true", "yes"),
        "CSV_IDEMPOTENCY_ENABLED": os.environ.get("CSV_IDEMPOTENCY_ENABLED", "true").lower() in ("1", "true", "yes"),
        "ADMIN_ACTION_COOLDOWN_SECONDS": int(os.environ.get("ADMIN_ACTION_COOLDOWN_SECONDS", "5")),
        "SCHEMA_GUARD_BYPASS_REASON": os.environ.get("SCHEMA_GUARD_BYPASS_REASON", "").strip(),
        "SCHEMA_GUARD_BYPASS_UNTIL": os.environ.get("SCHEMA_GUARD_BYPASS_UNTIL", "").strip(),
        "MLSUGGESTER_API_URL": os.environ.get("MLSUGGESTER_API_URL", "http://127.0.0.1:8001"),
        "MLSUGGESTER_DEFAULT_CURRENCY": os.environ.get("MLSUGGESTER_DEFAULT_CURRENCY", "KRW").upper(),
        "MLSUGGESTER_TOPK": int(os.environ.get("MLSUGGESTER_TOPK", "3")),
        "MLSUGGESTER_TIMEOUT": float(os.environ.get("MLSUGGESTER_TIMEOUT", "2.0")),
        # User-specific models (isolated training). When enabled we try a per-user model first.
        "MLSUGGESTER_PREFER_USER_MODEL": os.environ.get("MLSUGGESTER_PREFER_USER_MODEL", "true").lower() in ("1", "true", "yes"),
        "MLSUGGESTER_USER_ONLY": os.environ.get("MLSUGGESTER_USER_ONLY", "false").lower() in ("1", "true", "yes"),
        "MLSUGGESTER_AUTO_TRAIN_USER_MODEL": os.environ.get("MLSUGGESTER_AUTO_TRAIN_USER_MODEL", "true").lower() in ("1", "true", "yes"),
        "MLSUGGESTER_USER_MODEL_MIN_ROWS": int(os.environ.get("MLSUGGESTER_USER_MODEL_MIN_ROWS", "5")),
    }


# Snapshot kept for backward compatibility for callers that import DEFAULT_CONFIG.
DEFAULT_CONFIG = _build_default_config()


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Improve SQLite concurrency for local development."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
    except Exception:
        pass


def ensure_schema():
    """Create tables for development only when explicitly allowed."""
    db.create_all()


def _is_non_test_runtime(app: Flask) -> bool:
    # Deterministic switch used by startup gate tests and runtime behavior.
    return not bool(app.config.get("TESTING", False))


def _alembic_ini_path() -> Path:
    return Path(PROJECT_ROOT) / "alembic.ini"


def _resolve_alembic_database_uri() -> str | None:
    env_uri = os.environ.get("ALEMBIC_DATABASE_URL")
    if env_uri:
        return env_uri
    try:
        from alembic.config import Config

        cfg = Config(str(_alembic_ini_path()))
        resolved = (cfg.get_main_option("sqlalchemy.url") or "").strip()
        return resolved or None
    except Exception:
        return None


def _canonicalize_database_uri(raw_uri: str | None) -> str:
    if not raw_uri:
        return ""
    try:
        parsed = make_url(raw_uri)
    except Exception:
        return str(raw_uri).strip()

    driver = (parsed.drivername or "").lower()
    if driver.startswith("sqlite"):
        database = parsed.database or ""
        if database in {"", ":memory:"}:
            return f"{driver}:///{database or ':memory:'}"
        if database.startswith("file:"):
            return f"{driver}:///{database}"
        abs_path = database if os.path.isabs(database) else os.path.join(PROJECT_ROOT, database)
        return f"{driver}:///{os.path.realpath(abs_path)}"

    host = (parsed.host or "").lower()
    port = f":{parsed.port}" if parsed.port else ""
    database = parsed.database or ""
    query = parsed.query or {}
    query_text = "&".join(f"{k}={query[k]}" for k in sorted(query))
    suffix = f"?{query_text}" if query_text else ""
    # Canonical target identity intentionally excludes credentials.
    return f"{driver}://{host}{port}/{database}{suffix}"


def _resolve_current_revision() -> str | None:
    try:
        row = db.session.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        return str(row[0]) if row and row[0] else None
    except Exception:
        return None


def _resolve_head_revisions() -> list[str]:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(_alembic_ini_path()))
        cfg.set_main_option("script_location", str(Path(PROJECT_ROOT) / "alembic"))
        script = ScriptDirectory.from_config(cfg)
        heads = [str(head) for head in script.get_heads() if head]
        return sorted(set(heads))
    except Exception:
        return []


def _schema_revision_status() -> dict[str, Any]:
    current_revision = _resolve_current_revision()
    heads = _resolve_head_revisions()
    head_count = len(heads)
    head_revision = heads[0] if head_count == 1 else None
    at_head = bool(current_revision is not None and head_count == 1 and current_revision == heads[0])
    return {
        "current_revision": current_revision,
        "heads": heads,
        "head_count": head_count,
        "head_revision": head_revision,
        "at_head": at_head,
    }


def _missing_tables_from_report(report: dict[str, Any]) -> list[str]:
    missing_tables: set[str] = set()
    details = (report.get("missing_details") or {}) if isinstance(report, dict) else {}
    for artifacts in details.values():
        for artifact in artifacts or []:
            token = str(artifact or "")
            if token.startswith("table:"):
                missing_tables.add(token.split(":", 1)[1])
    return sorted(missing_tables)


def _startup_failure_payload(
    *,
    error_code: str,
    detail: str,
    required_action: str,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    code = error_code if error_code in STARTUP_CONTRACT_ERROR_CODES else "SCHEMA_NOT_READY"
    payload: dict[str, Any] = {
        "ok": False,
        "error_code": code,
        "message": f"{STARTUP_MIGRATION_FAILURE_PREFIX} {detail}",
        "required_action": required_action,
    }
    for key, value in (diagnostics or {}).items():
        if value is not None:
            payload[key] = value
    return payload


def _evaluate_startup_migration_contract(app: Flask) -> dict[str, Any]:
    runtime_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "").strip()
    alembic_uri = _resolve_alembic_database_uri()
    runtime_target = _canonicalize_database_uri(runtime_uri)
    alembic_target = _canonicalize_database_uri(alembic_uri)

    if bool(app.config.get("AUTO_CREATE_SCHEMA", False)):
        return _startup_failure_payload(
            error_code="SCHEMA_NOT_READY",
            detail="AUTO_CREATE_SCHEMA is forbidden in non-test runtime.",
            required_action="Disable AUTO_CREATE_SCHEMA and run Alembic migrations to head.",
            diagnostics={
                "auto_create_schema": True,
                "runtime_db_url": runtime_target,
                "alembic_db_url": alembic_target,
            },
        )

    if runtime_target and alembic_target and runtime_target != alembic_target:
        return _startup_failure_payload(
            error_code="DB_URL_MISMATCH",
            detail="Runtime DB URL does not match Alembic DB URL.",
            required_action="Set FINANCE_DATABASE_URL and ALEMBIC_DATABASE_URL to the same database target.",
            diagnostics={
                "runtime_db_url": runtime_target,
                "alembic_db_url": alembic_target,
            },
        )

    revision = _schema_revision_status()
    if not bool(revision.get("at_head")):
        return _startup_failure_payload(
            error_code="ALEMBIC_NOT_AT_HEAD",
            detail="Runtime database is not at Alembic head revision.",
            required_action="Run `alembic upgrade head` against the runtime database.",
            diagnostics={
                "at_head": False,
                "current_revision": revision.get("current_revision"),
                "head_revision": revision.get("head_revision"),
                "head_count": revision.get("head_count"),
                "heads": revision.get("heads"),
                "runtime_db_url": runtime_target,
                "alembic_db_url": alembic_target,
            },
        )

    caps_report = capability_report()
    if not bool(caps_report.get("ok")):
        capabilities = (caps_report.get("capabilities") or {}) if isinstance(caps_report, dict) else {}
        missing_capabilities = sorted([name for name, ok in capabilities.items() if not bool(ok)])
        missing_tables = _missing_tables_from_report(caps_report if isinstance(caps_report, dict) else {})
        return _startup_failure_payload(
            error_code="SCHEMA_CAPABILITY_MISSING",
            detail="Required schema capabilities are missing.",
            required_action="Apply Alembic migrations that satisfy all required schema capabilities.",
            diagnostics={
                "at_head": True,
                "current_revision": revision.get("current_revision"),
                "head_revision": revision.get("head_revision"),
                "head_count": revision.get("head_count"),
                "heads": revision.get("heads"),
                "missing_capabilities": missing_capabilities,
                "missing_tables": missing_tables,
            },
        )

    return {
        "ok": True,
        "at_head": True,
        "current_revision": revision.get("current_revision"),
        "head_revision": revision.get("head_revision"),
        "head_count": revision.get("head_count"),
        "heads": revision.get("heads"),
    }


def create_app():
    """Application factory for WSGI/CLI entrypoints."""
    app = Flask(
        __name__,
        instance_path=INSTANCE_DIR,
        static_folder=os.path.join(PROJECT_ROOT, "static"),
        static_url_path="/static",
        template_folder=os.path.join(PROJECT_ROOT, "templates"),
    )
    app.config.from_mapping(_build_default_config())
    env_name = os.environ.get("APP_ENV", "development").lower()
    env_overrides = {
        "development": {},
        "staging": {
            "SESSION_COOKIE_SECURE": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "MLSUGGESTER_PREFER_USER_MODEL": True,
        },
        "production": {
            "SESSION_COOKIE_SECURE": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "MLSUGGESTER_PREFER_USER_MODEL": True,
            "MLSUGGESTER_USER_ONLY": True,
        },
    }
    app.config.update(env_overrides.get(env_name, {}))

    # Normalize sqlite paths to absolute to avoid double instance/instance when working dir changes
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    try:
        parsed = make_url(db_uri) if db_uri else None
        if parsed and parsed.drivername.startswith("sqlite"):
            # Only fix relative file paths
            db_path = parsed.database
            if db_path and not os.path.isabs(db_path):
                abs_path = os.path.join(PROJECT_ROOT, db_path)
                app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{abs_path}"
    except Exception:
        # Leave uri as-is; startup will fail loudly if it's invalid
        pass

    # Resolve upload folder
    upload_folder = app.config.get("UPLOAD_FOLDER")
    if not upload_folder:
        upload_folder = os.path.join(INSTANCE_DIR, "uploads")
        app.config["UPLOAD_FOLDER"] = upload_folder
    os.makedirs(upload_folder, exist_ok=True)
    # Per-user ML model storage
    user_model_dir = app.config.get("MLSUGGESTER_USER_MODEL_DIR") or os.path.join(INSTANCE_DIR, "user_models")
    app.config["MLSUGGESTER_USER_MODEL_DIR"] = user_model_dir
    os.makedirs(user_model_dir, exist_ok=True)

    db.init_app(app)

    with app.app_context():
        register_blueprints(app)
        register_cli(app)
    app._test_schema_bootstrapped = False  # type: ignore[attr-defined]

    @app.before_request
    def _startup_migration_gate():
        if not _is_non_test_runtime(app):
            if bool(app.config.get("AUTO_CREATE_SCHEMA", False)) and not getattr(app, "_test_schema_bootstrapped", False):
                ensure_schema()
                app._test_schema_bootstrapped = True  # type: ignore[attr-defined]
            return None

        payload = _evaluate_startup_migration_contract(app)
        if bool(payload.get("ok")):
            return None

        app.logger.error("%s %s", STARTUP_MIGRATION_FAILURE_PREFIX, payload)
        if request.path == "/healthz":
            return payload, 503
        return payload, 503

    @app.errorhandler(OperationalError)
    def _handle_db_errors(exc):
        msg = str(exc.orig) if getattr(exc, "orig", None) else str(exc)
        if "no such table: user" in msg.lower():
            payload = _startup_failure_payload(
                error_code="SCHEMA_NOT_READY",
                detail="Database schema missing required table(s).",
                required_action="Run Alembic migrations to head for the runtime database.",
                diagnostics={"missing_tables": ["user"]},
            )
            app.logger.error("%s %s", STARTUP_MIGRATION_FAILURE_PREFIX, payload)
            return payload, 503
        return {"ok": False, "error": f"Database error: {msg}"}, 500

    @app.after_request
    def _static_cache_headers(resp):
        try:
            if request.path.startswith("/static/") and resp.status_code == 200:
                max_age = int(app.config.get("STATIC_CACHE_MAX_AGE") or 3600)
                resp.headers.setdefault("Cache-Control", f"public, max-age={max_age}, immutable")
        except Exception:
            pass
        return resp

    @app.context_processor
    def _inject_csrf_token():
        return {"csrf_token": _get_csrf_token()}

    return app


# Import models so metadata is registered for Alembic and shell usage.
from finance_app.models.accounting_models import (  # noqa: E402,F401
    AdminActionAudit,
    Account,
    AccountCategory,
    AccountMonthlyBalance,
    AccountOpeningBalance,
    AccountSuggestionHint,
    AccountSuggestionLog,
    CsvImportBatch,
    CsvImportRow,
    JournalEntry,
    JournalLine,
    LoanGroup,
    LoanGroupLink,
    LoginSession,
    ReceivableManualEntry,
    ReceivableTracker,
    SuggestionFeedback,
    TBResetSnapshot,
    TransactionJournalLink,
    TransactionLinkCandidate,
    Transaction,
    TrialBalanceSetting,
)
from finance_app.models.money_account import MoneyScheduleAccount, MoneyScheduleAccountLink  # noqa: E402,F401
from finance_app.models.money_schedule import (  # noqa: E402,F401
    AccountSnapshot,
    MoneyScheduleAssetInclude,
    MoneyScheduleDailyBalance,
    MoneyScheduleRecurringEvent,
    MoneyScheduleRow,
    MoneyScheduleScenario,
    MoneyScheduleScenarioRow,
    Setting,
)
from finance_app.models.scheduled_transaction import ScheduledTransaction  # noqa: E402,F401
from finance_app.models.user_models import RateLimitBucket, User, UserPost, UserProfile  # noqa: E402,F401

__all__ = [
    "app",
    "create_app",
    "ensure_schema",
    "db",
    "current_user",
    "_get_csrf_token",
    "require_csrf",
    "_parse_date_tuple",
    "_compute_ml_line_features",
    "record_suggestion_hint",
    "best_hint_suggestion",
    "_account_sort_key",
    "_category_prefix",
    "assign_codes_for_user",
    "ensure_account",
    "generate_account_code",
    "start_background_assign_account_ids",
    "_BG_JOBS",
    # Models
    "User",
    "UserProfile",
    "UserPost",
    "RateLimitBucket",
    "AdminActionAudit",
    "Transaction",
    "AccountSuggestionHint",
    "SuggestionFeedback",
    "AccountSuggestionLog",
    "CsvImportBatch",
    "CsvImportRow",
    "AccountCategory",
    "Account",
    "AccountOpeningBalance",
    "LoginSession",
    "TrialBalanceSetting",
    "AccountMonthlyBalance",
    "ReceivableTracker",
    "ReceivableManualEntry",
    "LoanGroup",
    "LoanGroupLink",
    "JournalEntry",
    "JournalLine",
    "TransactionJournalLink",
    "TransactionLinkCandidate",
    "TBResetSnapshot",
    "MoneyScheduleAccount",
    "MoneyScheduleAccountLink",
    "MoneyScheduleRow",
    "Setting",
    "MoneyScheduleAssetInclude",
    "MoneyScheduleDailyBalance",
    "AccountSnapshot",
    "MoneyScheduleRecurringEvent",
    "MoneyScheduleScenario",
    "MoneyScheduleScenarioRow",
    "ScheduledTransaction",
]


class _LazyAppProxy:
    """Lazily construct the Flask app on first attribute access."""

    _app: Flask | None = None

    def _get(self) -> Flask:
        if self._app is None:
            self._app = create_app()
        return self._app

    def __getattr__(self, item):
        return getattr(self._get(), item)


# Backwards-compatible module attribute for tests importing `app` directly.
# Eager creation remains default; if this module is imported from a partially
# initialized blueprint module, fall back to lazy proxy to avoid circular import.
try:
    app = create_app()
except ImportError:
    app = _LazyAppProxy()
