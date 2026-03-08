from __future__ import annotations

import os
import re

import pytest
from finance_app import create_app, db
from finance_app.models.user_models import User

POST_FORM_RE = re.compile(
    r"<form\b[^>]*method\s*=\s*(['\"]?)post\1[^>]*>(.*?)</form>",
    flags=re.IGNORECASE | re.DOTALL,
)
CSRF_INPUT_RE = re.compile(r"name\s*=\s*(['\"])csrf_token\1", flags=re.IGNORECASE)


@pytest.fixture()
def app_ctx(tmp_path):
    db_path = tmp_path / "template_csrf_presence.db"
    old_db_url = os.environ.get("FINANCE_DATABASE_URL")
    os.environ["FINANCE_DATABASE_URL"] = f"sqlite:///{db_path}"
    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        db.create_all()
        try:
            yield app
        finally:
            db.session.remove()
            db.drop_all()
            if old_db_url is None:
                os.environ.pop("FINANCE_DATABASE_URL", None)
            else:
                os.environ["FINANCE_DATABASE_URL"] = old_db_url


def _assert_post_forms_have_csrf(html: str, *, context: str) -> None:
    post_forms = POST_FORM_RE.findall(html or "")
    assert post_forms, f"No POST forms found in {context}"
    for index, (_, inner_html) in enumerate(post_forms, start=1):
        assert CSRF_INPUT_RE.search(inner_html), f"POST form #{index} missing csrf_token input in {context}"


@pytest.mark.parametrize(
    "path",
    [
        "/register",
        "/forgot-username",
        "/forgot-password",
    ],
)
def test_auth_templates_post_forms_include_csrf_token(app_ctx, path):
    client = app_ctx.test_client()
    response = client.get(path)
    assert response.status_code == 200
    _assert_post_forms_have_csrf(response.get_data(as_text=True), context=path)


def test_change_credentials_template_post_forms_include_csrf_token(app_ctx):
    with app_ctx.app_context():
        user = User(username="csrf_template_user", password_hash="pw")
        db.session.add(user)
        db.session.commit()
        user_id = int(user.id)

    client = app_ctx.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    response = client.get("/profile/change_credentials")
    assert response.status_code == 200
    _assert_post_forms_have_csrf(response.get_data(as_text=True), context="/profile/change_credentials")
