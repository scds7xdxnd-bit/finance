from datetime import date
from decimal import Decimal

import pytest
from finance_app import db
from finance_app.models.accounting_models import Account, AccountCategory, JournalEntry, JournalLine, LoanGroup
from finance_app.models.user_models import User
from finance_app.services.loan_group_service import (
    create_group,
    delete_group,
    get_group,
    group_summary,
    link_journal_lines,
    list_groups,
    unlink,
)


@pytest.fixture()
def app_ctx():
    from flask import Flask

    test_app = Flask(__name__)
    test_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    db.init_app(test_app)
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


def _seed_user_and_accounts():
    user = User(username="loan_user", password_hash="x")
    db.session.add(user)
    db.session.flush()
    cat = AccountCategory(user_id=user.id, name="Cash", tb_group="asset")
    db.session.add(cat)
    db.session.flush()
    acc = Account(user_id=user.id, name="Wallet", category_id=cat.id, currency_code="KRW", active=True)
    db.session.add(acc)
    db.session.flush()
    return user, acc


def _seed_journal_line(user_id: int, account_id: int, dc: str, amount: Decimal) -> JournalLine:
    je = JournalEntry(user_id=user_id, date=str(date.today()), description="loan test")
    db.session.add(je)
    db.session.flush()
    jl = JournalLine(journal_id=je.id, account_id=account_id, dc=dc, amount_base=amount)
    db.session.add(jl)
    db.session.commit()
    return jl


def test_loan_group_service_flow(app_ctx):
    user, acc = _seed_user_and_accounts()
    group = create_group(
        user_id=user.id,
        name="Loan1",
        direction="receivable",
        counterparty=None,
        currency="KRW",
        principal_amount=Decimal("100.00"),
        start_date=date.today(),
        notes=None,
    )
    assert isinstance(group, LoanGroup)
    assert list_groups(user.id)
    summary, entries = group_summary(user.id, group)
    assert summary["remaining"] == Decimal("100.00")
    assert summary["status"] == "open"
    assert entries == []

    line = _seed_journal_line(user.id, acc.id, dc="D", amount=Decimal("50.00"))
    created, error = link_journal_lines(user.id, group.id, [line.id], [Decimal("50.00")])
    assert error is None
    assert created
    summary2, entries2 = group_summary(user.id, group)
    assert summary2["remaining"] == Decimal("50.00")
    assert len(entries2) == 1

    # Unlink
    grp_after_unlink = unlink(user.id, created[0].id)
    assert grp_after_unlink is not None
    summary3, entries3 = group_summary(user.id, group)
    assert summary3["remaining"] == Decimal("100.00")
    assert entries3 == []

    assert delete_group(user.id, group.id) is True
    assert get_group(user.id, group.id) is None
