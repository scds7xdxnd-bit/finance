#!/usr/bin/env python3
"""Run a local SQLite migration smoke test for vNext capabilities."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFY_SQL = ROOT / "scripts" / "verify_schema_capabilities.sql"


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


def main() -> int:
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
            {"capability": row[0], "check": row[1], "ok": bool(row[2])}
            for row in rows
        ]
        failed = [row for row in checks if not row["ok"]]

        payload = {
            "ok": len(failed) == 0,
            "db_path": str(db_path),
            "failed_checks": failed,
            "total_checks": len(checks),
            "schema_status": json.loads(schema_status_out) if schema_status_out else {},
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["ok"] else 1
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
