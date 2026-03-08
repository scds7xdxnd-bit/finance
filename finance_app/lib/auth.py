import secrets
from functools import wraps

from flask import request, session

from finance_app.extensions import db
from finance_app.models.user_models import User

CSRF_FAILURE_MESSAGE = "CSRF token missing or invalid"
CSRF_FAILURE_STATUS = 400


def current_user():
    """Return the logged-in user based on session storage."""
    if "user_id" in session:
        try:
            return db.session.get(User, session["user_id"])
        except Exception:
            return None
    return None


def _get_csrf_token():
    """Return a CSRF token stored in the session, creating one if missing."""
    tok = session.get("csrf_token")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["csrf_token"] = tok
    return tok


def csrf_token_valid() -> bool:
    token = request.headers.get("X-CSRF-Token")
    if token is None:
        token = request.form.get("csrf_token")
    expected = session.get("csrf_token")
    return bool(token and expected and secrets.compare_digest(str(token), str(expected)))


def csrf_failure_response():
    return (CSRF_FAILURE_MESSAGE, CSRF_FAILURE_STATUS)


def require_csrf(fn):
    """Simple CSRF guard for JSON/form endpoints that do not use WTForms."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not csrf_token_valid():
            return csrf_failure_response()
        return fn(*args, **kwargs)

    return wrapper


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return ("Unauthorized", 401)
        if not getattr(user, "is_admin", False):
            return ("Forbidden", 403)
        return fn(*args, **kwargs)

    return wrapper
