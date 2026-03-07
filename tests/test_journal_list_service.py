from __future__ import annotations

import datetime as _dt

import pytest
from finance_app import User, create_app, db
from finance_app.models.accounting_models import Account, AccountCategory, JournalEntry, JournalLine
from finance_app.services.journal_service import list_entries


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


def _seed_user_and_accounts():
    user = User(username="juser", password_hash="pw")
    db.session.add(user)
    db.session.flush()
    cat = AccountCategory(user_id=user.id, name="Assets", tb_group="asset")
    db.session.add(cat)
    db.session.flush()
    acc = Account(user_id=user.id, name="Cash", category_id=cat.id, currency_code="USD", active=True)
    db.session.add(acc)
    db.session.flush()
    return user, acc


def _add_entry(user_id: int, acc_id: int, date_iso: str, desc: str, amt: float, dc: str = "D"):
    entry = JournalEntry(
        user_id=user_id,
        description=desc,
        date=date_iso.replace("-", "/"),
        date_parsed=_dt.date.fromisoformat(date_iso),
    )
    db.session.add(entry)
    db.session.flush()
    line = JournalLine(journal_id=entry.id, account_id=acc_id, dc=dc, amount_base=amt)
    db.session.add(line)
    return entry


def test_list_entries_basic_filters(app_ctx):
    with app_ctx.app_context():
        user, acc = _seed_user_and_accounts()
        other = User(username="other", password_hash="pw")
        db.session.add(other)
        db.session.flush()
        _add_entry(user.id, acc.id, "2025-01-05", "Rent", 100, "D")
        _add_entry(user.id, acc.id, "2025-01-10", "Salary", 200, "C")
        # Other user's entry should be excluded
        _add_entry(other.id, acc.id, "2025-01-15", "Other", 300, "D")
        db.session.commit()

        res = list_entries(user_id=user.id, q="rent", page=1, per_page=10)
        assert res["ok"] is True
        assert res["total"] == 1
        assert len(res["entries"]) == 1
        assert res["entries"][0]["description"] == "Rent"

        res_date = list_entries(user_id=user.id, start="2025-01-06", end="2025-01-31", page=1, per_page=10)
        assert res_date["total"] == 1
        assert res_date["entries"][0]["description"] == "Salary"

        res_acc = list_entries(user_id=user.id, account_id=acc.id, page=1, per_page=1)
        assert res_acc["total"] == 2
        assert res_acc["pages"] == 1  # per_page is clamped to minimum 5
        assert len(res_acc["entries"]) == 2
