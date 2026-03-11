from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
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
from finance_app.services.loan_group_service import create_group as loan_group_create
from helpers.contract_assertions import run_alembic_upgrade

DOCUMENTS_FAILURE_PREFIX = "Documents contract failed:"
KNOWN_YM = "2026-03"
ROUTE_RECEIVABLES_PDF = "/accounting/receivables/pdf"
ROUTE_PAYABLES_PDF = "/accounting/payables/pdf"
ROUTE_LOAN_RECEIPT_PDF = "/accounting/loan_receipt/pdf"


def _documents_assert(condition: bool, message: str) -> None:
    assert condition, f"{DOCUMENTS_FAILURE_PREFIX} {message}"


def _sqlite_url(db_path) -> str:
    return f"sqlite:///{db_path.resolve()}"


def _login(client, user_id: int, csrf_token: str = "documents-contract-csrf") -> str:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["csrf_token"] = csrf_token
    return csrf_token


def _seed_documents_data(user_id: int) -> dict[str, str]:
    receivable_cat = AccountCategory(user_id=user_id, name="Accounts Receivable", tb_group="asset")
    payable_cat = AccountCategory(user_id=user_id, name="Accounts Payable", tb_group="liability")
    revenue_cat = AccountCategory(user_id=user_id, name="Service Revenue", tb_group="income")
    expense_cat = AccountCategory(user_id=user_id, name="Operating Expense", tb_group="expense")
    db.session.add_all([receivable_cat, payable_cat, revenue_cat, expense_cat])
    db.session.flush()

    receivable_acc = Account(user_id=user_id, name="AR Trade", category_id=receivable_cat.id, currency_code="KRW", active=True)
    payable_acc = Account(user_id=user_id, name="AP Trade", category_id=payable_cat.id, currency_code="KRW", active=True)
    revenue_acc = Account(user_id=user_id, name="Revenue", category_id=revenue_cat.id, currency_code="KRW", active=True)
    expense_acc = Account(user_id=user_id, name="Expense", category_id=expense_cat.id, currency_code="KRW", active=True)
    db.session.add_all([receivable_acc, payable_acc, revenue_acc, expense_acc])
    db.session.flush()

    db.session.add(TrialBalanceSetting(user_id=user_id, initialized_on=dt.date(2026, 1, 1)))

    receivable_entry = JournalEntry(
        user_id=user_id,
        date="2026/03/10",
        date_parsed=dt.date(2026, 3, 10),
        description="Receivables PDF fixture row",
        posted_at=dt.datetime(2026, 3, 10, 10, 0, 0),
    )
    db.session.add(receivable_entry)
    db.session.flush()
    receivable_line = JournalLine(
        journal_id=receivable_entry.id,
        account_id=receivable_acc.id,
        dc="D",
        amount_base=Decimal("150.00"),
        line_no=1,
    )
    db.session.add(receivable_line)
    db.session.add(
        JournalLine(
            journal_id=receivable_entry.id,
            account_id=revenue_acc.id,
            dc="C",
            amount_base=Decimal("150.00"),
            line_no=2,
        )
    )

    payable_entry = JournalEntry(
        user_id=user_id,
        date="2026/03/11",
        date_parsed=dt.date(2026, 3, 11),
        description="Payables PDF fixture row",
        posted_at=dt.datetime(2026, 3, 11, 10, 0, 0),
    )
    db.session.add(payable_entry)
    db.session.flush()
    db.session.add(
        ReceivableTracker(
            user_id=user_id,
            journal_id=receivable_entry.id,
            journal_line_id=receivable_line.id,
            account_id=receivable_acc.id,
            category="receivable",
            contact_name="Fixture Counterparty",
            transaction_value=Decimal("150.00"),
            currency_code="KRW",
            amount_paid=Decimal("0.00"),
            remaining_amount=Decimal("150.00"),
            status="UNPAID",
        )
    )
    db.session.add(
        JournalLine(
            journal_id=payable_entry.id,
            account_id=expense_acc.id,
            dc="D",
            amount_base=Decimal("90.00"),
            line_no=1,
        )
    )
    db.session.add(
        JournalLine(
            journal_id=payable_entry.id,
            account_id=payable_acc.id,
            dc="C",
            amount_base=Decimal("90.00"),
            line_no=2,
        )
    )
    db.session.flush()

    loan_group = loan_group_create(
        user_id=user_id,
        name="Loan Receipt Fixture",
        direction="receivable",
        counterparty="Fixture Counterparty",
        currency="KRW",
        principal_amount=Decimal("150.00"),
        start_date=dt.date(2026, 3, 10),
        notes="documents contract fixture",
    )

    db.session.commit()
    return {
        "ym": KNOWN_YM,
        "loan_id": str(loan_group.id),
        "entry_id": str(receivable_entry.id),
    }


@pytest.fixture()
def documents_contract_ctx(tmp_path, monkeypatch):
    db_path = tmp_path / "documents_contract.db"
    db_url = _sqlite_url(db_path)

    monkeypatch.setenv("FINANCE_DATABASE_URL", db_url)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", db_url)
    monkeypatch.setenv("AUTO_CREATE_SCHEMA", "false")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    run_alembic_upgrade(db_url=db_url, target_revision="head")

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        user = User(
            username=f"documents_contract_{uuid4().hex[:10]}",
            password_hash="pw",
            email=f"documents_contract_{uuid4().hex[:8]}@example.com",
        )
        db.session.add(user)
        db.session.commit()
        user_id = int(user.id)
        seed = _seed_documents_data(user_id)

    client = app.test_client()
    csrf_token = _login(client, user_id)

    try:
        yield {
            "app": app,
            "client": client,
            "csrf_token": csrf_token,
            "user_id": user_id,
            **seed,
        }
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def _assert_non_pdf(response, *, endpoint: str) -> None:
    content_type = (response.headers.get("Content-Type") or "").lower()
    _documents_assert("application/pdf" not in content_type, f"{endpoint}: failure response must not be application/pdf")
    _documents_assert(not (response.data or b"").startswith(b"%PDF"), f"{endpoint}: failure response must not start with %PDF")


def _extract_filename(content_disposition: str) -> str:
    if not content_disposition:
        return ""
    filename_match = re.search(r'filename="?([^\";]+)"?', content_disposition, flags=re.IGNORECASE)
    if filename_match:
        return filename_match.group(1)
    filename_star_match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, flags=re.IGNORECASE)
    if filename_star_match:
        return filename_star_match.group(1)
    return ""


def _assert_pdf_success(response, *, endpoint: str, filename_pattern: str) -> None:
    _documents_assert(response.status_code == 200, f"{endpoint}: expected 200, got {response.status_code}")
    content_type = (response.headers.get("Content-Type") or "").lower()
    _documents_assert("application/pdf" in content_type, f"{endpoint}: expected application/pdf, got {content_type!r}")
    _documents_assert((response.data or b"").startswith(b"%PDF"), f"{endpoint}: body must start with %PDF")
    cd = response.headers.get("Content-Disposition") or ""
    _documents_assert(bool(cd), f"{endpoint}: missing Content-Disposition header")
    filename = _extract_filename(cd)
    _documents_assert(bool(filename), f"{endpoint}: unable to parse filename from Content-Disposition {cd!r}")
    _documents_assert(
        re.match(filename_pattern, filename) is not None,
        f"{endpoint}: filename {filename!r} does not match required pattern {filename_pattern!r}",
    )


def test_documents_contract_route_surface_exists(documents_contract_ctx):
    client = documents_contract_ctx["client"]
    ym = documents_contract_ctx["ym"]
    loan_id = documents_contract_ctx["loan_id"]

    checks = (
        (ROUTE_RECEIVABLES_PDF, {"ym": ym, "status": "all"}),
        (ROUTE_PAYABLES_PDF, {"ym": ym, "status": "all"}),
        (ROUTE_LOAN_RECEIPT_PDF, {"loan_id": loan_id, "ym": ym}),
    )
    for path, query in checks:
        resp = client.get(path, query_string=query)
        _documents_assert(
            resp.status_code in {200, 400, 401, 403, 503},
            f"{path}: route surface must exist (200/4xx/503), got {resp.status_code}",
        )


@pytest.mark.parametrize("path", [ROUTE_RECEIVABLES_PDF, ROUTE_PAYABLES_PDF])
def test_documents_contract_selector_parsing_invalid_ym_returns_400(documents_contract_ctx, path):
    client = documents_contract_ctx["client"]
    response = client.get(path, query_string={"ym": "2026-13", "status": "all"})
    _documents_assert(response.status_code == 400, f"{path}: invalid ym must return 400, got {response.status_code}")
    _assert_non_pdf(response, endpoint=f"GET {path} invalid ym")


@pytest.mark.parametrize("path", [ROUTE_RECEIVABLES_PDF, ROUTE_PAYABLES_PDF])
def test_documents_contract_selector_parsing_invalid_status_returns_400(documents_contract_ctx, path):
    client = documents_contract_ctx["client"]
    response = client.get(path, query_string={"ym": KNOWN_YM, "status": "pending"})
    _documents_assert(response.status_code == 400, f"{path}: invalid status must return 400, got {response.status_code}")
    _assert_non_pdf(response, endpoint=f"GET {path} invalid status")


@pytest.mark.parametrize("path", [ROUTE_RECEIVABLES_PDF, ROUTE_PAYABLES_PDF])
def test_documents_contract_selector_parsing_invalid_numeric_returns_400(documents_contract_ctx, path):
    client = documents_contract_ctx["client"]
    response = client.get(path, query_string={"ym": KNOWN_YM, "status": "all", "min_amount": "abc"})
    _documents_assert(response.status_code == 400, f"{path}: invalid numeric selector must return 400, got {response.status_code}")
    _assert_non_pdf(response, endpoint=f"GET {path} invalid numeric")


@pytest.mark.parametrize("path", [ROUTE_RECEIVABLES_PDF, ROUTE_PAYABLES_PDF])
def test_documents_contract_selector_parsing_min_gt_max_returns_400(documents_contract_ctx, path):
    client = documents_contract_ctx["client"]
    response = client.get(path, query_string={"ym": KNOWN_YM, "status": "all", "min_amount": "100", "max_amount": "10"})
    _documents_assert(response.status_code == 400, f"{path}: min_amount > max_amount must return 400, got {response.status_code}")
    _assert_non_pdf(response, endpoint=f"GET {path} min>max")


def test_documents_contract_loan_receipt_both_ids_returns_400(documents_contract_ctx):
    client = documents_contract_ctx["client"]
    response = client.get(
        ROUTE_LOAN_RECEIPT_PDF,
        query_string={"loan_id": documents_contract_ctx["loan_id"], "entry_id": documents_contract_ctx["entry_id"], "ym": KNOWN_YM},
    )
    _documents_assert(response.status_code == 400, f"{ROUTE_LOAN_RECEIPT_PDF}: both loan_id and entry_id must return 400, got {response.status_code}")
    _assert_non_pdf(response, endpoint=f"GET {ROUTE_LOAN_RECEIPT_PDF} both ids")


def test_documents_contract_loan_receipt_neither_id_returns_400(documents_contract_ctx):
    client = documents_contract_ctx["client"]
    response = client.get(ROUTE_LOAN_RECEIPT_PDF, query_string={"ym": KNOWN_YM})
    _documents_assert(response.status_code == 400, f"{ROUTE_LOAN_RECEIPT_PDF}: missing both loan_id and entry_id must return 400, got {response.status_code}")
    _assert_non_pdf(response, endpoint=f"GET {ROUTE_LOAN_RECEIPT_PDF} missing ids")


@pytest.mark.parametrize(
    ("path", "query", "filename_pattern"),
    [
        (ROUTE_RECEIVABLES_PDF, {"ym": KNOWN_YM, "status": "all"}, r"^receivables_2026-03_all.*\.pdf$"),
        (ROUTE_PAYABLES_PDF, {"ym": KNOWN_YM, "status": "all"}, r"^payables_2026-03_all.*\.pdf$"),
    ],
)
def test_documents_contract_success_pdf_receivables_payables(documents_contract_ctx, path, query, filename_pattern):
    client = documents_contract_ctx["client"]
    response = client.get(path, query_string=query)
    _assert_pdf_success(response, endpoint=f"GET {path}", filename_pattern=filename_pattern)


def test_documents_contract_success_pdf_loan_receipt(documents_contract_ctx):
    client = documents_contract_ctx["client"]
    response = client.get(
        ROUTE_LOAN_RECEIPT_PDF,
        query_string={"loan_id": documents_contract_ctx["loan_id"], "ym": KNOWN_YM},
    )
    _assert_pdf_success(
        response,
        endpoint=f"GET {ROUTE_LOAN_RECEIPT_PDF}",
        filename_pattern=r"^loan_receipt_[^/\\]+\.pdf$",
    )


def test_documents_contract_success_pdf_loan_receipt_entry_selector(documents_contract_ctx):
    client = documents_contract_ctx["client"]
    response = client.get(
        ROUTE_LOAN_RECEIPT_PDF,
        query_string={"entry_id": documents_contract_ctx["entry_id"], "ym": KNOWN_YM},
    )
    _assert_pdf_success(
        response,
        endpoint=f"GET {ROUTE_LOAN_RECEIPT_PDF} entry_id",
        filename_pattern=r"^loan_receipt_entry_[0-9]+\.pdf$",
    )


def test_documents_contract_schema_not_ready_returns_503_non_pdf(documents_contract_ctx, monkeypatch):
    import blueprints.accounting as accounting_module

    client = documents_contract_ctx["client"]

    def _fake_schema_not_ready(_required_caps, *, user_id=None):
        del user_id
        return (
            False,
            {
                "ok": False,
                "error_code": "SCHEMA_NOT_READY",
                "error": "schema not ready (simulated)",
                "message": "schema not ready (simulated)",
                "required_action": "run migrations",
            },
            503,
        )

    monkeypatch.setattr(accounting_module, "_guard_schema_caps", _fake_schema_not_ready)

    checks = (
        (ROUTE_RECEIVABLES_PDF, {"ym": KNOWN_YM, "status": "all"}),
        (ROUTE_PAYABLES_PDF, {"ym": KNOWN_YM, "status": "all"}),
        (ROUTE_LOAN_RECEIPT_PDF, {"loan_id": documents_contract_ctx["loan_id"], "ym": KNOWN_YM}),
    )
    for path, query in checks:
        response = client.get(path, query_string=query)
        _documents_assert(response.status_code == 503, f"{path}: schema_not_ready simulation must return 503, got {response.status_code}")
        _assert_non_pdf(response, endpoint=f"GET {path}")


def test_documents_contract_missing_target_returns_404_non_pdf(documents_contract_ctx):
    client = documents_contract_ctx["client"]
    response = client.get(
        ROUTE_LOAN_RECEIPT_PDF,
        query_string={"loan_id": str(uuid4()), "ym": KNOWN_YM},
    )
    _documents_assert(response.status_code == 404, f"{ROUTE_LOAN_RECEIPT_PDF}: missing target must return 404, got {response.status_code}")
    _assert_non_pdf(response, endpoint=f"GET {ROUTE_LOAN_RECEIPT_PDF} missing target")


def test_documents_contract_auth_or_forbidden_is_non_pdf(documents_contract_ctx):
    app = documents_contract_ctx["app"]
    anonymous_client = app.test_client()

    checks = (
        (ROUTE_RECEIVABLES_PDF, {"ym": KNOWN_YM, "status": "all"}),
        (ROUTE_PAYABLES_PDF, {"ym": KNOWN_YM, "status": "all"}),
        (ROUTE_LOAN_RECEIPT_PDF, {"loan_id": documents_contract_ctx["loan_id"], "ym": KNOWN_YM}),
    )
    for path, query in checks:
        response = anonymous_client.get(path, query_string=query)
        _documents_assert(
            response.status_code in {401, 403},
            f"{path}: unauth/forbidden must return 401/403, got {response.status_code}",
        )
        _assert_non_pdf(response, endpoint=f"GET {path} anonymous")
