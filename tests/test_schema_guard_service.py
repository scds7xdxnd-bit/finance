from __future__ import annotations

import os

import pytest
from finance_app import create_app, db
from finance_app.services.schema_guard_service import capability_report, guard_capabilities


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
