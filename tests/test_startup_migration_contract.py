from __future__ import annotations

import sqlite3
from pathlib import Path

from finance_app import create_app, db
from helpers.startup_migration_contract import (
    FAILURE_PREFIX,
    add_mismatch,
    assert_error_code_in,
    assert_no_mismatches,
    assert_non_health_503_contract,
    cleanup_app,
    looks_like_auto_create_forbidden,
    make_mismatch_sets,
    probe_endpoint,
    resolve_head_and_parent_revision,
    run_alembic_upgrade,
    sqlite_url,
    startup_failure_message,
)


def _configure_env(
    monkeypatch,
    *,
    runtime_db_url: str,
    alembic_db_url: str,
    auto_create_schema: bool = False,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("FINANCE_DATABASE_URL", runtime_db_url)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", alembic_db_url)
    monkeypatch.setenv("AUTO_CREATE_SCHEMA", "true" if auto_create_schema else "false")


def _new_app_non_test(
    monkeypatch,
    *,
    runtime_db_url: str,
    alembic_db_url: str,
    auto_create_schema: bool = False,
):
    _configure_env(
        monkeypatch,
        runtime_db_url=runtime_db_url,
        alembic_db_url=alembic_db_url,
        auto_create_schema=auto_create_schema,
    )
    app = create_app()
    app.config["TESTING"] = False
    return app


def _touch_sqlite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()


def test_startup_contract_failure_message_contract():
    mismatch_sets = make_mismatch_sets()
    add_mismatch(mismatch_sets, "at_head_violation", "expected=ALEMBIC_NOT_AT_HEAD observed=<missing>")
    message = startup_failure_message(
        context={"drill": "format_contract"},
        mismatch_sets=mismatch_sets,
    )
    assert message.startswith(FAILURE_PREFIX)
    assert "missing_payload_keys=" in message
    assert "unexpected_ready_endpoint_status=" in message
    assert "at_head_violation=" in message
    assert "capability_violation=" in message
    assert "db_url_mismatch_violation=" in message
    assert "create_all_drift_violation=" in message


def test_startup_contract_empty_db_drill(tmp_path, monkeypatch):
    db_path = tmp_path / "startup_empty_unmigrated.db"
    _touch_sqlite(db_path)
    db_url = sqlite_url(db_path)

    app = _new_app_non_test(
        monkeypatch,
        runtime_db_url=db_url,
        alembic_db_url=db_url,
        auto_create_schema=False,
    )
    mismatch_sets = make_mismatch_sets()

    try:
        client = app.test_client()

        health_probe = probe_endpoint(client, "/healthz")
        if health_probe.status_code not in {200, 503}:
            add_mismatch(
                mismatch_sets,
                "unexpected_ready_endpoint_status",
                f"/healthz:status={health_probe.status_code}",
            )
        if health_probe.payload.get("ok") is not False:
            add_mismatch(
                mismatch_sets,
                "unexpected_ready_endpoint_status",
                f"/healthz:ok={health_probe.payload.get('ok')}",
            )
        if "required_action" not in health_probe.payload:
            add_mismatch(
                mismatch_sets,
                "missing_payload_keys",
                "/healthz:required_action",
            )

        for path in ("/login", "/transactions"):
            probe = probe_endpoint(client, path)
            assert_non_health_503_contract(
                path=path,
                probe=probe,
                mismatch_sets=mismatch_sets,
            )

        assert_no_mismatches(
            context={"drill": "empty_db", "runtime_db": str(db_path)},
            mismatch_sets=mismatch_sets,
        )
    finally:
        cleanup_app(app)


def test_startup_contract_db_url_mismatch_drill(tmp_path, monkeypatch):
    runtime_db_path = tmp_path / "startup_runtime.db"
    alembic_db_path = tmp_path / "startup_alembic.db"
    runtime_db_url = sqlite_url(runtime_db_path)
    alembic_db_url = sqlite_url(alembic_db_path)

    head_revision, _ = resolve_head_and_parent_revision()
    run_alembic_upgrade(db_url=runtime_db_url, target_revision=head_revision)
    run_alembic_upgrade(db_url=alembic_db_url, target_revision=head_revision)

    app = _new_app_non_test(
        monkeypatch,
        runtime_db_url=runtime_db_url,
        alembic_db_url=alembic_db_url,
        auto_create_schema=False,
    )
    mismatch_sets = make_mismatch_sets()

    try:
        assert app.config.get("TESTING") is False
        probe = probe_endpoint(app.test_client(), "/login")
        assert_non_health_503_contract(
            path="/login",
            probe=probe,
            mismatch_sets=mismatch_sets,
        )
        assert_error_code_in(
            path="/login",
            probe=probe,
            expected_error_codes={"DB_URL_MISMATCH"},
            mismatch_set_key="db_url_mismatch_violation",
            mismatch_sets=mismatch_sets,
        )

        assert_no_mismatches(
            context={
                "drill": "db_url_mismatch",
                "runtime_db": str(runtime_db_path),
                "alembic_db": str(alembic_db_path),
            },
            mismatch_sets=mismatch_sets,
        )
    finally:
        cleanup_app(app)


def test_startup_contract_at_head_enforcement_drill(tmp_path, monkeypatch):
    db_path = tmp_path / "startup_at_head_minus_one.db"
    db_url = sqlite_url(db_path)

    _, parent_revision = resolve_head_and_parent_revision()
    run_alembic_upgrade(db_url=db_url, target_revision=parent_revision)

    app = _new_app_non_test(
        monkeypatch,
        runtime_db_url=db_url,
        alembic_db_url=db_url,
        auto_create_schema=False,
    )
    mismatch_sets = make_mismatch_sets()

    try:
        probe = probe_endpoint(app.test_client(), "/login")
        assert_non_health_503_contract(
            path="/login",
            probe=probe,
            mismatch_sets=mismatch_sets,
        )
        assert_error_code_in(
            path="/login",
            probe=probe,
            expected_error_codes={"ALEMBIC_NOT_AT_HEAD"},
            mismatch_set_key="at_head_violation",
            mismatch_sets=mismatch_sets,
        )

        assert_no_mismatches(
            context={
                "drill": "at_head_enforcement",
                "runtime_db": str(db_path),
                "target_revision": parent_revision,
            },
            mismatch_sets=mismatch_sets,
        )
    finally:
        cleanup_app(app)


def test_startup_contract_capability_enforcement_drill(tmp_path, monkeypatch):
    db_path = tmp_path / "startup_missing_capability.db"
    db_url = sqlite_url(db_path)
    head_revision, _ = resolve_head_and_parent_revision()
    run_alembic_upgrade(db_url=db_url, target_revision=head_revision)

    # Deterministic capability drill: keep Alembic version at head, then remove one required capability artifact.
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("DROP TABLE IF EXISTS admin_action_audit")
        conn.commit()

    app = _new_app_non_test(
        monkeypatch,
        runtime_db_url=db_url,
        alembic_db_url=db_url,
        auto_create_schema=False,
    )
    mismatch_sets = make_mismatch_sets()

    try:
        probe = probe_endpoint(app.test_client(), "/transactions")
        assert_non_health_503_contract(
            path="/transactions",
            probe=probe,
            mismatch_sets=mismatch_sets,
        )
        assert_error_code_in(
            path="/transactions",
            probe=probe,
            expected_error_codes={"SCHEMA_CAPABILITY_MISSING", "SCHEMA_NOT_READY"},
            mismatch_set_key="capability_violation",
            mismatch_sets=mismatch_sets,
        )

        assert_no_mismatches(
            context={
                "drill": "capability_enforcement",
                "runtime_db": str(db_path),
                "dropped_artifact": "table:admin_action_audit",
            },
            mismatch_sets=mismatch_sets,
        )
    finally:
        cleanup_app(app)


def test_startup_contract_create_all_drift_check(tmp_path, monkeypatch):
    db_path = tmp_path / "startup_create_all_drift.db"
    db_url = sqlite_url(db_path)
    _touch_sqlite(db_path)
    _configure_env(
        monkeypatch,
        runtime_db_url=db_url,
        alembic_db_url=db_url,
        auto_create_schema=True,
    )
    mismatch_sets = make_mismatch_sets()
    create_all_called = {"value": False}
    app = None

    def _raise_if_called(*args, **kwargs):
        create_all_called["value"] = True
        raise RuntimeError("QA_CREATE_ALL_DRIFT_SENTINEL")

    monkeypatch.setattr(db, "create_all", _raise_if_called)

    try:
        app = create_app()
        app.config["TESTING"] = False
    except Exception as exc:
        if create_all_called["value"]:
            add_mismatch(
                mismatch_sets,
                "create_all_drift_violation",
                "db.create_all invoked in non-test runtime with AUTO_CREATE_SCHEMA=true",
            )
        elif not looks_like_auto_create_forbidden(exc):
            add_mismatch(
                mismatch_sets,
                "create_all_drift_violation",
                f"unexpected_exception={type(exc).__name__}:{exc}",
            )
    else:
        if create_all_called["value"]:
            add_mismatch(
                mismatch_sets,
                "create_all_drift_violation",
                "db.create_all invoked in non-test runtime with AUTO_CREATE_SCHEMA=true",
            )
    finally:
        if app is not None:
            cleanup_app(app)

    assert_no_mismatches(
        context={"drill": "create_all_drift_check", "runtime_db": str(db_path)},
        mismatch_sets=mismatch_sets,
    )
