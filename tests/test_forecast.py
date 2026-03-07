from __future__ import annotations

import os
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal

import pytest
from finance_app import create_app, db
from finance_app.models.money_account import AccountType
from finance_app.models.money_account import MoneyScheduleAccount as Account
from finance_app.models.scheduled_transaction import ScheduledTransaction, TransactionStatus
from finance_app.services.forecast import compute_daily_forecast

app = create_app()
os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")
AUTO_CREATE_SCHEMA = os.environ.get("AUTO_CREATE_SCHEMA", "").lower() == "true"


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    tmp_dir = tempfile.mkdtemp(prefix="forecast-test-")
    db_path = os.path.join(tmp_dir, "test.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
        if AUTO_CREATE_SCHEMA:
            db.drop_all()
            db.create_all()
        try:
            yield app.test_client()
        finally:
            db.session.remove()
            if AUTO_CREATE_SCHEMA:
                db.drop_all()
    shutil.rmtree(tmp_dir, ignore_errors=True)


def _seed_basic_data():
    """Create one included and one excluded account with sample transactions."""
    if not AUTO_CREATE_SCHEMA:
        pytest.skip("AUTO_CREATE_SCHEMA is not enabled; skipping schema setup.")

    db.create_all()
    db.session.query(ScheduledTransaction).delete()
    db.session.query(Account).delete()
    db.session.commit()

    included = Account(
        name="Included Checking",
        type=AccountType.CHECKING,
        currency="KRW",
        current_balance=Decimal("100000"),
        is_included_in_closing=True,
    )
    excluded = Account(
        name="Excluded Wallet",
        type=AccountType.CASH,
        currency="KRW",
        current_balance=Decimal("50000"),
        is_included_in_closing=False,
    )

    db.session.add_all([included, excluded])
    db.session.flush()

    base_date = date(2024, 1, 1)

    fixtures = [
        # Day 1: inflow 20k, outflow 5k
        ScheduledTransaction(
            date=base_date,
            description="Gift",
            amount=Decimal("20000"),
            account=included,
            category="gift",
            status=TransactionStatus.PLANNED,
        ),
        ScheduledTransaction(
            date=base_date,
            description="Snacks",
            amount=Decimal("-5000"),
            account=included,
            category="food",
            status=TransactionStatus.PLANNED,
        ),
        # Day 2: only excluded account (should be ignored)
        ScheduledTransaction(
            date=base_date + timedelta(days=1),
            description="Ignored",
            amount=Decimal("10000"),
            account=excluded,
            category="misc",
            status=TransactionStatus.PLANNED,
        ),
        # Day 3: outflow 15k
        ScheduledTransaction(
            date=base_date + timedelta(days=2),
            description="Books",
            amount=Decimal("-15000"),
            account=included,
            category="education",
            status=TransactionStatus.COMPLETED,
        ),
    ]

    db.session.add_all(fixtures)
    db.session.commit()

    return base_date


def test_compute_daily_forecast_math():
    with app.app_context():
        base_date = _seed_basic_data()

        rows = compute_daily_forecast(
            db.session,
            start_date=base_date,
            end_date=base_date + timedelta(days=2),
            base_currency="KRW",
        )

        assert len(rows) == 3

        day1 = rows[0]
        assert day1["opening_balance"] == Decimal("100000")
        assert day1["inflow"] == Decimal("20000")
        assert day1["outflow"] == Decimal("5000")
        assert day1["closing_balance"] == Decimal("115000")

        day2 = rows[1]
        # No changes since only excluded account had activity
        assert day2["opening_balance"] == Decimal("115000")
        assert day2["inflow"] == Decimal("0")
        assert day2["closing_balance"] == Decimal("115000")

        day3 = rows[2]
        assert day3["opening_balance"] == Decimal("115000")
        assert day3["outflow"] == Decimal("15000")
        assert day3["closing_balance"] == Decimal("100000")


def test_forecast_api_returns_expected_shape(client):
    with app.app_context():
        base_date = _seed_basic_data()

    response = client.get(
        f"/api/forecast.json?start={base_date.isoformat()}&end={(base_date + timedelta(days=2)).isoformat()}&currency=KRW"
    )
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["currency"] == "KRW"
    assert payload["start"] == base_date.isoformat()
    assert len(payload["days"]) == 3

    first = payload["days"][0]
    assert first["date"] == base_date.isoformat()
    assert first["opening_balance"] == "100000.00"
    assert first["inflow"] == "20000.00"
    assert first["closing_balance"] == "115000.00"
