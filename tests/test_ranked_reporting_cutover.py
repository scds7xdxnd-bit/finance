from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from finance_app import (
    Account,
    AccountCategory,
    AccountOpeningBalance,
    JournalEntry,
    JournalLine,
    TrialBalanceSetting,
    User,
    app,
    db,
)

os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")
AUTO_CREATE_SCHEMA = os.environ.get("AUTO_CREATE_SCHEMA", "").lower() == "true"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "reporting" / "ranked_reports_journal_case.json"


@pytest.fixture()
def app_ctx():
    app.config["TESTING"] = True
    tmp_dir = tempfile.mkdtemp(prefix="ranked-report-cutover-")
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


def _seed_case(case_data: dict) -> int:
    user = User(username="reporting_cutover_user", password_hash="pw")
    db.session.add(user)
    db.session.flush()

    category_ids: dict[str, int] = {}
    for category in case_data.get("categories") or []:
        row = AccountCategory(
            user_id=user.id,
            name=category["name"],
            tb_group=category["tb_group"],
        )
        db.session.add(row)
        db.session.flush()
        category_ids[category["key"]] = row.id

    account_ids: dict[str, int] = {}
    for account in case_data.get("accounts") or []:
        row = Account(
            user_id=user.id,
            name=account["name"],
            category_id=category_ids[account["category"]],
            currency_code=(account.get("currency") or "KRW").upper(),
            active=True,
        )
        db.session.add(row)
        db.session.flush()
        account_ids[account["key"]] = row.id

    init_date = date.fromisoformat(case_data["initialized_on"])
    db.session.add(TrialBalanceSetting(user_id=user.id, initialized_on=init_date))
    for opening in case_data.get("opening_balances") or []:
        db.session.add(
            AccountOpeningBalance(
                user_id=user.id,
                account_id=account_ids[opening["account"]],
                amount=Decimal(str(opening["amount"])),
                as_of_date=init_date,
            )
        )

    for entry in case_data.get("journal_entries") or []:
        entry_date = date.fromisoformat(entry["date"])
        journal = JournalEntry(
            user_id=user.id,
            date=entry_date.isoformat(),
            date_parsed=entry_date,
            description=entry.get("description") or "",
        )
        db.session.add(journal)
        db.session.flush()
        for line in entry.get("lines") or []:
            db.session.add(
                JournalLine(
                    journal_id=journal.id,
                    account_id=account_ids[line["account"]],
                    dc=(line["dc"] or "").upper(),
                    amount_base=Decimal(str(line["amount"])),
                )
            )

    db.session.commit()
    return user.id


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def test_ranked_reporting_reconciles_across_json_and_pdf_inputs(app_ctx, monkeypatch):
    case_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    with app.app_context():
        user_id = _seed_case(case_data)

    client = app.test_client()
    _login(client, user_id)
    ym = case_data["ym"]

    tb_resp = client.get(f"/accounting/tb/monthly?ym={ym}")
    assert tb_resp.status_code == 200
    tb_payload = tb_resp.get_json()
    assert tb_payload["ok"] is True
    assert tb_payload["source"]["mode"] == "journal"
    assert tb_payload["source"]["legacy_rows_included_in_totals"] is False

    expected_tb = case_data["expected"]["tb_monthly"]
    assert tb_payload["totals"]["asset"]["bd"] == pytest.approx(expected_tb["asset_bd"])
    assert tb_payload["totals"]["asset"]["balance"] == pytest.approx(expected_tb["asset_balance"])
    assert tb_payload["totals"]["asset"]["period_debit"] == pytest.approx(expected_tb["asset_period_debit"])
    assert tb_payload["totals"]["asset"]["period_credit"] == pytest.approx(expected_tb["asset_period_credit"])
    assert tb_payload["totals"]["liability"]["balance"] == pytest.approx(expected_tb["liability_balance"])
    assert tb_payload["totals"]["income"]["balance"] == pytest.approx(expected_tb["income_balance"])
    assert tb_payload["totals"]["expense"]["balance"] == pytest.approx(expected_tb["expense_balance"])
    assert tb_payload["grand_totals"]["period_debit"] == pytest.approx(expected_tb["grand_period_debit"])
    assert tb_payload["grand_totals"]["period_credit"] == pytest.approx(expected_tb["grand_period_credit"])

    stmt_resp = client.get(f"/accounting/statement/data?ym={ym}")
    assert stmt_resp.status_code == 200
    stmt_payload = stmt_resp.get_json()
    assert stmt_payload["ok"] is True
    assert stmt_payload["source"]["mode"] == "journal"
    assert stmt_payload["source"]["legacy_rows_included_in_totals"] is False
    assert stmt_payload["coverage"]["available"] is True

    expected_stmt = case_data["expected"]["statements"]
    income_totals = stmt_payload["statements"]["income"]["totals"]
    assert income_totals["revenue"] == pytest.approx(expected_stmt["income"]["revenue"])
    assert income_totals["expense"] == pytest.approx(expected_stmt["income"]["expense"])
    assert income_totals["net_income"] == pytest.approx(expected_stmt["income"]["net_income"])

    balance_totals = stmt_payload["statements"]["balance"]["totals"]
    assert balance_totals["assets"] == pytest.approx(expected_stmt["balance"]["assets"])
    assert balance_totals["liabilities"] == pytest.approx(expected_stmt["balance"]["liabilities"])
    assert balance_totals["equity"] == pytest.approx(expected_stmt["balance"]["equity"])
    assert balance_totals["le_sum"] == pytest.approx(expected_stmt["balance"]["le_sum"])

    cashflow_totals = stmt_payload["statements"]["cashflow"]["totals"]
    assert cashflow_totals["opening"] == pytest.approx(expected_stmt["cashflow"]["opening"])
    assert cashflow_totals["closing"] == pytest.approx(expected_stmt["cashflow"]["closing"])
    assert cashflow_totals["change"] == pytest.approx(expected_stmt["cashflow"]["change"])

    tb_income = sum(
        float(row.get("period_credit") or 0.0) - float(row.get("period_debit") or 0.0)
        for row in (tb_payload.get("groups", {}).get("income") or [])
    )
    tb_expense = sum(
        float(row.get("period_debit") or 0.0) - float(row.get("period_credit") or 0.0)
        for row in (tb_payload.get("groups", {}).get("expense") or [])
    )
    assert income_totals["revenue"] == pytest.approx(tb_income)
    assert income_totals["expense"] == pytest.approx(tb_expense)
    assert income_totals["net_income"] == pytest.approx(tb_income - tb_expense)
    assert balance_totals["assets"] == pytest.approx(tb_payload["totals"]["asset"]["balance"])
    assert balance_totals["liabilities"] == pytest.approx(tb_payload["totals"]["liability"]["balance"])
    assert balance_totals["equity"] == pytest.approx(
        tb_payload["totals"]["asset"]["balance"] - tb_payload["totals"]["liability"]["balance"]
    )

    captured_statement_pdf: dict[str, dict] = {}

    def _fake_income_pdf(data, org, start_date, end_date, out_pdf, logo=None):
        captured_statement_pdf["data"] = data
        Path(out_pdf).write_bytes(b"%PDF-1.4\n%stub\n%%EOF\n")

    monkeypatch.setattr("statements_pdf.generate_income_statement_pdf_from_data", _fake_income_pdf)
    stmt_pdf_resp = client.get(f"/accounting/statement/pdf?kind=income&ym={ym}")
    assert stmt_pdf_resp.status_code == 200
    assert captured_statement_pdf["data"]["totals"]["revenue"] == pytest.approx(income_totals["revenue"])
    assert captured_statement_pdf["data"]["totals"]["expense"] == pytest.approx(income_totals["expense"])
    assert captured_statement_pdf["data"]["totals"]["net_income"] == pytest.approx(income_totals["net_income"])

    captured_tb_pdf: dict[str, dict] = {}

    def _fake_tb_pdf(data, org, start_date, end_date, out_pdf, logo=None, engine="weasy"):
        captured_tb_pdf["data"] = data
        Path(out_pdf).write_bytes(b"%PDF-1.4\n%stub\n%%EOF\n")
        return 1, "0" * 64

    monkeypatch.setattr("trial_balance_pdf.generate_trial_balance_pdf", _fake_tb_pdf)
    tb_pdf_resp = client.get(f"/accounting/tb/pdf?ym={ym}&scope=folders")
    assert tb_pdf_resp.status_code == 200
    row_totals = captured_tb_pdf["data"]["rows"]
    total_debit = sum(float(row.get("debit") or 0.0) for row in row_totals)
    total_credit = sum(float(row.get("credit") or 0.0) for row in row_totals)
    assert total_debit == pytest.approx(tb_payload["grand_totals"]["period_debit"])
    assert total_credit == pytest.approx(tb_payload["grand_totals"]["period_credit"])


def test_ranked_reporting_rejects_mixed_source_mode(app_ctx):
    case_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    with app.app_context():
        user_id = _seed_case(case_data)

    client = app.test_client()
    _login(client, user_id)
    ym = case_data["ym"]
    assert client.get(f"/accounting/tb/monthly?ym={ym}&source=mixed").status_code == 400
    assert client.get(f"/accounting/statement/data?ym={ym}&source=mixed").status_code == 400
    assert client.get(f"/accounting/statement/pdf?ym={ym}&kind=income&source=mixed").status_code == 400
    assert client.get(f"/accounting/tb/pdf?ym={ym}&source=mixed").status_code == 400
