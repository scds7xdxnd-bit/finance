from __future__ import annotations

import datetime as _dt
import json
import logging
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple, Union

logger = logging.getLogger(__name__)

DEFAULT_RATES: Dict[str, float] = {
    "KRW": 1.0,
    "CNY": 185.0,
    "MYR": 330.0,
}

RATE_FILES: Tuple[Path, ...] = (
    Path("instance/exchange_rates.json"),
    Path("data/exchange_rates_sample.json"),
)


def _coerce_date(value: Union[str, _dt.date, None]) -> _dt.date:
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value.strip())
        except Exception:
            pass
    return _dt.date.today()


def _parse_rate_file(path: Path) -> Dict[str, List[Tuple[_dt.date, float]]]:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    normalized: Dict[str, List[Tuple[_dt.date, float]]] = {}
    for currency, entries in (raw or {}).items():
        currency_code = (currency or "").strip().upper()
        if not currency_code:
            continue
        bucket: List[Tuple[_dt.date, float]] = []
        if isinstance(entries, dict):
            for key, value in entries.items():
                if str(key).lower() == "default":
                    try:
                        DEFAULT_RATES[currency_code] = float(value)
                    except Exception:
                        continue
                    continue
                try:
                    day = _dt.date.fromisoformat(str(key))
                    bucket.append((day, float(value)))
                except Exception:
                    continue
        if bucket:
            bucket.sort(key=lambda item: item[0])
            normalized[currency_code] = bucket
    return normalized


@lru_cache()
def _rate_table() -> Dict[str, List[Tuple[_dt.date, float]]]:
    aggregated: Dict[str, List[Tuple[_dt.date, float]]] = {}
    for path in RATE_FILES:
        if not path.exists():
            continue
        try:
            parsed = _parse_rate_file(path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to parse FX rate file %s: %s", path, exc)
            continue
        for currency, values in parsed.items():
            bucket = aggregated.setdefault(currency, [])
            bucket.extend(values)
            bucket.sort(key=lambda item: item[0])
    return aggregated


def _lookup_rate(currency: str, date: _dt.date) -> float:
    currency_code = currency.upper()
    table = _rate_table()
    if currency_code in table:
        entries = table[currency_code]
        for day, rate in reversed(entries):
            if day <= date:
                return rate
    return DEFAULT_RATES.get(currency_code, 1.0)


def get_rate_to_krw(currency: str, on_date: Union[str, _dt.date, None]) -> float:
    normalized_currency = (currency or "KRW").upper()
    if normalized_currency == "KRW":
        return 1.0
    date = _coerce_date(on_date)
    return _lookup_rate(normalized_currency, date)


def convert_to_krw(amount: Union[float, int, Decimal], currency: str, on_date: Union[str, _dt.date, None]) -> float:
    if amount in (None, ""):
        return 0.0
    rate = get_rate_to_krw(currency, on_date)
    quantized = Decimal(str(amount))
    converted = quantized * Decimal(str(rate))
    try:
        return float(converted)
    except Exception:  # pragma: no cover - Decimal edge cases
        return float(converted.quantize(Decimal("0.01")))
