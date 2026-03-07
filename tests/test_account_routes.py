from __future__ import annotations

import os

import pytest
from finance_app import User, create_app, db
from finance_app.models.accounting_models import Account, AccountCategory

os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")


@pytest.fixture()
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _login(client, user_id: int):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["csrf_token"] = "test-token"


def test_category_add_and_move_routes(app_ctx):
    app = app_ctx
    client = app.test_client()
    with app.app_context():
        user = User(username="acc_user", password_hash="pw")
        db.session.add(user)
        db.session.flush()
        cat1 = AccountCategory(user_id=user.id, name="Cat1", side="both", order=0)
        cat2 = AccountCategory(user_id=user.id, name="Cat2", side="both", order=1)
        db.session.add_all([cat1, cat2])
        db.session.flush()
        acc = Account(user_id=user.id, name="Cash", category_id=cat1.id, active=True, order=0, currency_code="USD")
        db.session.add(acc)
        db.session.commit()
        user_id = user.id
        cat1_id = cat1.id
        cat2_id = cat2.id
        acc_id = acc.id

    _login(client, user_id)

    # Add category
    resp = client.post(
        "/accounting/category/add",
        json={"name": "NewCat"},
        headers={"X-CSRF-Token": "test-token"},
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True

    with app.app_context():
        assert AccountCategory.query.filter_by(user_id=user.id, name="NewCat").first() is not None

    # Move account to cat2
    resp_move = client.post(
        "/accounting/account/move",
        json={"account_id": acc.id, "category_id": cat2.id, "order": 0},
        headers={"X-CSRF-Token": "test-token"},
    )
    assert resp_move.status_code == 200
    with app.app_context():
        refreshed = db.session.get(Account, acc_id)
        assert refreshed.category_id == cat2_id

    # Bulk move back to cat1
    resp_bulk = client.post(
        "/accounting/account/bulk_move",
        json={"account_ids": [acc_id], "category_id": cat1_id},
        headers={"X-CSRF-Token": "test-token"},
    )
    assert resp_bulk.status_code == 200
    with app.app_context():
        refreshed = db.session.get(Account, acc_id)
        assert refreshed.category_id == cat1_id

    # Bulk unassign
    resp_unassign = client.post(
        "/accounting/account/bulk_unassign",
        json={"account_ids": [acc_id]},
        headers={"X-CSRF-Token": "test-token"},
    )
    assert resp_unassign.status_code == 200
    with app.app_context():
        refreshed = db.session.get(Account, acc_id)
        assert refreshed.category_id is None
