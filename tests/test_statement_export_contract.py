from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

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
from helpers.statement_export_parity import REQUIRED_TOTAL_KEYS_BY_KIND, evaluate_statement_export_parity

os.environ.setdefault("AUTO_CREATE_SCHEMA", "true")
AUTO_CREATE_SCHEMA = os.environ.get("AUTO_CREATE_SCHEMA", "").lower() == "true"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "reporting" / "ranked_reports_journal_case.json"


@pytest.fixture()
def app_ctx(tmp_path):
    app.config["TESTING"] = True
    db_path = tmp_path / "statement_export_contract.db"
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


def _seed_case(case_data: dict[str, Any]) -> dict[str, Any]:
    user = User(username=f"statement_export_user_{uuid4().hex}", password_hash="pw")
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
    return {"user_id": user.id, "category_ids": category_ids}


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def _build_shared_selectors(*, ym: str, cash_folder_ids: list[int]) -> dict[str, str]:
    return {
        "ym": ym,
        "ym_compare": ym,
        "ccy": "KRW",
        "cash_folders": ",".join(str(folder_id) for folder_id in cash_folder_ids),
        "source": "journal",
    }


def _require_openpyxl() -> None:
    try:
        import openpyxl  # noqa: F401
    except Exception:
        pytest.fail(
            "XLSX parity gate requires openpyxl in the runtime environment. "
            "Install with: pip install -r requirements.txt",
            pytrace=False,
        )


def _run_data_export_pair(
    client,
    *,
    selectors: dict[str, str],
    kind: str,
    fmt: str,
    parse_fmt: str | None = None,
    simulate_total_mismatch_key: str | None = None,
):
    shared_query = urlencode(selectors)
    data_resp = client.get(f"/accounting/statement/data?{shared_query}")
    export_resp = client.get(f"/accounting/statement/export?{shared_query}&kind={kind}&format={fmt}")

    data_payload = data_resp.get_json(silent=True)
    parity = evaluate_statement_export_parity(
        selectors=selectors,
        kind=kind,
        data_status_code=data_resp.status_code,
        data_payload=data_payload,
        export_status_code=export_resp.status_code,
        export_content_type=export_resp.headers.get("Content-Type"),
        export_bytes=export_resp.data,
        fmt=parse_fmt or fmt,
        simulate_total_mismatch_key=simulate_total_mismatch_key,
    )
    return data_resp, data_payload, export_resp, parity


@pytest.mark.parametrize("kind", ["income", "balance", "cashflow"])
def test_statement_export_parity_csv_with_shared_selectors(app_ctx, kind):
    case_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    with app.app_context():
        seed = _seed_case(case_data)

    client = app.test_client()
    _login(client, seed["user_id"])

    base_resp = client.get(f"/accounting/statement/data?ym={case_data['ym']}")
    assert base_resp.status_code == 200
    base_payload = base_resp.get_json()

    cash_folder_ids = sorted(
        [
            int(next(opt["id"] for opt in base_payload["cash_folder_options"] if opt["name"] == "Cash")),
            int(next(opt["id"] for opt in base_payload["cash_folder_options"] if opt["name"] == "Savings")),
        ]
    )
    selectors = _build_shared_selectors(ym=case_data["ym"], cash_folder_ids=cash_folder_ids)

    data_resp, data_payload, export_resp, parity = _run_data_export_pair(
        client,
        selectors=selectors,
        kind=kind,
        fmt="csv",
    )

    assert data_resp.status_code == 200
    assert export_resp.status_code == 200
    assert (data_payload.get("source") or {}).get("legacy_rows_included_in_totals") is False
    assert sorted(data_payload.get("selected_cash_folders") or []) == cash_folder_ids
    assert set(REQUIRED_TOTAL_KEYS_BY_KIND[kind]).issubset(
        set((((data_payload.get("statements") or {}).get(kind) or {}).get("totals") or {}).keys())
    )
    assert parity.ok, parity.message


def test_statement_export_parity_xlsx_with_shared_selectors(app_ctx):
    _require_openpyxl()
    case_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    with app.app_context():
        seed = _seed_case(case_data)

    client = app.test_client()
    _login(client, seed["user_id"])

    base_resp = client.get(f"/accounting/statement/data?ym={case_data['ym']}")
    assert base_resp.status_code == 200
    base_payload = base_resp.get_json()

    cash_folder_ids = sorted(
        [
            int(next(opt["id"] for opt in base_payload["cash_folder_options"] if opt["name"] == "Cash")),
            int(next(opt["id"] for opt in base_payload["cash_folder_options"] if opt["name"] == "Savings")),
        ]
    )
    selectors = _build_shared_selectors(ym=case_data["ym"], cash_folder_ids=cash_folder_ids)

    _, _, _, parity = _run_data_export_pair(
        client,
        selectors=selectors,
        kind="income",
        fmt="xlsx",
    )

    assert parity.ok, parity.message


def test_statement_export_parity_xlsx_parse_error_includes_diagnostics(app_ctx):
    _require_openpyxl()
    case_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    with app.app_context():
        seed = _seed_case(case_data)

    client = app.test_client()
    _login(client, seed["user_id"])

    base_resp = client.get(f"/accounting/statement/data?ym={case_data['ym']}")
    assert base_resp.status_code == 200
    base_payload = base_resp.get_json()

    cash_folder_ids = sorted(
        [
            int(next(opt["id"] for opt in base_payload["cash_folder_options"] if opt["name"] == "Cash")),
            int(next(opt["id"] for opt in base_payload["cash_folder_options"] if opt["name"] == "Savings")),
        ]
    )
    selectors = _build_shared_selectors(ym=case_data["ym"], cash_folder_ids=cash_folder_ids)

    # Deterministic drill: request CSV bytes but force XLSX parser in parity harness.
    _, _, export_resp, parity = _run_data_export_pair(
        client,
        selectors=selectors,
        kind="income",
        fmt="csv",
        parse_fmt="xlsx",
    )

    assert parity.ok is False
    assert "export_parse_error" in parity.status_mismatch_keys
    assert parity.message.startswith("Statement export parity mismatch:")
    assert f"export_status_code={export_resp.status_code}" in parity.message
    assert f"content_type={export_resp.headers.get('Content-Type')}" in parity.message
    assert f"first8_hex={export_resp.data[:8].hex()}" in parity.message


def test_statement_export_source_policy_rejects_mixed(app_ctx):
    case_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    with app.app_context():
        seed = _seed_case(case_data)

    client = app.test_client()
    _login(client, seed["user_id"])

    selectors = {"ym": case_data["ym"], "source": "mixed"}
    data_resp, _, export_resp, parity = _run_data_export_pair(
        client,
        selectors=selectors,
        kind="income",
        fmt="csv",
    )

    assert data_resp.status_code == 400
    assert export_resp.status_code == 400
    assert parity.ok, parity.message


@pytest.mark.parametrize(
    ("legacy_fallback_enabled", "expected_status"),
    [
        (False, 400),
        (True, 503),
    ],
)
def test_statement_export_source_policy_non_journal_matches_data_status_class(
    app_ctx,
    monkeypatch,
    legacy_fallback_enabled,
    expected_status,
):
    case_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    with app.app_context():
        seed = _seed_case(case_data)

    client = app.test_client()
    _login(client, seed["user_id"])
    monkeypatch.setitem(app.config, "ALLOW_LEGACY_REPORT_FALLBACK", legacy_fallback_enabled)

    selectors = {"ym": case_data["ym"], "source": "legacy"}
    data_resp, _, export_resp, parity = _run_data_export_pair(
        client,
        selectors=selectors,
        kind="income",
        fmt="csv",
    )

    assert data_resp.status_code == expected_status
    assert export_resp.status_code == expected_status
    assert data_resp.status_code // 100 == export_resp.status_code // 100
    assert parity.ok, parity.message


def test_statement_export_parity_simulated_mismatch(app_ctx):
    case_data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    with app.app_context():
        seed = _seed_case(case_data)

    client = app.test_client()
    _login(client, seed["user_id"])

    base_resp = client.get(f"/accounting/statement/data?ym={case_data['ym']}")
    assert base_resp.status_code == 200
    base_payload = base_resp.get_json()

    cash_folder_ids = sorted(
        [
            int(next(opt["id"] for opt in base_payload["cash_folder_options"] if opt["name"] == "Cash")),
            int(next(opt["id"] for opt in base_payload["cash_folder_options"] if opt["name"] == "Savings")),
        ]
    )
    selectors = _build_shared_selectors(ym=case_data["ym"], cash_folder_ids=cash_folder_ids)

    _, _, _, parity = _run_data_export_pair(
        client,
        selectors=selectors,
        kind="income",
        fmt="csv",
        simulate_total_mismatch_key="revenue",
    )

    assert parity.ok is False
    assert parity.message.startswith("Statement export parity mismatch:")
    assert parity.selector_context == {
        "ym": case_data["ym"],
        "kind": "income",
        "ccy": "KRW",
        "cash_folders": selectors["cash_folders"],
        "source": "journal",
    }
    assert "revenue" in parity.totals_mismatch_keys
    assert any(
        [
            bool(parity.totals_mismatch_keys),
            bool(parity.metadata_mismatch_keys),
            bool(parity.status_mismatch_keys),
        ]
    )
    assert "totals_mismatch_keys" in parity.message
    assert "metadata_mismatch_keys" in parity.message
    assert "status_mismatch_keys" in parity.message
