import secrets
from functools import wraps

from flask import request, session

from finance_app.extensions import db
from finance_app.models.user_models import User


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


def require_csrf(fn):
    """Simple CSRF guard for JSON/form endpoints that do not use WTForms."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        if not token or token != session.get("csrf_token"):
            return ("CSRF token missing or invalid", 400)
        return fn(*args, **kwargs)

    return wrapper
