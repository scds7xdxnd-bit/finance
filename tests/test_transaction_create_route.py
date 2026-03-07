from __future__ import annotations

import pytest
from finance_app import User, create_app, db
from finance_app.models.accounting_models import JournalEntry, JournalLine


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


def test_add_transaction_json_flow(app_ctx):
    app = app_ctx
    client = app.test_client()
    with app.app_context():
        user = User(username="tx_user", password_hash="pw")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    _login(client, user_id)

    payload = {
        "date": "2025-01-15",
        "description": "Test entry",
        "lines": [
            {"dc": "D", "account": "Cash", "amount": 100, "memo": "inflow"},
            {"dc": "C", "account": "Revenue", "amount": 100, "memo": "outflow"},
        ],
    }
    resp = client.post("/add_transaction", json=payload)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    entry_id = body.get("entry_id")
    assert entry_id

    with app.app_context():
        entry = db.session.get(JournalEntry, entry_id)
        assert entry is not None
        lines = JournalLine.query.filter_by(journal_id=entry_id).order_by(JournalLine.id.asc()).all()
        assert len(lines) == 2
        assert {ln.dc for ln in lines} == {"D", "C"}
