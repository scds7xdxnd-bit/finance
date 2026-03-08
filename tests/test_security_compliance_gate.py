from __future__ import annotations

import datetime as dt
import os

import pytest
from finance_app import create_app, db
from helpers.security_compliance import (
    REQUIRED_EXCEPTION_COLUMNS,
    detect_exception_snapshot_drift,
    evaluate_security_compliance,
    load_exception_snapshot,
    load_exception_register,
    security_failure_message,
)


@pytest.fixture()
def app_ctx(tmp_path):
    db_path = tmp_path / "security_compliance_gate.db"
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


def test_security_exception_register_machine_parse_and_validation():
    rows = load_exception_register()
    assert rows, "SSOT 70.5 exception register should not be empty"

    expected_cols = set(REQUIRED_EXCEPTION_COLUMNS)
    for row in rows:
        row_cols = {
            "exception_id",
            "method",
            "path",
            "missing_controls",
            "required_end_state",
            "expires_on_utc",
            "status",
        }
        assert row_cols == expected_cols
        assert row.status in {"open", "closed"}
        assert row.expires_on_utc.isoformat() == str(row.expires_on_utc)


def test_security_exception_snapshot_drift_guard():
    rows = load_exception_register()
    snapshot = load_exception_snapshot()
    drift = detect_exception_snapshot_drift(rows, snapshot)
    assert drift["new_exception_ids"] == []
    assert drift["reopened_exception_ids"] == []
    assert drift["new_open_exception_ids"] == []

    mutated = {
        **snapshot,
        "exceptions": [
            entry
            for entry in (snapshot.get("exceptions") or [])
            if entry.get("exception_id") != "SEC-EX-010"
        ],
    }
    for entry in mutated["exceptions"]:
        if entry.get("exception_id") == "SEC-EX-001":
            entry["status"] = "closed"

    mutated_drift = detect_exception_snapshot_drift(rows, mutated)
    assert "SEC-EX-010" in mutated_drift["new_exception_ids"]
    assert "SEC-EX-010" in mutated_drift["new_open_exception_ids"]
    assert "SEC-EX-001" in mutated_drift["reopened_exception_ids"]


def test_security_compliance_gate_current_state(app_ctx):
    payload = evaluate_security_compliance(app_ctx)
    assert payload["ok"] is True, payload.get("message")
    assert payload["new_exception_ids"] == []
    assert payload["reopened_exception_ids"] == []
    assert payload["new_open_exception_ids"] == []
    assert payload["expired_exception_ids"] == []
    assert payload["missing_csrf_routes"] == []
    assert payload["missing_auth_routes"] == []
    assert payload["missing_scope_routes"] == []
    assert payload["method_safety_failures"] == []
    assert payload["forecast_fence_failures"] == []


def test_security_exception_expiry_simulated(app_ctx):
    payload = evaluate_security_compliance(app_ctx, today_utc=dt.date(2026, 6, 1))
    assert payload["ok"] is False
    assert payload["expired_exception_ids"], payload

    message = payload.get("message") or security_failure_message(payload)
    assert message.startswith("Security compliance gate failed:")
    assert "new_exception_ids" in message
    assert "reopened_exception_ids" in message
    assert "new_open_exception_ids" in message
    assert "expired_exception_ids" in message
    assert "missing_csrf_routes" in message
    assert "missing_auth_routes" in message
    assert "missing_scope_routes" in message
    assert "method_safety_failures" in message
    assert "forecast_fence_failures" in message
