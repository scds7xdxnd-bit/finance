from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Dict

from finance_app import db
from finance_app.models.money_account import MoneyScheduleAccount as Account
from finance_app.models.scheduled_transaction import ScheduledTransaction, TransactionStatus
from finance_app.services.forecast import compute_daily_forecast, month_grid
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

forecast_bp = Blueprint(
    "forecast",
    __name__,
    template_folder="../templates",
    static_folder="../static",
)


DEFAULT_BUFFER_FLOOR = Decimal("500000")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_floor(value: str | None) -> Decimal:
    if not value:
        return DEFAULT_BUFFER_FLOOR
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        return DEFAULT_BUFFER_FLOOR
    if parsed < 0:
        return DEFAULT_BUFFER_FLOOR
    return parsed


def _serialize_day(day: Dict) -> Dict:
    return {
        "date": day["date"].isoformat(),
        "opening_balance": str(day["opening_balance"]),
        "inflow": str(day["inflow"]),
        "outflow": str(day["outflow"]),
        "closing_balance": str(day["closing_balance"]),
        "items": [
            {
                "id": item.id,
                "description": item.description,
                "amount": str(item.amount),
                "category": item.category,
                "status": item.status.value if hasattr(item.status, "value") else item.status,
                "account_name": item.account.name if item.account else None,
            }
            for item in day["items"]
        ],
    }


def _format_currency(value: Decimal) -> str:
    quantized = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{quantized:,}"


@forecast_bp.route("/forecast")
def forecast_index():
    today = date.today()
    start_param = request.args.get("start")
    end_param = request.args.get("end")
    view = request.args.get("view", "table")
    currency = (request.args.get("currency") or "KRW").upper()
    buffer_floor = _parse_floor(request.args.get("floor"))

    start_date = _parse_date(start_param) or today
    default_end = start_date + timedelta(days=59)
    end_date = _parse_date(end_param) or default_end

    daily_rows = compute_daily_forecast(
        db.session, start_date=start_date, end_date=end_date, base_currency=currency
    )

    accounts = (
        db.session.query(Account)
        .filter(
            Account.currency == currency,
            Account.is_included_in_closing.is_(True),
        )
        .order_by(Account.name.asc())
        .all()
    )

    total_inflow = sum((row["inflow"] for row in daily_rows), start=Decimal("0"))
    total_outflow = sum((row["outflow"] for row in daily_rows), start=Decimal("0"))
    closing_balance = daily_rows[-1]["closing_balance"] if daily_rows else Decimal("0")
    opening_balance = daily_rows[0]["opening_balance"] if daily_rows else Decimal("0")

    at_risk_days = [row for row in daily_rows if row["closing_balance"] < buffer_floor]
    at_risk_dates = [row["date"].isoformat() for row in at_risk_days]
    earliest_at_risk = (
        min((row["date"] for row in at_risk_days), default=None)
        if at_risk_days
        else None
    )
    lowest_closing = min((row["closing_balance"] for row in daily_rows), default=None)

    calendar_months = month_grid(start_date, end_date)
    day_map: Dict[str, Dict] = {
        row["date"].isoformat(): row for row in daily_rows
    }

    js_payload = {
        "currency": currency,
        "opening_balance": str(opening_balance),
        "total_inflow": str(total_inflow),
        "total_outflow": str(total_outflow),
        "closing_balance": str(closing_balance),
        "buffer_floor": str(buffer_floor),
        "at_risk_dates": at_risk_dates,
        "days": [_serialize_day(row) for row in daily_rows],
    }

    return render_template(
        "forecast/index.html",
        view=view,
        start_date=start_date,
        end_date=end_date,
        currency=currency,
        daily_rows=daily_rows,
        total_inflow=total_inflow,
        total_outflow=total_outflow,
        closing_balance=closing_balance,
        opening_balance=opening_balance,
        buffer_floor=buffer_floor,
        at_risk_dates=at_risk_dates,
        earliest_at_risk=earliest_at_risk,
        lowest_closing=lowest_closing,
        calendar_months=calendar_months,
        day_map=day_map,
        format_currency=_format_currency,
        today=today,
        js_payload=js_payload,
        accounts=accounts,
    )


@forecast_bp.route("/api/forecast.json")
def forecast_api():
    today = date.today()
    start_param = request.args.get("start")
    end_param = request.args.get("end")
    currency = (request.args.get("currency") or "KRW").upper()
    buffer_floor = _parse_floor(request.args.get("floor"))

    start_date = _parse_date(start_param) or today
    default_end = start_date + timedelta(days=59)
    end_date = _parse_date(end_param) or default_end

    daily_rows = compute_daily_forecast(
        db.session, start_date=start_date, end_date=end_date, base_currency=currency
    )

    total_inflow = sum((row["inflow"] for row in daily_rows), start=Decimal("0"))
    total_outflow = sum((row["outflow"] for row in daily_rows), start=Decimal("0"))
    opening_balance = daily_rows[0]["opening_balance"] if daily_rows else Decimal("0")
    at_risk_dates = [
        row["date"].isoformat() for row in daily_rows if row["closing_balance"] < buffer_floor
    ]

    payload = {
        "currency": currency,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "opening_balance": str(opening_balance),
        "total_inflow": str(total_inflow),
        "total_outflow": str(total_outflow),
        "buffer_floor": str(buffer_floor),
        "at_risk_dates": at_risk_dates,
        "days": [_serialize_day(row) for row in daily_rows],
    }
    return jsonify(payload)


@forecast_bp.route("/forecast/schedule", methods=["POST"])
def add_schedule_item():
    description = (request.form.get("description") or "").strip()
    category = (request.form.get("category") or "").strip() or None
    amount_raw = request.form.get("amount")
    date_raw = request.form.get("date")
    account_id_raw = request.form.get("account_id")
    currency = (request.form.get("currency") or "KRW").upper()
    view = request.form.get("view") or "table"
    start = request.form.get("start")
    end = request.form.get("end")
    floor = request.form.get("floor")

    params = {"view": view, "currency": currency}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    if floor:
        params["floor"] = floor

    target_date = _parse_date(date_raw)
    try:
        amount = Decimal(amount_raw) if amount_raw is not None else None
    except (InvalidOperation, ValueError):
        amount = None

    try:
        account_id = int(account_id_raw) if account_id_raw is not None else None
    except ValueError:
        account_id = None

    if not description or amount is None or target_date is None or account_id is None:
        flash("Please provide description, date, amount, and account.", "danger")
        return redirect(url_for("forecast.forecast_index", **params))

    account = (
        db.session.query(Account)
        .filter(Account.id == account_id)
        .filter(Account.currency == currency)
        .filter(Account.is_included_in_closing.is_(True))
        .first()
    )
    if account is None:
        flash("Account not found or not eligible for closing balance.", "danger")
        return redirect(url_for("forecast.forecast_index", **params))

    tx = ScheduledTransaction(
        date=target_date,
        description=description,
        amount=amount,
        account=account,
        category=category,
        status=TransactionStatus.PLANNED,
    )
    db.session.add(tx)
    db.session.commit()

    flash("Scheduled item added.", "success")
    return redirect(url_for("forecast.forecast_index", **params))
