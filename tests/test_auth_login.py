import os
import re
import sys
import types

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

# Stub alembic before importing the app package to avoid heavy CLI deps during tests
if "alembic" not in sys.modules:
    alembic_pkg = types.ModuleType("alembic")
    command_mod = types.ModuleType("alembic.command")

    def _noop(*args, **kwargs):
        return None

    command_mod.upgrade = _noop

    config_mod = types.ModuleType("alembic.config")

    class _DummyConfig:
        def __init__(self, *args, **kwargs):
            pass

        def set_main_option(self, *args, **kwargs):
            return None

    config_mod.Config = _DummyConfig

    alembic_pkg.command = command_mod
    alembic_pkg.config = config_mod
    sys.modules["alembic"] = alembic_pkg
    sys.modules["alembic.command"] = command_mod
    sys.modules["alembic.config"] = config_mod

from blueprints.auth import auth_bp
from finance_app.extensions import db
from finance_app.models.user_models import User


@pytest.fixture()
def app_ctx():
    here = os.path.dirname(__file__)
    template_dir = os.path.abspath(os.path.join(here, "..", "templates"))
    app = Flask(__name__, template_folder=template_dir)
    app.config.update(
        SECRET_KEY="test-secret",
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)

    # Stub blueprints to satisfy menu/nav url_for calls during login render
    from flask import Blueprint

    user_bp = Blueprint("user_bp", __name__)
    transactions_bp = Blueprint("transactions_bp", __name__)
    accounting_bp = Blueprint("accounting_bp", __name__)
    money_schedule_bp = Blueprint("money_schedule", __name__)
    core_bp = Blueprint("core_bp", __name__)
    admin_bp = Blueprint("admin_bp", __name__)

    @user_bp.route("/profile")
    def profile():
        return "profile"

    @transactions_bp.route("/transactions")
    def transactions():
        return "transactions"

    @accounting_bp.route("/accounting")
    def accounting():
        return "accounting"

    @money_schedule_bp.route("/")
    def index():
        return "money-schedule"

    @core_bp.route("/documents")
    def documents():
        return "documents"

    @admin_bp.route("/admin/users")
    def admin_users():
        return "admin-users"

    @admin_bp.route("/admin/suggestions")
    def admin_suggestions():
        return "admin-suggestions"

    @admin_bp.route("/admin/tools")
    def admin_tools():
        return "admin-tools"

    app.register_blueprint(user_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(accounting_bp)
    app.register_blueprint(money_schedule_bp, url_prefix="/money-schedule")
    app.register_blueprint(core_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _extract_csrf(html: str) -> str | None:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return match.group(1) if match else None


def test_login_does_not_500(app_ctx):
    app = app_ctx
    client = app.test_client()
    with app.app_context():
        user = User(username="testuser", password_hash=generate_password_hash("secret123"))
        db.session.add(user)
        db.session.commit()

    # Fetch login page and extract CSRF token
    resp_get = client.get("/login")
    assert resp_get.status_code == 200
    csrf_token = _extract_csrf(resp_get.get_data(as_text=True))
    assert csrf_token, "CSRF token missing from login page"

    # Post credentials
    resp_post = client.post(
        "/login",
        data={"username": "testuser", "password": "secret123", "csrf_token": csrf_token},
        follow_redirects=False,
    )

    # Should either redirect (302) or render page with 200, but never 500
    assert resp_post.status_code in (200, 302), f"Unexpected status {resp_post.status_code}, body: {resp_post.get_data(as_text=True)}"
