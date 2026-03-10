from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FAILURE_PREFIX = "DB integrity gate failed:"
MISMATCH_SET_KEYS = (
    "missing_journal_integrity_capability",
    "missing_dc_constraint",
    "invalid_dc_insert_not_rejected",
    "unbalanced_finalize_not_rejected",
    "preexisting_invalid_rows_detected",
    "verifier_parity_missing_artifacts",
)


def sqlite_url(db_path: Path) -> str:
    return f"sqlite:///{db_path.resolve()}"


def run_alembic_upgrade(*, db_url: str, target_revision: str = "head") -> None:
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
            "Alembic upgrade failed.\n"
            f"target_revision={target_revision}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


def make_mismatch_sets() -> dict[str, list[str]]:
    return {key: [] for key in MISMATCH_SET_KEYS}


def add_mismatch(mismatch_sets: dict[str, list[str]], key: str, value: str) -> None:
    if key not in mismatch_sets:
        raise KeyError(f"Unknown mismatch set: {key}")
    mismatch_sets[key].append(str(value))


def db_integrity_failure_message(*, context: dict[str, Any], mismatch_sets: dict[str, list[str]]) -> str:
    normalized = {key: sorted(set(mismatch_sets.get(key) or [])) for key in MISMATCH_SET_KEYS}
    return (
        f"{FAILURE_PREFIX} "
        f"context={context} "
        f"missing_journal_integrity_capability={normalized['missing_journal_integrity_capability']} "
        f"missing_dc_constraint={normalized['missing_dc_constraint']} "
        f"invalid_dc_insert_not_rejected={normalized['invalid_dc_insert_not_rejected']} "
        f"unbalanced_finalize_not_rejected={normalized['unbalanced_finalize_not_rejected']} "
        f"preexisting_invalid_rows_detected={normalized['preexisting_invalid_rows_detected']} "
        f"verifier_parity_missing_artifacts={normalized['verifier_parity_missing_artifacts']}"
    )


def assert_no_mismatches(*, context: dict[str, Any], mismatch_sets: dict[str, list[str]]) -> None:
    if any(bool(mismatch_sets.get(key)) for key in MISMATCH_SET_KEYS):
        raise AssertionError(db_integrity_failure_message(context=context, mismatch_sets=mismatch_sets))


def json_from_text(text: str) -> dict[str, Any]:
    body = (text or "").strip()
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        start = body.find("{")
        end = body.rfind("}")
        if start >= 0 and end > start:
            return json.loads(body[start : end + 1])
        raise


def load_audit_queries(audit_sql_path: Path) -> list[str]:
    sql_text = audit_sql_path.read_text(encoding="utf-8")
    chunks = [chunk.strip() for chunk in sql_text.split(";")]
    return [chunk for chunk in chunks if chunk.lower().startswith("select")]


def run_verifier_sql(db_path: Path, verifier_sql_path: Path) -> list[dict[str, str]]:
    sql_text = verifier_sql_path.read_text(encoding="utf-8")
    completed = subprocess.run(
        ["sqlite3", str(db_path)],
        input=sql_text,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "verify_schema_capabilities.sql execution failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    rows: list[dict[str, str]] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        rows.append(
            {
                "scope": parts[0],
                "artifact_type": parts[1],
                "artifact_id": parts[2],
                "ok": parts[3],
                "message": parts[4],
            }
        )
    return rows
