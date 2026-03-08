from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

from finance_app import create_app, db

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = ROOT / "alembic.ini"
FAILURE_PREFIX = "Startup/migration contract failed:"
REQUIRED_503_PAYLOAD_KEYS = ("ok", "error_code", "message", "required_action")
MISMATCH_SET_KEYS = (
    "missing_payload_keys",
    "unexpected_ready_endpoint_status",
    "at_head_violation",
    "capability_violation",
    "db_url_mismatch_violation",
    "create_all_drift_violation",
)


@dataclass
class StartupContractProbe:
    status_code: int
    payload: dict[str, Any]
    body_preview: str


def sqlite_url(db_path: Path) -> str:
    return f"sqlite:///{db_path.resolve()}"


def run_alembic_upgrade(*, db_url: str, target_revision: str) -> None:
    env = dict(os.environ)
    env["ALEMBIC_DATABASE_URL"] = db_url
    completed = subprocess.run(
        ["alembic", "upgrade", target_revision],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Failed to run Alembic upgrade.\n"
            f"target_revision={target_revision}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


def resolve_head_and_parent_revision() -> tuple[str, str]:
    config = Config(str(ALEMBIC_INI_PATH))
    script = ScriptDirectory.from_config(config)
    heads = list(script.get_heads())
    if len(heads) != 1:
        raise RuntimeError(f"Expected exactly one Alembic head revision, observed={heads}")
    head = heads[0]
    revision = script.get_revision(head)
    if revision is None:
        raise RuntimeError(f"Unable to resolve Alembic head revision metadata for head={head}")
    down_revision = revision.down_revision
    if isinstance(down_revision, tuple):
        parent = str(down_revision[0]) if down_revision else ""
    else:
        parent = str(down_revision or "")
    if not parent:
        raise RuntimeError(f"Unable to resolve head-1 revision for head={head}")
    return head, parent


def make_mismatch_sets() -> dict[str, list[str]]:
    return {key: [] for key in MISMATCH_SET_KEYS}


def add_mismatch(mismatch_sets: dict[str, list[str]], key: str, value: str) -> None:
    if key not in mismatch_sets:
        raise KeyError(f"Unknown mismatch set: {key}")
    mismatch_sets[key].append(str(value))


def startup_failure_message(
    *,
    context: dict[str, Any],
    mismatch_sets: dict[str, list[str]],
) -> str:
    normalized = {
        key: sorted(set(mismatch_sets.get(key) or []))
        for key in MISMATCH_SET_KEYS
    }
    return (
        f"{FAILURE_PREFIX} "
        f"context={context} "
        f"missing_payload_keys={normalized['missing_payload_keys']} "
        f"unexpected_ready_endpoint_status={normalized['unexpected_ready_endpoint_status']} "
        f"at_head_violation={normalized['at_head_violation']} "
        f"capability_violation={normalized['capability_violation']} "
        f"db_url_mismatch_violation={normalized['db_url_mismatch_violation']} "
        f"create_all_drift_violation={normalized['create_all_drift_violation']}"
    )


def assert_no_mismatches(
    *,
    context: dict[str, Any],
    mismatch_sets: dict[str, list[str]],
) -> None:
    has_any = any(bool(mismatch_sets.get(key)) for key in MISMATCH_SET_KEYS)
    if has_any:
        raise AssertionError(startup_failure_message(context=context, mismatch_sets=mismatch_sets))


def create_isolated_app(
    *,
    runtime_db_url: str,
    alembic_db_url: str,
    auto_create_schema: bool = False,
) -> Any:
    os.environ["FINANCE_DATABASE_URL"] = runtime_db_url
    os.environ["ALEMBIC_DATABASE_URL"] = alembic_db_url
    os.environ["AUTO_CREATE_SCHEMA"] = "true" if auto_create_schema else "false"
    app = create_app()
    app.config["TESTING"] = False
    return app


def probe_endpoint(client, path: str) -> StartupContractProbe:
    response = client.get(path)
    payload = response.get_json(silent=True) or {}
    preview = response.get_data(as_text=True)[:200]
    return StartupContractProbe(
        status_code=int(response.status_code),
        payload=payload if isinstance(payload, dict) else {},
        body_preview=preview,
    )


def required_payload_keys_missing(payload: dict[str, Any]) -> list[str]:
    missing = []
    for key in REQUIRED_503_PAYLOAD_KEYS:
        if key not in payload:
            missing.append(key)
    if payload.get("ok") is not False:
        missing.append("ok=false")
    return missing


def assert_non_health_503_contract(
    *,
    path: str,
    probe: StartupContractProbe,
    mismatch_sets: dict[str, list[str]],
) -> None:
    if probe.status_code != 503:
        add_mismatch(
            mismatch_sets,
            "unexpected_ready_endpoint_status",
            f"{path}:status={probe.status_code}",
        )

    for missing_key in required_payload_keys_missing(probe.payload):
        add_mismatch(
            mismatch_sets,
            "missing_payload_keys",
            f"{path}:{missing_key}",
        )


def assert_error_code_in(
    *,
    path: str,
    probe: StartupContractProbe,
    expected_error_codes: set[str],
    mismatch_set_key: str,
    mismatch_sets: dict[str, list[str]],
) -> None:
    observed = str(probe.payload.get("error_code") or "")
    if observed not in expected_error_codes:
        add_mismatch(
            mismatch_sets,
            mismatch_set_key,
            f"{path}:error_code={observed or '<missing>'};expected={sorted(expected_error_codes)}",
        )


def looks_like_auto_create_forbidden(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "auto_create_schema" in text and any(
        token in text for token in ("forbidden", "not allowed", "disabled", "deny")
    )


def cleanup_app(app: Any) -> None:
    with app.app_context():
        db.session.remove()
        try:
            db.engine.dispose()
        except Exception:
            pass
