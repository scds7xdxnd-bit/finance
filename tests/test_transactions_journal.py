from __future__ import annotations

import os
import shutil
import tempfile
from decimal import Decimal

import pytest
from finance_app import User, create_app, db
from finance_app.blueprints.transactions import save_transaction
from finance_app.models.accounting_models import JournalEntry
from flask import session

os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")


@pytest.fixture()
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    tmp_dir = tempfile.mkdtemp(prefix="transactions-api-")
    db_path = os.path.join(tmp_dir, "test.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
        db.drop_all()
        db.create_all()
        try:
            yield app
        finally:
            db.session.remove()
            db.drop_all()
    shutil.rmtree(tmp_dir, ignore_errors=True)


def _make_user():
    user = User(username="txn_user", password_hash="pw")
    db.session.add(user)
    db.session.flush()
    db.session.refresh(user)
    return user


def test_save_transaction_rejects_unbalanced(app_ctx):
    app = app_ctx
    with app.app_context():
        user = _make_user()
        db.session.commit()
        user_id = user.id

    with app.test_request_context("/transactions", method="POST"):
        session["user_id"] = user_id
        ok, result, status = save_transaction(
            {
                "date": "2024-01-01",
                "description": "Unbalanced",
                "lines": [
                    {"dc": "D", "account": "Cash", "amount": 100},
                    {"dc": "C", "account": "Revenue", "amount": 50},
                ],
            }
        )
        assert ok is False
        assert status == 400
        assert "balanced" in result["error"].lower()


def test_save_transaction_creates_balanced_entry(app_ctx):
    app = app_ctx
    with app.app_context():
        user = _make_user()
        db.session.commit()
        user_id = user.id

    with app.test_request_context("/transactions", method="POST"):
        session["user_id"] = user_id
        ok, result, status = save_transaction(
            {
                "date": "2024-01-01",
                "description": "Balanced entry",
                "lines": [
                    {"dc": "D", "account": "Cash", "amount": Decimal("25.00")},
                    {"dc": "C", "account": "Revenue", "amount": Decimal("25.00")},
                ],
            }
        )
        assert ok is True
        assert status == 200
        entry_id = result.get("entry_id")
        assert entry_id

    with app.app_context():
        stored = db.session.get(JournalEntry, entry_id)
        assert stored is not None
        assert len(stored.lines) == 2
