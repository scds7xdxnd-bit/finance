from __future__ import annotations

import datetime as dt
import io
import os
import time

import pytest
from finance_app import User, create_app, db
from finance_app.models.accounting_models import AdminActionAudit, JournalEntry, Transaction
from finance_app.models.money_account import AccountType
from finance_app.models.money_account import MoneyScheduleAccount as Account
from helpers.security_compliance import (
    has_active_exception,
    load_exception_register,
    probe_forecast_option_a,
    probe_logout_method_safety,
)


@pytest.fixture()
def app_ctx(tmp_path):
    db_path = tmp_path / "security_routes.db"
    old_db_url = os.environ.get("FINANCE_DATABASE_URL")
    os.environ["FINANCE_DATABASE_URL"] = f"sqlite:///{db_path}"
    app = create_app()
    app.config["TESTING"] = True
    app.config["SCHEMA_GUARD_ENFORCE"] = True
    with app.app_context():
        db.create_all()
        try:
            yield app
        finally:
            db.session.remove()
            db.drop_all()
            if old_db_url is None:
                os.environ.pop("FINANCE_DATABASE_URL", None)
            else:
                os.environ["FINANCE_DATABASE_URL"] = old_db_url


def _login(client, user_id: int, csrf_token: str = "csrf-token") -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["csrf_token"] = csrf_token


def _confirm_at_ms(seconds_ago: int = 6) -> str:
    return str(int(time.time() * 1000) - (seconds_ago * 1000))


def test_upload_csv_requires_csrf(app_ctx):
    # SSOT 70 (Non-Negotiable): state-changing routes must enforce CSRF.
    app = app_ctx
    client = app.test_client()
    with app.app_context():
        user = User(username="csv_user", password_hash="pw")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    _login(client, user_id)

    resp = client.post(
        "/upload_csv",
        data={"csv_file": (io.BytesIO(b"date,description\n"), "sample.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "CSRF token missing or invalid" in resp.get_data(as_text=True)


def test_upload_csv_schema_guard_hard_fails(app_ctx, monkeypatch):
    # SSOT 60/70: guarded sensitive endpoints must hard-fail on missing capabilities.
    app = app_ctx
    client = app.test_client()
    with app.app_context():
        user = User(username="guard_user", password_hash="pw")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    _login(client, user_id)

    import blueprints.transactions as tx_module

    monkeypatch.setattr(
        tx_module,
        "guard_capabilities",
        lambda *_args, **_kwargs: (
            False,
            {
                "ok": False,
                "error": "Schema capability requirements not met",
                "missing_capabilities": ["csv_idempotency"],
            },
            503,
        ),
    )

    resp = client.post(
        "/upload_csv",
        data={"csv_file": (io.BytesIO(b"date,description\n"), "sample.csv")},
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": "csrf-token"},
    )
    assert resp.status_code == 503
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "csv_idempotency" in payload.get("missing_capabilities", [])


def test_transactions_delete_enforces_csrf_and_scope(app_ctx):
    # SSOT 70: CSRF required + cross-user mutation forbidden.
    app = app_ctx
    with app.app_context():
        owner = User(username="owner", password_hash="pw")
        other = User(username="other", password_hash="pw")
        db.session.add_all([owner, other])
        db.session.flush()
        tx = Transaction(
            user_id=owner.id,
            date="2026/03/01",
            description="scope-marker",
            debit_account="Cash",
            debit_amount=10.0,
            credit_account="Revenue",
            credit_amount=10.0,
        )
        db.session.add(tx)
        db.session.commit()
        owner_id = owner.id
        other_id = other.id
        tx_id = tx.id

    other_client = app.test_client()
    _login(other_client, other_id, csrf_token="other-csrf")

    missing_csrf = other_client.post(f"/transactions/delete/{tx_id}", follow_redirects=False)
    assert missing_csrf.status_code == 400

    cross_user = other_client.post(
        f"/transactions/delete/{tx_id}",
        follow_redirects=False,
        headers={"X-CSRF-Token": "other-csrf"},
    )
    assert cross_user.status_code in (302, 401, 403)
    with app.app_context():
        assert db.session.get(Transaction, tx_id) is not None

    owner_client = app.test_client()
    _login(owner_client, owner_id, csrf_token="owner-csrf")
    owner_delete = owner_client.post(
        f"/transactions/delete/{tx_id}",
        follow_redirects=False,
        headers={"X-CSRF-Token": "owner-csrf"},
    )
    assert owner_delete.status_code in (302, 200)
    with app.app_context():
        assert db.session.get(Transaction, tx_id) is None


def test_admin_delete_requires_admin_and_writes_audit(app_ctx):
    # SSOT 70: admin mutation routes require admin auth and audit logging.
    app = app_ctx
    with app.app_context():
        admin = User(username="sec_admin", password_hash="pw", is_admin=True)
        non_admin = User(username="sec_user", password_hash="pw", is_admin=False)
        target = User(username="victim_user", password_hash="pw", is_admin=False)
        db.session.add_all([admin, non_admin, target])
        db.session.commit()
        admin_id = admin.id
        non_admin_id = non_admin.id
        target_id = target.id
        target_username = target.username

    payload = {
        "confirm_action": "delete_user",
        "confirm_at_ms": _confirm_at_ms(),
        "confirm_username": target_username,
    }

    non_admin_client = app.test_client()
    _login(non_admin_client, non_admin_id, csrf_token="user-csrf")
    forbidden = non_admin_client.post(
        f"/admin/delete/{target_id}",
        data=payload,
        follow_redirects=False,
        headers={"X-CSRF-Token": "user-csrf"},
    )
    assert forbidden.status_code in (302, 401, 403)
    with app.app_context():
        assert db.session.get(User, target_id) is not None

    admin_client = app.test_client()
    _login(admin_client, admin_id, csrf_token="admin-csrf")
    allowed = admin_client.post(
        f"/admin/delete/{target_id}",
        data=payload,
        follow_redirects=False,
        headers={"X-CSRF-Token": "admin-csrf"},
    )
    assert allowed.status_code in (302, 200)
    with app.app_context():
        assert db.session.get(User, target_id) is None
        audit = (
            AdminActionAudit.query.filter_by(
                actor_user_id=admin_id,
                action="delete_user",
                target_id=str(target_id),
                status="ok",
            )
            .order_by(AdminActionAudit.created_at.desc())
            .first()
        )
        assert audit is not None


def test_admin_delete_requires_csrf(app_ctx):
    # SSOT 70 (Non-Negotiable): admin mutation routes must enforce CSRF.
    app = app_ctx
    with app.app_context():
        admin = User(username="csrf_admin", password_hash="pw", is_admin=True)
        target = User(username="csrf_target", password_hash="pw", is_admin=False)
        db.session.add_all([admin, target])
        db.session.commit()
        admin_id = admin.id
        target_id = target.id
        target_username = target.username

    client = app.test_client()
    _login(client, admin_id, csrf_token="admin-csrf")
    resp = client.post(
        f"/admin/delete/{target_id}",
        data={
            "confirm_action": "delete_user",
            "confirm_at_ms": _confirm_at_ms(),
            "confirm_username": target_username,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "CSRF token missing or invalid" in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(User, target_id) is not None


def test_tb_reset_requires_admin(app_ctx):
    # SSOT 70 class-A route guard: admin required for TB reset.
    app = app_ctx
    client = app.test_client()
    with app.app_context():
        user = User(username="tb_user", password_hash="pw", is_admin=False)
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    _login(client, user_id)

    resp = client.post(
        "/accounting/tb/reset",
        json={
            "confirm_phrase": "RESET TB",
            "confirm_at_ms": _confirm_at_ms(),
            "reason": "test",
        },
        headers={"X-CSRF-Token": "csrf-token"},
    )
    assert resp.status_code == 403


def test_journal_delete_enforces_csrf_and_scope(app_ctx, monkeypatch):
    # SSOT 70 class-B route: journal deletion must enforce CSRF and owner scope.
    app = app_ctx
    import blueprints.accounting as accounting_module

    monkeypatch.setattr(
        accounting_module,
        "_guard_schema_caps",
        lambda *_args, **_kwargs: (True, {"ok": True}, 200),
    )
    with app.app_context():
        owner = User(username="journal_owner", password_hash="pw")
        other = User(username="journal_other", password_hash="pw")
        db.session.add_all([owner, other])
        db.session.flush()
        entry = JournalEntry(
            user_id=owner.id,
            date="2026/03/01",
            description="journal-scope-marker",
        )
        db.session.add(entry)
        db.session.commit()
        owner_id = owner.id
        other_id = other.id
        entry_id = entry.id

    other_client = app.test_client()
    _login(other_client, other_id, csrf_token="other-csrf")
    missing_csrf = other_client.post(f"/accounting/journal/delete/{entry_id}")
    assert missing_csrf.status_code == 400

    cross_user = other_client.post(
        f"/accounting/journal/delete/{entry_id}",
        headers={"X-CSRF-Token": "other-csrf"},
    )
    assert cross_user.status_code in (401, 403)
    with app.app_context():
        assert db.session.get(JournalEntry, entry_id) is not None

    owner_client = app.test_client()
    _login(owner_client, owner_id, csrf_token="owner-csrf")
    owner_delete = owner_client.post(
        f"/accounting/journal/delete/{entry_id}",
        headers={"X-CSRF-Token": "owner-csrf"},
    )
    assert owner_delete.status_code == 200
    payload = owner_delete.get_json()
    assert payload and payload.get("ok") is True
    with app.app_context():
        assert db.session.get(JournalEntry, entry_id) is None


def test_tb_reset_schema_guard_hard_fails(app_ctx, monkeypatch):
    # SSOT 60 hard-fail map: /accounting/tb/reset requires tb_snapshot + admin_audit.
    app = app_ctx
    with app.app_context():
        admin = User(username="tb_guard_admin", password_hash="pw", is_admin=True)
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    import blueprints.accounting as accounting_module

    monkeypatch.setattr(
        accounting_module,
        "guard_capabilities",
        lambda *_args, **_kwargs: (
            False,
            {
                "ok": False,
                "error": "Schema capability requirements not met",
                "missing_capabilities": ["tb_snapshot", "admin_audit"],
            },
            503,
        ),
    )

    client = app.test_client()
    _login(client, admin_id, csrf_token="admin-csrf")
    resp = client.post(
        "/accounting/tb/reset",
        json={
            "confirm_phrase": "RESET TB",
            "confirm_at_ms": _confirm_at_ms(),
            "reason": "schema guard probe",
        },
        headers={"X-CSRF-Token": "admin-csrf"},
    )
    assert resp.status_code == 503
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "tb_snapshot" in payload.get("missing_capabilities", [])
    assert "admin_audit" in payload.get("missing_capabilities", [])


def test_admin_mutation_schema_guard_hard_fails(app_ctx, monkeypatch):
    # SSOT 60/70: admin mutation routes hard-fail when admin_audit capability is missing.
    app = app_ctx
    with app.app_context():
        admin = User(username="guard_admin", password_hash="pw", is_admin=True)
        target = User(username="guard_target", password_hash="pw", is_admin=False)
        db.session.add_all([admin, target])
        db.session.commit()
        admin_id = admin.id
        target_id = target.id

    import blueprints.admin as admin_module

    monkeypatch.setattr(
        admin_module,
        "guard_capabilities",
        lambda *_args, **_kwargs: (
            False,
            {
                "ok": False,
                "error": "Schema capability requirements not met",
                "missing_capabilities": ["admin_audit"],
            },
            503,
        ),
    )

    client = app.test_client()
    _login(client, admin_id, csrf_token="admin-csrf")
    resp = client.post(
        f"/admin/grant/{target_id}",
        data={
            "confirm_action": "grant_admin",
            "confirm_at_ms": _confirm_at_ms(),
        },
        headers={"X-CSRF-Token": "admin-csrf"},
    )
    assert resp.status_code == 503
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "admin_audit" in payload.get("missing_capabilities", [])


def test_logout_method_safety_or_active_exception_contract(app_ctx):
    # SSOT 70.5 / 70.6 transition contract:
    # unsafe GET /logout is allowed only while active unexpired exception exists.
    app = app_ctx
    rows = load_exception_register()
    today = dt.datetime.now(dt.timezone.utc).date()
    probe = probe_logout_method_safety(app)

    if probe.get("get_logs_out_without_csrf"):
        assert has_active_exception(
            rows,
            method="GET",
            path="/logout",
            control="method_safety",
            today_utc=today,
        ), probe
    else:
        assert int(probe.get("get_status_code") or 0) in (400, 401, 403, 405), probe


def test_forecast_option_a_or_active_exception_contract(app_ctx):
    # SSOT 70.6 Option A probes run in both modes.
    # During transition, failures are allowed only when covered by active unexpired exceptions.
    app = app_ctx
    rows = load_exception_register()
    today = dt.datetime.now(dt.timezone.utc).date()
    violations = probe_forecast_option_a(app)
    uncovered = [
        violation
        for violation in violations
        if not has_active_exception(
            rows,
            method=str(violation["method"]),
            path=str(violation["path"]),
            control=str(violation["control"]),
            today_utc=today,
        )
    ]
    assert not uncovered, uncovered


def test_forecast_schedule_audit_outcome_messages(app_ctx, monkeypatch):
    app = app_ctx
    app.config["FORECAST_LEGACY_ENABLED"] = True

    with app.app_context():
        admin = User(username="forecast_audit_admin", password_hash="pw", is_admin=True)
        account = Account(
            name="Forecast Audit Account",
            type=AccountType.CHECKING,
            currency="KRW",
            current_balance=0,
            is_included_in_closing=True,
        )
        db.session.add_all([admin, account])
        db.session.commit()
        admin_id = int(admin.id)
        account_id = int(account.id)

    client = app.test_client()
    _login(client, admin_id, csrf_token="forecast-admin-csrf")

    schedule_form = {
        "description": "audit-probe",
        "amount": "100",
        "date": dt.date.today().isoformat(),
        "account_id": str(account_id),
        "currency": "KRW",
    }

    import routes.forecast as forecast_module

    monkeypatch.setattr(
        forecast_module,
        "guard_capabilities",
        lambda *_args, **_kwargs: (
            False,
            {
                "ok": False,
                "error": "Schema capability requirements not met",
                "missing_capabilities": ["admin_audit"],
            },
            503,
        ),
    )

    blocked = client.post(
        "/forecast/schedule",
        data=schedule_form,
        headers={"X-CSRF-Token": "forecast-admin-csrf"},
        follow_redirects=False,
    )
    assert blocked.status_code == 503
    with app.app_context():
        blocked_audit = (
            AdminActionAudit.query.filter_by(actor_user_id=admin_id, action="forecast_schedule:blocked_guard")
            .order_by(AdminActionAudit.created_at.desc())
            .first()
        )
        assert blocked_audit is not None

    monkeypatch.setattr(
        forecast_module,
        "guard_capabilities",
        lambda *_args, **_kwargs: (True, {"ok": True}, 200),
    )

    success = client.post(
        "/forecast/schedule",
        data=schedule_form,
        headers={"X-CSRF-Token": "forecast-admin-csrf"},
        follow_redirects=False,
    )
    assert success.status_code in (302, 303)
    with app.app_context():
        success_audit = (
            AdminActionAudit.query.filter_by(actor_user_id=admin_id, action="forecast_schedule:success")
            .order_by(AdminActionAudit.created_at.desc())
            .first()
        )
        assert success_audit is not None
