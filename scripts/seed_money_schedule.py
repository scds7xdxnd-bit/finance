from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal

from finance_app import MoneyScheduleAccount, TrialBalanceSetting, User, create_app, db
from finance_app.models.money_schedule import AccountSnapshot, MoneyScheduleRow
from finance_app.services.money_schedule_service import ensure_row, recompute_from, set_init_date

AUTO_CREATE_SCHEMA = os.environ.get("AUTO_CREATE_SCHEMA", "").lower() == "true"


def seed_money_schedule() -> None:
    today = date.today()
    start = today - timedelta(days=3)
    end = today + timedelta(days=3)

    app = create_app()
    with app.app_context():
        if not AUTO_CREATE_SCHEMA:
            print("AUTO_CREATE_SCHEMA is not true; skipping db.create_all for seed_money_schedule.")
            return

        db.create_all()

        AccountSnapshot.query.delete()
        MoneyScheduleRow.query.delete()
        MoneyScheduleAccount.query.delete()
        db.session.commit()

        balance_seed = {
            "Wallet": Decimal("150000"),
            "Checking": Decimal("1200000"),
            "Savings": Decimal("2150000"),
        }

        accounts = [
            MoneyScheduleAccount(
                name="Wallet",
                type="cash",
                currency="KRW",
                is_included_in_closing=True,
                current_balance=balance_seed["Wallet"],
            ),
            MoneyScheduleAccount(
                name="Checking",
                type="checking",
                currency="KRW",
                is_included_in_closing=True,
                current_balance=balance_seed["Checking"],
            ),
            MoneyScheduleAccount(
                name="Savings",
                type="savings",
                currency="KRW",
                is_included_in_closing=True,
                current_balance=balance_seed["Savings"],
            ),
        ]
        db.session.add_all(accounts)
        db.session.flush()

        current_balances = balance_seed.copy()

        snapshots: list[AccountSnapshot] = []
        for offset in range((end - start).days + 1):
            day = start + timedelta(days=offset)
            day_snapshots = []
            for acct in accounts:
                # Simulate slight drift in balances to produce variance.
                delta = Decimal("50000") if acct.name == "Checking" and day.weekday() == 4 else Decimal("0")
                if acct.name == "Checking" and day.weekday() == 1:
                    delta -= Decimal("70000")
                current_balances[acct.name] = current_balances[acct.name] + delta
                day_snapshots.append(
                    AccountSnapshot(
                        account=acct,
                        date=day,
                        eod_balance=current_balances[acct.name],
                    )
                )
            snapshots.extend(day_snapshots)
        db.session.add_all(snapshots)

        # Ensure a demo user exists up front for scoping seeded rows.
        user = User.query.first()
        if not user:
            user = User(username="money_schedule_demo", password_hash="demo")
            db.session.add(user)
            db.session.flush()

        schedule_samples = {
            0: ("Pocket money", Decimal("50000"), Decimal("0")),
            2: ("Groceries", Decimal("0"), Decimal("45000")),
            4: ("Scholarship", Decimal("480000"), Decimal("0")),
            5: ("Rent", Decimal("0"), Decimal("700000")),
            6: ("Freelance", Decimal("320000"), Decimal("0")),
        }

        for offset in range((end - start).days + 1):
            day = start + timedelta(days=offset)
            ensure_row(day, user.id)
            if offset in schedule_samples:
                desc, inflow, outflow = schedule_samples[offset]
                row = MoneyScheduleRow.query.filter_by(user_id=user.id, date=day).first()
                row.description = desc
                row.inflow = inflow
                row.outflow = outflow

        # Align Trial Balance initialization with the seed start date.
        tb_setting = TrialBalanceSetting.query.filter_by(user_id=user.id).first()
        if not tb_setting:
            tb_setting = TrialBalanceSetting(user_id=user.id, initialized_on=start)
            db.session.add(tb_setting)
        else:
            tb_setting.initialized_on = start

        db.session.commit()
        set_init_date(start.isoformat())
        recompute_from(start, user.id)
        print(f"Seeded money schedule rows from {start} to {end} with demo data for user {user.id}.")


if __name__ == "__main__":
    seed_money_schedule()
