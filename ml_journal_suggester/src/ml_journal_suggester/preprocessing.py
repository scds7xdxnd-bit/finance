from __future__ import annotations

"""Data preparation utilities."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from .data_schemas import AggregatedTransaction
from .utils import LOGGER, read_jsonl


@dataclass
class PreprocessedData:
    dataframe: pd.DataFrame
    chart_of_accounts: List[str]
    co_occurrence: Dict[str, Dict[str, float]]


def _parse_date(value: str) -> datetime.date:
    return datetime.fromisoformat(value).date()


def load_raw_transactions(path: Path) -> pd.DataFrame:
    rows = read_jsonl(path)
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError(f"No transactions found in {path}")
    frame["date"] = frame["date"].apply(_parse_date)
    if "currency" not in frame.columns:
        frame["currency"] = None
    return frame


def _aggregate_group(group: pd.DataFrame) -> Optional[AggregatedTransaction]:
    debits = group[group["side"].str.upper().isin(["DR", "DEBIT"])]
    credits = group[group["side"].str.upper().isin(["CR", "CREDIT"])]
    debit_total = float(debits["amount"].sum())
    credit_total = float(credits["amount"].sum())
    if abs(debit_total - credit_total) > 1e-6:
        return None
    debit_map = debits.groupby("account")["amount"].sum().to_dict()
    credit_map = credits.groupby("account")["amount"].sum().to_dict()
    debit_accounts = list(debit_map.keys())
    credit_accounts = list(credit_map.keys())
    is_multiline = len(group) > 2 or len(debit_accounts) > 1 or len(credit_accounts) > 1
    first = group.iloc[0]
    return AggregatedTransaction(
        tx_id=str(first["tx_id"]),
        date=first["date"],
        description=str(first["description"]),
        total_amount=debit_total,
        debit_accounts=debit_accounts,
        credit_accounts=credit_accounts,
        debit_sums_by_account={k: float(v) for k, v in debit_map.items()},
        credit_sums_by_account={k: float(v) for k, v in credit_map.items()},
        is_multiline=is_multiline,
        currency=str(first.get("currency")) if pd.notna(first.get("currency")) else None,
    )


def aggregate_transactions(frame: pd.DataFrame) -> Tuple[pd.DataFrame, List[str], Dict[str, Dict[str, float]]]:
    records: List[AggregatedTransaction] = []
    co_occurrence: Dict[str, Dict[str, float]] = {}
    for tx_id, group in frame.groupby("tx_id", sort=False):
        aggregated = _aggregate_group(group)
        if not aggregated:
            continue
        records.append(aggregated)
        for debit in aggregated.debit_accounts:
            for credit in aggregated.credit_accounts:
                co_occurrence.setdefault(debit, {}).setdefault(credit, 0.0)
                co_occurrence[debit][credit] += 1.0
    if not records:
        raise ValueError("No balanced transactions found after aggregation.")
    df = pd.DataFrame(
        {
            "tx_id": [r.tx_id for r in records],
            "date": [r.date for r in records],
            "description": [r.description for r in records],
            "total_amount": [r.total_amount for r in records],
            "debit_accounts": [r.debit_accounts for r in records],
            "credit_accounts": [r.credit_accounts for r in records],
            "debit_sums_by_account": [r.debit_sums_by_account for r in records],
            "credit_sums_by_account": [r.credit_sums_by_account for r in records],
            "is_multiline": [r.is_multiline for r in records],
            "currency": [r.currency for r in records],
        }
    )
    chart = sorted({account for r in records for account in (r.debit_accounts + r.credit_accounts)})
    # Normalise co-occurrence counts to probabilities per debit account.
    for debit, mapping in co_occurrence.items():
        total = sum(mapping.values())
        if total == 0:
            continue
        for credit in list(mapping.keys()):
            mapping[credit] = mapping[credit] / total
    return df, chart, co_occurrence


def build_parent_map(accounts: Iterable[str]) -> Dict[str, str]:
    """Return a best-effort map leaf -> parent folder based on colon-separated names."""

    parent_map: Dict[str, str] = {}
    for account in accounts:
        parts = account.split(":")
        if len(parts) <= 1:
            continue
        parent_map[account] = ":".join(parts[:-1])
    return parent_map


def prepare_training_data(path: Path, cache_parquet: Optional[Path] = None) -> PreprocessedData:
    if cache_parquet and cache_parquet.exists():
        df = pd.read_parquet(cache_parquet)
        chart = sorted({account for row in df["debit_accounts"] for account in row} | {account for row in df["credit_accounts"] for account in row})
        co_occurrence = load_yaml_co_occurrence(cache_parquet.with_suffix(".co.json"))
        return PreprocessedData(df, chart, co_occurrence)

    raw = load_raw_transactions(path)
    df, chart, co_occurrence = aggregate_transactions(raw)
    if cache_parquet:
        cache_parquet.parent.mkdir(parents=True, exist_ok=True)
        try:
            df.to_parquet(cache_parquet, index=False)
            save_yaml_co_occurrence(cache_parquet.with_suffix(".co.json"), co_occurrence)
        except Exception as exc:  # pragma: no cover - optional dependency path
            LOGGER.warning("Skipping parquet cache because engine is unavailable: %s", exc)
    return PreprocessedData(df, chart, co_occurrence)


def save_yaml_co_occurrence(path: Path, mapping: Dict[str, Dict[str, float]]) -> None:
    import json

    path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")


def load_yaml_co_occurrence(path: Path) -> Dict[str, Dict[str, float]]:
    import json

    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "PreprocessedData",
    "prepare_training_data",
    "aggregate_transactions",
    "build_parent_map",
]
