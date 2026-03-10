from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_ENDPOINT_REGISTRY_KEYS = (
    "window.FINANCE_ENDPOINTS.transactions.add",
    "window.FINANCE_ENDPOINTS.ml.suggestions",
    "window.FINANCE_ENDPOINTS.ml.suggestionLog",
    "window.FINANCE_ENDPOINTS.accounting.tbMonthly",
    "window.FINANCE_ENDPOINTS.accounting.statements.data",
)


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
            "Alembic upgrade failed for frontend contract fixture setup.\n"
            f"target_revision={target_revision}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


def assert_json_envelope(response, *, endpoint: str) -> dict[str, Any]:
    payload = response.get_json(silent=True)
    assert isinstance(payload, dict), f"{endpoint}: response is not JSON object"
    assert isinstance(payload.get("ok"), bool), f"{endpoint}: missing/invalid boolean ok"
    if payload.get("ok") is False:
        assert isinstance(payload.get("error"), str) and payload.get("error"), f"{endpoint}: ok=false requires error string"
    return payload


def find_missing_endpoint_registry_keys(html_text: str) -> list[str]:
    patterns = {
        "window.FINANCE_ENDPOINTS.transactions.add": r"transactions\s*:\s*Object\.freeze\(\{[\s\S]*?\badd\s*:",
        "window.FINANCE_ENDPOINTS.ml.suggestions": r"ml\s*:\s*Object\.freeze\(\{[\s\S]*?\bsuggestions\s*:",
        "window.FINANCE_ENDPOINTS.ml.suggestionLog": r"ml\s*:\s*Object\.freeze\(\{[\s\S]*?\bsuggestionLog\s*:",
        "window.FINANCE_ENDPOINTS.accounting.tbMonthly": r"accounting\s*:\s*Object\.freeze\(\{[\s\S]*?\btbMonthly\s*:",
        "window.FINANCE_ENDPOINTS.accounting.statements.data": r"accounting\s*:\s*Object\.freeze\(\{[\s\S]*?statements\s*:\s*Object\.freeze\(\{[\s\S]*?\bdata\s*:",
    }
    missing: list[str] = []
    for key in REQUIRED_ENDPOINT_REGISTRY_KEYS:
        pattern = patterns[key]
        if re.search(pattern, html_text, flags=re.IGNORECASE) is None:
            missing.append(key)
    return sorted(missing)
