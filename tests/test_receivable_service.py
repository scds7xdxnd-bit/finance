from __future__ import annotations

import os
import shutil
import tempfile
from decimal import Decimal

import pytest
from finance_app import User, create_app, db
from finance_app.models.accounting_models import (
    Account,
    AccountCategory,
    JournalEntry,
    JournalLine,
    ReceivableManualEntry,
)
from finance_app.services.receivable_service import (
    link_receivable_lines,
    resolve_receivable_scope,
    serialize_manual_receivable,
    serialize_receivable_line,
)

os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")


@pytest.fixture()
def app_ctx():
    app = create_app()
    app.config["TESTING"] = True
    tmp_dir = tempfile.mkdtemp(prefix="receivable-service-")
    db_path = os.path.join(tmp_dir, "test.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
        db.drop_all()
        db.create_all()
        try:
            yield app
        finally:
            db.session.remove()
            db.drop_all()
    shutil.rmtree(tmp_dir, ignore_errors=True)


def _setup_accounts(user_id: int):
    receivable_cat = AccountCategory(user_id=user_id, name="AR", tb_group="asset")
    db.session.add(receivable_cat)
    db.session.flush()
    recv_acc = Account(user_id=user_id, name="AR-Base", category_id=receivable_cat.id, currency_code="USD", active=True)
    db.session.add(recv_acc)
    db.session.commit()
    return recv_acc


def test_link_receivable_lines_connects_settlement_to_origin(app_ctx):
    app = app_ctx
    with app.app_context():
        user = User(username="rx_user", password_hash="pw")
        db.session.add(user)
        db.session.flush()
        acc = _setup_accounts(user.id)

        entry = JournalEntry(user_id=user.id, description="base")
        db.session.add(entry)
        db.session.flush()
        base_line = JournalLine(journal_id=entry.id, account_id=acc.id, dc="D", amount_base=Decimal("100"))
        settle_line = JournalLine(journal_id=entry.id, account_id=acc.id, dc="C", amount_base=Decimal("100"))
        db.session.add_all([base_line, settle_line])
        db.session.commit()

        result = link_receivable_lines(
            user_id=user.id,
            line=settle_line,
            account=acc,
            kind="receivable",
            action="set",
            linked_line=base_line,
            linked_account=acc,
            linked_kind="receivable",
            link_kind=None,
        )
        assert result["ok"] is True
        db.session.commit()

        # Settlement line should point at origin
        from finance_app.models.accounting_models import ReceivableTracker

        tracker = ReceivableTracker.query.filter_by(user_id=user.id, journal_line_id=settle_line.id).first()
        assert tracker is not None
        assert tracker.linked_line_id == base_line.id
        assert tracker.link_kind in ("installment", "paired")


def test_link_receivable_lines_clear_and_remove(app_ctx):
    app = app_ctx
    with app.app_context():
        user = User(username="rx_user2", password_hash="pw")
        db.session.add(user)
        db.session.flush()
        acc = _setup_accounts(user.id)

        entry = JournalEntry(user_id=user.id, description="base")
        db.session.add(entry)
        db.session.flush()
        base_line = JournalLine(journal_id=entry.id, account_id=acc.id, dc="D", amount_base=Decimal("50"))
        settle_line = JournalLine(journal_id=entry.id, account_id=acc.id, dc="C", amount_base=Decimal("50"))
        db.session.add_all([base_line, settle_line])
        db.session.commit()

        link_receivable_lines(
            user_id=user.id,
            line=settle_line,
            account=acc,
            kind="receivable",
            action="set",
            linked_line=base_line,
            linked_account=acc,
            linked_kind="receivable",
            link_kind=None,
        )
        db.session.commit()

        # Remove link
        link_receivable_lines(
            user_id=user.id,
            line=settle_line,
            account=acc,
            kind="receivable",
            action="remove",
            linked_line=base_line,
            linked_account=acc,
            linked_kind="receivable",
        )
        db.session.commit()
        from finance_app.models.accounting_models import ReceivableTracker

        tracker = ReceivableTracker.query.filter_by(user_id=user.id, journal_line_id=settle_line.id).first()
        assert tracker is not None
        assert tracker.linked_line_id is None

        # Clear links should also no-op without error
        link_receivable_lines(
            user_id=user.id,
            line=settle_line,
            account=acc,
            kind="receivable",
            action="clear",
        )
        db.session.commit()


def test_resolve_scope_and_serialize_helpers(app_ctx):
    app = app_ctx
    with app.app_context():
        user = User(username="rx_scope", password_hash="pw")
        db.session.add(user)
        db.session.flush()
        # Create categories and accounts
        receivable_cat = AccountCategory(user_id=user.id, name="Short-term Receivable", tb_group="asset")
        debt_cat = AccountCategory(user_id=user.id, name="Short-term Debt", tb_group="liability")
        db.session.add_all([receivable_cat, debt_cat])
        db.session.flush()
        recv_acc = Account(user_id=user.id, name="AR", category_id=receivable_cat.id, currency_code="USD", active=True)
        debt_acc = Account(user_id=user.id, name="Debt", category_id=debt_cat.id, currency_code="USD", active=True)
        db.session.add_all([recv_acc, debt_acc])
        db.session.commit()

        scoped_cats, scoped_accounts, cat_map = resolve_receivable_scope(user.id)
        assert receivable_cat.id in scoped_cats["receivable"]
        assert debt_cat.id in scoped_cats["debt"]
        assert recv_acc.id in scoped_accounts["receivable"]
        assert debt_acc.id in scoped_accounts["debt"]
        assert cat_map[receivable_cat.id].name == "Short-term Receivable"

        # Create journal items to serialize
        entry = JournalEntry(user_id=user.id, description="serialize test")
        db.session.add(entry)
        db.session.flush()
        line = JournalLine(journal_id=entry.id, account_id=recv_acc.id, dc="D", amount_base=Decimal("25.50"))
        db.session.add(line)
        db.session.commit()

        tracker = None
        row = serialize_receivable_line(user.id, line, entry, recv_acc, "receivable", cat_map, tracker, lambda raw: (None, None, None))
        assert row["account_name"] == "AR"
        assert row["flow"] == "loan_provided"
        assert row["type"] == "receivable"

        manual = ReceivableManualEntry(
            user_id=user.id,
            account_id=recv_acc.id,
            category="receivable",
            amount=Decimal("10"),
            currency_code="USD",
            description="Manual",
            reference="M-1",
            memo="memo",
            contact_name="Alice",
            transaction_value=10,
            due_date=None,
            payment_dates="[]",
            notes="note",
            date="2025-01-01",
            date_parsed=None,
            status="UNPAID",
        )
        db.session.add(manual)
        db.session.commit()

        mrow = serialize_manual_receivable(manual, recv_acc, "receivable", cat_map)
        assert mrow["account_name"] == "AR"
        assert mrow["flow"] == "loan_provided"
        assert mrow["type"] == "receivable"
