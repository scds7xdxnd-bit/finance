from __future__ import annotations

import re

import pandas as pd


def _clean(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s\-/&:.,]", " ", s)   # keep common punctuation
    return s.strip()

# Columns required from the transformed dataset
REQUIRED = [
    "Transaction_ID", "Line_ID", "Date", "Description", "Account_Name",
    "Currency", "Line_Type", "Amount", "Relative_Amount",
    "Num_Debit_Lines", "Num_Credit_Lines"
]

def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure required columns and create date-derived features."""
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in training data: {missing}")

    df = df.copy()
    # Date features
    d = pd.to_datetime(df["Date"], errors="coerce")
    df["year"] = d.dt.year.fillna(0).astype(int)
    df["month"] = d.dt.month.fillna(0).astype(int)
    df["dow"] = d.dt.dayofweek.fillna(0).astype(int)
    df["is_month_end"] = d.dt.is_month_end.fillna(False).astype(int)

    # Safety for numerics
    for c in ["Amount", "Relative_Amount", "Num_Debit_Lines", "Num_Credit_Lines"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # Keep only rows with non-empty labels
    df = df[df["Account_Name"].astype(str).str.len() > 0].reset_index(drop=True)
    df["Description"] = df["Description"].astype(str).fillna("").map(_clean)
    return df

def feature_target_split(df: pd.DataFrame):
    """Return X (features), y (labels)."""
    # Features we’ll feed to the model
    numeric = ["Amount", "Relative_Amount", "Num_Debit_Lines", "Num_Credit_Lines", "year", "month", "dow", "is_month_end"]
    categorical = ["Currency", "Line_Type"]
    text = ["Description"]
    X = df[numeric + categorical + text].copy()
    y = df["Account_Name"].astype(str).copy()
    return X, y
