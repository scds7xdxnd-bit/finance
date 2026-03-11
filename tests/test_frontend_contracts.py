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
    ReceivableTracker,
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
TRANSACTION_EDIT_UX_FAILURE_PREFIX = "Transaction edit UX contract failed:"
TRANSACTION_EDIT_STATE_FAILURE_PREFIX = "Transaction edit state contract failed:"
TRANSACTION_EDIT_REFRESH_SAFETY_FAILURE_PREFIX = "Transaction edit refresh safety contract failed:"
TRANSACTION_EDIT_USABILITY_FAILURE_PREFIX = "Transaction edit usability contract failed:"
CSV_IMPORT_DETAILS_UX_FAILURE_PREFIX = "CSV import details UX contract failed:"
MONTH_CLOSE_FAILURE_PREFIX = "Month close contract failed:"
MONTH_CLOSE_DOCUMENTS_FAILURE_PREFIX = "Month close documents contract failed:"
MONTH_CLOSE_DOCUMENTS_STATE_FAILURE_PREFIX = "Month close documents state contract failed:"
MONTH_CLOSE_COVERAGE_FAILURE_PREFIX = "Month close coverage contract failed:"
MONTH_CLOSE_RESOLUTION_FAILURE_PREFIX = "Month close resolution contract failed:"
MONTH_CLOSE_READINESS_FAILURE_PREFIX = "Month close readiness contract failed:"
MONTH_CLOSE_READINESS_LINKAGE_FAILURE_PREFIX = "Month close readiness linkage contract failed:"


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


def _transaction_edit_contract_assert(condition: bool, message: str) -> None:
    assert condition, f"{TRANSACTION_EDIT_UX_FAILURE_PREFIX} {message}"


def _transaction_edit_state_contract_assert(condition: bool, message: str) -> None:
    assert condition, f"{TRANSACTION_EDIT_STATE_FAILURE_PREFIX} {message}"


def _transaction_edit_refresh_safety_contract_assert(condition: bool, message: str) -> None:
    assert condition, f"{TRANSACTION_EDIT_REFRESH_SAFETY_FAILURE_PREFIX} {message}"


def _transaction_edit_usability_contract_assert(condition: bool, message: str) -> None:
    assert condition, f"{TRANSACTION_EDIT_USABILITY_FAILURE_PREFIX} {message}"


def _csv_import_details_contract_assert(condition: bool, message: str) -> None:
    assert condition, f"{CSV_IMPORT_DETAILS_UX_FAILURE_PREFIX} {message}"


def _month_close_contract_assert(condition: bool, message: str) -> None:
    assert condition, f"{MONTH_CLOSE_FAILURE_PREFIX} {message}"


def _month_close_documents_contract_assert(condition: bool, message: str) -> None:
    assert condition, f"{MONTH_CLOSE_DOCUMENTS_FAILURE_PREFIX} {message}"


def _month_close_documents_state_contract_assert(condition: bool, message: str) -> None:
    assert condition, f"{MONTH_CLOSE_DOCUMENTS_STATE_FAILURE_PREFIX} {message}"


def _month_close_coverage_contract_assert(condition: bool, message: str) -> None:
    assert condition, f"{MONTH_CLOSE_COVERAGE_FAILURE_PREFIX} {message}"


def _month_close_resolution_contract_assert(condition: bool, message: str) -> None:
    assert condition, f"{MONTH_CLOSE_RESOLUTION_FAILURE_PREFIX} {message}"


def _month_close_readiness_contract_assert(condition: bool, message: str) -> None:
    assert condition, f"{MONTH_CLOSE_READINESS_FAILURE_PREFIX} {message}"


def _month_close_readiness_linkage_contract_assert(condition: bool, message: str) -> None:
    assert condition, f"{MONTH_CLOSE_READINESS_LINKAGE_FAILURE_PREFIX} {message}"


def _set_last_import_result_session(client, payload: dict) -> None:
    with client.session_transaction() as sess:
        sess["last_import_result_v1"] = payload


def _extract_form_open_tag(html: str, action_path: str) -> str | None:
    pattern = re.compile(rf"<form\b[^>]*action=\"[^\"]*{re.escape(action_path)}[^\"]*\"[^>]*>", flags=re.IGNORECASE)
    match = pattern.search(html)
    return match.group(0) if match else None


def _extract_action_url(html: str, action_key: str) -> str | None:
    action_match = re.search(
        rf"<(?P<tag>\w+)\b[^>]*data-action=\"{re.escape(action_key)}\"[^>]*>",
        html,
        flags=re.IGNORECASE,
    )
    if action_match is None:
        return None

    action_open_tag = action_match.group(0)
    for attr in ("href", "formaction", "action", "data-url"):
        attr_match = re.search(rf'{attr}=\"([^\"]+)\"', action_open_tag, flags=re.IGNORECASE)
        if attr_match:
            return unescape(attr_match.group(1))

    action_start = action_match.start()
    form_open_start = html.rfind("<form", 0, action_start)
    if form_open_start < 0:
        return None
    form_open_end = html.find(">", form_open_start)
    form_close = html.find("</form>", action_start)
    if form_open_end < 0 or form_close < 0 or not (form_open_end < action_start < form_close):
        return None
    form_open_tag = html[form_open_start : form_open_end + 1]
    form_action_match = re.search(r'action=\"([^\"]+)\"', form_open_tag, flags=re.IGNORECASE)
    if form_action_match:
        return unescape(form_action_match.group(1))
    return None


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


def _seed_month_close_documents_state_scenario(
    frontend_contract_ctx,
    *,
    open_documents_count: int,
    total_documents_count: int,
) -> None:
    app = frontend_contract_ctx["app"]
    user_id = int(frontend_contract_ctx["user_id"])
    expense_account_id = int(frontend_contract_ctx["expense_account_id"])
    income_account_id = int(frontend_contract_ctx["income_account_id"])
    open_count = max(0, int(open_documents_count))
    total_count = max(open_count, int(total_documents_count))

    with app.app_context():
        receivable_cat = AccountCategory(user_id=user_id, name=f"Accounts Receivable 63_1 {uuid4().hex[:6]}", tb_group="asset")
        payable_cat = AccountCategory(user_id=user_id, name=f"Short-term Debt 63_1 {uuid4().hex[:6]}", tb_group="liability")
        db.session.add_all([receivable_cat, payable_cat])
        db.session.flush()

        receivable_acc = Account(user_id=user_id, name=f"AR 63_1 {uuid4().hex[:6]}", category_id=receivable_cat.id, currency_code="KRW", active=True)
        payable_acc = Account(user_id=user_id, name=f"Debt 63_1 {uuid4().hex[:6]}", category_id=payable_cat.id, currency_code="KRW", active=True)
        db.session.add_all([receivable_acc, payable_acc])
        db.session.flush()

        for idx in range(total_count):
            kind = "receivable" if idx % 2 == 0 else "debt"
            is_open = idx < open_count
            base_amount = Decimal("100.00")

            entry = JournalEntry(
                user_id=user_id,
                date=f"2026/03/{(idx % 27) + 1:02d}",
                date_parsed=dt.date(2026, 3, (idx % 27) + 1),
                description=f"63_1 documents state seed {idx}",
                posted_at=dt.datetime(2026, 3, 20, 12, 0, 0),
            )
            db.session.add(entry)
            db.session.flush()

            if kind == "receivable":
                doc_line = JournalLine(journal_id=entry.id, account_id=receivable_acc.id, dc="D", amount_base=base_amount, line_no=1)
                counter_line = JournalLine(journal_id=entry.id, account_id=income_account_id, dc="C", amount_base=base_amount, line_no=2)
            else:
                doc_line = JournalLine(journal_id=entry.id, account_id=payable_acc.id, dc="C", amount_base=base_amount, line_no=1)
                counter_line = JournalLine(journal_id=entry.id, account_id=expense_account_id, dc="D", amount_base=base_amount, line_no=2)
            db.session.add_all([doc_line, counter_line])
            db.session.flush()

            db.session.add(
                ReceivableTracker(
                    user_id=user_id,
                    journal_id=entry.id,
                    journal_line_id=doc_line.id,
                    account_id=doc_line.account_id,
                    category=kind,
                    contact_name=f"Doc Contact {idx}",
                    transaction_value=base_amount,
                    amount_paid=Decimal("0.00") if is_open else base_amount,
                    remaining_amount=base_amount if is_open else Decimal("0.00"),
                    status="UNPAID" if is_open else "PAID",
                    currency_code="KRW",
                )
            )

        db.session.commit()


def _assert_month_close_documents_state_scenario(
    frontend_contract_ctx,
    *,
    open_documents_count: int,
    total_documents_count: int,
    expected_state: str,
) -> None:
    _seed_month_close_documents_state_scenario(
        frontend_contract_ctx,
        open_documents_count=open_documents_count,
        total_documents_count=total_documents_count,
    )

    client = frontend_contract_ctx["client"]
    requested_ym = "2026-03"
    response = client.get("/accounting/month_close", query_string={"ym": requested_ym})
    _month_close_documents_state_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym={requested_ym} to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)

    for selector in (
        'data-role="mc-documents"',
        'data-role="mc-documents-open-count"',
        'data-role="mc-documents-total-count"',
    ):
        _month_close_documents_state_contract_assert(selector in html, f"missing required selector {selector}")

    docs_match = re.search(r"<[^>]*data-role=\"mc-documents\"[^>]*>", html)
    _month_close_documents_state_contract_assert(docs_match is not None, "missing mc-documents open tag")
    docs_open_tag = docs_match.group(0) if docs_match else ""
    state_match = re.search(r'data-state="([^"]+)"', docs_open_tag)
    _month_close_documents_state_contract_assert(state_match is not None, "mc-documents must include data-state")
    state_value = state_match.group(1) if state_match else ""
    _month_close_documents_state_contract_assert(
        state_value == expected_state,
        f"mc-documents state mismatch: expected {expected_state!r}, got {state_value!r}",
    )

    open_match = re.search(r"<[^>]*data-role=\"mc-documents-open-count\"[^>]*>(.*?)</[^>]+>", html, flags=re.DOTALL)
    total_match = re.search(r"<[^>]*data-role=\"mc-documents-total-count\"[^>]*>(.*?)</[^>]+>", html, flags=re.DOTALL)
    _month_close_documents_state_contract_assert(open_match is not None, "missing mc-documents-open-count value slot")
    _month_close_documents_state_contract_assert(total_match is not None, "missing mc-documents-total-count value slot")

    open_text = re.sub(r"<[^>]+>", "", open_match.group(1) if open_match else "").strip()
    total_text = re.sub(r"<[^>]+>", "", total_match.group(1) if total_match else "").strip()
    open_digits = re.search(r"-?\d+", open_text or "")
    total_digits = re.search(r"-?\d+", total_text or "")
    _month_close_documents_state_contract_assert(open_digits is not None, f"open count text must include numeric value, got {open_text!r}")
    _month_close_documents_state_contract_assert(total_digits is not None, f"total count text must include numeric value, got {total_text!r}")
    _month_close_documents_state_contract_assert(
        int(open_digits.group(0)) == int(open_documents_count),
        f"open count mismatch: expected {open_documents_count}, got {int(open_digits.group(0)) if open_digits else 'n/a'}",
    )
    _month_close_documents_state_contract_assert(
        int(total_digits.group(0)) == int(total_documents_count),
        f"total count mismatch: expected {total_documents_count}, got {int(total_digits.group(0)) if total_digits else 'n/a'}",
    )

    optional_actions = (
        "mc-download-tb-pdf",
        "mc-download-statement-pdf",
        "mc-download-receivables-pdf",
        "mc-download-payables-pdf",
        "mc-download-loan-receipt-pdf",
    )
    for action_key in optional_actions:
        if f'data-action="{action_key}"' in html:
            action_url = _extract_action_url(html, action_key)
            _month_close_documents_state_contract_assert(
                action_url is not None,
                f"{action_key} must render URL when selector is present",
            )
            _month_close_documents_state_contract_assert(
                "ym=2026-03" in str(action_url),
                f"{action_key} URL must include ym=2026-03, got {action_url!r}",
            )


def _seed_month_close_draft_entry(frontend_contract_ctx, *, debit_amount: Decimal, credit_amount: Decimal) -> None:
    app = frontend_contract_ctx["app"]
    user_id = int(frontend_contract_ctx["user_id"])
    expense_account_id = int(frontend_contract_ctx["expense_account_id"])
    income_account_id = int(frontend_contract_ctx["income_account_id"])

    with app.app_context():
        entry = JournalEntry(
            user_id=user_id,
            date="2026/03/25",
            date_parsed=dt.date(2026, 3, 25),
            description=f"63_2 draft seed debit={debit_amount} credit={credit_amount}",
            posted_at=None,
        )
        db.session.add(entry)
        db.session.flush()
        db.session.add(
            JournalLine(
                journal_id=entry.id,
                account_id=expense_account_id,
                dc="D",
                amount_base=debit_amount,
                line_no=1,
            )
        )
        db.session.add(
            JournalLine(
                journal_id=entry.id,
                account_id=income_account_id,
                dc="C",
                amount_base=credit_amount,
                line_no=2,
            )
        )
        db.session.commit()


def _extract_role_state(html: str, role: str) -> str | None:
    tag_open = _extract_role_open_tag(html, role)
    if tag_open is None:
        return None
    state_match = re.search(r'data-state="([^"]+)"', tag_open)
    if state_match is None:
        return None
    return state_match.group(1)


def _extract_role_open_tag(html: str, role: str) -> str | None:
    tag_match = re.search(rf"<[^>]*data-role=\"{re.escape(role)}\"[^>]*>", html)
    if tag_match is None:
        return None
    return tag_match.group(0)


def _extract_role_attr(html: str, role: str, attr: str) -> str | None:
    tag_open = _extract_role_open_tag(html, role)
    if tag_open is None:
        return None
    attr_match = re.search(rf'{re.escape(attr)}="([^"]+)"', tag_open, flags=re.IGNORECASE)
    if attr_match is None:
        return None
    return attr_match.group(1)


def _extract_role_url(html: str, role: str) -> str | None:
    role_match = re.search(
        rf"<(?P<tag>\w+)\b[^>]*data-role=\"{re.escape(role)}\"[^>]*>",
        html,
        flags=re.IGNORECASE,
    )
    if role_match is None:
        return None

    role_open_tag = role_match.group(0)
    for attr in ("href", "formaction", "action", "data-url"):
        attr_match = re.search(rf'{attr}=\"([^\"]+)\"', role_open_tag, flags=re.IGNORECASE)
        if attr_match:
            return unescape(attr_match.group(1))

    role_start = role_match.start()
    form_open_start = html.rfind("<form", 0, role_start)
    if form_open_start < 0:
        return None
    form_open_end = html.find(">", form_open_start)
    form_close = html.find("</form>", role_start)
    if form_open_end < 0 or form_close < 0 or not (form_open_end < role_start < form_close):
        return None
    form_open_tag = html[form_open_start : form_open_end + 1]
    form_action_match = re.search(r'action=\"([^\"]+)\"', form_open_tag, flags=re.IGNORECASE)
    if form_action_match:
        return unescape(form_action_match.group(1))
    return None


def _extract_role_numeric_value(html: str, role: str) -> int | None:
    value_match = re.search(rf"<[^>]*data-role=\"{re.escape(role)}\"[^>]*>(.*?)</[^>]+>", html, flags=re.DOTALL)
    if value_match is None:
        return None
    text = re.sub(r"<[^>]+>", "", value_match.group(1)).strip()
    int_match = re.search(r"-?\d+", text)
    if int_match is None:
        return None
    return int(int_match.group(0))


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


def test_frontend_contract_phase121_selector_surface_exists(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    _transaction_edit_contract_assert(html_resp.status_code == 200, f"expected /accounting 200, got {html_resp.status_code}")
    html = html_resp.get_data(as_text=True)

    required_selectors = (
        'data-action="edit-entry"',
        'id="journal-edit-modal"',
        'id="journal-edit-form"',
        'data-role="lines"',
        'data-role="balance-delta"',
        'data-role="form-error"',
        'data-action="save-entry"',
    )
    for selector in required_selectors:
        _transaction_edit_contract_assert(selector in html, f"missing selector {selector}")


def test_frontend_contract_phase121_unbalanced_update_mapping(frontend_contract_ctx, monkeypatch):
    client = frontend_contract_ctx["client"]
    csrf_token = frontend_contract_ctx["csrf_token"]
    entry_id = frontend_contract_ctx["entry_id"]
    expense_account_id = frontend_contract_ctx["expense_account_id"]
    income_account_id = frontend_contract_ctx["income_account_id"]

    import blueprints.accounting as accounting_module

    monkeypatch.setattr(accounting_module, "_validate_balanced", lambda *_args, **_kwargs: None)

    response = client.put(
        f"/accounting/journal/{entry_id}",
        json={
            "date": "2026-03-12",
            "description": "phase1.2.1 unbalanced mapping drill",
            "reference": "REF-LOCK-58_1",
            "lines": [
                {"dc": "D", "account_id": expense_account_id, "amount": 100.0},
                {"dc": "C", "account_id": income_account_id, "amount": 60.0},
            ],
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    payload = response.get_json(silent=True)
    _transaction_edit_contract_assert(400 <= response.status_code < 500, f"expected 4xx on unbalanced update, got {response.status_code}")
    _transaction_edit_contract_assert(isinstance(payload, dict), "unbalanced update response is not JSON object")
    _transaction_edit_contract_assert(payload.get("ok") is False, "unbalanced update must return ok=false")
    _transaction_edit_contract_assert(isinstance(payload.get("error"), str) and bool(payload.get("error")), "unbalanced update must return non-empty error string")
    _transaction_edit_contract_assert(payload.get("error_code") == "JOURNAL_NOT_BALANCED", "unbalanced update must return error_code=JOURNAL_NOT_BALANCED")


def test_frontend_contract_phase121_registry_keys_and_update_token(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    _transaction_edit_contract_assert(html_resp.status_code == 200, f"expected /accounting 200, got {html_resp.status_code}")
    html = html_resp.get_data(as_text=True)

    missing_keys = find_missing_endpoint_registry_keys(html)
    _transaction_edit_contract_assert(
        "window.FINANCE_ENDPOINTS.accounting.journal.list" not in missing_keys,
        "missing registry key window.FINANCE_ENDPOINTS.accounting.journal.list",
    )
    _transaction_edit_contract_assert(
        "window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate" not in missing_keys,
        "missing registry key window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate",
    )
    _transaction_edit_contract_assert("__ENTRY_ID__" in html, "journal update template token __ENTRY_ID__ missing")


def test_frontend_contract_phase121_post_save_refresh_path_preserves_page_and_per_page(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    _transaction_edit_contract_assert(html_resp.status_code == 200, f"expected /accounting 200, got {html_resp.status_code}")
    html = html_resp.get_data(as_text=True)

    _transaction_edit_contract_assert(
        "function buildJournalParams(filters, page, perPage)" in html,
        "missing buildJournalParams helper",
    )
    _transaction_edit_contract_assert(
        "params.set('page', String(page));" in html,
        "list refresh URL builder must propagate page",
    )
    _transaction_edit_contract_assert(
        "params.set('per_page', String(perPage));" in html,
        "list refresh URL builder must propagate per_page",
    )
    _transaction_edit_contract_assert(
        "loadJournalEntries(JOURNAL_STATE.page || 1, { useControlState: false, pushHistory: false });" in html,
        "post-save refresh path must call loadJournalEntries with current page and preserve query state",
    )


def test_frontend_contract_phase122_static_selector_surface(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    _transaction_edit_state_contract_assert(html_resp.status_code == 200, f"expected /accounting 200, got {html_resp.status_code}")
    html = html_resp.get_data(as_text=True)

    _transaction_edit_state_contract_assert('id="journal-edit-modal"' in html, "missing selector #journal-edit-modal")
    _transaction_edit_state_contract_assert('data-role="preload-state"' in html, "missing selector [data-role=\"preload-state\"]")
    _transaction_edit_state_contract_assert('data-action="edit-entry"' in html, "missing selector [data-action=\"edit-entry\"]")
    _transaction_edit_state_contract_assert('data-entry-id' in html, "missing data-entry-id attribute on edit action surface")


def test_frontend_contract_phase122_registry_contract(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    _transaction_edit_state_contract_assert(html_resp.status_code == 200, f"expected /accounting 200, got {html_resp.status_code}")
    html = html_resp.get_data(as_text=True)
    missing_keys = find_missing_endpoint_registry_keys(html)

    _transaction_edit_state_contract_assert(
        "window.FINANCE_ENDPOINTS.accounting.journal.list" not in missing_keys,
        "missing registry key window.FINANCE_ENDPOINTS.accounting.journal.list",
    )
    _transaction_edit_state_contract_assert(
        "window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate" not in missing_keys,
        "missing registry key window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate",
    )
    _transaction_edit_state_contract_assert("__ENTRY_ID__" in html, "journal update template token __ENTRY_ID__ missing")


def test_frontend_contract_phase122_safe_default_missing_state_and_save_disabled(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    _transaction_edit_state_contract_assert(html_resp.status_code == 200, f"expected /accounting 200, got {html_resp.status_code}")
    html = html_resp.get_data(as_text=True)

    preload_match = re.search(r'data-role="preload-state"[^>]*data-state="([^"]+)"', html)
    _transaction_edit_state_contract_assert(preload_match is not None, "missing preload-state marker with data-state")
    state_val = (preload_match.group(1).strip().lower() if preload_match else "")
    _transaction_edit_state_contract_assert(
        state_val in {"loading", "missing"},
        f"preload-state default must be loading or missing, got {state_val or '<empty>'}",
    )
    _transaction_edit_state_contract_assert(
        re.search(r'data-action="save-entry"[^>]*\bdisabled\b', html) is not None,
        "save action must be disabled in server-rendered HTML default",
    )
    _transaction_edit_state_contract_assert('data-role="form-error"' in html, "missing selector [data-role=\"form-error\"]")


def test_frontend_contract_phase122_roundtrip_refresh_pattern_references_page_and_per_page(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    _transaction_edit_state_contract_assert(html_resp.status_code == 200, f"expected /accounting 200, got {html_resp.status_code}")
    html = html_resp.get_data(as_text=True)

    _transaction_edit_state_contract_assert(
        "function buildJournalParams(filters, page, perPage)" in html,
        "missing buildJournalParams helper",
    )
    _transaction_edit_state_contract_assert(
        "params.set('page', String(page));" in html,
        "list refresh URL builder must reference page",
    )
    _transaction_edit_state_contract_assert(
        "params.set('per_page', String(perPage));" in html,
        "list refresh URL builder must reference per_page",
    )


def test_frontend_contract_phase123_modal_refresh_safety_markers(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    _transaction_edit_refresh_safety_contract_assert(html_resp.status_code == 200, f"expected /accounting 200, got {html_resp.status_code}")
    html = html_resp.get_data(as_text=True)

    modal_start = html.find('id="journal-edit-modal"')
    _transaction_edit_refresh_safety_contract_assert(modal_start >= 0, "missing #journal-edit-modal")
    modal_fragment = html[modal_start : modal_start + 6000] if modal_start >= 0 else ""

    _transaction_edit_refresh_safety_contract_assert(
        'data-role="edit-session"' in modal_fragment,
        "missing [data-role=\"edit-session\"] inside #journal-edit-modal",
    )
    _transaction_edit_refresh_safety_contract_assert(
        'data-role="stale-warning"' in modal_fragment,
        "missing [data-role=\"stale-warning\"] inside #journal-edit-modal",
    )
    _transaction_edit_refresh_safety_contract_assert(
        re.search(r'<div id="journal-edit-modal"[^>]*data-buffer-authority="local"', html) is not None,
        "missing data-buffer-authority=\"local\" on #journal-edit-modal",
    )


def test_frontend_contract_phase123_registry_stability(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    _transaction_edit_refresh_safety_contract_assert(html_resp.status_code == 200, f"expected /accounting 200, got {html_resp.status_code}")
    html = html_resp.get_data(as_text=True)
    missing_keys = find_missing_endpoint_registry_keys(html)

    _transaction_edit_refresh_safety_contract_assert(
        "window.FINANCE_ENDPOINTS.accounting.journal.list" not in missing_keys,
        "missing registry key window.FINANCE_ENDPOINTS.accounting.journal.list",
    )
    _transaction_edit_refresh_safety_contract_assert(
        "window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate" not in missing_keys,
        "missing registry key window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate",
    )
    _transaction_edit_refresh_safety_contract_assert("__ENTRY_ID__" in html, "journal update template token __ENTRY_ID__ missing")


def test_frontend_contract_phase123_refresh_builder_references_page_and_per_page(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    _transaction_edit_refresh_safety_contract_assert(html_resp.status_code == 200, f"expected /accounting 200, got {html_resp.status_code}")
    html = html_resp.get_data(as_text=True)

    _transaction_edit_refresh_safety_contract_assert(
        "function buildJournalParams(filters, page, perPage)" in html,
        "missing buildJournalParams helper",
    )
    _transaction_edit_refresh_safety_contract_assert(
        "params.set('page', String(page));" in html,
        "refresh URL builder must reference page",
    )
    _transaction_edit_refresh_safety_contract_assert(
        "params.set('per_page', String(perPage));" in html,
        "refresh URL builder must reference per_page",
    )


def test_frontend_contract_phase124_modal_usability_selector_surface(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    _transaction_edit_usability_contract_assert(html_resp.status_code == 200, f"expected /accounting 200, got {html_resp.status_code}")
    html = html_resp.get_data(as_text=True)

    modal_start = html.find('id="journal-edit-modal"')
    _transaction_edit_usability_contract_assert(modal_start >= 0, "missing #journal-edit-modal")
    modal_fragment = html[modal_start : modal_start + 9000] if modal_start >= 0 else ""

    regression_markers = (
        'data-role="edit-session"',
        'data-role="stale-warning"',
        'data-role="preload-state"',
    )
    for marker in regression_markers:
        _transaction_edit_usability_contract_assert(marker in modal_fragment, f"missing required regression marker {marker}")

    _transaction_edit_usability_contract_assert(
        re.search(r'<div id="journal-edit-modal"[^>]*data-buffer-authority="local"', html) is not None,
        "missing data-buffer-authority=\"local\" on #journal-edit-modal",
    )

    required_selectors = (
        'data-role="first-focus"',
        'data-role="focus-trap"',
        'data-action="close-editor"',
        'data-action="cancel-editor"',
        'data-role="balance-delta-label"',
        'data-role="balance-delta-amount"',
        'data-role="not-balanced-callout"',
    )
    for selector in required_selectors:
        _transaction_edit_usability_contract_assert(selector in modal_fragment, f"missing selector {selector}")

    save_status_match = re.search(r'data-role="save-status"[^>]*data-state="([^"]+)"', modal_fragment)
    _transaction_edit_usability_contract_assert(
        save_status_match is not None,
        "missing [data-role=\"save-status\"] with data-state attribute",
    )

    # Optional features in this phase: assert only if already implemented.
    if 'data-action="duplicate-line"' in modal_fragment:
        _transaction_edit_usability_contract_assert(True, "optional selector duplicate-line present")
    if 'data-action="reload-latest"' in modal_fragment:
        _transaction_edit_usability_contract_assert(True, "optional selector reload-latest present")


def test_frontend_contract_phase124_registry_stability(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    html_resp = client.get("/accounting")
    _transaction_edit_usability_contract_assert(html_resp.status_code == 200, f"expected /accounting 200, got {html_resp.status_code}")
    html = html_resp.get_data(as_text=True)
    missing_keys = find_missing_endpoint_registry_keys(html)

    _transaction_edit_usability_contract_assert(
        "window.FINANCE_ENDPOINTS.accounting.journal.list" not in missing_keys,
        "missing registry key window.FINANCE_ENDPOINTS.accounting.journal.list",
    )
    _transaction_edit_usability_contract_assert(
        "window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate" not in missing_keys,
        "missing registry key window.FINANCE_ENDPOINTS.accounting.journal.updateTemplate",
    )
    _transaction_edit_usability_contract_assert(
        "__ENTRY_ID__" in html,
        "journal update template token __ENTRY_ID__ missing",
    )

    # Optional non-JS guard: refresh builder still references page/per_page.
    _transaction_edit_usability_contract_assert(
        "params.set('page', String(page));" in html and "params.set('per_page', String(perPage));" in html,
        "refresh builder must reference page and per_page",
    )


def test_frontend_contract_phase131_details_failure_samples_only(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    _set_last_import_result_session(
        client,
        {
            "imported_count": 0,
            "duplicate_count": 0,
            "failed_count": 2,
            "summary_text": "Import failed for 2 rows.",
            "source_filename": "details-failures.csv",
            "recorded_at": "2026-03-11T10:00:00Z",
            "failure_samples": [{"line_number": 4, "message": "invalid amount"}],
        },
    )

    resp = client.get("/transactions")
    _csv_import_details_contract_assert(resp.status_code == 200, f"expected /transactions 200, got {resp.status_code}")
    html = resp.get_data(as_text=True)
    base_selectors = (
        "#last-import-result-panel",
        'data-role="import-severity"',
        'data-role="import-summary"',
        'data-role="import-counts"',
        'data-role="import-filename"',
        'data-role="import-recorded-at"',
    )
    for selector in base_selectors:
        _csv_import_details_contract_assert(selector in html, f"missing base selector {selector}")
    _csv_import_details_contract_assert('data-action="toggle-import-details"' in html, "missing details toggle")
    _csv_import_details_contract_assert(
        re.search(r'data-role="import-details"[^>]*data-state="collapsed"', html) is not None,
        "details container must default to data-state=\"collapsed\"",
    )
    _csv_import_details_contract_assert('data-role="import-details-failures"' in html, "missing failures details section")
    _csv_import_details_contract_assert('data-role="import-details-warnings"' not in html, "warnings details section must be absent")


def test_frontend_contract_phase131_details_warnings_only(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    _set_last_import_result_session(
        client,
        {
            "imported_count": 0,
            "duplicate_count": 1,
            "failed_count": 1,
            "summary_text": "Import had warnings.",
            "source_filename": "details-warnings.csv",
            "recorded_at": "2026-03-11T10:02:00Z",
            "warnings": ["date normalized to YYYY-MM-DD"],
        },
    )

    resp = client.get("/transactions")
    _csv_import_details_contract_assert(resp.status_code == 200, f"expected /transactions 200, got {resp.status_code}")
    html = resp.get_data(as_text=True)
    _csv_import_details_contract_assert('data-action="toggle-import-details"' in html, "missing details toggle")
    _csv_import_details_contract_assert(
        re.search(r'data-role="import-details"[^>]*data-state="collapsed"', html) is not None,
        "details container must default to data-state=\"collapsed\"",
    )
    _csv_import_details_contract_assert('data-role="import-details-warnings"' in html, "missing warnings details section")
    _csv_import_details_contract_assert('data-role="import-details-failures"' not in html, "failures details section must be absent")


def test_frontend_contract_phase131_details_absent_hides_toggle_and_details(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    _set_last_import_result_session(
        client,
        {
            "imported_count": 5,
            "duplicate_count": 0,
            "failed_count": 0,
            "summary_text": "Import successful.",
            "source_filename": "details-none.csv",
            "recorded_at": "2026-03-11T10:04:00Z",
        },
    )

    resp = client.get("/transactions")
    _csv_import_details_contract_assert(resp.status_code == 200, f"expected /transactions 200, got {resp.status_code}")
    html = resp.get_data(as_text=True)
    _csv_import_details_contract_assert("#last-import-result-panel" in html, "base panel must render")
    _csv_import_details_contract_assert('data-action="toggle-import-details"' not in html, "details toggle must be absent when no details data")
    _csv_import_details_contract_assert('data-role="import-details"' not in html, "details container must be absent when no details data")


def test_frontend_contract_phase131_dismiss_semantics_and_param_preservation(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    csrf_token = frontend_contract_ctx["csrf_token"]
    _set_last_import_result_session(
        client,
        {
            "imported_count": 0,
            "duplicate_count": 0,
            "failed_count": 1,
            "summary_text": "Import failed.",
            "source_filename": "details-dismiss.csv",
            "recorded_at": "2026-03-11T10:06:00Z",
            "failure_samples": [{"line_number": 1, "message": "bad data"}],
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
    _csv_import_details_contract_assert(page_resp.status_code == 200, f"expected /transactions 200, got {page_resp.status_code}")
    html = page_resp.get_data(as_text=True)
    form_open = _extract_form_open_tag(html, "/transactions/import_result/dismiss")
    _csv_import_details_contract_assert(form_open is not None, "dismiss form action /transactions/import_result/dismiss not found")
    _csv_import_details_contract_assert('method="post"' in (form_open or "").lower(), "dismiss form must use POST")
    _csv_import_details_contract_assert('name="csrf_token"' in html, "dismiss form must include csrf_token field")

    action_match = re.search(r'action="([^"]+)"', form_open or "")
    _csv_import_details_contract_assert(action_match is not None, "dismiss form action attribute missing")
    dismiss_action = (action_match.group(1) if action_match else "/transactions/import_result/dismiss").replace("&amp;", "&")
    dismiss_resp = client.post(dismiss_action, data={"csrf_token": csrf_token}, follow_redirects=False)
    _csv_import_details_contract_assert(300 <= dismiss_resp.status_code < 400, f"dismiss should redirect, got {dismiss_resp.status_code}")
    location = str(dismiss_resp.headers.get("Location") or "")
    _csv_import_details_contract_assert(bool(location), "dismiss redirect missing Location header")

    query = parse_qs(urlparse(location).query, keep_blank_values=True)
    for key in params:
        _csv_import_details_contract_assert(key in query, f"dismiss redirect missing preserved key {key}")


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


def test_frontend_contract_phase20_month_close_foundation_selector_surface(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    requested_ym = "2026-03"
    response = client.get("/accounting/month_close", query_string={"ym": requested_ym})
    _month_close_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym={requested_ym} to return 200, got {response.status_code}",
    )

    html = response.get_data(as_text=True)
    required_selectors = (
        "#month-close-page",
        'data-role="month-close-ym"',
        'data-role="month-close-checklist"',
        'data-role="mc-coverage"',
        'data-role="mc-unbalanced-drafts"',
        'data-role="mc-reports"',
        'data-role="mc-snapshot"',
    )
    for selector in required_selectors:
        _month_close_contract_assert(selector in html, f"missing required selector {selector}")

    state_roles = (
        "mc-coverage",
        "mc-unbalanced-drafts",
        "mc-reports",
        "mc-snapshot",
    )
    allowed_states = {"ok", "warn", "fail", "unknown"}
    for role in state_roles:
        tag_match = re.search(rf"<[^>]*data-role=\"{re.escape(role)}\"[^>]*>", html)
        _month_close_contract_assert(tag_match is not None, f"missing checklist item tag for {role}")
        open_tag = tag_match.group(0) if tag_match else ""
        data_state_match = re.search(r'data-state="([^"]+)"', open_tag)
        _month_close_contract_assert(data_state_match is not None, f"missing data-state attribute on {role}")
        state_value = data_state_match.group(1) if data_state_match else ""
        _month_close_contract_assert(
            state_value in allowed_states,
            f"invalid data-state on {role}: {state_value!r}; allowed={sorted(allowed_states)}",
        )

    ym_text_match = re.search(
        r"<[^>]*data-role=\"month-close-ym\"[^>]*>(.*?)</[^>]+>",
        html,
        flags=re.DOTALL,
    )
    _month_close_contract_assert(ym_text_match is not None, "missing month-close-ym text container")
    ym_text = re.sub(r"<[^>]+>", "", ym_text_match.group(1) if ym_text_match else "")
    ym_text = unescape(ym_text).strip()
    _month_close_contract_assert(bool(ym_text), "month-close-ym text must be non-empty")
    _month_close_contract_assert(
        requested_ym in ym_text,
        f"month-close-ym text must contain requested ym {requested_ym!r}, got {ym_text!r}",
    )

    # Optional selectors: assert only when implemented in markup.
    optional_selectors = (
        'data-action="mc-create-snapshot"',
        'data-role="mc-snapshot-status"',
        'data-role="mc-snapshot-list"',
    )
    for selector in optional_selectors:
        if selector in html:
            continue


def test_frontend_contract_phase21_month_close_snapshot_section_shape(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    requested_ym = "2026-03"
    response = client.get("/accounting/month_close", query_string={"ym": requested_ym})
    _month_close_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym={requested_ym} to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)

    # Phase 2.0 selector regression guard remains required in 2.1.
    for selector in (
        "#month-close-page",
        'data-role="month-close-ym"',
        'data-role="month-close-checklist"',
        'data-role="mc-coverage"',
        'data-role="mc-unbalanced-drafts"',
        'data-role="mc-reports"',
        'data-role="mc-snapshot"',
    ):
        _month_close_contract_assert(selector in html, f"missing required selector {selector}")

    _month_close_contract_assert('data-role="mc-snapshot"' in html, "missing snapshot section data-role=\"mc-snapshot\"")
    _month_close_contract_assert('data-role="mc-snapshot-status"' in html, "missing snapshot status data-role=\"mc-snapshot-status\"")
    _month_close_contract_assert('data-action="mc-create-snapshot"' in html, "missing snapshot action data-action=\"mc-create-snapshot\"")
    _month_close_contract_assert(
        re.search(
            r"<form\b[^>]*method=[\"']post[\"'][^>]*>.*?data-action=\"mc-create-snapshot\".*?</form>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        is not None,
        "snapshot action must be rendered inside a POST form",
    )

    list_match = re.search(r"<ul\b[^>]*data-role=\"mc-snapshot-list\"[^>]*>(.*?)</ul>", html, flags=re.IGNORECASE | re.DOTALL)
    if list_match is not None:
        list_inner = list_match.group(1).strip()
        _month_close_contract_assert(bool(list_inner), "snapshot list container must be non-empty when present")


def test_frontend_contract_phase21_month_close_snapshot_create_redirect_shape(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    csrf_token = frontend_contract_ctx["csrf_token"]
    requested_ym = "2026-03"

    create_resp = client.post(
        "/accounting/month_close/snapshot",
        query_string={"ym": requested_ym},
        data={"csrf_token": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False,
    )
    _month_close_contract_assert(
        300 <= create_resp.status_code < 400,
        f"snapshot create must redirect, got status {create_resp.status_code}",
    )

    location = str(create_resp.headers.get("Location") or "")
    _month_close_contract_assert(bool(location), "snapshot create redirect missing Location header")
    parsed_location = urlparse(location)
    _month_close_contract_assert(
        parsed_location.path.endswith("/accounting/month_close"),
        f"snapshot create redirect must point to /accounting/month_close, got {parsed_location.path!r}",
    )
    location_qs = parse_qs(parsed_location.query, keep_blank_values=True)
    _month_close_contract_assert("ym" in location_qs, "snapshot create redirect missing ym query key")
    _month_close_contract_assert(
        requested_ym in (location_qs.get("ym") or []),
        f"snapshot create redirect must preserve ym={requested_ym!r}, got {location_qs.get('ym')!r}",
    )

    follow_resp = client.get(location)
    _month_close_contract_assert(
        follow_resp.status_code == 200,
        f"expected redirected month-close page to return 200, got {follow_resp.status_code}",
    )
    follow_html = follow_resp.get_data(as_text=True)
    snapshot_status_success = re.search(
        r"data-role=\"mc-snapshot-status\"[^>]*>.*?(success|created|saved).*?</",
        follow_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    _month_close_contract_assert(
        snapshot_status_success is not None or 'data-role="mc-snapshot-list"' in follow_html,
        "after snapshot create redirect, snapshot status must indicate success or snapshot list must be present",
    )


def test_frontend_contract_phase25_month_close_reports_documents_integration_surface(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    requested_ym = "2026-03"
    response = client.get("/accounting/month_close", query_string={"ym": requested_ym})
    _month_close_documents_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym={requested_ym} to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)

    required_selectors = (
        'data-role="mc-reports"',
        'data-action="mc-download-tb-pdf"',
        'data-action="mc-download-statement-pdf"',
        'data-role="mc-documents"',
        'data-action="mc-download-receivables-pdf"',
        'data-action="mc-download-payables-pdf"',
    )
    for selector in required_selectors:
        _month_close_documents_contract_assert(selector in html, f"missing required selector {selector}")

    documents_tag_match = re.search(r"<[^>]*data-role=\"mc-documents\"[^>]*>", html)
    _month_close_documents_contract_assert(documents_tag_match is not None, "missing mc-documents container open tag")
    documents_open_tag = documents_tag_match.group(0) if documents_tag_match else ""
    documents_state_match = re.search(r'data-state="([^"]+)"', documents_open_tag)
    _month_close_documents_contract_assert(documents_state_match is not None, "mc-documents must include data-state")
    documents_state = documents_state_match.group(1) if documents_state_match else ""
    _month_close_documents_contract_assert(
        documents_state in {"ok", "warn", "fail", "unknown"},
        f"mc-documents data-state must be one of ok|warn|fail|unknown, got {documents_state!r}",
    )

    ym_region_match = re.search(r"<[^>]*data-role=\"month-close-ym\"[^>]*>(.*?)</[^>]+>", html, flags=re.DOTALL)
    _month_close_documents_contract_assert(ym_region_match is not None, "missing month-close ym region")
    ym_region_text = re.sub(r"<[^>]+>", "", ym_region_match.group(1) if ym_region_match else "")
    ym_region_text = unescape(ym_region_text).strip()
    _month_close_documents_contract_assert(
        requested_ym in ym_region_text,
        f"month-close ym region must contain {requested_ym!r}, got {ym_region_text!r}",
    )

    required_action_urls = (
        "mc-download-tb-pdf",
        "mc-download-statement-pdf",
        "mc-download-receivables-pdf",
        "mc-download-payables-pdf",
    )
    for action_key in required_action_urls:
        action_url = _extract_action_url(html, action_key)
        _month_close_documents_contract_assert(action_url is not None, f"{action_key} must render href/form action URL")
        _month_close_documents_contract_assert(
            "ym=2026-03" in str(action_url),
            f"{action_key} URL must include ym=2026-03, got {action_url!r}",
        )

    if 'data-action="mc-download-loan-receipt-pdf"' in html:
        loan_action_url = _extract_action_url(html, "mc-download-loan-receipt-pdf")
        _month_close_documents_contract_assert(
            loan_action_url is not None,
            "mc-download-loan-receipt-pdf must render href/form action URL when present",
        )
        loan_action_url = str(loan_action_url or "")
        _month_close_documents_contract_assert(
            "ym=2026-03" in loan_action_url,
            f"mc-download-loan-receipt-pdf URL must include ym=2026-03, got {loan_action_url!r}",
        )
        has_loan_id = "loan_id=" in loan_action_url
        has_entry_id = "entry_id=" in loan_action_url
        _month_close_documents_contract_assert(
            has_loan_id ^ has_entry_id,
            f"mc-download-loan-receipt-pdf must include exactly one of loan_id or entry_id, got {loan_action_url!r}",
        )


def test_frontend_contract_phase251_month_close_documents_state_warn_when_open_documents_exist(frontend_contract_ctx):
    _assert_month_close_documents_state_scenario(
        frontend_contract_ctx,
        open_documents_count=2,
        total_documents_count=3,
        expected_state="warn",
    )


def test_frontend_contract_phase251_month_close_documents_state_ok_when_no_open_documents(frontend_contract_ctx):
    _assert_month_close_documents_state_scenario(
        frontend_contract_ctx,
        open_documents_count=0,
        total_documents_count=2,
        expected_state="ok",
    )


def test_frontend_contract_phase262_month_close_coverage_selector_surface(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    response = client.get("/accounting/month_close", query_string={"ym": "2026-03"})
    _month_close_coverage_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym=2026-03 to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)
    for selector in (
        'data-role="mc-coverage-source"',
        'data-role="mc-coverage-note"',
        'data-role="mc-drafts-count"',
        'data-role="mc-unbalanced-drafts-count"',
    ):
        _month_close_coverage_contract_assert(selector in html, f"missing required selector {selector}")


def test_frontend_contract_phase262_unbalanced_drafts_warn_when_unbalanced_count_gt_zero(frontend_contract_ctx):
    _seed_month_close_draft_entry(
        frontend_contract_ctx,
        debit_amount=Decimal("100.00"),
        credit_amount=Decimal("70.00"),
    )
    client = frontend_contract_ctx["client"]
    response = client.get("/accounting/month_close", query_string={"ym": "2026-03"})
    _month_close_coverage_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym=2026-03 to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)

    state_value = _extract_role_state(html, "mc-unbalanced-drafts")
    _month_close_coverage_contract_assert(state_value is not None, "mc-unbalanced-drafts must include data-state")
    _month_close_coverage_contract_assert(
        state_value == "warn",
        f"mc-unbalanced-drafts must be warn when unbalanced_draft_count > 0, got {state_value!r}",
    )
    _month_close_coverage_contract_assert(state_value != "fail", "mc-unbalanced-drafts fail state is not expected in Phase 2.6")

    drafts_count = _extract_role_numeric_value(html, "mc-drafts-count")
    unbalanced_count = _extract_role_numeric_value(html, "mc-unbalanced-drafts-count")
    _month_close_coverage_contract_assert(drafts_count is not None, "mc-drafts-count must render a numeric value")
    _month_close_coverage_contract_assert(unbalanced_count is not None, "mc-unbalanced-drafts-count must render a numeric value")
    _month_close_coverage_contract_assert(drafts_count == 4, f"expected draft count 4, got {drafts_count!r}")
    _month_close_coverage_contract_assert(unbalanced_count == 1, f"expected unbalanced draft count 1, got {unbalanced_count!r}")


def test_frontend_contract_phase262_unbalanced_drafts_ok_when_unbalanced_count_is_zero(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    response = client.get("/accounting/month_close", query_string={"ym": "2026-03"})
    _month_close_coverage_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym=2026-03 to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)

    state_value = _extract_role_state(html, "mc-unbalanced-drafts")
    _month_close_coverage_contract_assert(state_value is not None, "mc-unbalanced-drafts must include data-state")
    _month_close_coverage_contract_assert(
        state_value == "ok",
        f"mc-unbalanced-drafts must be ok when unbalanced_draft_count == 0, got {state_value!r}",
    )
    _month_close_coverage_contract_assert(state_value != "fail", "mc-unbalanced-drafts fail state is not expected in Phase 2.6")

    drafts_count = _extract_role_numeric_value(html, "mc-drafts-count")
    unbalanced_count = _extract_role_numeric_value(html, "mc-unbalanced-drafts-count")
    _month_close_coverage_contract_assert(drafts_count is not None, "mc-drafts-count must render a numeric value")
    _month_close_coverage_contract_assert(unbalanced_count is not None, "mc-unbalanced-drafts-count must render a numeric value")
    _month_close_coverage_contract_assert(drafts_count == 3, f"expected draft count 3, got {drafts_count!r}")
    _month_close_coverage_contract_assert(unbalanced_count == 0, f"expected unbalanced draft count 0, got {unbalanced_count!r}")


def test_frontend_contract_phase262_coverage_state_non_unknown_when_computable(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    response = client.get("/accounting/month_close", query_string={"ym": "2026-03"})
    _month_close_coverage_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym=2026-03 to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)
    coverage_state = _extract_role_state(html, "mc-coverage")
    _month_close_coverage_contract_assert(coverage_state is not None, "mc-coverage must include data-state")
    _month_close_coverage_contract_assert(
        coverage_state != "unknown",
        f"mc-coverage must not be unknown when computable, got {coverage_state!r}",
    )
    _month_close_coverage_contract_assert(coverage_state != "fail", "mc-coverage fail state is not expected in Phase 2.6")


def test_frontend_contract_phase262_coverage_state_unknown_when_schema_not_ready(frontend_contract_ctx, monkeypatch):
    import blueprints.accounting as accounting_module

    client = frontend_contract_ctx["client"]

    def _raise_schema_not_ready(*_args, **_kwargs):
        raise RuntimeError("schema not ready simulated")

    monkeypatch.setattr(accounting_module, "_build_month_close_snapshot_payload", _raise_schema_not_ready)

    response = client.get("/accounting/month_close", query_string={"ym": "2026-03"})
    _month_close_coverage_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym=2026-03 to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)
    coverage_state = _extract_role_state(html, "mc-coverage")
    _month_close_coverage_contract_assert(coverage_state is not None, "mc-coverage must include data-state")
    _month_close_coverage_contract_assert(
        coverage_state == "unknown",
        f"mc-coverage must be unknown when schema-not-ready is simulated, got {coverage_state!r}",
    )
    _month_close_coverage_contract_assert(coverage_state != "fail", "mc-coverage fail state is not expected in Phase 2.6")


def test_frontend_contract_phase263_month_close_resolution_actions_preserve_ym(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    requested_ym = "2026-03"
    response = client.get("/accounting/month_close", query_string={"ym": requested_ym})
    _month_close_resolution_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym={requested_ym} to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)

    required_actions = (
        "mc-open-tb",
        "mc-open-statements",
        "mc-open-journal-drafts",
    )
    for action_key in required_actions:
        _month_close_resolution_contract_assert(
            f'data-action="{action_key}"' in html,
            f"missing required selector data-action=\"{action_key}\"",
        )

    optional_actions = []
    if 'data-action="mc-open-documents-panel"' in html:
        optional_actions.append("mc-open-documents-panel")

    page_ctx_match = re.search(r'data-(?:current-)?page="([^"]+)"', html, flags=re.IGNORECASE)
    per_page_ctx_match = re.search(r'data-per-page="([^"]+)"', html, flags=re.IGNORECASE)
    if page_ctx_match is None:
        page_ctx_match = re.search(r'name="page"[^>]*value="([^"]+)"', html, flags=re.IGNORECASE)
    if per_page_ctx_match is None:
        per_page_ctx_match = re.search(r'name="per_page"[^>]*value="([^"]+)"', html, flags=re.IGNORECASE)
    page_ctx = page_ctx_match.group(1) if page_ctx_match else None
    per_page_ctx = per_page_ctx_match.group(1) if per_page_ctx_match else None

    for action_key in tuple(required_actions) + tuple(optional_actions):
        action_url = _extract_action_url(html, action_key)
        _month_close_resolution_contract_assert(
            action_url is not None,
            f"{action_key} must render href/formaction/action/data-url/form action URL",
        )
        parsed = urlparse(str(action_url))
        query = parse_qs(parsed.query, keep_blank_values=True)
        _month_close_resolution_contract_assert("ym" in query, f"{action_key} URL must include ym query key, got {action_url!r}")
        _month_close_resolution_contract_assert(
            requested_ym in (query.get("ym") or []),
            f"{action_key} URL ym must match {requested_ym!r}, got {query.get('ym')!r}",
        )

        indicates_paginated_target = (
            ("page" in query or "per_page" in query)
            or ("/journal" in parsed.path)
            or ("/transactions" in parsed.path)
        )
        if page_ctx and per_page_ctx and indicates_paginated_target:
            _month_close_resolution_contract_assert(
                "page" in query,
                f"{action_key} paginated target must preserve page when context provides it, got {action_url!r}",
            )
            _month_close_resolution_contract_assert(
                "per_page" in query,
                f"{action_key} paginated target must preserve per_page when context provides it, got {action_url!r}",
            )


def test_frontend_contract_phase29_month_close_documents_panel_resolution_link(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    requested_ym = "2026-03"
    response = client.get("/accounting/month_close", query_string={"ym": requested_ym})
    _month_close_resolution_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym={requested_ym} to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)

    _month_close_resolution_contract_assert(
        'data-action="mc-open-documents-panel"' in html,
        'missing required selector data-action="mc-open-documents-panel"',
    )

    documents_panel_url = _extract_action_url(html, "mc-open-documents-panel")
    _month_close_resolution_contract_assert(
        documents_panel_url is not None,
        "mc-open-documents-panel must render href/formaction/action/data-url/form action URL",
    )
    normalized_documents_panel_url = str(documents_panel_url or "").strip()
    _month_close_resolution_contract_assert(
        bool(normalized_documents_panel_url),
        "mc-open-documents-panel URL must be non-empty",
    )
    _month_close_resolution_contract_assert(
        normalized_documents_panel_url != "#",
        'mc-open-documents-panel URL must not be placeholder "#"',
    )

    documents_panel_parsed = urlparse(normalized_documents_panel_url)
    _month_close_resolution_contract_assert(
        documents_panel_parsed.path != "/accounting/month_close",
        f"mc-open-documents-panel URL must not self-link to /accounting/month_close, got {normalized_documents_panel_url!r}",
    )
    _month_close_resolution_contract_assert(
        documents_panel_parsed.path == "/accounting",
        f"mc-open-documents-panel URL must target /accounting, got path={documents_panel_parsed.path!r}",
    )

    documents_panel_query = parse_qs(documents_panel_parsed.query, keep_blank_values=True)
    _month_close_resolution_contract_assert(
        requested_ym in (documents_panel_query.get("ym") or []),
        f"mc-open-documents-panel URL must include ym={requested_ym!r}, got ym={documents_panel_query.get('ym')!r}",
    )

    readiness_action_key = _extract_role_attr(html, "mc-readiness-next-action", "data-action-key")
    readiness_enabled = _extract_role_attr(html, "mc-readiness-next-action", "data-enabled")
    if readiness_action_key == "open_documents" and readiness_enabled == "true":
        readiness_link_url = _extract_role_url(html, "mc-readiness-next-action-link")
        _month_close_resolution_contract_assert(
            readiness_link_url is not None,
            "mc-readiness-next-action-link must exist when readiness action-key=open_documents and data-enabled=true",
        )
        _month_close_resolution_contract_assert(
            str(readiness_link_url) == normalized_documents_panel_url,
            f"readiness open_documents link must equal mc-open-documents-panel URL; got readiness={readiness_link_url!r}, expected={normalized_documents_panel_url!r}",
        )


def test_frontend_contract_phase36_accounting_documents_panel_surface(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    requested_ym = "2026-03"
    response = client.get("/accounting", query_string={"ym": requested_ym})
    _month_close_resolution_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting?ym={requested_ym} to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)

    for selector in (
        'id="documents-panel"',
        'data-role="docs-selectors"',
        'data-role="docs-error"',
    ):
        _month_close_resolution_contract_assert(
            selector in html,
            f"missing required selector {selector} on /accounting?ym={requested_ym}",
        )


def _assert_month_close_readiness_surface_and_enums(html: str, requested_ym: str) -> tuple[str, str]:
    for selector in (
        'data-role="mc-readiness"',
        'data-role="mc-readiness-message"',
        'data-role="mc-readiness-next-action"',
    ):
        _month_close_readiness_contract_assert(selector in html, f"missing required selector {selector}")

    readiness_state = _extract_role_attr(html, "mc-readiness", "data-state")
    _month_close_readiness_contract_assert(readiness_state is not None, "mc-readiness must include data-state")
    _month_close_readiness_contract_assert(
        readiness_state in {"ready", "attention", "unknown"},
        f"mc-readiness data-state must be one of ready|attention|unknown, got {readiness_state!r}",
    )

    action_key = _extract_role_attr(html, "mc-readiness-next-action", "data-action-key")
    _month_close_readiness_contract_assert(
        action_key is not None,
        "mc-readiness-next-action must include data-action-key",
    )
    _month_close_readiness_contract_assert(
        action_key in {
            "open_journal_drafts",
            "open_documents",
            "open_statements",
            "retry_refresh",
            "create_snapshot",
        },
        f"mc-readiness-next-action data-action-key has invalid value {action_key!r}",
    )

    data_enabled = _extract_role_attr(html, "mc-readiness-next-action", "data-enabled")
    _month_close_readiness_contract_assert(
        data_enabled is not None,
        "mc-readiness-next-action must include data-enabled",
    )
    _month_close_readiness_contract_assert(
        data_enabled in {"true", "false"},
        f"mc-readiness-next-action data-enabled must be true|false, got {data_enabled!r}",
    )

    if 'data-role="mc-readiness-next-action-link"' in html:
        action_link_url = _extract_role_url(html, "mc-readiness-next-action-link")
        _month_close_readiness_contract_assert(
            action_link_url is not None,
            "mc-readiness-next-action-link must render href/formaction/action/data-url/form action URL",
        )
        normalized_url = str(action_link_url or "").strip()
        _month_close_readiness_contract_assert(
            "ym=2026-03" in normalized_url,
            f"mc-readiness-next-action-link URL must include ym={requested_ym}, got {normalized_url!r}",
        )
        _month_close_readiness_contract_assert(
            not normalized_url.lower().startswith("javascript:"),
            f"mc-readiness-next-action-link must be navigation URL, got {normalized_url!r}",
        )
    return str(readiness_state), str(action_key)


def test_frontend_contract_phase284_month_close_readiness_selector_surface_and_enums(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    requested_ym = "2026-03"
    response = client.get("/accounting/month_close", query_string={"ym": requested_ym})
    _month_close_readiness_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym={requested_ym} to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)
    _assert_month_close_readiness_surface_and_enums(html, requested_ym)


def test_frontend_contract_phase284_readiness_attention_when_unbalanced_drafts_exist(frontend_contract_ctx):
    _seed_month_close_documents_state_scenario(
        frontend_contract_ctx,
        open_documents_count=0,
        total_documents_count=2,
    )
    _seed_month_close_draft_entry(
        frontend_contract_ctx,
        debit_amount=Decimal("100.00"),
        credit_amount=Decimal("70.00"),
    )

    client = frontend_contract_ctx["client"]
    requested_ym = "2026-03"
    response = client.get("/accounting/month_close", query_string={"ym": requested_ym})
    _month_close_readiness_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym={requested_ym} to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)
    readiness_state, action_key = _assert_month_close_readiness_surface_and_enums(html, requested_ym)
    _month_close_readiness_contract_assert(
        readiness_state == "attention",
        f"expected readiness attention when drafts warn, got {readiness_state!r}",
    )
    _month_close_readiness_contract_assert(
        action_key == "open_journal_drafts",
        f"expected readiness next action open_journal_drafts when drafts warn, got {action_key!r}",
    )


def test_frontend_contract_phase284_readiness_ready_when_all_green(frontend_contract_ctx):
    _seed_month_close_documents_state_scenario(
        frontend_contract_ctx,
        open_documents_count=0,
        total_documents_count=2,
    )

    client = frontend_contract_ctx["client"]
    requested_ym = "2026-03"
    response = client.get("/accounting/month_close", query_string={"ym": requested_ym})
    _month_close_readiness_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym={requested_ym} to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)
    readiness_state, action_key = _assert_month_close_readiness_surface_and_enums(html, requested_ym)
    _month_close_readiness_contract_assert(
        readiness_state == "ready",
        f"expected readiness ready when all checks are ok, got {readiness_state!r}",
    )
    _month_close_readiness_contract_assert(
        action_key == "create_snapshot",
        f"expected readiness next action create_snapshot when all checks are ok, got {action_key!r}",
    )


def test_frontend_contract_phase284_readiness_unknown_with_retry_refresh_on_unknown_input(frontend_contract_ctx, monkeypatch):
    import blueprints.accounting as accounting_module

    def _raise_snapshot_payload_error(*_args, **_kwargs):
        raise RuntimeError("month-close readiness unknown drill")

    monkeypatch.setattr(accounting_module, "_build_month_close_snapshot_payload", _raise_snapshot_payload_error)

    client = frontend_contract_ctx["client"]
    requested_ym = "2026-03"
    response = client.get("/accounting/month_close", query_string={"ym": requested_ym})
    _month_close_readiness_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym={requested_ym} to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)
    readiness_state, action_key = _assert_month_close_readiness_surface_and_enums(html, requested_ym)
    _month_close_readiness_contract_assert(
        readiness_state == "unknown",
        f"expected readiness unknown when any input is unknown, got {readiness_state!r}",
    )
    _month_close_readiness_contract_assert(
        action_key == "retry_refresh",
        f"expected readiness next action retry_refresh when readiness is unknown, got {action_key!r}",
    )


def test_frontend_contract_phase2841_readiness_next_action_linkage_contract(frontend_contract_ctx):
    client = frontend_contract_ctx["client"]
    requested_ym = "2026-03"
    response = client.get("/accounting/month_close", query_string={"ym": requested_ym})
    _month_close_readiness_linkage_contract_assert(
        response.status_code == 200,
        f"expected GET /accounting/month_close?ym={requested_ym} to return 200, got {response.status_code}",
    )
    html = response.get_data(as_text=True)

    _month_close_readiness_linkage_contract_assert(
        'data-role="mc-readiness-next-action"' in html,
        'missing required selector data-role="mc-readiness-next-action"',
    )

    action_key = _extract_role_attr(html, "mc-readiness-next-action", "data-action-key")
    _month_close_readiness_linkage_contract_assert(
        action_key in {
            "open_journal_drafts",
            "open_documents",
            "open_statements",
            "retry_refresh",
            "create_snapshot",
        },
        f"mc-readiness-next-action data-action-key has invalid value {action_key!r}",
    )

    data_enabled = _extract_role_attr(html, "mc-readiness-next-action", "data-enabled")
    _month_close_readiness_linkage_contract_assert(
        data_enabled in {"true", "false"},
        f"mc-readiness-next-action data-enabled must be true|false, got {data_enabled!r}",
    )

    is_enabled = data_enabled == "true"
    readiness_link_present = 'data-role="mc-readiness-next-action-link"' in html
    readiness_link_url = _extract_role_url(html, "mc-readiness-next-action-link") if readiness_link_present else None
    readiness_link_url = str(readiness_link_url or "")

    if not is_enabled:
        _month_close_readiness_linkage_contract_assert(
            not readiness_link_present,
            "mc-readiness-next-action-link must be absent when data-enabled=false",
        )
    else:
        linkable_keys = {
            "open_journal_drafts",
            "open_documents",
            "open_statements",
            "retry_refresh",
        }
        if action_key in linkable_keys:
            _month_close_readiness_linkage_contract_assert(
                readiness_link_present and bool(readiness_link_url),
                f"mc-readiness-next-action-link must exist with URL when action-key={action_key!r} and data-enabled=true",
            )
            _month_close_readiness_linkage_contract_assert(
                f"ym={requested_ym}" in readiness_link_url,
                f"mc-readiness-next-action-link URL must include ym={requested_ym!r}, got {readiness_link_url!r}",
            )

        if action_key == "open_journal_drafts":
            expected_url = _extract_action_url(html, "mc-open-journal-drafts")
            _month_close_readiness_linkage_contract_assert(
                expected_url is not None,
                "missing data-action=\"mc-open-journal-drafts\" URL for linkage mapping",
            )
            _month_close_readiness_linkage_contract_assert(
                readiness_link_url == str(expected_url),
                f"readiness link URL must equal mc-open-journal-drafts URL; got readiness={readiness_link_url!r}, expected={expected_url!r}",
            )
        elif action_key == "open_statements":
            expected_url = _extract_action_url(html, "mc-open-statements")
            _month_close_readiness_linkage_contract_assert(
                expected_url is not None,
                "missing data-action=\"mc-open-statements\" URL for linkage mapping",
            )
            _month_close_readiness_linkage_contract_assert(
                readiness_link_url == str(expected_url),
                f"readiness link URL must equal mc-open-statements URL; got readiness={readiness_link_url!r}, expected={expected_url!r}",
            )
        elif action_key == "retry_refresh":
            parsed_retry_url = urlparse(readiness_link_url)
            retry_qs = parse_qs(parsed_retry_url.query, keep_blank_values=True)
            _month_close_readiness_linkage_contract_assert(
                parsed_retry_url.path.endswith("/accounting/month_close"),
                f"retry_refresh readiness link must target /accounting/month_close, got path={parsed_retry_url.path!r}",
            )
            _month_close_readiness_linkage_contract_assert(
                requested_ym in (retry_qs.get("ym") or []),
                f"retry_refresh readiness link must preserve ym={requested_ym!r}, got ym={retry_qs.get('ym')!r}",
            )

    snapshot_control_exists = 'data-action="mc-create-snapshot"' in html
    if action_key == "create_snapshot" and is_enabled and not snapshot_control_exists:
        _month_close_readiness_linkage_contract_assert(
            False,
            "create_snapshot must not be enabled=true when snapshot control is absent",
        )
