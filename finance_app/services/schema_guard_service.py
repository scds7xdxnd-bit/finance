"""Schema capability checks for sensitive operations."""

from __future__ import annotations

import datetime as _dt
import re
from typing import Dict, Iterable, List, Tuple

from sqlalchemy import inspect, text

from finance_app.extensions import db


_CAPABILITY_REQUIREMENTS = {
    "tx_linking": {
        "tables": ["transaction_journal_link"],
        "columns": {"transaction_journal_link": ["transaction_id", "journal_entry_id", "source"]},
        "indexes": [
            ("transaction_journal_link", "ix_tx_journal_link_user_journal"),
            ("transaction_journal_link", "ix_tx_journal_link_user_source"),
        ],
        "uniques": [
            ("transaction_journal_link", "uq_tx_journal_link_user_tx"),
            ("transaction_journal_link", "uq_tx_journal_link_user_journal_entry"),
        ],
        "checks": [("transaction_journal_link", "ck_tx_journal_link_source_nonempty")],
    },
    "link_candidates": {
        "tables": ["transaction_link_candidate"],
        "columns": {
            "transaction_link_candidate": [
                "transaction_id",
                "journal_entry_id",
                "confidence",
                "status",
                "source",
            ]
        },
        "indexes": [
            ("transaction_link_candidate", "ix_tx_link_candidate_user_status"),
            ("transaction_link_candidate", "ix_tx_link_candidate_user_tx_reason"),
        ],
        "checks": [("transaction_link_candidate", "ck_tx_link_candidate_source_nonempty")],
    },
    "csv_idempotency": {
        "tables": ["csv_import_batch", "csv_import_row"],
        "indexes": [("csv_import_row", "ix_csv_import_row_user_status")],
        "uniques": [
            ("csv_import_batch", "uq_csv_import_batch_user_file"),
            ("csv_import_row", "uq_csv_import_row_user_account_direction_key"),
        ],
        "checks": [
            ("csv_import_batch", "ck_csv_import_batch_status"),
            ("csv_import_row", "ck_csv_import_row_direction"),
        ],
    },
    "tb_snapshot": {
        "tables": ["tb_reset_snapshot"],
        "columns": {"tb_reset_snapshot": ["db_copy_path", "sha256", "restore_status", "file_size_bytes"]},
        "indexes": [("tb_reset_snapshot", "ix_tb_reset_snapshot_user_created")],
        "uniques": [("tb_reset_snapshot", "uq_tb_reset_snapshot_user_path")],
        "checks": [
            ("tb_reset_snapshot", "ck_tb_reset_snapshot_sha256_len"),
            ("tb_reset_snapshot", "ck_tb_reset_snapshot_file_size_nonneg"),
            ("tb_reset_snapshot", "ck_tb_reset_snapshot_restore_status"),
        ],
    },
    "admin_audit": {
        "tables": ["admin_action_audit"],
        "columns": {"admin_action_audit": ["actor_user_id", "action", "status", "created_at"]},
        "indexes": [("admin_action_audit", "ix_admin_action_audit_actor_created")],
    },
    "journal_report_perf": {
        "tables": ["journal_entry", "journal_line"],
        "indexes": [
            ("journal_entry", "ix_journal_entry_user_date_parsed"),
            ("journal_entry", "ix_journal_entry_user_reference"),
            ("journal_line", "ix_journal_line_journal_account_dc"),
            ("journal_line", "ix_journal_line_account_dc_journal"),
        ],
    },
}


def _table_columns(insp, table_name: str) -> List[str]:
    try:
        return [c.get("name") for c in insp.get_columns(table_name)]
    except Exception:
        return []


def _table_indexes(insp, table_name: str) -> List[str]:
    try:
        return [idx.get("name") for idx in insp.get_indexes(table_name)]
    except Exception:
        return []


def _table_uniques(insp, table_name: str) -> List[str]:
    names = set()
    try:
        names.update(uq.get("name") for uq in insp.get_unique_constraints(table_name) if uq.get("name"))
    except Exception:
        pass

    # SQLite keeps named UNIQUE constraints in CREATE TABLE SQL; parse as fallback.
    for name in _sqlite_named_constraints(table_name, kind="unique"):
        names.add(name)
    return sorted(names)


def _sqlite_named_constraints(table_name: str, kind: str) -> List[str]:
    if db.engine.dialect.name != "sqlite":
        return []
    try:
        row = db.session.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"),
            {"name": table_name},
        ).fetchone()
    except Exception:
        return []
    sql = (row[0] or "") if row and row[0] else ""
    if not sql:
        return []
    pattern = rf"constraint\s+([A-Za-z0-9_]+)\s+{kind}\s*\("
    return [m.group(1) for m in re.finditer(pattern, sql, flags=re.IGNORECASE)]


def _table_checks(insp, table_name: str) -> List[str]:
    names = set()
    try:
        names.update(ck.get("name") for ck in insp.get_check_constraints(table_name) if ck.get("name"))
    except Exception:
        pass
    for name in _sqlite_named_constraints(table_name, kind="check"):
        names.add(name)
    return sorted(names)


def required_capabilities() -> List[str]:
    return list(_CAPABILITY_REQUIREMENTS.keys())


def capability_report() -> Dict[str, object]:
    insp = inspect(db.engine)
    tables = set(insp.get_table_names())
    caps: Dict[str, bool] = {}
    details: Dict[str, List[str]] = {}

    for capability, req in _CAPABILITY_REQUIREMENTS.items():
        missing: List[str] = []

        for table_name in req.get("tables", []):
            if table_name not in tables:
                missing.append(f"table:{table_name}")

        for table_name, columns in (req.get("columns") or {}).items():
            if table_name not in tables:
                continue
            existing = set(_table_columns(insp, table_name))
            for column in columns:
                if column not in existing:
                    missing.append(f"column:{table_name}.{column}")

        for table_name, index_name in req.get("indexes", []):
            if table_name not in tables:
                continue
            if index_name not in _table_indexes(insp, table_name):
                missing.append(f"index:{table_name}.{index_name}")

        for table_name, unique_name in req.get("uniques", []):
            if table_name not in tables:
                continue
            if unique_name not in _table_uniques(insp, table_name):
                missing.append(f"unique:{table_name}.{unique_name}")

        for table_name, check_name in req.get("checks", []):
            if table_name not in tables:
                continue
            if check_name not in _table_checks(insp, table_name):
                missing.append(f"check:{table_name}.{check_name}")

        caps[capability] = len(missing) == 0
        if missing:
            details[capability] = missing

    return {
        "ok": all(caps.values()),
        "capabilities": caps,
        "missing_details": details,
    }


def missing_capabilities(required_caps: Iterable[str]) -> Tuple[List[str], Dict[str, object]]:
    report = capability_report()
    caps = report.get("capabilities") or {}
    missing = [cap for cap in required_caps if not bool(caps.get(cap))]
    return missing, report


def guard_capabilities(required_caps: Iterable[str], enforce: bool = True):
    """Return (ok, payload, status_code)."""
    missing, report = missing_capabilities(required_caps)
    if missing and enforce:
        payload = {
            "ok": False,
            "error": "Schema capability requirements not met",
            "missing_capabilities": missing,
            "capabilities": report.get("capabilities") or {},
            "missing_details": report.get("missing_details") or {},
        }
        return False, payload, 503
    return True, {"ok": True, "capabilities": report.get("capabilities") or {}}, 200


def validate_schema_guard_bypass(config) -> tuple[bool, dict]:
    """Validate emergency schema-guard bypass metadata.

    Contracts:
      - only relevant when SCHEMA_GUARD_ENFORCE is false
      - SCHEMA_GUARD_BYPASS_REASON must be present
      - SCHEMA_GUARD_BYPASS_UNTIL must be an ISO datetime
      - bypass window must be active and at most 7 days
    """
    enforce = bool(config.get("SCHEMA_GUARD_ENFORCE", True))
    if enforce:
        return True, {"ok": True, "enforce": True}

    reason = str(config.get("SCHEMA_GUARD_BYPASS_REASON") or "").strip()
    until_raw = str(config.get("SCHEMA_GUARD_BYPASS_UNTIL") or "").strip()
    if not reason:
        return False, {"ok": False, "error": "SCHEMA_GUARD_BYPASS_REASON is required when bypass is enabled."}
    if not until_raw:
        return False, {"ok": False, "error": "SCHEMA_GUARD_BYPASS_UNTIL is required when bypass is enabled."}

    try:
        normalized = until_raw[:-1] + "+00:00" if until_raw.endswith("Z") else until_raw
        until_dt = _dt.datetime.fromisoformat(normalized)
    except Exception:
        return False, {"ok": False, "error": "SCHEMA_GUARD_BYPASS_UNTIL must be a valid ISO datetime."}

    if until_dt.tzinfo is None:
        until_dt = until_dt.replace(tzinfo=_dt.timezone.utc)
    now = _dt.datetime.now(_dt.timezone.utc)
    if until_dt <= now:
        return False, {"ok": False, "error": "SCHEMA_GUARD_BYPASS_UNTIL is expired."}
    if (until_dt - now) > _dt.timedelta(days=7):
        return False, {"ok": False, "error": "SCHEMA_GUARD_BYPASS_UNTIL exceeds 7-day emergency window."}

    return True, {
        "ok": True,
        "enforce": False,
        "reason": reason,
        "until": until_dt.isoformat(),
    }
