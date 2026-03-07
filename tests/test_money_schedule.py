from __future__ import annotations

import os
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

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
from finance_app.models.money_schedule import (
    MoneyScheduleAssetInclude,
    MoneyScheduleDailyBalance,
    MoneyScheduleRecurringEvent,
    MoneyScheduleRow,
    MoneyScheduleScenario,
    MoneyScheduleScenarioRow,
)
from finance_app.services.money_schedule_service import (
    apply_recurring_events,
    create_recurring_event,
    create_scenario_from_window,
    delete_recurring_event,
    delete_scenario_for_user,
    ensure_rows_between,
    quick_add_entry,
    recompute_from,
    toggle_recurring_event,
    update_recurring_event,
    update_row_amounts,
    update_scenario_row,
)

os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")


@pytest.fixture()
def app_ctx():
    app.config["TESTING"] = True
    tmp_dir = tempfile.mkdtemp(prefix="ms-test-")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    auto_create_schema = os.environ.get("AUTO_CREATE_SCHEMA", "").lower() == "true"

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
        # Reset cached engines so URI override takes effect.
        try:
            app.extensions["sqlalchemy"].engines = {}
        except Exception:
            pass
        if auto_create_schema:
            db.create_all()
        try:
            yield
        finally:
            db.session.remove()
            if auto_create_schema:
                db.drop_all()
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture()
def client(app_ctx):
    return app.test_client()


def _add_journal_entry(user_id: int, entry_date: date, lines: list[tuple[int, str, Decimal | int | float | str]]) -> None:
    entry = JournalEntry(
        user_id=user_id,
        date=entry_date.isoformat(),
        date_parsed=entry_date,
        description="auto-test",
    )
    db.session.add(entry)
    db.session.flush()

    journal_lines = [
        JournalLine(
            journal_id=entry.id,
            account_id=account_id,
            dc=dc,
            amount_base=Decimal(str(amount)),
        )
        for account_id, dc, amount in lines
    ]
    db.session.add_all(journal_lines)


def _create_user(username: str = "schedule_user") -> User:
    user = User(username=username, password_hash="pass")
    db.session.add(user)
    db.session.flush()
    return user


def _seed_basic_accounts(user_id: int, base: date):
    asset_cat = AccountCategory(user_id=user_id, name="Cash", tb_group="asset")
    db.session.add(asset_cat)
    db.session.flush()
    cash = Account(user_id=user_id, name="Main Cash", category_id=asset_cat.id, currency_code="KRW", active=True)
    db.session.add(cash)
    db.session.flush()
    db.session.add(AccountOpeningBalance(user_id=user_id, account_id=cash.id, amount=1000, as_of_date=base))
    # Ensure init date exists
    if not TrialBalanceSetting.query.filter_by(user_id=user_id).first():
        db.session.add(TrialBalanceSetting(user_id=user_id, initialized_on=base))
    db.session.commit()
    return cash


def test_money_schedule_row_constraints(app_ctx):
    user = _create_user("constraint_user")
    row = MoneyScheduleRow(user_id=user.id, date=date(2024, 1, 1), inflow=Decimal("10"), outflow=Decimal("0"))
    db.session.add(row)
    db.session.commit()

    db.session.add(MoneyScheduleRow(user_id=user.id, date=date(2024, 1, 2), inflow=Decimal("-1"), outflow=Decimal("0")))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    db.session.add(MoneyScheduleRow(user_id=user.id, date=date(2024, 1, 1), inflow=Decimal("0"), outflow=Decimal("0")))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_recompute_sets_predicted_and_variance(app_ctx):
    base = date(2024, 2, 1)
    user = User(username="tb_user", password_hash="pass")
    db.session.add(user)
    db.session.flush()
    db.session.add(TrialBalanceSetting(user_id=user.id, initialized_on=base))

    category = AccountCategory(user_id=user.id, name="Assets", tb_group="asset")
    db.session.add(category)
    db.session.flush()

    account = Account(
        user_id=user.id,
        name="Wallet",
        category_id=category.id,
        currency_code="KRW",
        active=True,
    )
    db.session.add(account)
    db.session.flush()

    db.session.add(
        AccountOpeningBalance(
            user_id=user.id,
            account_id=account.id,
            amount=100000,
            as_of_date=base,
        )
    )
    db.session.add(
        MoneyScheduleAssetInclude(user_id=user.id, account_id=account.id, initial_balance=Decimal("100000"))
    )

    _add_journal_entry(
        user.id,
        base + timedelta(days=1),
        [(account.id, "D", Decimal("35000"))],
    )
    _add_journal_entry(
        user.id,
        base + timedelta(days=2),
        [(account.id, "C", Decimal("15000"))],
    )

    rows = [
        MoneyScheduleRow(user_id=user.id, date=base, inflow=Decimal("0"), outflow=Decimal("0")),
        MoneyScheduleRow(user_id=user.id, date=base + timedelta(days=1), inflow=Decimal("20000"), outflow=Decimal("5000")),
        MoneyScheduleRow(user_id=user.id, date=base + timedelta(days=2), inflow=Decimal("0"), outflow=Decimal("10000")),
    ]
    db.session.add_all(rows)
    db.session.commit()

    recompute_from(base, user.id)

    db.session.refresh(rows[0])
    db.session.refresh(rows[1])
    db.session.refresh(rows[2])

    assert rows[0].predicted_closing == Decimal("100000.00")
    assert rows[0].variance == Decimal("0.00")

    assert rows[1].predicted_closing == Decimal("115000.00")
    assert rows[1].variance == Decimal("20000.00")

    assert rows[2].predicted_closing == Decimal("105000.00")
    assert rows[2].variance == Decimal("15000.00")

    rows[1].inflow = Decimal("1000")
    rows[1].outflow = Decimal("500")
    db.session.commit()
    recompute_from(rows[1].date, user.id)

    db.session.refresh(rows[0])
    db.session.refresh(rows[1])
    db.session.refresh(rows[2])

    assert rows[0].predicted_closing == Decimal("100000.00")
    assert rows[1].predicted_closing == Decimal("100500.00")
    assert rows[2].predicted_closing == Decimal("90500.00")


def test_quick_add_and_update_row_amounts(app_ctx):
    base = date(2024, 3, 1)
    user = _create_user("ms_user")
    _seed_basic_accounts(user.id, base)
    ensure_rows_between(base, base + timedelta(days=2), user.id)
    db.session.commit()

    target_day = base + timedelta(days=1)
    updated = quick_add_entry(user.id, target_day, description="Test inflow", direction="inflow", amount=Decimal("100"))
    assert updated is not None
    assert updated.inflow == Decimal("100.00")
    assert updated.outflow == Decimal("0.00")

    updated2 = update_row_amounts(
        user_id=user.id,
        day=base + timedelta(days=1),
        description="Day 2",
        inflow=Decimal("50"),
        outflow=Decimal("25"),
    )
    assert updated2 is not None
    assert updated2.inflow == Decimal("50.00")
    assert updated2.outflow == Decimal("25.00")

    recompute_from(base, user.id)
    refreshed = MoneyScheduleRow.query.filter_by(user_id=user.id, date=base).first()
    refreshed2 = MoneyScheduleRow.query.filter_by(user_id=user.id, date=base + timedelta(days=1)).first()
    assert refreshed.predicted_closing is not None
    assert refreshed2.predicted_closing is not None


def test_recurring_event_service_crud(app_ctx):
    base = date(2024, 4, 1)
    user = _create_user("event_user")
    _seed_basic_accounts(user.id, base)

    payload = {
        "description": "Rent",
        "direction": "outflow",
        "amount": Decimal("1000.00"),
        "start_date": base,
        "end_date": None,
        "frequency": "monthly",
        "interval": 1,
        "weekdays": None,
        "month_day": 1,
        "custom_dates": None,
        "notes": None,
        "user_id": user.id,
    }
    ev = create_recurring_event(user.id, payload)
    assert ev.id is not None
    updated = update_recurring_event(user.id, ev.id, {"description": "Rent Updated", "amount": Decimal("1200.00")})
    assert updated.description == "Rent Updated"
    assert updated.amount == Decimal("1200.00")
    toggled = toggle_recurring_event(user.id, ev.id)
    assert toggled.is_active is False
    toggled_again = toggle_recurring_event(user.id, ev.id)
    assert toggled_again.is_active is True
    deleted = delete_recurring_event(user.id, ev.id)
    assert deleted is True
    assert MoneyScheduleRecurringEvent.query.filter_by(id=ev.id).first() is None


def test_scenario_update_and_delete(app_ctx):
    base = date(2024, 5, 1)
    user = _create_user("scenario_user")
    _seed_basic_accounts(user.id, base)

    # Seed base rows and recompute
    ensure_rows_between(base, base + timedelta(days=2), user.id)
    row1 = MoneyScheduleRow.query.filter_by(user_id=user.id, date=base + timedelta(days=1)).first()
    row1.inflow = Decimal("100.00")
    row1.outflow = Decimal("50.00")
    db.session.commit()
    recompute_from(base, user.id)

    scenario = create_scenario_from_window(
        name="What-if",
        description=None,
        user_id=user.id,
        start_date=base,
        end_date=base + timedelta(days=2),
        clone_rows=True,
    )
    updated = update_scenario_row(
        scenario_id=scenario.id,
        user_id=user.id,
        day=base + timedelta(days=1),
        description="Adjusted",
        inflow=Decimal("200.00"),
        outflow=Decimal("25.00"),
    )
    assert updated is not None
    assert updated.inflow == Decimal("200.00")
    assert updated.outflow == Decimal("25.00")

    deleted = delete_scenario_for_user(user.id, scenario.id)
    assert deleted is not None
    assert MoneyScheduleScenario.query.filter_by(id=scenario.id).first() is None


def test_initial_balance_respects_asset_includes(app_ctx):
    base = date(2024, 5, 1)
    user = User(username="tb_user_include", password_hash="pass")
    db.session.add(user)
    db.session.flush()
    db.session.add(TrialBalanceSetting(user_id=user.id, initialized_on=base))

    category = AccountCategory(user_id=user.id, name="Assets", tb_group="asset")
    db.session.add(category)
    db.session.flush()

    wallet = Account(user_id=user.id, name="Wallet", category_id=category.id, currency_code="KRW", active=True)
    checking = Account(user_id=user.id, name="Checking", category_id=category.id, currency_code="KRW", active=True)
    db.session.add_all([wallet, checking])
    db.session.flush()

    db.session.add(AccountOpeningBalance(user_id=user.id, account_id=wallet.id, amount=50000, as_of_date=base))
    db.session.add(AccountOpeningBalance(user_id=user.id, account_id=checking.id, amount=200000, as_of_date=base))

    # Only include wallet in baseline
    db.session.add(MoneyScheduleAssetInclude(user_id=user.id, account_id=wallet.id, initial_balance=Decimal("50000")))
    db.session.commit()

    db.session.add(MoneyScheduleRow(user_id=user.id, date=base, inflow=Decimal("0"), outflow=Decimal("0")))
    db.session.add(MoneyScheduleRow(user_id=user.id, date=base + timedelta(days=1), inflow=Decimal("10000"), outflow=Decimal("0")))
    db.session.commit()

    recompute_from(base, user.id)

    rows = (
        MoneyScheduleRow.query.filter_by(user_id=user.id)
        .order_by(MoneyScheduleRow.date.asc())
        .all()
    )
    assert rows[0].predicted_closing == Decimal("50000.00")
    assert rows[1].predicted_closing == Decimal("60000.00")


def test_edit_route_updates_and_recomputes(client):
    base = date(2024, 3, 1)
    with app.app_context():
        user = User(username="tb_user_edit", password_hash="pass")
        db.session.add(user)
        db.session.flush()
        user_id = user.id
        db.session.add(TrialBalanceSetting(user_id=user.id, initialized_on=base))

        category = AccountCategory(user_id=user.id, name="Assets", tb_group="asset")
        db.session.add(category)
        db.session.flush()

        account = Account(user_id=user.id, name="Wallet", category_id=category.id, currency_code="KRW", active=True)
        db.session.add(account)
        db.session.flush()

        db.session.add(AccountOpeningBalance(user_id=user.id, account_id=account.id, amount=100000, as_of_date=base))
        db.session.add(MoneyScheduleAssetInclude(user_id=user.id, account_id=account.id, initial_balance=Decimal("100000")))
        _add_journal_entry(
            user.id,
            base + timedelta(days=1),
            [(account.id, "D", Decimal("20000"))],
        )
        db.session.add(MoneyScheduleRow(user_id=user.id, date=base, inflow=Decimal("0"), outflow=Decimal("0")))
        db.session.add(MoneyScheduleRow(user_id=user.id, date=base + timedelta(days=1), inflow=Decimal("0"), outflow=Decimal("0")))
        db.session.commit()
        recompute_from(base, user.id)

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    response = client.post(
        "/money-schedule/edit",
        data={
            "date": (base + timedelta(days=1)).isoformat(),
            "description": "Invoice",
            "inflow": "50000",
            "outflow": "5000",
        },
        headers={"X-Requested-With": "fetch"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["description"] == "Invoice"
    assert payload["predicted"] is not None

    with app.app_context():
        row = MoneyScheduleRow.query.filter_by(user_id=user_id, date=base + timedelta(days=1)).first()
        assert row.description == "Invoice"
        assert row.inflow == Decimal("50000.00")
        assert row.outflow == Decimal("5000.00")
        assert row.predicted_closing is not None
        assert row.actual_closing == Decimal("120000.00")


def test_event_routes_toggle_and_delete(client):
    base = date(2024, 7, 1)
    with app.app_context():
        user = _create_user("event_route_user")
        db.session.add(TrialBalanceSetting(user_id=user.id, initialized_on=base))
        db.session.commit()
        user_id = user.id
        event = MoneyScheduleRecurringEvent(
            user_id=user_id,
            description="Gym",
            direction="outflow",
            amount=Decimal("50"),
            start_date=base,
            end_date=None,
            frequency="monthly",
            interval=1,
            is_active=True,
        )
        db.session.add(event)
        db.session.commit()
        event_id = event.id

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    resp_toggle = client.post(f"/money-schedule/events/{event_id}/toggle")
    assert resp_toggle.status_code == 302
    with app.app_context():
        updated = db.session.get(MoneyScheduleRecurringEvent, event_id)
        assert updated.is_active is False

    resp_delete = client.post(f"/money-schedule/events/{event_id}/delete")
    assert resp_delete.status_code == 302
    with app.app_context():
        assert db.session.get(MoneyScheduleRecurringEvent, event_id) is None


def test_scenario_edit_route(client):
    base = date(2024, 8, 1)
    with app.app_context():
        user = _create_user("scenario_route_user")
        db.session.add(TrialBalanceSetting(user_id=user.id, initialized_on=base))
        db.session.commit()
        user_id = user.id

        ensure_rows_between(base, base + timedelta(days=2), user.id)
        db.session.commit()
        scenario = create_scenario_from_window(
            name="Route Scenario",
            description=None,
            user_id=user_id,
            start_date=base,
            end_date=base + timedelta(days=2),
            clone_rows=True,
        )
        scenario_id = scenario.id

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    resp = client.post(
        f"/money-schedule/scenarios/{scenario_id}/edit",
        data={
            "date": (base + timedelta(days=1)).isoformat(),
            "description": "Route edit",
            "inflow": "123.45",
            "outflow": "67.89",
        },
        headers={"X-Requested-With": "fetch"},
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["description"] == "Route edit"
    assert payload["inflow"] == "123.45"
    assert payload["outflow"] == "67.89"

    with app.app_context():
        row = MoneyScheduleScenarioRow.query.filter_by(scenario_id=scenario_id, date=base + timedelta(days=1)).first()
        assert row is not None
        assert row.description == "Route edit"
        assert row.inflow == Decimal("123.45")
        assert row.outflow == Decimal("67.89")


def test_event_create_and_edit_route(client):
    base = date(2024, 9, 1)
    with app.app_context():
        user = _create_user("event_route_create_user")
        db.session.add(TrialBalanceSetting(user_id=user.id, initialized_on=base))
        db.session.commit()
        user_id = user.id

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    create_resp = client.post(
        "/money-schedule/events",
        data={
            "description": "Stipend",
            "direction": "inflow",
            "amount": "250.00",
            "start_date": base.isoformat(),
            "frequency": "monthly",
            "interval": "1",
        },
    )
    assert create_resp.status_code == 302
    with app.app_context():
        ev = MoneyScheduleRecurringEvent.query.filter_by(user_id=user_id, description="Stipend").first()
        assert ev is not None
        ev_id = ev.id

    edit_resp = client.post(
        f"/money-schedule/events/{ev_id}/edit",
        data={
            "description": "Stipend Updated",
            "direction": "inflow",
            "amount": "300.00",
            "start_date": base.isoformat(),
            "frequency": "monthly",
            "interval": "1",
        },
    )
    assert edit_resp.status_code == 302
    with app.app_context():
        ev2 = db.session.get(MoneyScheduleRecurringEvent, ev_id)
        assert ev2.description == "Stipend Updated"
        assert ev2.amount == Decimal("300.00")


def test_scenario_create_and_delete_route(client):
    base = date(2024, 10, 1)
    with app.app_context():
        user = _create_user("scenario_route_create_user")
        db.session.add(TrialBalanceSetting(user_id=user.id, initialized_on=base))
        db.session.commit()
        user_id = user.id
        ensure_rows_between(base, base + timedelta(days=2), user_id)
        db.session.commit()

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    create_resp = client.post(
        "/money-schedule/scenarios",
        data={
            "name": "Route Create Scenario",
            "start": base.isoformat(),
            "end": (base + timedelta(days=2)).isoformat(),
        },
    )
    assert create_resp.status_code == 302
    created_location = create_resp.headers.get("Location") or ""
    assert "scenario_id" in created_location
    with app.app_context():
        scenario = MoneyScheduleScenario.query.filter_by(user_id=user_id, name="Route Create Scenario").first()
        assert scenario is not None
        scenario_id = scenario.id

    delete_resp = client.post(f"/money-schedule/scenarios/{scenario_id}/delete")
    assert delete_resp.status_code == 302
    with app.app_context():
        assert MoneyScheduleScenario.query.filter_by(id=scenario_id).first() is None


def test_recurring_events_auto_fill(app_ctx):
    base = date(2024, 6, 3)
    with app.app_context():
        user = _create_user("auto_fill_user")
        event = MoneyScheduleRecurringEvent(
            description="Lunch stipend",
            direction="inflow",
            amount=Decimal("15000"),
            start_date=base,
            end_date=base + timedelta(days=14),
            frequency="weekly",
            interval=1,
            weekdays="0,2",
            user_id=user.id,
        )
        db.session.add(event)
        db.session.commit()

        ensure_rows_between(base, base + timedelta(days=6), user.id)
        apply_recurring_events(base, base + timedelta(days=6), user.id)

        rows = (
            MoneyScheduleRow.query.filter(MoneyScheduleRow.user_id == user.id)
            .filter(MoneyScheduleRow.date >= base)
            .filter(MoneyScheduleRow.date <= base + timedelta(days=6))
            .order_by(MoneyScheduleRow.date.asc())
            .all()
        )
        monday = rows[0]
        wednesday = rows[2]
        assert monday.inflow == Decimal("15000.00")
        assert wednesday.inflow == Decimal("15000.00")
        assert monday.is_auto_generated is True
        assert wednesday.is_auto_generated is True


def test_recurring_event_edit(client):
    base = date(2024, 7, 1)
    with app.app_context():
        user = _create_user("event_edit_user")
        user_id = user.id
        event = MoneyScheduleRecurringEvent(
            description="Allowance",
            direction="inflow",
            amount=Decimal("20000"),
            start_date=base,
            frequency="monthly",
            interval=1,
            month_day=1,
            user_id=user.id,
        )
        db.session.add(event)
        db.session.commit()
        event_id = event.id

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    response = client.post(
        f"/money-schedule/events/{event_id}/edit",
        data={
            "description": "Allowance Updated",
            "direction": "outflow",
            "amount": "25000",
            "start_date": base.isoformat(),
            "end_date": (base + timedelta(days=30)).isoformat(),
            "frequency": "weekly",
            "interval": "2",
            "weekdays": ["1", "3"],
            "notes": "Adjust cadence",
            "start": base.isoformat(),
            "end": (base + timedelta(days=7)).isoformat(),
            "view": "list",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        updated = db.session.get(MoneyScheduleRecurringEvent, event_id)
        assert updated.description == "Allowance Updated"
        assert updated.direction == "outflow"
        assert updated.interval == 2
        assert updated.weekdays == "1,3"


def test_recompute_from_last_change(client):
    base = date(2024, 2, 1)
    with app.app_context():
        user = _create_user("last_change_user")
        _seed_basic_accounts(user.id, base)
        ensure_rows_between(base, base + timedelta(days=2), user.id)
        rows = (
            MoneyScheduleRow.query.filter_by(user_id=user.id)
            .order_by(MoneyScheduleRow.date.asc())
            .all()
        )
        rows[0].inflow = Decimal("100")
        rows[1].outflow = Decimal("50")
        db.session.commit()

        from finance_app.services.money_schedule_service import recompute_from_last_change

        recompute_from_last_change(user.id, fallback_day=base)

        refreshed = (
            MoneyScheduleRow.query.filter_by(user_id=user.id)
            .order_by(MoneyScheduleRow.date.asc())
            .all()
        )
        assert all(row.predicted_closing is not None for row in refreshed)


def test_rebuild_daily_balances_stops_at_last_row(client):
    base = date(2024, 3, 1)
    with app.app_context():
        user = _create_user("daily_balance_cap")
        _seed_basic_accounts(user.id, base)
        ensure_rows_between(base, base + timedelta(days=2), user.id)

        from finance_app.services.money_schedule_service import recompute_from

        recompute_from(base, user.id)

        last_row_date = (
            db.session.query(db.func.max(MoneyScheduleRow.date))
            .filter(MoneyScheduleRow.user_id == user.id)
            .scalar()
        )
        last_balance = (
            db.session.query(db.func.max(MoneyScheduleDailyBalance.date))
            .filter(MoneyScheduleDailyBalance.user_id == user.id)
            .scalar()
        )
        assert last_balance == last_row_date
