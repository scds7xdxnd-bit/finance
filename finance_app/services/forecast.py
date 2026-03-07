from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Sequence, Tuple

from sqlalchemy.orm import Session

from finance_app.models.money_account import MoneyScheduleAccount as Account
from finance_app.models.scheduled_transaction import ScheduledTransaction


@dataclass
class DailyForecastRow:
    date: date
    opening_balance: Decimal
    inflow: Decimal
    outflow: Decimal
    closing_balance: Decimal
    items: Sequence[ScheduledTransaction]


def _daterange(start: date, end: date) -> Iterable[date]:
    current = start
    delta = timedelta(days=1)
    while current <= end:
        yield current
        current += delta


def compute_daily_forecast(
    session: Session,
    start_date: date,
    end_date: date,
    base_currency: str = "KRW",
) -> List[Dict]:
    """Compute daily opening/inflow/outflow/closing cash balances."""
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    included_accounts: Sequence[Account] = (
        session.query(Account)
        .filter(
            Account.currency == base_currency,
            Account.is_included_in_closing.is_(True),
        )
        .all()
    )

    opening_balance = sum(
        (
            Decimal(account.current_balance or Decimal("0"))
            for account in included_accounts
        ),
        start=Decimal("0"),
    )

    transactions: Sequence[ScheduledTransaction] = (
        session.query(ScheduledTransaction)
        .join(Account)
        .filter(
            ScheduledTransaction.date >= start_date,
            ScheduledTransaction.date <= end_date,
            Account.currency == base_currency,
            Account.is_included_in_closing.is_(True),
        )
        .order_by(ScheduledTransaction.date.asc(), ScheduledTransaction.id.asc())
        .all()
    )

    tx_by_day: Dict[date, List[ScheduledTransaction]] = {}
    for tx in transactions:
        tx_by_day.setdefault(tx.date, []).append(tx)

    daily_rows: List[Dict] = []
    running_opening = Decimal(opening_balance)

    for current_day in _daterange(start_date, end_date):
        items = tx_by_day.get(current_day, [])
        inflow = sum(
            (Decimal(tx.amount) for tx in items if tx.amount and tx.amount > 0),
            start=Decimal("0"),
        )
        outflow = sum(
            (Decimal(-tx.amount) for tx in items if tx.amount and tx.amount < 0),
            start=Decimal("0"),
        )
        closing = running_opening + inflow - outflow

        daily_rows.append(
            {
                "date": current_day,
                "opening_balance": running_opening,
                "inflow": inflow,
                "outflow": outflow,
                "closing_balance": closing,
                "items": items,
            }
        )

        running_opening = closing

    return daily_rows


def month_grid(start_date: date, end_date: date) -> List[Dict]:
    """Prepare calendar grids spanning start_date..end_date inclusive."""
    months: List[Tuple[int, int]] = []
    current = date(start_date.year, start_date.month, 1)
    limit = date(end_date.year, end_date.month, 1)

    while current <= limit:
        months.append((current.year, current.month))
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        current = date(year, month, 1)

    cal = calendar.Calendar(firstweekday=6)  # start weeks on Sunday
    result: List[Dict] = []

    for year, month in months:
        weeks = cal.monthdatescalendar(year, month)
        # Ensure we always produce six weeks to keep grid height stable
        while len(weeks) < 6:
            last_week = weeks[-1]
            next_week = [
                last_week[-1] + timedelta(days=offset + 1) for offset in range(7)
            ]
            weeks.append(next_week)

        grid = []
        for week in weeks:
            row = []
            for day in week:
                row.append(
                    {
                        "date": day,
                        "in_month": day.month == month,
                    }
                )
            grid.append(row)

        result.append(
            {
                "label": date(year, month, 1).strftime("%B %Y"),
                "weeks": grid,
            }
        )

    return result
