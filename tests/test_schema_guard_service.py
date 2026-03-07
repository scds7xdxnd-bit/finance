from __future__ import annotations

import datetime as dt
import os

import pytest
from finance_app import create_app, db
from finance_app.services.schema_guard_service import (
    capability_report,
    guard_capabilities,
    validate_schema_guard_bypass,
)
from sqlalchemy.engine.url import make_url


@pytest.fixture()
def app_ctx(tmp_path):
    db_path = tmp_path / "schema_guard.db"
    old_db_url = os.environ.get("FINANCE_DATABASE_URL")
    os.environ["FINANCE_DATABASE_URL"] = f"sqlite:///{db_path}"
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
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


def test_capability_report_has_expected_keys(app_ctx):
    with app_ctx.app_context():
        report = capability_report()
        assert "capabilities" in report
        caps = report["capabilities"]
        for key in ("tx_linking", "link_candidates", "csv_idempotency", "tb_snapshot", "admin_audit", "journal_report_perf"):
            assert key in caps

        ok, _, status = guard_capabilities(
            ["csv_idempotency", "tb_snapshot", "admin_audit", "journal_report_perf"],
            enforce=True,
        )
        assert ok is True
        assert status == 200


def test_validate_schema_guard_bypass_requires_reason_and_until():
    ok, payload = validate_schema_guard_bypass(
        {
            "SCHEMA_GUARD_ENFORCE": False,
            "SCHEMA_GUARD_BYPASS_REASON": "",
            "SCHEMA_GUARD_BYPASS_UNTIL": "",
        }
    )
    assert ok is False
    assert "SCHEMA_GUARD_BYPASS_REASON" in payload.get("error", "")


def test_validate_schema_guard_bypass_rejects_expired_or_long_window():
    now = dt.datetime.now(dt.timezone.utc)
    expired = (now - dt.timedelta(minutes=1)).isoformat()
    too_long = (now + dt.timedelta(days=8)).isoformat()

    ok_expired, payload_expired = validate_schema_guard_bypass(
        {
            "SCHEMA_GUARD_ENFORCE": False,
            "SCHEMA_GUARD_BYPASS_REASON": "runbook-approved",
            "SCHEMA_GUARD_BYPASS_UNTIL": expired,
        }
    )
    assert ok_expired is False
    assert "expired" in payload_expired.get("error", "").lower()

    ok_long, payload_long = validate_schema_guard_bypass(
        {
            "SCHEMA_GUARD_ENFORCE": False,
            "SCHEMA_GUARD_BYPASS_REASON": "runbook-approved",
            "SCHEMA_GUARD_BYPASS_UNTIL": too_long,
        }
    )
    assert ok_long is False
    assert "7-day" in payload_long.get("error", "")


def test_validate_schema_guard_bypass_accepts_active_window():
    now = dt.datetime.now(dt.timezone.utc)
    until = (now + dt.timedelta(hours=2)).isoformat()
    ok, payload = validate_schema_guard_bypass(
        {
            "SCHEMA_GUARD_ENFORCE": False,
            "SCHEMA_GUARD_BYPASS_REASON": "incident-1234",
            "SCHEMA_GUARD_BYPASS_UNTIL": until,
        }
    )
    assert ok is True
    assert payload.get("enforce") is False
    assert payload.get("reason") == "incident-1234"


def test_create_app_uses_database_url_fallback(monkeypatch, tmp_path):
    db_path = tmp_path / "legacy_env.db"
    monkeypatch.delenv("FINANCE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    app = create_app()
    parsed = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
    assert parsed.drivername == "sqlite"
    assert parsed.database == str(db_path)
