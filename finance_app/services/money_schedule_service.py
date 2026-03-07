from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date as ddate
from datetime import datetime as dt_datetime
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_

from finance_app import db
from finance_app.models.money_schedule import (
    MoneyScheduleAssetInclude,
    MoneyScheduleDailyBalance,
    MoneyScheduleRecurringEvent,
    MoneyScheduleRow,
    MoneyScheduleScenario,
    MoneyScheduleScenarioRow,
    Setting,
)

EPS = Decimal("0.01")


def _require_user_id(user_id: int | None) -> int:
    if user_id is None:
        raise ValueError("Money schedule operations require an authenticated user.")
    return user_id


def _quantize(value: Decimal | float | int | None) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return value.quantize(EPS, rounding=ROUND_HALF_UP)


def get_init_date() -> ddate | None:
    # Prefer the Trial Balance initialization date when available.
    from finance_app import TrialBalanceSetting

    trial_balance_row = (
        db.session.query(TrialBalanceSetting.initialized_on)
        .filter(TrialBalanceSetting.initialized_on.isnot(None))
        .order_by(TrialBalanceSetting.initialized_on.asc())
        .first()
    )
    if trial_balance_row and trial_balance_row[0]:
        return trial_balance_row[0]

    setting = db.session.get(Setting, "money_schedule_init_date")
    if setting is None:
        return None
    return ddate.fromisoformat(setting.value)


def set_init_date(iso_date: str) -> None:
    from finance_app import TrialBalanceSetting

    target_date = ddate.fromisoformat(iso_date)
    tb_settings = TrialBalanceSetting.query.all()
    if tb_settings:
        for row in tb_settings:
            row.initialized_on = target_date
        db.session.commit()
        return

    setting = Setting(key="money_schedule_init_date", value=iso_date)
    db.session.merge(setting)
    db.session.commit()


def _default_balance_for_account(account_id: int) -> Decimal:
    from finance_app import AccountOpeningBalance

    total = (
        db.session.query(func.coalesce(func.sum(AccountOpeningBalance.amount), 0))
        .filter(AccountOpeningBalance.account_id == account_id)
        .scalar()
    )
    return _quantize(total) or Decimal("0.00")


def _get_included_accounts(user_id: int | None) -> list[tuple[int, Decimal]]:
    uid = _require_user_id(user_id)
    includes = MoneyScheduleAssetInclude.query.filter_by(user_id=uid).all()
    if includes:
        result: list[tuple[int, Decimal]] = []
        for entry in includes:
            initial = (
                _quantize(entry.initial_balance)
                if entry.initial_balance is not None
                else _default_balance_for_account(entry.account_id)
            )
            result.append((entry.account_id, initial or Decimal("0.00")))
        return result

    from finance_app import Account, AccountCategory

    asset_categories = (
        AccountCategory.query.filter(AccountCategory.user_id == uid)
        .filter(AccountCategory.tb_group == "asset")
        .all()
    )
    category_ids = [cat.id for cat in asset_categories]
    if not category_ids:
        return []

    accounts = (
        Account.query.filter(Account.user_id == uid)
        .filter(Account.category_id.in_(category_ids))
        .filter(Account.active.is_(True))
        .all()
    )

    return [
        (account.id, _default_balance_for_account(account.id))
        for account in accounts
    ]


def _included_account_ids(user_id: int | None) -> set[int]:
    return {account_id for account_id, _ in _get_included_accounts(user_id)}


def _initial_balance(user_id: int | None) -> Decimal:
    accounts = _get_included_accounts(user_id)
    if not accounts:
        return Decimal("0.00")
    total = sum(initial for _, initial in accounts)
    return _quantize(total) or Decimal("0.00")


def list_asset_accounts(user_id: int | None) -> list[dict[str, object]]:
    """Return asset accounts with balances for selection."""
    uid = _require_user_id(user_id)
    from finance_app import Account, AccountCategory, AccountOpeningBalance

    asset_categories = (
        AccountCategory.query.filter(AccountCategory.user_id == uid)
        .filter(AccountCategory.tb_group == "asset")
        .all()
    )
    category_ids = [cat.id for cat in asset_categories]
    if not category_ids:
        return []

    accounts = (
        Account.query.filter(Account.user_id == uid)
        .filter(Account.category_id.in_(category_ids))
        .filter(Account.active.is_(True))
        .order_by(Account.name.asc())
        .all()
    )
    if not accounts:
        return []

    balances = {
        row.account_id: Decimal(str(row.amount or 0))
        for row in (
            AccountOpeningBalance.query.filter(AccountOpeningBalance.account_id.in_([account.id for account in accounts]))
            .filter(AccountOpeningBalance.user_id == uid)
            .all()
        )
    }
    result: list[dict[str, object]] = []
    for account in accounts:
        balance = balances.get(account.id, Decimal("0"))
        result.append(
            {
                "id": account.id,
                "name": account.name,
                "code": account.code,
                "currency": account.currency_code,
                "balance": balance,
            }
        )
    return result


def selected_asset_ids(user_id: int | None) -> set[int]:
    """Return selected asset ids for money schedule baseline."""
    uid = _require_user_id(user_id)
    from finance_app import Account

    query = (
        MoneyScheduleAssetInclude.query.filter(MoneyScheduleAssetInclude.user_id == uid)
        .join(Account, MoneyScheduleAssetInclude.account_id == Account.id)
        .filter(Account.user_id == uid)
    )
    return {include.account_id for include in query.all()}


def update_asset_includes(user_id: int | None, account_ids: set[int]) -> None:
    """Replace asset includes for the user with provided account ids."""
    uid = _require_user_id(user_id)
    from finance_app import Account

    owned_account_ids: set[int] = set()
    if account_ids:
        owned_account_ids = {
            acc.id
            for acc in Account.query.filter(Account.user_id == uid).filter(Account.id.in_(account_ids))
        }

    MoneyScheduleAssetInclude.query.filter_by(user_id=uid).delete()
    db.session.flush()

    for acc_id in owned_account_ids:
        initial = _default_balance_for_account(acc_id)
        db.session.add(
            MoneyScheduleAssetInclude(
                user_id=uid,
                account_id=acc_id,
                initial_balance=initial,
            )
        )
    db.session.commit()


def _coerce_transaction_date(raw: str | None) -> ddate | None:
    if not raw:
        return None
    try:
        return ddate.fromisoformat(raw)
    except ValueError:
        pass
    for fmt in ("%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return dt_datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def rebuild_daily_balances(user_id: int | None, end_date: ddate | None = None) -> None:
    uid = _require_user_id(user_id)
    init_date = get_init_date()
    if init_date is None:
        MoneyScheduleDailyBalance.query.filter_by(user_id=uid).delete()
        db.session.commit()
        return

    accounts_info = _get_included_accounts(uid)
    if not accounts_info:
        MoneyScheduleDailyBalance.query.filter_by(user_id=uid).delete()
        db.session.commit()
        return
    account_ids = {account_id for account_id, _ in accounts_info}
    account_id_list = list(account_ids)

    today = ddate.today()
    limit_end = min(end_date, today) if end_date else today

    # Gather net change per day for included accounts.
    net_by_day: dict[ddate, Decimal] = {}
    from finance_app import (  # local import to avoid circular
        Account,  # ensure account ownership
        JournalEntry,
        JournalLine,
    )
    owned_account_ids = {
        acc.id
        for acc in Account.query.filter(Account.id.in_(account_id_list))
        .filter(Account.user_id == uid)
        .all()
    }
    if not owned_account_ids:
        MoneyScheduleDailyBalance.query.filter_by(user_id=uid).delete()
        db.session.commit()
        return
    account_id_list = list(owned_account_ids)

    journal_rows = (
        db.session.query(
            JournalEntry.date_parsed,
            JournalEntry.date,
            JournalLine.dc,
            JournalLine.amount_base,
        )
        .join(JournalEntry, JournalLine.journal_id == JournalEntry.id)
        .filter(JournalEntry.user_id == uid)
        .filter(JournalLine.account_id.in_(list(owned_account_ids)))
        .all()
    )

    for date_value, raw_date, dc, amount in journal_rows:
        effective_date = date_value
        if effective_date is None and raw_date:
            effective_date = _coerce_transaction_date(raw_date)
        if effective_date is None:
            continue
        if effective_date < init_date or effective_date > limit_end:
            continue
        if amount is None:
            continue

        if effective_date not in net_by_day:
            net_by_day[effective_date] = Decimal("0.00")

        delta = Decimal(str(amount))
        if dc == "C":
            net_by_day[effective_date] -= delta
        else:
            net_by_day[effective_date] += delta

        net_by_day[effective_date] = _quantize(net_by_day[effective_date]) or Decimal("0.00")

    MoneyScheduleDailyBalance.query.filter_by(user_id=uid).delete()
    db.session.flush()

    balance = _quantize(_initial_balance(uid)) or Decimal("0.00")
    current = init_date
    step = timedelta(days=1)
    while current <= limit_end:
        net = net_by_day.get(current, Decimal("0"))
        balance = _quantize(balance + net) or Decimal("0.00")
        db.session.add(
            MoneyScheduleDailyBalance(user_id=uid, date=current, closing_balance=balance)
        )
        current += step

    db.session.commit()


def ensure_row(day: ddate, user_id: int | None) -> MoneyScheduleRow:
    uid = _require_user_id(user_id)
    row = MoneyScheduleRow.query.filter_by(user_id=uid, date=day).first()
    if row is None:
        row = MoneyScheduleRow(
            user_id=uid,
            date=day,
            inflow=Decimal("0.00"),
            outflow=Decimal("0.00"),
        )
        db.session.add(row)
    return row


def ensure_rows_between(start_day: ddate, end_day: ddate, user_id: int | None) -> None:
    uid = _require_user_id(user_id)
    if end_day < start_day:
        return
    current = start_day
    step = timedelta(days=1)
    while current <= end_day:
        ensure_row(current, uid)
        current += step


def _previous_predicted(before_day: ddate, user_id: int | None) -> Decimal | None:
    uid = _require_user_id(user_id)
    previous_row = (
        MoneyScheduleRow.query.filter(MoneyScheduleRow.user_id == uid)
        .filter(MoneyScheduleRow.date < before_day)
        .order_by(MoneyScheduleRow.date.desc())
        .first()
    )
    if previous_row and previous_row.predicted_closing is not None:
        return _quantize(previous_row.predicted_closing)
    return None


def recompute_from(start_day: ddate, user_id: int | None) -> None:
    """Recalculate predicted/actual/variance from start_day forward in date order."""
    uid = _require_user_id(user_id)
    rows = (
        MoneyScheduleRow.query.filter(MoneyScheduleRow.user_id == uid)
        .filter(MoneyScheduleRow.date >= start_day)
        .order_by(MoneyScheduleRow.date.asc())
        .all()
    )
    if not rows:
        return

    last_row_date = rows[-1].date if rows else None
    rebuild_daily_balances(uid, end_date=last_row_date)

    init_date = get_init_date()
    prev_pred = _previous_predicted(rows[0].date, uid)
    init_balance = _initial_balance(uid)

    row_dates = {row.date for row in rows}
    balance_entries = (
        MoneyScheduleDailyBalance.query.filter(
            MoneyScheduleDailyBalance.user_id == uid,
            MoneyScheduleDailyBalance.date.in_(row_dates)
        ).all()
        if row_dates
        else []
    )
    balance_map = {
        entry.date: _quantize(entry.closing_balance) or Decimal("0.00")
        for entry in balance_entries
    }

    for row in rows:
        inflow = _quantize(row.inflow or Decimal("0"))
        outflow = _quantize(row.outflow or Decimal("0"))
        row.inflow = inflow
        row.outflow = outflow

        is_init_day = init_date is not None and row.date == init_date
        if is_init_day:
            row.inflow = Decimal("0.00")
            row.outflow = Decimal("0.00")
            row.description = row.description or ""
            baseline = balance_map.get(row.date, _quantize(init_balance) or Decimal("0.00"))
            row.predicted_closing = baseline
            prev_pred = row.predicted_closing
        else:
            baseline_pred = prev_pred if prev_pred is not None else init_balance
            predicted = baseline_pred + inflow - outflow
            row.predicted_closing = _quantize(predicted)
            prev_pred = row.predicted_closing

        actual_from_store = balance_map.get(row.date, Decimal("0.00"))
        row.actual_closing = _quantize(actual_from_store)

        if row.actual_closing is not None and row.predicted_closing is not None:
            row.variance = _quantize(row.actual_closing - row.predicted_closing)
        else:
            row.variance = None

    db.session.commit()


def recompute_from_last_change(user_id: int | None, fallback_day: ddate | None = None) -> None:
    """Recompute starting from the most recently updated money schedule row for a user."""
    uid = _require_user_id(user_id)
    latest = (
        MoneyScheduleRow.query.filter(MoneyScheduleRow.user_id == uid)
        .order_by(MoneyScheduleRow.updated_at.desc(), MoneyScheduleRow.date.desc())
        .first()
    )
    target = fallback_day or (latest.date if latest else None)
    if not target:
        return
    recompute_from(target, uid)


def _reset_auto_generated_rows(start_day: ddate, end_day: ddate, user_id: int | None) -> None:
    uid = _require_user_id(user_id)
    rows = (
        MoneyScheduleRow.query.filter(MoneyScheduleRow.user_id == uid)
        .filter(MoneyScheduleRow.date >= start_day)
        .filter(MoneyScheduleRow.date <= end_day)
        .filter(MoneyScheduleRow.is_auto_generated.is_(True))
        .all()
    )
    for row in rows:
        row.inflow = Decimal("0.00")
        row.outflow = Decimal("0.00")
        row.description = ""
        row.is_auto_generated = False


def _row_available_for_auto(row: MoneyScheduleRow) -> bool:
    if row.is_auto_generated:
        return True
    inflow = _quantize(row.inflow or Decimal("0")) or Decimal("0")
    outflow = _quantize(row.outflow or Decimal("0")) or Decimal("0")
    has_description = bool((row.description or "").strip())
    return inflow == Decimal("0") and outflow == Decimal("0") and not has_description


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _event_matches_date(event: MoneyScheduleRecurringEvent, target: ddate) -> bool:
    if target < event.start_date:
        return False
    if event.end_date and target > event.end_date:
        return False

    freq = (event.frequency or "monthly").lower()
    interval = max(1, event.interval or 1)
    delta_days = (target - event.start_date).days

    if freq in {"once", "single"}:
        return target == event.start_date
    if freq == "daily":
        return delta_days >= 0 and delta_days % interval == 0
    if freq == "weekly":
        if delta_days < 0:
            return False
        week_delta = delta_days // 7
        if week_delta % interval != 0:
            return False
        weekdays = event.weekday_list() or [event.start_date.weekday()]
        return target.weekday() in weekdays
    if freq == "custom":
        return target in event.custom_date_set()

    base_index = event.start_date.year * 12 + event.start_date.month
    target_index = target.year * 12 + target.month
    if target_index < base_index:
        return False
    month_span = target_index - base_index
    if month_span % interval != 0:
        return False
    month_day = event.month_day or event.start_date.day
    last_dom = _days_in_month(target.year, target.month)
    effective_dom = min(month_day, last_dom)
    return target.day == effective_dom


def quick_add_entry(user_id: int | None, day: ddate, description: str, direction: str, amount: Decimal) -> MoneyScheduleRow:
    """Add a single inflow/outflow and recompute forward."""
    uid = _require_user_id(user_id)
    row = ensure_row(day, uid)
    row.description = description
    if direction == "inflow":
        row.inflow = _quantize((row.inflow or Decimal("0")) + amount) or Decimal("0.00")
    else:
        row.outflow = _quantize((row.outflow or Decimal("0")) + amount) or Decimal("0.00")
    row.is_auto_generated = False
    db.session.flush()
    recompute_from_last_change(uid, fallback_day=day)
    return MoneyScheduleRow.query.filter_by(user_id=uid, date=day).first() or row


def update_row_amounts(
    user_id: int | None,
    day: ddate,
    description: str,
    inflow: Decimal,
    outflow: Decimal,
) -> MoneyScheduleRow | None:
    """Update a specific day amounts/description and recompute forward."""
    uid = _require_user_id(user_id)
    row = ensure_row(day, uid)
    row.description = description
    row.inflow = _quantize(inflow) or Decimal("0.00")
    row.outflow = _quantize(outflow) or Decimal("0.00")
    row.is_auto_generated = False
    db.session.flush()
    recompute_from_last_change(uid, fallback_day=day)
    return MoneyScheduleRow.query.filter_by(user_id=uid, date=day).first()


def create_recurring_event(user_id: int | None, payload: dict) -> MoneyScheduleRecurringEvent:
    """Create a recurring event for the user."""
    uid = _require_user_id(user_id)
    clean_payload = dict(payload or {})
    clean_payload.pop("user_id", None)
    event = MoneyScheduleRecurringEvent(user_id=uid, **clean_payload)
    db.session.add(event)
    db.session.commit()
    return event


def update_recurring_event(user_id: int | None, event_id: int, payload: dict) -> MoneyScheduleRecurringEvent | None:
    """Update a recurring event and return it."""
    uid = _require_user_id(user_id)
    event = MoneyScheduleRecurringEvent.query.filter_by(id=event_id, user_id=uid).first()
    if not event:
        return None
    for key, value in payload.items():
        setattr(event, key, value)
    db.session.commit()
    return event


def toggle_recurring_event(user_id: int | None, event_id: int) -> MoneyScheduleRecurringEvent | None:
    """Toggle active flag on a recurring event."""
    uid = _require_user_id(user_id)
    event = MoneyScheduleRecurringEvent.query.filter_by(id=event_id, user_id=uid).first()
    if not event:
        return None
    event.is_active = not event.is_active
    db.session.commit()
    return event


def delete_recurring_event(user_id: int | None, event_id: int) -> bool:
    """Delete a recurring event if owned by user."""
    uid = _require_user_id(user_id)
    event = MoneyScheduleRecurringEvent.query.filter_by(id=event_id, user_id=uid).first()
    if not event:
        return False
    db.session.delete(event)
    db.session.commit()
    return True


def update_scenario_row(
    scenario_id: int,
    user_id: int | None,
    day: ddate,
    description: str,
    inflow: Decimal,
    outflow: Decimal,
) -> MoneyScheduleScenarioRow | None:
    """Create or update a scenario row and recompute scenario."""
    uid = _require_user_id(user_id)
    scenario = MoneyScheduleScenario.query.filter_by(id=scenario_id, user_id=uid).first()
    if not scenario:
        return None
    row = MoneyScheduleScenarioRow.query.filter_by(scenario_id=scenario.id, date=day).first()
    if row is None:
        row = MoneyScheduleScenarioRow(
            scenario_id=scenario.id,
            date=day,
            inflow=inflow,
            outflow=outflow,
            description=description,
        )
        db.session.add(row)
    else:
        row.description = description
        row.inflow = inflow
        row.outflow = outflow
    db.session.flush()
    recompute_scenario(scenario.id, uid)
    return MoneyScheduleScenarioRow.query.filter_by(scenario_id=scenario.id, date=day).first()


def delete_scenario_for_user(user_id: int | None, scenario_id: int) -> MoneyScheduleScenario | None:
    """Delete a scenario and its rows."""
    uid = _require_user_id(user_id)
    scenario = MoneyScheduleScenario.query.filter_by(id=scenario_id, user_id=uid).first()
    if not scenario:
        return None
    MoneyScheduleScenarioRow.query.filter_by(scenario_id=scenario.id).delete(synchronize_session=False)
    db.session.delete(scenario)
    db.session.commit()
    return scenario


def _iter_event_occurrences(
    event: MoneyScheduleRecurringEvent, start_day: ddate, end_day: ddate
):
    window_start = max(start_day, event.start_date)
    window_end = min(end_day, event.end_date) if event.end_date else end_day
    current = window_start
    while current <= window_end:
        if _event_matches_date(event, current):
            yield current
        current += timedelta(days=1)


def apply_recurring_events(start_day: ddate, end_day: ddate, user_id: int | None) -> None:
    if end_day < start_day:
        return
    uid = _require_user_id(user_id)
    events = (
        MoneyScheduleRecurringEvent.query.filter(
            MoneyScheduleRecurringEvent.is_active.is_(True)
        )
        .filter(MoneyScheduleRecurringEvent.user_id == uid)
        .filter(MoneyScheduleRecurringEvent.start_date <= end_day)
        .filter(
            or_(
                MoneyScheduleRecurringEvent.end_date.is_(None),
                MoneyScheduleRecurringEvent.end_date >= start_day,
            )
        )
        .all()
    )
    if not events:
        return

    _reset_auto_generated_rows(start_day, end_day, uid)

    aggregated: dict[ddate, dict[str, object]] = defaultdict(
        lambda: {
            "inflow": Decimal("0.00"),
            "outflow": Decimal("0.00"),
            "descriptions": [],
        }
    )

    for event in events:
        amount = _quantize(event.amount) or Decimal("0.00")
        if amount <= 0:
            continue
        for occ in _iter_event_occurrences(event, start_day, end_day):
            bucket = aggregated[occ]
            if event.direction == "outflow":
                bucket["outflow"] = _quantize(bucket["outflow"] + amount) or Decimal("0.00")
            else:
                bucket["inflow"] = _quantize(bucket["inflow"] + amount) or Decimal("0.00")
            bucket["descriptions"].append(event.description)

    if not aggregated:
        return

    for occ_date, payload in aggregated.items():
        row = ensure_row(occ_date, uid)
        if not _row_available_for_auto(row):
            continue
        row.inflow = payload["inflow"]
        row.outflow = payload["outflow"]
        if payload["descriptions"]:
            unique_desc = list(dict.fromkeys(payload["descriptions"]))
            row.description = " + ".join(unique_desc)[:255]
        row.is_auto_generated = True

    db.session.flush()


# Backward-compatible alias
def finance_apply_recurring_events(start_day: ddate, end_day: ddate, user_id: int | None) -> None:
    apply_recurring_events(start_day, end_day, user_id)


def detect_schedule_alerts(
    rows: list[MoneyScheduleRow],
    today: ddate,
    *,
    deficit_horizon_days: int = 30,
    large_payment_horizon_days: int = 7,
    large_outflow_threshold: Decimal = Decimal("500000"),
    max_large_payments: int = 3,
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    """Inspect rows for an upcoming deficit and large outflows.

    Returns (deficit_warning, large_outflows).
    """
    if not rows:
        return None, []

    deficit_warning: dict[str, object] | None = None
    large_outflows: list[dict[str, object]] = []

    horizon_deficit_end = today + timedelta(days=max(deficit_horizon_days, 0))
    horizon_large_end = today + timedelta(days=max(large_payment_horizon_days, 0))

    for row in sorted(rows, key=lambda r: r.date):
        if row.date >= today and row.date <= horizon_deficit_end:
            if row.predicted_closing is not None and row.predicted_closing < 0:
                deficit_warning = {
                    "date": row.date,
                    "predicted": _quantize(row.predicted_closing) or Decimal("0.00"),
                }
                break

    for row in sorted(rows, key=lambda r: r.date):
        if row.date < today or row.date > horizon_large_end:
            continue
        outflow = _quantize(row.outflow or Decimal("0")) or Decimal("0")
        if outflow >= large_outflow_threshold:
            large_outflows.append(
                {
                    "date": row.date,
                    "outflow": outflow,
                    "description": row.description or "",
                }
            )

    large_outflows.sort(key=lambda item: (item["date"], -item["outflow"]))
    return deficit_warning, large_outflows[:max_large_payments]


def _recompute_scenario_rows(
    rows: list[MoneyScheduleScenarioRow],
    user_id: int,
) -> None:
    if not rows:
        return

    init_balance = _initial_balance(user_id)
    init_date = get_init_date()
    prev_pred: Decimal | None = None
    baseline = _quantize(init_balance) or Decimal("0.00")

    for row in sorted(rows, key=lambda r: r.date):
        inflow = _quantize(row.inflow or Decimal("0")) or Decimal("0")
        outflow = _quantize(row.outflow or Decimal("0")) or Decimal("0")
        row.inflow = inflow
        row.outflow = outflow

        is_init_day = init_date is not None and row.date == init_date
        if is_init_day:
            row.predicted_closing = baseline
            prev_pred = row.predicted_closing
        else:
            base_pred = prev_pred if prev_pred is not None else baseline
            row.predicted_closing = _quantize(base_pred + inflow - outflow)
            prev_pred = row.predicted_closing

        row.actual_closing = None
        row.variance = None


def create_scenario_from_window(
    name: str,
    description: str | None,
    user_id: int | None,
    start_date: ddate,
    end_date: ddate,
    *,
    clone_rows: bool = True,
) -> MoneyScheduleScenario:
    uid = _require_user_id(user_id)
    if end_date < start_date:
        raise ValueError("End date must be on or after start date.")

    init_date = get_init_date()
    effective_start = max(start_date, init_date) if init_date else start_date

    ensure_rows_between(effective_start, end_date, uid)
    apply_recurring_events(effective_start, end_date, uid)
    recompute_from(effective_start, uid)

    scenario = MoneyScheduleScenario(
        user_id=uid,
        name=name or "Scenario",
        description=description or None,
        base_start=effective_start,
        base_end=end_date,
    )
    db.session.add(scenario)
    db.session.flush()

    scenario_rows: list[MoneyScheduleScenarioRow] = []
    if clone_rows:
        base_rows = (
            MoneyScheduleRow.query.filter_by(user_id=uid)
            .filter(MoneyScheduleRow.date >= effective_start)
            .filter(MoneyScheduleRow.date <= end_date)
            .order_by(MoneyScheduleRow.date.asc())
            .all()
        )
        for row in base_rows:
            scenario_rows.append(
                MoneyScheduleScenarioRow(
                    scenario_id=scenario.id,
                    date=row.date,
                    description=row.description or "",
                    inflow=row.inflow or Decimal("0"),
                    outflow=row.outflow or Decimal("0"),
                )
            )
    else:
        current = effective_start
        step = timedelta(days=1)
        while current <= end_date:
            scenario_rows.append(
                MoneyScheduleScenarioRow(
                    scenario_id=scenario.id,
                    date=current,
                    description="",
                    inflow=Decimal("0"),
                    outflow=Decimal("0"),
                )
            )
            current += step

    db.session.add_all(scenario_rows)
    _recompute_scenario_rows(scenario_rows, uid)
    db.session.commit()
    return scenario


def recompute_scenario(scenario_id: int, user_id: int | None) -> None:
    uid = _require_user_id(user_id)
    scenario = (
        MoneyScheduleScenario.query.filter_by(id=scenario_id, user_id=uid)
        .first()
    )
    if not scenario:
        raise ValueError("Scenario not found.")
    rows = (
        MoneyScheduleScenarioRow.query.filter_by(scenario_id=scenario.id)
        .order_by(MoneyScheduleScenarioRow.date.asc())
        .all()
    )
    _recompute_scenario_rows(rows, uid)
    db.session.commit()
