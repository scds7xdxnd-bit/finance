from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd
from dateutil.parser import parse as dtparse

from .utils import (
    detect_currency_pairs,
    isclose,
    normalize_line_type_any_currency,
    safe_float,
    stable_txn_id,
)

BASE_REQUIRED = ["Date", "Affected Accounts", "Transaction Description"]

def _coerce_types(df: pd.DataFrame, currency_pairs: List[Tuple[str, str, str]]) -> pd.DataFrame:
    df = df.copy()
    # Date -> ISO
    def to_iso(d):
        if pd.isna(d):
            return ""
        try:
            return dtparse(str(d)).date().isoformat()
        except Exception:
            return str(d)

    df["Date"] = df["Date"].apply(to_iso)
    # Strings
    for c in ["Affected Accounts", "Transaction Description"]:
        df[c] = df[c].astype(str).fillna("").str.strip()
    # Amounts
    for _, dcol, ccol in currency_pairs:
        if dcol in df.columns:
            df[dcol] = pd.to_numeric(df[dcol], errors="coerce").fillna(0.0).astype(float)
        else:
            df[dcol] = 0.0
        if ccol in df.columns:
            df[ccol] = pd.to_numeric(df[ccol], errors="coerce").fillna(0.0).astype(float)
        else:
            df[ccol] = 0.0
    return df

def infer_transactions(df_raw: pd.DataFrame) -> List[pd.DataFrame]:
    """
    Build transactions by scanning rows in order:
      - Start a new block when (Date, Description) changes OR after a 'total' line.
      - If no 'total' appears, contiguous rows with identical (Date, Description) form one transaction.
    """
    for c in BASE_REQUIRED:
        if c not in df_raw.columns:
            raise ValueError(f"Missing base column: {c}")

    # Detect currencies
    currencies, pairs = detect_currency_pairs(list(df_raw.columns))
    if not currencies:
        raise ValueError("No currency columns detected. Expected headers like 'Debited Amount KRW' / 'Credited Amount KRW'.")

    df = _coerce_types(df_raw, pairs)

    rows = []
    current = []
    last_key = None

    for _, r in df.iterrows():
        key = (r["Date"], r["Transaction Description"])
        debit_vals = [safe_float(r[dcol]) for _, dcol, _ in pairs]
        credit_vals = [safe_float(r[ccol]) for _, _, ccol in pairs]
        ltype = normalize_line_type_any_currency(debit_vals, credit_vals, r["Affected Accounts"])

        row = dict(r)
        row["__line_type__"] = ltype

        if last_key is None:
            current = [row]
            last_key = key
            continue

        if key == last_key:
            current.append(row)
            if ltype == "total":
                rows.append(pd.DataFrame(current))
                current = []
                last_key = None
        else:
            if current:
                rows.append(pd.DataFrame(current))
            current = [row]
            last_key = key

    if current:
        rows.append(pd.DataFrame(current))

    # attach metadata for later use
    for blk in rows:
        blk.attrs["currency_pairs"] = pairs  # [(cur, dcol, ccol), ...]
        blk.attrs["currencies"] = [cur for cur, _, _ in pairs]

    return rows

def _compute_totals_per_currency(block: pd.DataFrame, pairs: List[Tuple[str, str, str]]) -> Dict[str, Dict[str, float]]:
    # Posting lines only
    posting = block[block["__line_type__"].isin(["debit", "credit"])]
    totals = {}
    for cur, dcol, ccol in pairs:
        sum_deb = float(posting[dcol].sum())
        sum_cre = float(posting[ccol].sum())

        # Explicit total rows (optional)
        tt = block[block["__line_type__"] == "total"]
        if not tt.empty:
            ref_deb = float(tt[dcol].mean()) if tt[dcol].sum() > 0 else sum_deb
            ref_cre = float(tt[ccol].mean()) if tt[ccol].sum() > 0 else sum_cre
        else:
            ref_deb, ref_cre = sum_deb, sum_cre

        totals[cur] = {
            "sum_debit": sum_deb,
            "sum_credit": sum_cre,
            "ref_debit": ref_deb,
            "ref_credit": ref_cre,
        }
    return totals

def explode_to_lines(blocks: List[pd.DataFrame], balance_tol: float = 1e-6):
    """
    Convert block-wise transactions into a long, line-level per-currency table.
    Drops 'total' and 'unknown' lines from the output but uses them for totals.
    """
    line_rows = []
    imbalanced = []

    for bi, blk in enumerate(blocks):
        pairs = blk.attrs["currency_pairs"]
        currencies = blk.attrs["currencies"]

        date_iso = str(blk.iloc[0]["Date"])
        desc = str(blk.iloc[0]["Transaction Description"])
        txn_id = stable_txn_id(date_iso, desc, bi)

        totals = _compute_totals_per_currency(blk, pairs)

        # Record imbalance per currency
        any_imbal = False
        for cur in currencies:
            if not isclose(totals[cur]["sum_debit"], totals[cur]["sum_credit"], tol=balance_tol):
                any_imbal = True
        if any_imbal:
            row = {"Transaction_ID": txn_id, "Date": date_iso, "Description": desc}
            for cur in currencies:
                t = totals[cur]
                row[f"{cur}_Sum_Debit"] = t["sum_debit"]
                row[f"{cur}_Sum_Credit"] = t["sum_credit"]
                row[f"{cur}_Ref_Debit"] = t["ref_debit"]
                row[f"{cur}_Ref_Credit"] = t["ref_credit"]
            imbalanced.append(row)

        # Posting lines
        posting = blk[blk["__line_type__"].isin(["debit", "credit"])].copy()
        if posting.empty:
            continue

        posting["Line_ID"] = range(len(posting))
        num_debit = int((posting["__line_type__"] == "debit").sum())
        num_credit = int((posting["__line_type__"] == "credit").sum())

        # Precompute side-wise per-currency maxima for Is_Max_Line
        max_debit_per_cur = {}
        max_credit_per_cur = {}
        for cur, dcol, ccol in pairs:
            max_debit_per_cur[cur] = posting.loc[posting["__line_type__"] == "debit", dcol].max() if num_debit else 0.0
            max_credit_per_cur[cur] = posting.loc[posting["__line_type__"] == "credit", ccol].max() if num_credit else 0.0

        # Emit one row per currency where amount > 0
        for _, r in posting.iterrows():
            account = r["Affected Accounts"]
            ltype = r["__line_type__"]
            for cur, dcol, ccol in pairs:
                if ltype == "debit":
                    amt = float(r[dcol])
                    if amt <= 0:
                        continue
                    is_max = 1 if isclose(amt, max_debit_per_cur[cur]) and amt > 0 else 0
                    total_d = totals[cur]["ref_debit"]
                    total_c = totals[cur]["ref_credit"]
                else:
                    amt = float(r[ccol])
                    if amt <= 0:
                        continue
                    is_max = 1 if isclose(amt, max_credit_per_cur[cur]) and amt > 0 else 0
                    total_d = totals[cur]["ref_debit"]
                    total_c = totals[cur]["ref_credit"]

                denom = max(total_d, total_c, 1e-9)
                rel = float(amt) / float(denom)

                line_rows.append(
                    {
                        "Transaction_ID": txn_id,
                        "Line_ID": int(r["Line_ID"]),
                        "Date": date_iso,
                        "Description": desc,
                        "Account_Name": account,
                        "Currency": cur,
                        "Line_Type": ltype,      # 'debit' or 'credit'
                        "Amount": amt,           # >= 0 for this currency
                        "Transaction_Total_Debit": total_d,
                        "Transaction_Total_Credit": total_c,
                        "Relative_Amount": rel,
                        "Is_Max_Line": is_max,
                        "Num_Debit_Lines": num_debit,
                        "Num_Credit_Lines": num_credit,
                    }
                )

    lines_df = pd.DataFrame(
        line_rows,
        columns=[
            "Transaction_ID",
            "Line_ID",
            "Date",
            "Description",
            "Account_Name",
            "Currency",
            "Line_Type",
            "Amount",
            "Transaction_Total_Debit",
            "Transaction_Total_Credit",
            "Relative_Amount",
            "Is_Max_Line",
            "Num_Debit_Lines",
            "Num_Credit_Lines",
        ],
    )

    imbalanced_df = pd.DataFrame(imbalanced) if imbalanced else pd.DataFrame()

    return lines_df, imbalanced_df
