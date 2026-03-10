from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import uuid4

import pytest
from finance_app import (
    Account,
    AccountCategory,
    JournalEntry,
    JournalLine,
    TrialBalanceSetting,
    User,
    create_app,
    db,
)
from helpers.contract_assertions import (
    assert_json_envelope,
    find_missing_endpoint_registry_keys,
    run_alembic_upgrade,
)


def _sqlite_url(db_path) -> str:
    return f"sqlite:///{db_path.resolve()}"


def _login(client, user_id: int, csrf_token: str = "frontend-contract-csrf") -> str:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["csrf_token"] = csrf_token
    return csrf_token


def _seed_minimal_reporting_data(user_id: int) -> str:
    ym = "2026-03"

    expense_cat = AccountCategory(user_id=user_id, name="Operating Expense", tb_group="expense")
    income_cat = AccountCategory(user_id=user_id, name="Sales", tb_group="income")
    db.session.add(expense_cat)
    db.session.add(income_cat)
    db.session.flush()

    expense_acc = Account(user_id=user_id, name="Office Expense", category_id=expense_cat.id, currency_code="KRW", active=True)
    income_acc = Account(user_id=user_id, name="Service Revenue", category_id=income_cat.id, currency_code="KRW", active=True)
    db.session.add(expense_acc)
    db.session.add(income_acc)
    db.session.flush()

    db.session.add(TrialBalanceSetting(user_id=user_id, initialized_on=dt.date(2026, 1, 1)))

    entry = JournalEntry(
        user_id=user_id,
        date="2026/03/10",
        date_parsed=dt.date(2026, 3, 10),
        description="contract-shape seed",
        posted_at=None,
    )
    db.session.add(entry)
    db.session.flush()

    db.session.add(
        JournalLine(
            journal_id=entry.id,
            account_id=expense_acc.id,
            dc="D",
            amount_base=Decimal("100.00"),
            line_no=1,
        )
    )
    db.session.add(
        JournalLine(
            journal_id=entry.id,
            account_id=income_acc.id,
            dc="C",
            amount_base=Decimal("100.00"),
            line_no=2,
        )
    )
    db.session.commit()
    return ym


@pytest.fixture()
def frontend_contract_ctx(tmp_path, monkeypatch):
    db_path = tmp_path / "frontend_contracts.db"
    db_url = _sqlite_url(db_path)

    monkeypatch.setenv("FINANCE_DATABASE_URL", db_url)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", db_url)
    monkeypatch.setenv("AUTO_CREATE_SCHEMA", "false")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    run_alembic_upgrade(db_url=db_url, target_revision="head")

    app = create_app()
    app.config["TESTING"] = True
    app.config["MLSUGGESTER_PREFER_USER_MODEL"] = False
    app.config["MLSUGGESTER_USER_ONLY"] = False

    with app.app_context():
        user = User(
            username=f"frontend_contract_{uuid4().hex[:10]}",
            password_hash="pw",
            email=f"frontend_contract_{uuid4().hex[:8]}@example.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = int(user.id)
        ym = _seed_minimal_reporting_data(user_id)

    client = app.test_client()
    csrf_token = _login(client, user_id)

    try:
        yield {
            "app": app,
            "client": client,
            "user_id": user_id,
            "csrf_token": csrf_token,
            "ym": ym,
        }
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_frontend_contract_add_transaction_envelope_and_shape(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    csrf_token = frontend_contract_ctx["csrf_token"]

    success_resp = client.post(
        "/add_transaction",
        json={
            "date": "2026-03-11",
            "description": "frontend contract add tx",
            "lines": [
                {"line_id": "l1", "dc": "D", "account": "Office Expense", "amount": 50},
                {"line_id": "l2", "dc": "C", "account": "Service Revenue", "amount": 50},
            ],
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    success_payload = assert_json_envelope(success_resp, endpoint="POST /add_transaction (success)")
    assert success_resp.status_code == 200
    assert success_payload["ok"] is True
    assert "mode" in success_payload
    assert bool(success_payload.get("entry_id") or success_payload.get("transaction_id"))

    failure_resp = client.post(
        "/add_transaction",
        json={"date": "2026-03-11", "description": "", "lines": []},
        headers={"X-CSRF-Token": csrf_token},
    )
    failure_payload = assert_json_envelope(failure_resp, endpoint="POST /add_transaction (failure)")
    assert failure_payload["ok"] is False
    assert 400 <= failure_resp.status_code < 500 or failure_resp.status_code == 503


def test_frontend_contract_ml_suggestions_envelope_and_shape(frontend_contract_ctx, monkeypatch):
    client = frontend_contract_ctx["client"]

    import finance_app.controllers.core as core_controller

    monkeypatch.setattr(
        core_controller,
        "call_ml_api",
        lambda *_args, **_kwargs: (
            {
                "currency": "KRW",
                "top_k": 3,
                "model_version": "qa-contract",
                "model_hash": "qa-contract-hash",
                "model_path": "qa-contract",
                "results": [
                    {
                        "predictions": [
                            {"account_name": "Office Expense", "probability": 0.91},
                            {"account_name": "Service Revenue", "probability": 0.07},
                        ]
                    }
                ],
            },
            None,
        ),
    )

    success_resp = client.post(
        "/api/ml_suggestions",
        json={
            "lines": [
                {"line_id": "line-1", "dc": "D", "account": "Office Expense", "amount": 100},
                {"line_id": "line-2", "dc": "C", "account": "Service Revenue", "amount": 100},
            ],
            "target_line_id": "line-1",
            "description": "contract shape only",
            "currency": "KRW",
        },
    )
    success_payload = assert_json_envelope(success_resp, endpoint="POST /api/ml_suggestions (success)")
    assert success_resp.status_code == 200
    assert success_payload["ok"] is True
    for key in ("predictions", "currency", "transaction_id", "line_id", "line_type", "status", "fallback"):
        assert key in success_payload
    assert isinstance(success_payload.get("predictions"), list)
    for item in success_payload.get("predictions") or []:
        assert "account_name" in item
        assert "probability" in item

    failure_resp = client.post("/api/ml_suggestions", json={})
    failure_payload = assert_json_envelope(failure_resp, endpoint="POST /api/ml_suggestions (failure)")
    assert failure_payload["ok"] is False


def test_frontend_contract_suggestion_log_envelope_and_shape(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]

    success_resp = client.post(
        "/api/suggestions/log",
        json={
            "logs": [
                {
                    "currency": "KRW",
                    "transaction_id": "tx-contract-1",
                    "line_id": "line-contract-1",
                    "line_type": "debit",
                    "chosen_account": "Office Expense",
                    "predictions": [{"account_name": "Office Expense", "probability": 0.8}],
                    "description": "contract logging",
                    "date": "2026-03-10",
                }
            ]
        },
    )
    success_payload = assert_json_envelope(success_resp, endpoint="POST /api/suggestions/log (success)")
    assert success_resp.status_code == 200
    assert success_payload["ok"] is True
    assert "saved" in success_payload

    failure_resp = client.post("/api/suggestions/log", json={"logs": []})
    failure_payload = assert_json_envelope(failure_resp, endpoint="POST /api/suggestions/log (failure)")
    assert failure_payload["ok"] is False


def test_frontend_contract_tb_monthly_envelope_and_shape(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    ym = frontend_contract_ctx["ym"]

    success_resp = client.get(f"/accounting/tb/monthly?ym={ym}")
    success_payload = assert_json_envelope(success_resp, endpoint="GET /accounting/tb/monthly (success)")
    assert success_resp.status_code == 200
    assert success_payload["ok"] is True
    for key in ("groups", "grand_totals", "source"):
        assert key in success_payload

    failure_resp = client.get("/accounting/tb/monthly?ym=invalid-ym")
    failure_payload = assert_json_envelope(failure_resp, endpoint="GET /accounting/tb/monthly (failure)")
    assert failure_payload["ok"] is False
    assert "error" in failure_payload and isinstance(failure_payload["error"], str)


def test_frontend_contract_statement_data_envelope_and_shape(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    ym = frontend_contract_ctx["ym"]

    success_resp = client.get(f"/accounting/statement/data?ym={ym}")
    success_payload = assert_json_envelope(success_resp, endpoint="GET /accounting/statement/data (success)")
    assert success_resp.status_code == 200
    assert success_payload["ok"] is True
    for key in ("period", "generated_at", "statements", "source"):
        assert key in success_payload

    coverage = success_payload.get("coverage")
    if isinstance(coverage, dict):
        assert "coverage_count" in coverage
        assert "coverage_amount" in coverage

    failure_resp = client.get("/accounting/statement/data")
    failure_payload = assert_json_envelope(failure_resp, endpoint="GET /accounting/statement/data (failure)")
    assert failure_payload["ok"] is False
    assert "error" in failure_payload and isinstance(failure_payload["error"], str)


def test_frontend_contract_endpoint_registry_keys_present(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    assert html_resp.status_code == 200
    html = html_resp.get_data(as_text=True)

    missing_keys = find_missing_endpoint_registry_keys(html)
    assert missing_keys == [], f"Missing endpoint registry keys: {missing_keys}"
