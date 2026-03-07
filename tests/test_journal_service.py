from __future__ import annotations

import os
import shutil
import tempfile
from decimal import Decimal

import pytest
from finance_app import User, create_app, db
from finance_app.models.accounting_models import Account
from finance_app.services.journal_service import (
    JournalBalanceError,
    JournalLinePayload,
    _validate_balanced,
    create_journal_entry,
)

os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")


@pytest.fixture()
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    tmp_dir = tempfile.mkdtemp(prefix="journal-service-")
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


def test_validate_balanced_rejects_unbalanced_lines():
    with pytest.raises(JournalBalanceError):
        _validate_balanced(
            [
                JournalLinePayload(dc="D", account_id=1, amount=Decimal("100.00")),
                JournalLinePayload(dc="C", account_id=2, amount=Decimal("50.00")),
            ]
        )


def test_create_journal_entry_persists_lines(app_ctx):
    app = app_ctx
    with app.app_context():
        user = User(username="journal_user", password_hash="x")
        db.session.add(user)
        db.session.flush()

        acc = Account(user_id=user.id, name="Cash", side="both", order=0)
        db.session.add(acc)
        db.session.commit()

        entry = create_journal_entry(
            user_id=user.id,
            date="2024/01/01",
            date_parsed=None,
            description="Test entry",
            reference="TEST-1",
            lines=[
                JournalLinePayload(dc="D", account_id=acc.id, amount=Decimal("10.00")),
                JournalLinePayload(dc="C", account_id=acc.id, amount=Decimal("10.00")),
            ],
        )
        db.session.commit()

        fetched = db.session.get(type(entry), entry.id)
        assert fetched is not None
        assert len(fetched.lines) == 2
