from __future__ import annotations

from enum import Enum

from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import relationship

from finance_app.extensions import db


class TransactionStatus(str, Enum):
    PLANNED = "planned"
    COMPLETED = "completed"


class ScheduledTransaction(db.Model):
    """Scheduled inflow/outflow used for cash forecast."""

    __tablename__ = "money_schedule_transactions"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    description = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    account_id = db.Column(
        db.Integer,
        db.ForeignKey("money_schedule_accounts.id"),
        nullable=False,
    )
    category = db.Column(db.String(120))
    status = db.Column(
        SQLEnum(TransactionStatus, name="money_schedule_tx_status"),
        default=TransactionStatus.PLANNED,
        nullable=False,
    )

    account = relationship(
        "finance_app.models.money_account.MoneyScheduleAccount",
        back_populates="scheduled_transactions",
    )

    def __repr__(self) -> str:
        return f"<ScheduledTransaction id={self.id} date={self.date} amount={self.amount}>"
