import os

from flask import Flask, request
from sqlalchemy import event, inspect
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

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
INSTANCE_DIR = os.path.join(PROJECT_ROOT, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)
DEFAULT_DB_PATH = os.path.join(INSTANCE_DIR, "finance_app.db")


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
        if app.config.get("AUTO_CREATE_SCHEMA", False):
            ensure_schema()
        register_blueprints(app)
        register_cli(app)

    # Lazy schema check on first request (helps when DB is wiped mid-run)
    app._schema_checked = False  # type: ignore[attr-defined]

    @app.before_request
    def _ensure_schema_if_missing():
        if getattr(app, "_schema_checked", False):
            return None
        try:
            insp = inspect(db.engine)
            required = {"user", "rate_limit_bucket", "account_suggestion_log", "account_suggestion_hint"}
            missing = [t for t in required if not insp.has_table(t)]
            if missing:
                if app.config.get("AUTO_CREATE_SCHEMA", False):
                    ensure_schema()
                else:
                    app._schema_checked = True  # type: ignore[attr-defined]
                    return (
                        {
                            "ok": False,
                            "error": "Database schema missing. Run Alembic migrations to create the required tables.",
                            "missing_tables": missing,
                        },
                        503,
                    )
            app._schema_checked = True  # type: ignore[attr-defined]
        except Exception:
            # Leave unchecked; the OperationalError handler will still emit a clear message
            app._schema_checked = True  # type: ignore[attr-defined]
        return None

    @app.errorhandler(OperationalError)
    def _handle_db_errors(exc):
        msg = str(exc.orig) if getattr(exc, "orig", None) else str(exc)
        if "no such table: user" in msg.lower():
            return (
                {
                    "ok": False,
                    "error": "Database schema missing. Run Alembic migrations to create the user table.",
                },
                503,
            )
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
