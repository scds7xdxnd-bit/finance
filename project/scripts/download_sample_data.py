"""Generate a synthetic dataset compatible with the project schema."""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

import numpy as np
import pandas as pd
from src.common import settings
from src.data.schema import (
    ALLOWED_MERCHANT_TYPES,
    TARGET_COLUMN,
    summarize_table,
)

DEFAULT_ROWS = 500


def _synthetic_probability(amount: float, merchant: str, hour: int) -> float:
    base = 0.1
    base += 0.00005 * max(amount - 500, 0)
    if merchant == "travel":
        base += 0.15
    if hour > 21 or hour < 6:
        base += 0.1
    return max(0.01, min(0.95, base))


def generate(rows: int = DEFAULT_ROWS, seed: int | None = None) -> pd.DataFrame:
    if seed is None:
        seed = int(os.getenv("SEED", "42"))
    random.seed(seed)
    np.random.seed(seed)

    merchants = sorted(ALLOWED_MERCHANT_TYPES)
    data = []
    for idx in range(rows):
        account = f"acct_{random.randint(1000, 9999)}"
        transaction_id = f"txn_{seed}_{idx}"
        merchant = random.choice(merchants)
        amount = round(np.random.lognormal(mean=3, sigma=0.5), 2)
        hour = random.randint(0, 23)
        prob = _synthetic_probability(amount, merchant, hour)
        label = int(np.random.binomial(1, prob))
        data.append(
            {
                "transaction_id": transaction_id,
                "account_id": account,
                "amount": float(amount),
                "merchant_type": merchant,
                "transaction_hour": hour,
                TARGET_COLUMN: label,
            }
        )
    return pd.DataFrame(data)


def main() -> None:
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    df = generate()
    csv_path = data_dir / settings.DEFAULT_DATA_FILENAME
    parquet_path = data_dir / "sample.parquet"

    df.to_csv(csv_path, index=False)
    df.to_parquet(parquet_path, index=False)

    summary = summarize_table(df)
    summary["path_csv"] = str(csv_path)
    summary["path_parquet"] = str(parquet_path)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
