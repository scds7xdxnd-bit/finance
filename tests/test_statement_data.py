from __future__ import annotations

import os
import shutil
import tempfile
from datetime import date
from decimal import Decimal

import pytest
from finance_app import (
    Account,
    AccountCategory,
    AccountOpeningBalance,
    JournalEntry,
    JournalLine,
    TrialBalanceSetting,
    User,
    app,
    db,
)

os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")
AUTO_CREATE_SCHEMA = os.environ.get("AUTO_CREATE_SCHEMA", "").lower() == "true"


@pytest.fixture()
def app_ctx():
    app.config["TESTING"] = True
    tmp_dir = tempfile.mkdtemp(prefix="stmt-data-test-")
    db_path = os.path.join(tmp_dir, "test.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
        if AUTO_CREATE_SCHEMA:
            db.create_all()
        try:
            yield
        finally:
            db.session.remove()
            if AUTO_CREATE_SCHEMA:
                db.drop_all()
    shutil.rmtree(tmp_dir, ignore_errors=True)


def _post_entry(user_id: int, entry_date: date, lines: list[tuple[int, str, Decimal | int | float]]) -> None:
    entry = JournalEntry(
        user_id=user_id,
        date=entry_date.isoformat(),
        date_parsed=entry_date,
        description="stmt-data",
    )
    db.session.add(entry)
    db.session.flush()
    journal_lines = [
        JournalLine(journal_id=entry.id, account_id=account_id, dc=dc, amount_base=Decimal(str(amount)))
        for account_id, dc, amount in lines
    ]
    db.session.add_all(journal_lines)


def test_statement_data_endpoint_returns_financial_summaries(app_ctx):
    base = date(2024, 1, 1)
    with app.app_context():
        user = User(username="stmt_user", password_hash="pass")
        db.session.add(user)
        db.session.flush()

        asset_cat = AccountCategory(user_id=user.id, name="Cash", tb_group="asset")
        savings_cat = AccountCategory(user_id=user.id, name="Savings", tb_group="asset")
        liability_cat = AccountCategory(user_id=user.id, name="Loans", tb_group="liability")
        income_cat = AccountCategory(user_id=user.id, name="Sales", tb_group="income")
        expense_cat = AccountCategory(user_id=user.id, name="Operating", tb_group="expense")
        db.session.add_all([asset_cat, savings_cat, liability_cat, income_cat, expense_cat])
        db.session.flush()

        cash = Account(user_id=user.id, name="Main Cash", category_id=asset_cat.id, currency_code="KRW", active=True)
        savings = Account(user_id=user.id, name="High Yield Savings", category_id=savings_cat.id, currency_code="KRW", active=True)
        loan = Account(user_id=user.id, name="Short-term Loan", category_id=liability_cat.id, currency_code="KRW", active=True)
        revenue = Account(user_id=user.id, name="Product Revenue", category_id=income_cat.id, currency_code="KRW", active=True)
        expense = Account(user_id=user.id, name="Office Expense", category_id=expense_cat.id, currency_code="KRW", active=True)
        db.session.add_all([cash, savings, loan, revenue, expense])
        db.session.flush()

        db.session.add(TrialBalanceSetting(user_id=user.id, initialized_on=base))
        db.session.add(AccountOpeningBalance(user_id=user.id, account_id=cash.id, amount=1000, as_of_date=base))
        db.session.add(AccountOpeningBalance(user_id=user.id, account_id=savings.id, amount=500, as_of_date=base))

        _post_entry(
            user.id,
            date(2024, 1, 10),
            [
                (cash.id, "D", Decimal("700")),
                (revenue.id, "C", Decimal("700")),
            ],
        )
        _post_entry(
            user.id,
            date(2024, 1, 12),
            [
                (expense.id, "D", Decimal("200")),
                (cash.id, "C", Decimal("200")),
            ],
        )
        _post_entry(
            user.id,
            date(2024, 1, 15),
            [
                (savings.id, "D", Decimal("300")),
                (revenue.id, "C", Decimal("300")),
            ],
        )
        _post_entry(
            user.id,
            date(2024, 1, 20),
            [
                (cash.id, "D", Decimal("1000")),
                (loan.id, "C", Decimal("1000")),
            ],
        )
        db.session.commit()
        user_id = user.id
        asset_cat_id = asset_cat.id
        savings_cat_id = savings_cat.id

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    resp = client.get("/accounting/statement/data?ym=2024-01")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["period"] == {"start": "2024-01-01", "end": "2024-01-31"}

    income = payload["statements"]["income"]
    assert income["totals"]["revenue"] == pytest.approx(1000.0)
    assert income["totals"]["expense"] == pytest.approx(200.0)
    assert income["totals"]["net_income"] == pytest.approx(800.0)

    balance = payload["statements"]["balance"]
    assert balance["totals"]["assets"] == pytest.approx(3300.0)
    assert balance["totals"]["liabilities"] == pytest.approx(1000.0)
    assert balance["totals"]["equity"] == pytest.approx(2300.0)
    assert balance["totals"]["le_sum"] == pytest.approx(balance["totals"]["assets"])
    assert balance["currency_totals"][0]["currency"] == "KRW"
    assert balance["currency_totals"][0]["equity"] == pytest.approx(2300.0)

    cashflow = payload["statements"]["cashflow"]
    assert cashflow["opening"] == pytest.approx(1500.0)
    assert cashflow["closing"] == pytest.approx(3300.0)
    assert cashflow["change"] == pytest.approx(1800.0)
    assert cashflow["currency_totals"][0]["currency"] == "KRW"
    assert cashflow["currency_totals"][0]["change"] == pytest.approx(1800.0)
    assert set(cashflow["applied_folder_ids"]) == {asset_cat_id, savings_cat_id}

    assert income["currency_totals"][0]["currency"] == "KRW"
    assert income["currency_totals"][0]["net_income"] == pytest.approx(800.0)

    options = payload["cash_folder_options"]
    assert {opt["name"] for opt in options} == {"Cash", "Savings"}
    assert payload["selected_cash_folders"] == []

    resp_custom = client.get(f"/accounting/statement/data?ym=2024-01&cash_folders={asset_cat_id}")
    assert resp_custom.status_code == 200
    payload_custom = resp_custom.get_json()
    cashflow_custom = payload_custom["statements"]["cashflow"]
    assert cashflow_custom["opening"] == pytest.approx(1000.0)
    assert cashflow_custom["closing"] == pytest.approx(2500.0)
    assert cashflow_custom["change"] == pytest.approx(1500.0)
    assert cashflow_custom["applied_folder_ids"] == [asset_cat_id]
    assert payload_custom["selected_cash_folders"] == [asset_cat_id]
