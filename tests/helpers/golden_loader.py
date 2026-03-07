"""Golden fixture loader and DB seeding helpers for vNext gate tests."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

from finance_app import (
    Account,
    AccountCategory,
    AccountOpeningBalance,
    JournalEntry,
    JournalLine,
    TrialBalanceSetting,
    User,
    db,
)

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SeedArtifacts:
    user_ids: Dict[str, int]
    category_ids: Dict[str, int]
    account_ids: Dict[str, int]
    journal_entry_ids: Dict[str, int]


def load_golden_case(filename: str = "vnext_gate_minimal.json") -> dict[str, Any]:
    case_path = ROOT / "tests" / "fixtures" / "golden" / filename
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    _validate_minimal_contract(payload, case_path)
    return payload


def load_csv_fixture_text(path_from_repo_root: str) -> str:
    return (ROOT / path_from_repo_root).read_text(encoding="utf-8")


def seed_golden_case(payload: dict[str, Any]) -> SeedArtifacts:
    user_ids: dict[str, int] = {}
    category_ids: dict[str, int] = {}
    account_ids: dict[str, int] = {}
    journal_entry_ids: dict[str, int] = {}

    for row in payload.get("users") or []:
        user = User(
            username=row["username"],
            password_hash="pw",
            is_admin=bool(row.get("is_admin", False)),
        )
        db.session.add(user)
        db.session.flush()
        user_ids[row["key"]] = int(user.id)

    init_date = dt.date.fromisoformat(payload["period"]["start"])
    for user_key, user_id in user_ids.items():
        db.session.add(TrialBalanceSetting(user_id=user_id, initialized_on=init_date))

    for row in payload.get("categories") or []:
        cat = AccountCategory(
            user_id=user_ids[row["user"]],
            name=row["name"],
            tb_group=row["tb_group"],
        )
        db.session.add(cat)
        db.session.flush()
        category_ids[row["key"]] = int(cat.id)

    for row in payload.get("accounts") or []:
        account = Account(
            user_id=user_ids[row["user"]],
            name=row["name"],
            category_id=category_ids[row["category"]],
            currency_code=(row.get("currency") or "KRW").upper(),
            active=bool(row.get("active", True)),
        )
        db.session.add(account)
        db.session.flush()
        account_ids[row["key"]] = int(account.id)

    for row in payload.get("opening_balances") or []:
        db.session.add(
            AccountOpeningBalance(
                user_id=user_ids[row["user"]],
                account_id=account_ids[row["account"]],
                amount=float(row["amount"]),
                as_of_date=dt.date.fromisoformat(row["as_of_date"]),
            )
        )

    for row in payload.get("journal_entries") or []:
        entry_date = dt.date.fromisoformat(row["date"])
        entry = JournalEntry(
            user_id=user_ids[row["user"]],
            date=entry_date.isoformat(),
            date_parsed=entry_date,
            description=row["description"],
            reference=row.get("reference"),
        )
        db.session.add(entry)
        db.session.flush()
        journal_entry_ids[row["key"]] = int(entry.id)

        for idx, line in enumerate(row.get("lines") or [], start=1):
            db.session.add(
                JournalLine(
                    journal_id=entry.id,
                    account_id=account_ids[line["account"]],
                    dc=(line["dc"] or "").upper(),
                    amount_base=Decimal(str(line["amount"])),
                    memo=line.get("memo") or "",
                    line_no=idx,
                )
            )

    db.session.commit()
    return SeedArtifacts(
        user_ids=user_ids,
        category_ids=category_ids,
        account_ids=account_ids,
        journal_entry_ids=journal_entry_ids,
    )


def _validate_minimal_contract(payload: dict[str, Any], case_path: Path) -> None:
    required = {
        "schema_version",
        "case_id",
        "period",
        "scenario_coverage",
        "thresholds",
        "users",
        "categories",
        "accounts",
        "opening_balances",
        "journal_entries",
        "write_mode_matrix",
        "csv_import_batches",
        "sensitive_flow_probes",
        "expected",
    }
    missing = sorted(required.difference(payload.keys()))
    if missing:
        raise ValueError(f"Golden fixture missing required keys at {case_path}: {missing}")

    expected_scenarios = {
        "transfer",
        "refund",
        "fee",
        "split",
        "receivable_repayment",
        "csv_overlap_exports",
    }
    got = set(payload.get("scenario_coverage") or [])
    missing_scenarios = sorted(expected_scenarios.difference(got))
    if missing_scenarios:
        raise ValueError(f"Golden fixture missing required scenario_coverage entries: {missing_scenarios}")

    if payload.get("schema_version") != "qa-golden-v1":
        raise ValueError(f"Unsupported schema_version {payload.get('schema_version')!r}; expected 'qa-golden-v1'")
