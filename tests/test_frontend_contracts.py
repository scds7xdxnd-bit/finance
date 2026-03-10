from __future__ import annotations

import datetime as dt
from html import unescape
import re
from decimal import Decimal
from urllib.parse import parse_qs, urlparse
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

CSV_IMPORT_UX_FAILURE_PREFIX = "CSV import UX contract failed:"


def _sqlite_url(db_path) -> str:
    return f"sqlite:///{db_path.resolve()}"


def _login(client, user_id: int, csrf_token: str = "frontend-contract-csrf") -> str:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["csrf_token"] = csrf_token
    return csrf_token


def _seed_minimal_reporting_data(user_id: int) -> dict[str, int | str]:
    ym = "2026-03"
    roundtrip_query = "seed & roundtrip"

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

    entry_specs = (
        ("2026/03/10", dt.date(2026, 3, 10), f"{roundtrip_query} alpha", Decimal("100.00")),
        ("2026/03/11", dt.date(2026, 3, 11), f"{roundtrip_query} beta", Decimal("120.00")),
        ("2026/03/12", dt.date(2026, 3, 12), f"{roundtrip_query} gamma", Decimal("140.00")),
    )
    primary_entry_id: int | None = None
    for idx, (date_str, date_parsed, description, amount) in enumerate(entry_specs):
        entry = JournalEntry(
            user_id=user_id,
            date=date_str,
            date_parsed=date_parsed,
            description=description,
            posted_at=None,
        )
        db.session.add(entry)
        db.session.flush()
        if idx == 0:
            primary_entry_id = int(entry.id)
        db.session.add(
            JournalLine(
                journal_id=entry.id,
                account_id=expense_acc.id,
                dc="D",
                amount_base=amount,
                line_no=1,
            )
        )
        db.session.add(
            JournalLine(
                journal_id=entry.id,
                account_id=income_acc.id,
                dc="C",
                amount_base=amount,
                line_no=2,
            )
        )
    db.session.commit()
    return {
        "ym": ym,
        "entry_id": int(primary_entry_id or 0),
        "expense_account_id": int(expense_acc.id),
        "income_account_id": int(income_acc.id),
        "expense_category_id": int(expense_cat.id),
        "roundtrip_query": roundtrip_query,
        "expense_account_name": str(expense_acc.name),
        "expense_category_name": str(expense_cat.name),
    }


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
        seed = _seed_minimal_reporting_data(user_id)

    client = app.test_client()
    csrf_token = _login(client, user_id)

    try:
        yield {
            "app": app,
            "client": client,
            "user_id": user_id,
            "csrf_token": csrf_token,
            "ym": str(seed["ym"]),
            "entry_id": int(seed["entry_id"]),
            "expense_account_id": int(seed["expense_account_id"]),
            "income_account_id": int(seed["income_account_id"]),
            "expense_category_id": int(seed["expense_category_id"]),
            "roundtrip_query": str(seed["roundtrip_query"]),
            "expense_account_name": str(seed["expense_account_name"]),
            "expense_category_name": str(seed["expense_category_name"]),
        }
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def _phase11_transactions_params(frontend_contract_ctx) -> dict[str, str]:
    return {
        "q": str(frontend_contract_ctx["roundtrip_query"]),
        "account": str(frontend_contract_ctx["expense_account_name"]),
        "category": str(frontend_contract_ctx["expense_category_name"]),
        "min_amount": "50.00",
        "max_amount": "200.00",
        "start_date": "2026-03-01",
        "end_date": "2026-03-31",
        "page": "1",
        "per_page": "1",
    }


def _csv_import_contract_assert(condition: bool, message: str) -> None:
    assert condition, f"{CSV_IMPORT_UX_FAILURE_PREFIX} {message}"


def _set_last_import_result_session(client, payload: dict) -> None:
    with client.session_transaction() as sess:
        sess["last_import_result_v1"] = payload


def _extract_form_open_tag(html: str, action_path: str) -> str | None:
    pattern = re.compile(rf"<form\b[^>]*action=\"[^\"]*{re.escape(action_path)}[^\"]*\"[^>]*>", flags=re.IGNORECASE)
    match = pattern.search(html)
    return match.group(0) if match else None


def _assert_unbalanced_update_mapping(frontend_contract_ctx, monkeypatch) -> None:
    client = frontend_contract_ctx["client"]
    csrf_token = frontend_contract_ctx["csrf_token"]
    entry_id = frontend_contract_ctx["entry_id"]
    expense_account_id = frontend_contract_ctx["expense_account_id"]
    income_account_id = frontend_contract_ctx["income_account_id"]

    import blueprints.accounting as accounting_module

    # Force DB-level finalization guard path by bypassing service-level balance precheck.
    monkeypatch.setattr(accounting_module, "_validate_balanced", lambda *_args, **_kwargs: None)

    response = client.put(
        f"/accounting/journal/{entry_id}",
        json={
            "date": "2026-03-12",
            "description": "phase1.2 unbalanced mapping drill",
            "reference": "REF-LOCK-2",
            "lines": [
                {"dc": "D", "account_id": expense_account_id, "amount": 100.0},
                {"dc": "C", "account_id": income_account_id, "amount": 60.0},
            ],
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    payload = assert_json_envelope(response, endpoint="PUT /accounting/journal/<entry_id> (unbalanced)")
    assert 400 <= response.status_code < 500
    assert payload["ok"] is False
    assert "error" in payload and isinstance(payload["error"], str)
    assert payload.get("error_code") == "JOURNAL_NOT_BALANCED"


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


def test_frontend_contract_journal_list_shape(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    response = client.get("/accounting/journal/list?page=1&per_page=25")
    payload = assert_json_envelope(response, endpoint="GET /accounting/journal/list (success)")
    assert response.status_code == 200
    assert payload["ok"] is True
    for key in ("entries", "page", "pages", "total"):
        assert key in payload


def test_frontend_contract_journal_update_shape(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    csrf_token = frontend_contract_ctx["csrf_token"]
    entry_id = frontend_contract_ctx["entry_id"]
    expense_account_id = frontend_contract_ctx["expense_account_id"]
    income_account_id = frontend_contract_ctx["income_account_id"]

    response = client.put(
        f"/accounting/journal/{entry_id}",
        json={
            "date": "2026-03-12",
            "description": "phase1 contract update",
            "reference": "REF-LOCK-1",
            "lines": [
                {"dc": "D", "account_id": expense_account_id, "amount": 80.0, "memo": "debit"},
                {"dc": "C", "account_id": income_account_id, "amount": 80.0, "memo": "credit"},
            ],
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    payload = assert_json_envelope(response, endpoint="PUT /accounting/journal/<entry_id> (success)")
    assert response.status_code == 200
    assert payload["ok"] is True
    assert "entry" in payload


def test_frontend_contract_phase12_unbalanced_update_mapping(frontend_contract_ctx, monkeypatch):
    _assert_unbalanced_update_mapping(frontend_contract_ctx, monkeypatch)


def test_frontend_contract_transactions_pagination_roundtrip_preserves_active_params(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    params = _phase11_transactions_params(frontend_contract_ctx)
    response = client.get("/transactions", query_string=params)
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    hrefs = []
    for raw_href in re.findall(r'href="([^"]+)"', html):
        href = unescape(raw_href)
        parsed = urlparse(href)
        if parsed.path == "/transactions" and "page=" in parsed.query:
            hrefs.append(href)
    assert hrefs, "Frontend contract lock failed: expected at least one transactions pagination href"

    for href in hrefs:
        parsed = urlparse(href)
        assert "%26" in parsed.query, "Frontend contract lock failed: q ampersand must be URL-encoded in pagination href"
        query = parse_qs(parsed.query, keep_blank_values=True)
        for key in ("q", "account", "category", "min_amount", "max_amount", "start_date", "end_date", "per_page"):
            assert query.get(key) == [params[key]], f"Frontend contract lock failed: pagination href dropped {key}"
        assert query.get("page"), "Frontend contract lock failed: pagination href missing page"


def test_frontend_contract_transactions_list_progressive_enhancement_html(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    params = _phase11_transactions_params(frontend_contract_ctx)
    response = client.get("/transactions/list", query_string=params)
    assert response.status_code == 200
    assert response.get_json(silent=True) is None
    assert "text/html" in str(response.content_type or "")


def test_frontend_contract_journal_list_accepts_phase11_filter_params(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    response = client.get(
        "/accounting/journal/list",
        query_string={
            "q": str(frontend_contract_ctx["roundtrip_query"]),
            "account_id": str(frontend_contract_ctx["expense_account_id"]),
            "category_id": str(frontend_contract_ctx["expense_category_id"]),
            "min_amount": "50.00",
            "max_amount": "200.00",
            "start": "2026-03-01",
            "end": "2026-03-31",
            "page": "1",
            "per_page": "5",
        },
    )
    payload = assert_json_envelope(response, endpoint="GET /accounting/journal/list (phase1.1 params)")
    assert response.status_code == 200
    assert payload["ok"] is True
    for key in ("entries", "page", "pages", "total"):
        assert key in payload


def test_frontend_contract_endpoint_registry_keys_present(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    assert html_resp.status_code == 200
    html = html_resp.get_data(as_text=True)

    missing_keys = find_missing_endpoint_registry_keys(html)
    assert missing_keys == [], f"Missing endpoint registry keys: {missing_keys}"


def test_frontend_contract_phase12_registry_journal_keys_and_token(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    assert html_resp.status_code == 200
    html = html_resp.get_data(as_text=True)
    missing_keys = find_missing_endpoint_registry_keys(html)
    for required in (
        "window.FINANCE_ENDPOINTS.accounting.journal.list",
        "window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate",
    ):
        assert required not in missing_keys, f"Frontend contract lock failed: missing registry key {required}"

    assert "__ENTRY_ID__" in html, "Frontend contract lock failed: accounting.journal.updateTemplate missing __ENTRY_ID__ token"


def test_frontend_contract_phase13_import_panel_presence_and_selector_surface(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    _set_last_import_result_session(
        client,
        {
            "imported_count": 2,
            "duplicate_count": 1,
            "failed_count": 0,
            "summary_text": "Imported 2 rows; skipped 1 duplicate.",
            "source_filename": "phase13.csv",
            "recorded_at": "2026-03-10T13:00:00Z",
        },
    )

    resp = client.get("/transactions")
    _csv_import_contract_assert(resp.status_code == 200, f"expected /transactions 200, got {resp.status_code}")
    html = resp.get_data(as_text=True)

    required_selectors = (
        "#last-import-result-panel",
        'data-role="import-severity"',
        'data-role="import-summary"',
        'data-role="import-counts"',
        'data-role="import-recorded-at"',
        'data-role="import-filename"',
        'data-action="dismiss-import-result"',
    )
    for selector in required_selectors:
        _csv_import_contract_assert(selector in html, f"missing selector {selector}")


def test_frontend_contract_phase13_dismiss_semantics_post_csrf(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    _set_last_import_result_session(
        client,
        {
            "imported_count": 1,
            "duplicate_count": 0,
            "failed_count": 0,
            "summary_text": "Imported 1 row.",
            "source_filename": "dismiss.csv",
            "recorded_at": "2026-03-10T13:01:00Z",
        },
    )

    resp = client.get("/transactions")
    _csv_import_contract_assert(resp.status_code == 200, f"expected /transactions 200, got {resp.status_code}")
    html = resp.get_data(as_text=True)

    form_open = _extract_form_open_tag(html, "/transactions/import_result/dismiss")
    _csv_import_contract_assert(form_open is not None, "dismiss form action /transactions/import_result/dismiss not found")
    _csv_import_contract_assert('method="post"' in (form_open or "").lower(), "dismiss form must use POST method")
    _csv_import_contract_assert('name="csrf_token"' in html, "dismiss form must include csrf_token field")
    _csv_import_contract_assert('data-action="dismiss-import-result"' in html, "dismiss control must include data-action=\"dismiss-import-result\"")


def test_frontend_contract_phase13_dismiss_redirect_preserves_active_filter_params(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    csrf_token = frontend_contract_ctx["csrf_token"]
    _set_last_import_result_session(
        client,
        {
            "imported_count": 0,
            "duplicate_count": 3,
            "failed_count": 1,
            "summary_text": "Partial import.",
            "source_filename": "redirect.csv",
            "recorded_at": "2026-03-10T13:02:00Z",
        },
    )

    params = {
        "q": "seed",
        "account": str(frontend_contract_ctx["expense_account_name"]),
        "category": str(frontend_contract_ctx["expense_category_name"]),
        "min_amount": "10.00",
        "max_amount": "500.00",
        "start_date": "2026-03-01",
        "end_date": "2026-03-31",
        "page": "2",
        "per_page": "25",
    }
    page_resp = client.get("/transactions", query_string=params)
    _csv_import_contract_assert(page_resp.status_code == 200, f"expected /transactions 200, got {page_resp.status_code}")

    html = page_resp.get_data(as_text=True)
    form_open = _extract_form_open_tag(html, "/transactions/import_result/dismiss")
    _csv_import_contract_assert(form_open is not None, "dismiss form action /transactions/import_result/dismiss not found")

    action_match = re.search(r'action="([^"]+)"', form_open or "")
    _csv_import_contract_assert(action_match is not None, "dismiss form action attribute missing")
    dismiss_action = (action_match.group(1) if action_match else "/transactions/import_result/dismiss").replace("&amp;", "&")

    post_resp = client.post(dismiss_action, data={"csrf_token": csrf_token}, follow_redirects=False)
    _csv_import_contract_assert(300 <= post_resp.status_code < 400, f"dismiss should redirect, got status {post_resp.status_code}")
    location = str(post_resp.headers.get("Location") or "")
    _csv_import_contract_assert(bool(location), "dismiss redirect missing Location header")

    parsed = urlparse(location)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key in params:
        _csv_import_contract_assert(key in query, f"dismiss redirect missing preserved key {key}")
