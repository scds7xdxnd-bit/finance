from __future__ import annotations

import os
import shutil
import tempfile
from datetime import date

import pytest
from finance_app import (
    Account,
    AccountCategory,
    JournalEntry,
    JournalLine,
    ReceivableManualEntry,
    User,
    app,
    db,
)

os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")
AUTO_CREATE_SCHEMA = os.environ.get("AUTO_CREATE_SCHEMA", "").lower() == "true"


@pytest.fixture()
def app_ctx():
    app.config["TESTING"] = True
    tmp_dir = tempfile.mkdtemp(prefix="receivables-test-")
    db_path = os.path.join(tmp_dir, "test.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

    with app.app_context():
        db.session.remove()
        db.engine.dispose()
        if AUTO_CREATE_SCHEMA:
            db.create_all()
        try:
            yield
        finally:
            db.session.remove()
            if AUTO_CREATE_SCHEMA:
                db.drop_all()
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_receivables_create_creates_journal_entry(app_ctx):
    with app.app_context():
        user = User(username="receivable_user", password_hash="pass")
        db.session.add(user)
        db.session.flush()

        receivable_cat = AccountCategory(user_id=user.id, name="Accounts Receivable", tb_group="asset")
        revenue_cat = AccountCategory(user_id=user.id, name="Revenue", tb_group="income")
        db.session.add_all([receivable_cat, revenue_cat])
        db.session.flush()

        receivable_account = Account(
            user_id=user.id,
            name="AR - Domestic",
            category_id=receivable_cat.id,
            currency_code="USD",
            active=True,
        )
        revenue_account = Account(
            user_id=user.id,
            name="Sales Revenue",
            category_id=revenue_cat.id,
            currency_code="USD",
            active=True,
        )
        db.session.add_all([receivable_account, revenue_account])
        db.session.flush()
        user_id = user.id
        receivable_id = receivable_account.id
        revenue_id = revenue_account.id
        db.session.commit()
        entry_count_before = JournalEntry.query.count()
        line_count_before = JournalLine.query.count()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["csrf_token"] = "csrf-token"

    payload = {
        "direction": "receivable",
        "account_id": receivable_id,
        "offset_account_id": revenue_id,
        "amount": 5000,
        "currency": "USD",
        "description": "New invoice",
        "date": date(2024, 8, 1).isoformat(),
        "reference": "INV-1042",
        "memo": "Launch project",
        "contact_name": "Acme Co",
        "due_date": "2024-09-01",
        "payment_dates": ["2024-09-15"],
        "notes": "Expect payment within 45 days",
    }
    resp = client.post(
        "/accounting/receivables/create",
        json=payload,
        headers={"X-CSRF-Token": "csrf-token"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["row"]["contact_name"] == "Acme Co"
    assert data["row"]["flow"] == "loan_provided"
    assert data["row"]["is_saved"] is True

    created_line_id = data["row"]["line_id"]
    assert created_line_id
    assert data["row"].get("is_manual") is True
    assert data["row"]["journal_id"] is None

    with app.app_context():
        assert JournalEntry.query.count() == entry_count_before
        assert JournalLine.query.count() == line_count_before
        manual = ReceivableManualEntry.query.filter_by(user_id=user_id).one()
        assert manual.account_id == receivable_id
        assert manual.category == "receivable"
        assert manual.contact_name == "Acme Co"
        assert manual.transaction_value == pytest.approx(5000.0)
        assert manual.currency_code == "USD"
