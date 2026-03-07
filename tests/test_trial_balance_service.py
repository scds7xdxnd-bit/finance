from __future__ import annotations

import datetime as _dt
import os

import pytest
from finance_app import User, create_app, db
from finance_app.models.accounting_models import (
    Account,
    AccountCategory,
    AccountOpeningBalance,
    JournalEntry,
    JournalLine,
    TrialBalanceSetting,
)
from finance_app.services.trial_balance_service import (
    monthly,
    reset_data,
    set_first_month,
    set_initialization,
)

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


def _setup_user_with_account():
    user = User(username="tb_user", password_hash="pw")
    db.session.add(user)
    db.session.flush()
    cat = AccountCategory(user_id=user.id, name="Assets", tb_group="asset")
    db.session.add(cat)
    db.session.flush()
    acc = Account(
        user_id=user.id,
        name="Cash",
        category_id=cat.id,
        currency_code="USD",
        active=True,
    )
    db.session.add(acc)
    db.session.flush()
    return user, cat, acc


def test_set_initialization_and_reset(app_ctx):
    with app_ctx.app_context():
        user, cat, acc = _setup_user_with_account()
        res = set_initialization(user.id, "2025-01-01")
        assert res["ok"] is True
        tbs = TrialBalanceSetting.query.filter_by(user_id=user.id).first()
        assert tbs and tbs.initialized_on == _dt.date(2025, 1, 1)

        # Seed opening balance and a tb_group
        AccountOpeningBalance.query.delete()
        db.session.add(AccountOpeningBalance(user_id=user.id, account_id=acc.id, amount=100))
        db.session.commit()
        assert AccountOpeningBalance.query.count() == 1

        reset_res = reset_data(user.id)
        assert reset_res["ok"] is True
        assert AccountOpeningBalance.query.count() == 0
        tbs = TrialBalanceSetting.query.filter_by(user_id=user.id).first()
        assert tbs is not None
        assert tbs.initialized_on is None


def test_monthly_aggregation(app_ctx):
    with app_ctx.app_context():
        user, cat, acc = _setup_user_with_account()
        # Opening balance
        db.session.add(AccountOpeningBalance(user_id=user.id, account_id=acc.id, amount=100))
        db.session.add(TrialBalanceSetting(user_id=user.id, initialized_on=_dt.date(2025, 1, 1)))
        db.session.flush()
        # Journal entry within month
        entry = JournalEntry(
            user_id=user.id,
            description="Deposit",
            date="2025/01/10",
            date_parsed=_dt.date(2025, 1, 10),
        )
        db.session.add(entry)
        db.session.flush()
        line = JournalLine(journal_id=entry.id, account_id=acc.id, dc="D", amount_base=50)
        db.session.add(line)
        db.session.commit()

        res = monthly(user.id, "2025-01")
        assert res["ok"] is True
        asset_groups = res["groups"].get("asset") or []
        assert len(asset_groups) >= 1
        asset_row = asset_groups[0]
        assert round(asset_row["bd"], 2) == 100.0
        assert round(asset_row["balance"], 2) == 150.0
        totals = res["totals"]["asset"]
        assert round(totals["balance"], 2) == 150.0
        assert round(totals["period_debit"], 2) == 50.0


def test_set_first_month_validation(app_ctx):
    with app_ctx.app_context():
        user, _, _ = _setup_user_with_account()
        ok_res = set_first_month(user.id, "2025-02")
        assert ok_res["ok"] is True
        bad_res = set_first_month(user.id, "bad")
        assert bad_res["ok"] is False
