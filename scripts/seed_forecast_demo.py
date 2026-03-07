from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from finance_app import create_app, db  # noqa: E402
from finance_app.models.money_account import AccountType, MoneyScheduleAccount  # noqa: E402
from finance_app.models.scheduled_transaction import ScheduledTransaction, TransactionStatus  # noqa: E402

AUTO_CREATE_SCHEMA = os.environ.get("AUTO_CREATE_SCHEMA", "").lower() == "true"


def seed_forecast_demo():
    today = date.today()

    app = create_app()
    with app.app_context():
        if not AUTO_CREATE_SCHEMA:
            print("AUTO_CREATE_SCHEMA is not true; skipping db.create_all for seed_forecast_demo.")
            return

        db.create_all()

        ScheduledTransaction.query.delete()
        MoneyScheduleAccount.query.delete()
        db.session.commit()

        accounts = [
            MoneyScheduleAccount(name="Wallet", type=AccountType.CASH, currency="KRW", current_balance=Decimal("150000")),
            MoneyScheduleAccount(name="Checking", type=AccountType.CHECKING, currency="KRW", current_balance=Decimal("1200000")),
            MoneyScheduleAccount(name="Savings", type=AccountType.SAVINGS, currency="KRW", current_balance=Decimal("2150000")),
        ]

        db.session.add_all(accounts)
        db.session.flush()

        account_lookup = {account.name: account for account in accounts}

        schedule_rows = [
            {
                "days_from_today": 5,
                "description": "Scholarship",
                "amount": Decimal("4800000"),
                "account": "Checking",
                "category": "scholarship",
                "status": TransactionStatus.PLANNED,
            },
            {
                "days_from_today": 12,
                "description": "Rent",
                "amount": Decimal("-700000"),
                "account": "Checking",
                "category": "rent",
                "status": TransactionStatus.PLANNED,
            },
            {
                "days_from_today": 18,
                "description": "Debt repayment",
                "amount": Decimal("-300000"),
                "account": "Checking",
                "category": "debt_repayment",
                "status": TransactionStatus.PLANNED,
            },
            {
                "days_from_today": 24,
                "description": "Allowance",
                "amount": Decimal("650000"),
                "account": "Wallet",
                "category": "allowance",
                "status": TransactionStatus.PLANNED,
            },
            {
                "days_from_today": 8,
                "description": "Book sale",
                "amount": Decimal("120000"),
                "account": "Wallet",
                "category": "sale",
                "status": TransactionStatus.PLANNED,
            },
            {
                "days_from_today": 15,
                "description": "Groceries",
                "amount": Decimal("-110000"),
                "account": "Wallet",
                "category": "groceries",
                "status": TransactionStatus.PLANNED,
            },
            {
                "days_from_today": 30,
                "description": "Freelance gig",
                "amount": Decimal("350000"),
                "account": "Checking",
                "category": "income",
                "status": TransactionStatus.PLANNED,
            },
            {
                "days_from_today": 33,
                "description": "Utilities",
                "amount": Decimal("-90000"),
                "account": "Checking",
                "category": "utilities",
                "status": TransactionStatus.PLANNED,
            },
            {
                "days_from_today": 42,
                "description": "Concert refund",
                "amount": Decimal("95000"),
                "account": "Savings",
                "category": "refund",
                "status": TransactionStatus.COMPLETED,
            },
            {
                "days_from_today": 55,
                "description": "Insurance premium",
                "amount": Decimal("-180000"),
                "account": "Savings",
                "category": "insurance",
                "status": TransactionStatus.PLANNED,
            },
        ]

        transactions = []
        for row in schedule_rows:
            tx = ScheduledTransaction(
                date=today + timedelta(days=row["days_from_today"]),
                description=row["description"],
                amount=row["amount"],
                category=row["category"],
                status=row["status"],
                account=account_lookup[row["account"]],
            )
            transactions.append(tx)

        db.session.add_all(transactions)
        db.session.commit()

        print(f"Seeded {len(accounts)} accounts and {len(transactions)} scheduled transactions.")


if __name__ == "__main__":
    seed_forecast_demo()
