from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance_app.extensions import db


class MoneyScheduleRow(db.Model):
    """Single day in the money schedule forecast."""

    __tablename__ = "money_schedule_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), default="", server_default="")
    inflow: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    outflow: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    predicted_closing: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    actual_closing: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    variance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_auto_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=db.func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=db.func.now(), onupdate=db.func.now())

    __table_args__ = (
        CheckConstraint("inflow >= 0", name="ck_money_schedule_inflow_nonneg"),
        CheckConstraint("outflow >= 0", name="ck_money_schedule_outflow_nonneg"),
        UniqueConstraint("user_id", "date", name="uq_money_schedule_user_date"),
    )

    def __repr__(self) -> str:
        return f"<MoneyScheduleRow user={self.user_id} date={self.date} inflow={self.inflow} outflow={self.outflow}>"


class Setting(db.Model):
    """Key/value settings bucket for the money schedule."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(512), nullable=False)


class MoneyScheduleAssetInclude(db.Model):
    """Explicit account inclusion overrides for the money schedule baseline."""

    __tablename__ = "money_schedule_asset_includes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    account_id: Mapped[int] = mapped_column(db.Integer, nullable=False, index=True)
    initial_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))


class MoneyScheduleDailyBalance(db.Model):
    """Materialized daily closing balance used for actual cash tracking."""

    __tablename__ = "money_schedule_daily_balances"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=db.func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_money_schedule_balance_user_day"),
    )


class AccountSnapshot(db.Model):
    """End-of-day balance for an account."""

    __tablename__ = "account_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("money_schedule_accounts.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    eod_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    account = relationship(
        "finance_app.models.money_account.MoneyScheduleAccount",
        back_populates="snapshots",
    )

    __table_args__ = (
        UniqueConstraint("account_id", "date", name="uq_account_snapshot_day"),
    )

    def __repr__(self) -> str:
        return f"<AccountSnapshot account={self.account_id} date={self.date} balance={self.eod_balance}>"


class MoneyScheduleRecurringEvent(db.Model):
    """Recurring template that auto-fills money schedule rows."""

    __tablename__ = "money_schedule_recurring_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # 'inflow' or 'outflow'
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, index=True)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    interval: Mapped[int] = mapped_column(db.Integer, nullable=False, default=1)
    weekdays: Mapped[str | None] = mapped_column(String(32))  # comma separated weekday ints
    month_day: Mapped[int | None] = mapped_column(db.Integer)
    custom_dates: Mapped[dict | list | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default="1")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=db.func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=db.func.now(), onupdate=db.func.now())

    def weekday_list(self) -> list[int]:
        if not self.weekdays:
            return []
        try:
            return [int(token.strip()) for token in self.weekdays.split(",") if token.strip()]
        except ValueError:
            return []

    def custom_date_set(self) -> set[date]:
        values = self.custom_dates or []
        result: set[date] = set()
        for value in values:
            try:
                if isinstance(value, str):
                    result.add(date.fromisoformat(value))
                elif isinstance(value, dict) and value.get("date"):
                    result.add(date.fromisoformat(value["date"]))
            except (ValueError, TypeError):
                continue
        return result

    def __repr__(self) -> str:
        return f"<MoneyScheduleRecurringEvent id={self.id} {self.frequency} {self.direction} {self.amount}>"


class MoneyScheduleScenario(db.Model):
    """Saved what-if plan cloned from the main money schedule."""

    __tablename__ = "money_schedule_scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    base_start: Mapped[date] = mapped_column(Date, nullable=False)
    base_end: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=db.func.now())

    def __repr__(self) -> str:
        return f"<MoneyScheduleScenario id={self.id} name={self.name!r}>"


class MoneyScheduleScenarioRow(db.Model):
    """Daily row inside a scenario (predicted-only, no actuals)."""

    __tablename__ = "money_schedule_scenario_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("money_schedule_scenarios.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), default="", server_default="")
    inflow: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    outflow: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    predicted_closing: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    actual_closing: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    variance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=db.func.now())

    __table_args__ = (
        UniqueConstraint("scenario_id", "date", name="uq_ms_scenario_day"),
    )

    def __repr__(self) -> str:
        return f"<MoneyScheduleScenarioRow scenario={self.scenario_id} date={self.date}>"
