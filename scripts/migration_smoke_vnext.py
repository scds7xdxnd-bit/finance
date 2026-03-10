#!/usr/bin/env python3
"""Run a local SQLite migration smoke test for vNext capabilities."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERIFY_SQL = ROOT / "scripts" / "verify_schema_capabilities.sql"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run(cmd: list[str], env: dict[str, str]) -> str:
    completed = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return (completed.stdout or "").strip()


def _truthy(raw: Any) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _required_artifact_set() -> set[str]:
    from finance_app.services.schema_guard_service import _CAPABILITY_REQUIREMENTS

    artifact_ids: set[str] = set()
    for req in _CAPABILITY_REQUIREMENTS.values():
        for table_name in req.get("tables", []):
            artifact_ids.add(f"table:{table_name}")
        for table_name, columns in (req.get("columns") or {}).items():
            for column_name in columns:
                artifact_ids.add(f"column:{table_name}.{column_name}")
        for table_name, index_name in req.get("indexes", []):
            artifact_ids.add(f"index:{table_name}.{index_name}")
        for table_name, unique_name in req.get("uniques", []):
            artifact_ids.add(f"unique:{table_name}.{unique_name}")
        for table_name, check_name in req.get("checks", []):
            artifact_ids.add(f"check:{table_name}.{check_name}")
        for trigger_name in req.get("triggers", []):
            artifact_ids.add(f"trigger:{trigger_name}")
    return artifact_ids


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--simulate-parity-mismatch",
        default="0",
        help="Test-only drill flag. Truthy value forces parity mismatch without changing SQL.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    simulate_parity_mismatch = _truthy(args.simulate_parity_mismatch)

    fd, db_path_raw = tempfile.mkstemp(prefix="finance_migration_smoke_", suffix=".db")
    os.close(fd)
    db_path = Path(db_path_raw)

    env = dict(os.environ)
    env["ALEMBIC_DATABASE_URL"] = f"sqlite:///{db_path}"
    env["FINANCE_DATABASE_URL"] = f"sqlite:///{db_path}"

    try:
        _run(["alembic", "upgrade", "head"], env=env)
        schema_status_out = _run(["python3", "-m", "flask", "--app", "finance_app", "schema-status"], env=env)

        sql = VERIFY_SQL.read_text(encoding="utf-8")
        with sqlite3.connect(str(db_path)) as conn:
            rows = conn.execute(sql).fetchall()

        checks = [
            {
                "scope": str(row[0]),
                "artifact_type": str(row[1]),
                "artifact_id": str(row[2]),
                "ok": bool(row[3]),
                "message": (str(row[4]) if row[4] is not None else None),
            }
            for row in rows
        ]
        failed = [row for row in checks if not row["ok"]]
        total_checks = len(checks)

        required_artifact_count = len(_required_artifact_set())
        if simulate_parity_mismatch:
            required_artifact_count += 1

        parity_delta = total_checks - required_artifact_count
        parity_ok = parity_delta == 0
        parity_message = ""
        if not parity_ok:
            parity_message = (
                "Schema verifier parity mismatch: "
                f"total_checks={total_checks} "
                f"required_artifact_count={required_artifact_count} "
                f"delta={parity_delta}"
            )

        ok = (len(failed) == 0) and parity_ok
        print(
            f"parity_ok={str(parity_ok).lower()} "
            f"total_checks={total_checks} "
            f"required_artifact_count={required_artifact_count}"
        )

        payload = {
            "ok": ok,
            "db_path": str(db_path),
            "failed_checks": failed,
            "total_checks": total_checks,
            "required_artifact_count": required_artifact_count,
            "parity_ok": parity_ok,
            "parity_message": parity_message,
            "parity_delta": parity_delta,
            "schema_status": json.loads(schema_status_out) if schema_status_out else {},
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if ok else 1
    except subprocess.CalledProcessError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"command_failed: {' '.join(exc.cmd)}",
                    "stdout": exc.stdout,
                    "stderr": exc.stderr,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    finally:
        for suffix in ("", "-shm", "-wal"):
            try:
                (Path(str(db_path) + suffix)).unlink(missing_ok=True)
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
