from __future__ import annotations

from datetime import date as ddate
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from finance_app.extensions import db
from finance_app.lib.auth import current_user
from finance_app.models.money_schedule import (
    MoneyScheduleRecurringEvent,
    MoneyScheduleRow,
    MoneyScheduleScenario,
    MoneyScheduleScenarioRow,
)
from finance_app.services.money_schedule_service import (
    _quantize,
    apply_recurring_events,
    create_recurring_event,
    create_scenario_from_window,
    delete_recurring_event,
    delete_scenario_for_user,
    detect_schedule_alerts,
    ensure_row,
    ensure_rows_between,
    get_init_date,
    list_asset_accounts,
    quick_add_entry,
    recompute_from_last_change,
    selected_asset_ids,
    toggle_recurring_event,
    update_asset_includes,
    update_recurring_event,
    update_row_amounts,
    update_scenario_row,
)
from flask import Response, flash, jsonify, redirect, render_template, request, url_for

from . import bp

SEOUL_TZ = ZoneInfo("Asia/Seoul")


def _parse_iso_date(value: str | None, default: ddate) -> ddate:
    if not value:
        return default
    return ddate.fromisoformat(value)


def _current_user_id() -> int | None:
    user = current_user()
    return user.id if user else None


def _window_params_from_request() -> dict[str, str]:
    params: dict[str, str] = {}
    start = request.form.get("start") or request.args.get("start")
    end = request.form.get("end") or request.args.get("end")
    view = request.form.get("view") or request.args.get("view")
    scenario_id = request.form.get("scenario_id") or request.args.get("scenario_id")
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    if view:
        params["view"] = view
    if scenario_id:
        params["scenario_id"] = scenario_id
    return params


@bp.get("/")
def index() -> Response:
    now_local = datetime.now(SEOUL_TZ)
    today = now_local.date()
    user_id = _current_user_id()
    if user_id is None:
        flash("Login required to view the money schedule.", "danger")
        return redirect(url_for("auth_bp.login"))

    start_param = request.args.get("start")
    end_param = request.args.get("end")
    scenario_param = request.args.get("scenario_id")
    view_mode = request.args.get("view", "list").lower()
    if view_mode not in {"list", "calendar"}:
        view_mode = "list"

    default_start = today - timedelta(days=14)
    default_end = today + timedelta(days=14)

    start_date = _parse_iso_date(start_param, default_start)
    end_date = _parse_iso_date(end_param, default_end)

    scenario: MoneyScheduleScenario | None = None
    scenario_mode = False
    if scenario_param and scenario_param.isdigit():
        scenario = (
            MoneyScheduleScenario.query.filter_by(id=int(scenario_param), user_id=user_id)
            .first()
        )
        scenario_mode = scenario is not None
        if scenario_mode:
            start_date = scenario.base_start
            end_date = scenario.base_end
        else:
            flash("Scenario not found.", "warning")

    init_date = get_init_date()
    effective_start = start_date
    if init_date:
        ensure_row(init_date, user_id)
        db.session.flush()
        effective_start = max(init_date, start_date)
    else:
        flash(
            "Set the Trial Balance initialization date to seed the Money Schedule baseline.",
            "danger",
        )

    ensure_rows_between(effective_start, end_date, user_id)
    db.session.flush()

    apply_recurring_events(effective_start, end_date, user_id)

    # Recompute from the most recent change, defaulting to the start of the window.
    recompute_from_last_change(user_id, fallback_day=effective_start)

    page = max(1, int(request.args.get("page", "1")))
    page_size = 25

    base_query = (
        MoneyScheduleRow.query.filter(MoneyScheduleRow.user_id == user_id)
        .filter(MoneyScheduleRow.date >= effective_start)
        .filter(MoneyScheduleRow.date <= end_date)
        .order_by(MoneyScheduleRow.date.asc())
    )

    calendar_months: list[dict[str, object]] = []

    if scenario_mode:
        scenario_query = (
            MoneyScheduleScenarioRow.query.filter_by(scenario_id=scenario.id)
            .order_by(MoneyScheduleScenarioRow.date.asc())
        )
        total_rows = scenario_query.count()
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        if view_mode == "calendar":
            rows = scenario_query.all()
            page = 1
            total_pages = 1
            rows_for_alerts = rows
            try:
                from finance_app.services.forecast import month_grid

                calendar_months = month_grid(effective_start, end_date)
            except Exception:
                calendar_months = []
        else:
            if page > total_pages:
                page = total_pages
            rows = (
                scenario_query.offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            rows_for_alerts = scenario_query.all()
        closing_row = scenario_query.filter(MoneyScheduleScenarioRow.date == end_date).first()
        if closing_row:
            latest_predicted = closing_row.predicted_closing
        else:
            last_row = scenario_query.order_by(MoneyScheduleScenarioRow.date.desc()).first()
            latest_predicted = last_row.predicted_closing if last_row else None
        latest_actual = None
    else:
        total_rows = base_query.count()
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        if page > total_pages:
            page = total_pages
        if view_mode == "calendar":
            rows = base_query.all()
            page = 1
            total_pages = 1
            rows_for_alerts = rows
            try:
                from finance_app.services.forecast import month_grid

                calendar_months = month_grid(effective_start, end_date)
            except Exception:
                calendar_months = []
        else:
            rows = (
                base_query.offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            rows_for_alerts = base_query.all()
        closing_row = base_query.filter(MoneyScheduleRow.date == end_date).first()
        if closing_row:
            latest_predicted = closing_row.predicted_closing
        else:
            last_row = base_query.order_by(MoneyScheduleRow.date.desc()).first()
            latest_predicted = last_row.predicted_closing if last_row else None
        latest_actual_row = (
            MoneyScheduleRow.query.filter(MoneyScheduleRow.user_id == user_id)
            .filter(MoneyScheduleRow.actual_closing.isnot(None))
            .order_by(MoneyScheduleRow.date.desc())
            .first()
        )
        latest_actual = latest_actual_row.actual_closing if latest_actual_row else None

    total_inflow = sum((row.inflow or Decimal("0")) for row in rows)
    total_outflow = sum((row.outflow or Decimal("0")) for row in rows)
    net_change = total_inflow - total_outflow

    row_map = {row.date: row for row in rows_for_alerts}

    deficit_warning, large_payments = detect_schedule_alerts(rows_for_alerts, today)
    large_payment_dates = {item["date"] for item in large_payments}

    accounts = list_asset_accounts(user_id)
    selected_ids = selected_asset_ids(user_id)

    listed_ids = {account["id"] for account in accounts}
    if user_id is not None and (selected_ids - listed_ids):
        from finance_app import Account

        for missing_id in selected_ids - listed_ids:
            account = (
                Account.query.filter(Account.id == missing_id)
                .filter(Account.user_id == user_id)
                .first()
            )
            if account:
                accounts.append(
                    {
                        "id": account.id,
                        "name": account.name,
                        "code": account.code,
                        "currency": account.currency_code,
                        "balance": Decimal("0"),
                    }
                )

    events = (
        MoneyScheduleRecurringEvent.query.filter(MoneyScheduleRecurringEvent.user_id == user_id)
        .order_by(
            MoneyScheduleRecurringEvent.is_active.desc(),
            MoneyScheduleRecurringEvent.start_date.asc(),
            MoneyScheduleRecurringEvent.description.asc(),
        ).all()
    )

    scenarios = (
        MoneyScheduleScenario.query.filter_by(user_id=user_id)
        .order_by(MoneyScheduleScenario.created_at.desc())
        .all()
    )

    base_comparison: dict[str, object] | None = None
    if scenario_mode:
        base_rows_for_compare = base_query.all()
        base_total_inflow = sum((row.inflow or Decimal("0")) for row in base_rows_for_compare)
        base_total_outflow = sum((row.outflow or Decimal("0")) for row in base_rows_for_compare)
        base_net = base_total_inflow - base_total_outflow
        base_last = base_rows_for_compare[-1] if base_rows_for_compare else None
        base_closing = base_last.predicted_closing if base_last else None
        scenario_last = rows_for_alerts[-1] if rows_for_alerts else None
        scenario_closing = scenario_last.predicted_closing if scenario_last else None
        closing_delta = None
        if base_closing is not None and scenario_closing is not None:
            closing_delta = _quantize(scenario_closing - base_closing)
        base_comparison = {
            "base_total_inflow": base_total_inflow,
            "base_total_outflow": base_total_outflow,
            "base_net": base_net,
            "base_closing": base_closing,
            "scenario_closing": scenario_closing,
            "closing_delta": closing_delta,
            "net_change_delta": _quantize(net_change - base_net),
        }

    base_series: list[dict[str, object]] = []
    scenario_series: list[dict[str, object]] = []
    if scenario_mode:
        max_points = 200
        for row in base_query.limit(max_points).all():
            base_series.append(
                {
                    "date": row.date.isoformat(),
                    "predicted": float(row.predicted_closing) if row.predicted_closing is not None else None,
                }
            )
        for row in rows_for_alerts[:max_points]:
            scenario_series.append(
                {
                    "date": row.date.isoformat(),
                    "predicted": float(row.predicted_closing) if row.predicted_closing is not None else None,
                }
            )

    return render_template(
        "money_schedule/index.html",
        rows=rows,
        start_date=effective_start,
        end_date=end_date,
        today=today,
        init_date=init_date,
        page=page,
        total_pages=total_pages,
        page_size=page_size,
        total_inflow=total_inflow,
        total_outflow=total_outflow,
        net_change=net_change,
        latest_predicted=latest_predicted,
        latest_actual=latest_actual,
        accounts=accounts,
        selected_ids=selected_ids,
        view_mode=view_mode,
        calendar_months=calendar_months,
        row_map=row_map,
        recurring_events=events,
        deficit_warning=deficit_warning,
        large_payments=large_payments,
        large_payment_dates=large_payment_dates,
        scenario=scenario,
        scenario_mode=scenario_mode,
        scenarios=scenarios,
        base_comparison=base_comparison,
        base_series=base_series,
        scenario_series=scenario_series,
    )


@bp.post("/assets")
def update_assets() -> Response:
    user_id = _current_user_id()
    if user_id is None:
        flash("Login required.", "danger")
        return redirect(url_for("auth_bp.login"))
    account_ids = {
        int(acc_id)
        for acc_id in request.form.getlist("account_ids")
        if acc_id.isdigit()
    }

    update_asset_includes(user_id, account_ids)
    flash("Money schedule baseline accounts updated.", "success")

    params: dict[str, str] = {}
    start = request.form.get("start")
    end = request.form.get("end")
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    return redirect(url_for("money_schedule.index", **params))




def _validate_amount(raw_value: str, field: str) -> Decimal:
    try:
        amount = Decimal(raw_value)
    except (InvalidOperation, TypeError):
        raise ValueError(f"{field} must be a number.")
    if amount < 0:
        raise ValueError(f"{field} must be non-negative.")
    return _quantize(amount) or Decimal("0.00")


@bp.post("/quick_add")
def quick_add() -> Response:
    """Lightweight add of a single inflow/outflow row."""
    user_id = _current_user_id()
    if user_id is None:
        flash("Login required.", "danger")
        return redirect(url_for("auth_bp.login"))

    description = (request.form.get("description") or "").strip() or "Quick entry"
    direction = (request.form.get("direction") or "outflow").lower()
    amount_raw = request.form.get("amount", "0")
    date_raw = request.form.get("date")
    params: dict[str, str] = {}
    for key in ("start", "end", "view", "floor"):
        value = request.form.get(key)
        if value:
            params[key] = value

    if not date_raw:
        flash("Date is required.", "danger")
        return redirect(url_for("money_schedule.index", **params))

    try:
        day = ddate.fromisoformat(date_raw)
        amount = _validate_amount(amount_raw, "Amount")
    except (ValueError, InvalidOperation) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("money_schedule.index", **params))

    quick_add_entry(user_id, day, description=description, direction=direction, amount=amount)

    flash("Item added to Money Schedule.", "success")
    return redirect(url_for("money_schedule.index", **params))


@bp.post("/edit")
def edit() -> Response:
    user_id = _current_user_id()
    if user_id is None:
        flash("Login required.", "danger")
        return redirect(url_for("auth_bp.login"))
    iso_date = request.form.get("date")
    desc = request.form.get("description", "")
    inflow_raw = request.form.get("inflow", "0")
    outflow_raw = request.form.get("outflow", "0")

    if not iso_date:
        flash("Missing date for update.", "danger")
        return redirect(url_for("money_schedule.index"))

    try:
        day = ddate.fromisoformat(iso_date)
        inflow = _validate_amount(inflow_raw, "Inflow")
        outflow = _validate_amount(outflow_raw, "Outflow")
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("money_schedule.index"))

    updated = update_row_amounts(user_id, day, description=desc, inflow=inflow, outflow=outflow)

    wants_json = request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"
    if wants_json and updated:
        return jsonify(
            {
                "date": updated.date.isoformat(),
                "description": updated.description or "",
                "inflow": str(updated.inflow or Decimal("0.00")),
                "outflow": str(updated.outflow or Decimal("0.00")),
                "predicted": str(updated.predicted_closing) if updated.predicted_closing is not None else None,
                "actual": str(updated.actual_closing) if updated.actual_closing is not None else None,
                "variance": str(updated.variance) if updated.variance is not None else None,
                "message": "Updated and recomputed.",
            }
        )

    flash("Money schedule updated.", "success")
    return redirect(url_for("money_schedule.index"))


def _parse_weekdays() -> str | None:
    tokens = request.form.getlist("weekdays")
    cleaned: list[str] = []
    for token in tokens:
        if token.isdigit():
            cleaned.append(str(int(token)))
    return ",".join(sorted(set(cleaned))) if cleaned else None


def _parse_custom_dates(raw: str) -> list[str]:
    if not raw:
        return []
    normalized = raw.replace("\n", ",")
    tokens = [token.strip() for token in normalized.split(",") if token.strip()]
    result: list[str] = []
    for token in tokens:
        try:
            ddate.fromisoformat(token)
        except ValueError:
            continue
        if token not in result:
            result.append(token)
    return result


def _extract_event_payload() -> tuple[dict[str, object] | None, str | None]:
    description = (request.form.get("description") or "").strip()
    direction = (request.form.get("direction") or "inflow").lower()
    amount_raw = request.form.get("amount", "0")
    start_raw = request.form.get("start_date")
    end_raw = request.form.get("end_date")
    frequency = (request.form.get("frequency") or "monthly").lower()
    interval_raw = request.form.get("interval", "1")
    month_day_raw = request.form.get("month_day")
    notes = (request.form.get("notes") or "").strip() or None

    if not description or not start_raw:
        return None, "Description and start date are required for recurring events."

    try:
        amount = _validate_amount(amount_raw, "Amount")
        start_date = ddate.fromisoformat(start_raw)
        end_date = ddate.fromisoformat(end_raw) if end_raw else None
        interval = max(1, int(interval_raw))
        month_day = int(month_day_raw) if month_day_raw else None
    except ValueError as exc:
        return None, str(exc)

    weekdays = _parse_weekdays()
    custom_dates = _parse_custom_dates(request.form.get("custom_dates", ""))

    if end_date and end_date < start_date:
        return None, "End date must be on or after the start date."

    if frequency == "custom" and not custom_dates:
        return None, "Provide at least one custom date for custom frequency."

    if frequency == "weekly":
        if not weekdays:
            weekdays = str(start_date.weekday())
        month_day = None
    elif frequency == "monthly":
        if month_day is None:
            month_day = start_date.day
        if month_day < 1 or month_day > 31:
            return None, "Day of month must be between 1 and 31."
    else:
        month_day = None

    payload = {
        "description": description,
        "direction": "outflow" if direction == "outflow" else "inflow",
        "amount": amount,
        "start_date": start_date,
        "end_date": end_date,
        "frequency": frequency,
        "interval": interval,
        "weekdays": weekdays,
        "month_day": month_day,
        "custom_dates": custom_dates or None,
        "notes": notes,
    }
    return payload, None


@bp.post("/events")
def create_event() -> Response:
    user_id = _current_user_id()
    if user_id is None:
        flash("Login required.", "danger")
        return redirect(url_for("auth_bp.login"))
    params = _window_params_from_request()
    payload, error = _extract_event_payload()
    if error:
        flash(error, "danger")
        return redirect(url_for("money_schedule.index", **params))

    payload["user_id"] = user_id
    create_recurring_event(user_id, payload)
    flash("Recurring event added.", "success")
    return redirect(url_for("money_schedule.index", **params))


@bp.post("/events/<int:event_id>/edit")
def edit_event(event_id: int) -> Response:
    user_id = _current_user_id()
    if user_id is None:
        flash("Login required.", "danger")
        return redirect(url_for("auth_bp.login"))
    params = _window_params_from_request()
    event = MoneyScheduleRecurringEvent.query.filter_by(id=event_id, user_id=user_id).first()
    if not event:
        flash("Event not found.", "danger")
        return redirect(url_for("money_schedule.index", **params))

    payload, error = _extract_event_payload()
    if error:
        flash(error, "danger")
        return redirect(url_for("money_schedule.index", **params))

    update_recurring_event(user_id, event_id, payload)
    flash("Recurring event updated.", "success")
    return redirect(url_for("money_schedule.index", **params))


@bp.post("/events/<int:event_id>/toggle")
def toggle_event(event_id: int) -> Response:
    user_id = _current_user_id()
    if user_id is None:
        flash("Login required.", "danger")
        return redirect(url_for("auth_bp.login"))
    params = _window_params_from_request()
    event = toggle_recurring_event(user_id, event_id)
    if not event:
        flash("Event not found.", "danger")
        return redirect(url_for("money_schedule.index", **params))
    status = "activated" if event.is_active else "paused"
    flash(f"Event {status}.", "success")
    return redirect(url_for("money_schedule.index", **params))


@bp.post("/events/<int:event_id>/delete")
def delete_event(event_id: int) -> Response:
    user_id = _current_user_id()
    if user_id is None:
        flash("Login required.", "danger")
        return redirect(url_for("auth_bp.login"))
    params = _window_params_from_request()
    deleted = delete_recurring_event(user_id, event_id)
    if not deleted:
        flash("Event not found.", "danger")
        return redirect(url_for("money_schedule.index", **params))
    flash("Recurring event deleted.", "success")
    return redirect(url_for("money_schedule.index", **params))


@bp.post("/scenarios")
def create_scenario() -> Response:
    user_id = _current_user_id()
    if user_id is None:
        flash("Login required.", "danger")
        return redirect(url_for("auth_bp.login"))

    now_local = datetime.now(SEOUL_TZ)
    today = now_local.date()
    start_raw = request.form.get("start") or request.args.get("start") or today.isoformat()
    end_raw = request.form.get("end") or request.args.get("end") or today.isoformat()
    name = (request.form.get("name") or "").strip() or f"Scenario {today.isoformat()}"
    description = (request.form.get("description") or "").strip() or None
    clone_rows = (request.form.get("clone_rows") or "1") != "0"

    try:
        start_date = _parse_iso_date(start_raw, today)
        end_date = _parse_iso_date(end_raw, today)
        scenario = create_scenario_from_window(name, description, user_id, start_date, end_date, clone_rows=clone_rows)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("money_schedule.index", start=start_raw, end=end_raw))

    flash("Scenario created.", "success")
    params = {"start": start_raw, "end": end_raw, "scenario_id": scenario.id}
    view = request.form.get("view") or request.args.get("view")
    if view:
        params["view"] = view
    return redirect(url_for("money_schedule.index", **params))


@bp.post("/scenarios/<int:scenario_id>/edit")
def edit_scenario_row(scenario_id: int) -> Response:
    user_id = _current_user_id()
    if user_id is None:
        flash("Login required.", "danger")
        return redirect(url_for("auth_bp.login"))

    params = _window_params_from_request()
    scenario = MoneyScheduleScenario.query.filter_by(id=scenario_id, user_id=user_id).first()
    if not scenario:
        flash("Scenario not found.", "danger")
        return redirect(url_for("money_schedule.index", **params))

    iso_date = request.form.get("date")
    desc = request.form.get("description", "")
    inflow_raw = request.form.get("inflow", "0")
    outflow_raw = request.form.get("outflow", "0")

    if not iso_date:
        flash("Missing date for update.", "danger")
        return redirect(url_for("money_schedule.index", **params))

    try:
        day = ddate.fromisoformat(iso_date)
        inflow = _validate_amount(inflow_raw, "Inflow")
        outflow = _validate_amount(outflow_raw, "Outflow")
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("money_schedule.index", **params))

    updated = update_scenario_row(
        scenario_id=scenario.id,
        user_id=user_id,
        day=day,
        description=desc,
        inflow=inflow,
        outflow=outflow,
    )

    wants_json = request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"
    if wants_json and updated:
        return jsonify(
            {
                "date": updated.date.isoformat(),
                "description": updated.description or "",
                "inflow": str(updated.inflow or Decimal("0.00")),
                "outflow": str(updated.outflow or Decimal("0.00")),
                "predicted": str(updated.predicted_closing) if updated.predicted_closing is not None else None,
                "variance": None,
                "message": "Scenario updated.",
            }
        )

    flash("Scenario updated.", "success")
    return redirect(url_for("money_schedule.index", **params))


@bp.post("/scenarios/<int:scenario_id>/delete")
def delete_scenario(scenario_id: int) -> Response:
    user_id = _current_user_id()
    if user_id is None:
        flash("Login required.", "danger")
        return redirect(url_for("auth_bp.login"))

    params = _window_params_from_request()
    scenario = delete_scenario_for_user(user_id, scenario_id)
    if not scenario:
        flash("Scenario not found.", "danger")
        return redirect(url_for("money_schedule.index", **params))
    flash("Scenario deleted.", "success")

    params.pop("scenario_id", None)
    if scenario.base_start:
        params.setdefault("start", scenario.base_start.isoformat())
    if scenario.base_end:
        params.setdefault("end", scenario.base_end.isoformat())
    return redirect(url_for("money_schedule.index", **params))
