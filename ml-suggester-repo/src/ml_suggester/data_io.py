from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

BASE_REQUIRED = ["Date", "Affected Accounts", "Transaction Description"]

def _pick_sheet(obj, sheet_name):
    """Return a DataFrame for the requested sheet or the first available."""
    if isinstance(obj, dict):
        if sheet_name is None:
            first_key = next(iter(obj.keys()))
            return obj[first_key]
        if isinstance(sheet_name, int):
            key = list(obj.keys())[sheet_name]
            return obj[key]
        return obj[sheet_name]
    return obj

def _normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    # Drop index-like columns
    cols = []
    for c in df.columns:
        name = str(c).strip()
        if name.lower().startswith("unnamed"):
            # skip unnamed index columns
            continue
        cols.append(name)
    df = df.loc[:, cols].copy()

    # Alias mapping for base columns
    rename_map = {}
    lower_map = {c.lower(): c for c in df.columns}

    # Affected Accounts
    for cand in ["affected accounts", "affected account", "account name", "account", "account_names"]:
        if cand in lower_map:
            rename_map[lower_map[cand]] = "Affected Accounts"
            break

    # Transaction Description
    for cand in ["transaction description", "description", "desc"]:
        if cand in lower_map:
            rename_map[lower_map[cand]] = "Transaction Description"
            break

    # Date (keep if already 'Date', else try aliases)
    if "Date" not in df.columns:
        for cand in ["date", "날짜", "日期"]:
            if cand in lower_map:
                rename_map[lower_map[cand]] = "Date"
                break

    df = df.rename(columns=rename_map)
    return df

def _find_numbered_debit_credit_columns(df: pd.DataFrame):
    """
    Find columns like:
      Debit, Credit, Debit.1, Credit.1, 'Debit .2', 'Credit .2', etc.
    Returns two lists aligned by index: debit_cols[i] pairs with credit_cols[i].
    """
    deb_pat = re.compile(r"^debit(?:\s*\.?\s*(\d+))?$", re.IGNORECASE)
    cre_pat = re.compile(r"^credit(?:\s*\.?\s*(\d+))?$", re.IGNORECASE)

    debit_cols = []
    credit_cols = []
    # Maps index suffix -> column
    dmap, cmap = {}, {}
    base_debit, base_credit = None, None

    for c in df.columns:
        m = deb_pat.match(c)
        if m:
            idx = m.group(1)
            if idx is None:
                base_debit = c
            else:
                dmap[int(idx)] = c
            continue
        m = cre_pat.match(c)
        if m:
            idx = m.group(1)
            if idx is None:
                base_credit = c
            else:
                cmap[int(idx)] = c

    # Build aligned lists by increasing index
    # First pair: base debit/credit (no index)
    if base_debit or base_credit:
        debit_cols.append(base_debit or "")
        credit_cols.append(base_credit or "")

    # Then numbered pairs: 1,2,3,...
    for i in sorted(set(dmap.keys()) | set(cmap.keys())):
        debit_cols.append(dmap.get(i, ""))
        credit_cols.append(cmap.get(i, ""))

    # Filter out completely empty pairs
    clean_debit, clean_credit = [], []
    for d, c in zip(debit_cols, credit_cols):
        if d or c:
            clean_debit.append(d)
            clean_credit.append(c)
    return clean_debit, clean_credit

def _attach_currency_codes(df: pd.DataFrame, currencies: list[str] | None) -> pd.DataFrame:
    """
    If columns already contain currency codes like 'Debited Amount KRW', we keep them.
    Otherwise, map generic Debit/Credit columns (and their numbered variants) to the
    provided currencies, renaming them to the standard schema:
      'Debited Amount XXX' / 'Credited Amount XXX'
    """
    # If we already have proper columns, do nothing
    has_proper = any(col.startswith("Debited Amount ") or col.startswith("Credited Amount ") for col in df.columns)
    if has_proper:
        return df

    # Discover generic debit/credit columns
    debit_cols, credit_cols = _find_numbered_debit_credit_columns(df)

    if not debit_cols and not credit_cols:
        return df  # nothing to do; detect_currency_pairs will error later

    # If currencies not provided, require them (we can't guess order reliably)
    if not currencies:
        raise ValueError(
            "Your sheet has generic Debit/Credit columns without currency codes. "
            "Provide the mapping order via --currencies, e.g. --currencies 'KRW,MYR,CNY'. "
            f"Detected debit cols={debit_cols}, credit cols={credit_cols}"
        )

    # Align lengths
    n = max(len(debit_cols), len(credit_cols), len(currencies))
    # Pad missing with empty strings
    debit_cols += [""] * (n - len(debit_cols))
    credit_cols += [""] * (n - len(credit_cols))
    currencies += ["CUR"+str(i) for i in range(len(currencies), n)]  # safety (won't usually happen)

    # Create/rename to standard schema
    new_cols = {}
    for i in range(n):
        cur = currencies[i]
        dstd = f"Debited Amount {cur}"
        cstd = f"Credited Amount {cur}"

        dsrc = debit_cols[i]
        csrc = credit_cols[i]

        if dsrc and dsrc in df.columns:
            new_cols[dsrc] = dstd
        else:
            # create empty column if missing
            df[dstd] = 0.0

        if csrc and csrc in df.columns:
            new_cols[csrc] = cstd
        else:
            df[cstd] = 0.0

    if new_cols:
        df = df.rename(columns=new_cols)
    return df

def load_excel(path: str, sheet_name: str | int | None = None, currencies: list[str] | None = None) -> pd.DataFrame:
    """
    Expect base columns:
      Date, Affected Accounts, Transaction Description
    And currency columns either as:
      - Debited Amount XXX / Credited Amount XXX
      - or generic Debit / Credit (+ numbered variants) mapped via --currencies order
    """
    raw = pd.read_excel(path, sheet_name=sheet_name if sheet_name is not None else None, engine="openpyxl")
    df = _pick_sheet(raw, sheet_name)
    df = df.rename(columns={str(c): str(c).strip() for c in df.columns})
    df = _normalize_headers(df)
    df = _attach_currency_codes(df, currencies)

    missing = [c for c in BASE_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}. Found: {list(df.columns)}")
    return df

def write_table(df, out_path: str, out_format: str = "parquet"):
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out_format.lower() == "parquet":
        df.to_parquet(out, index=False)
    elif out_format.lower() == "csv":
        df.to_csv(out, index=False)
    else:
        raise ValueError("out_format must be 'parquet' or 'csv'")
