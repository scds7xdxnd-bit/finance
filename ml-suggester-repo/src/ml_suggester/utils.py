from __future__ import annotations

import re
from typing import List, Optional, Tuple
from uuid import UUID, uuid5

TXN_NS = UUID("12345678-1234-5678-1234-567812345678")  # deterministic namespace

def stable_txn_id(date_iso: str, description: str, block_index: int) -> str:
    """Deterministic Transaction_ID using uuid5 over (date|description|block_index)."""
    key = f"{date_iso}|{description}|{block_index}"
    return str(uuid5(TXN_NS, key))

def isclose(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs((a or 0.0) - (b or 0.0)) <= tol

def safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0

def detect_currency_pairs(columns: List[str]) -> Tuple[List[str], List[Tuple[str, str, str]]]:
    """
    Detect currencies from headers like:
      'Debited Amount KRW', 'Credited Amount KRW', ...
    Returns:
      currencies: ['KRW','MYR',...]
      pairs: [('KRW','Debited Amount KRW','Credited Amount KRW'), ...]
    """
    deb_re = re.compile(r"^Debited Amount ([A-Z]{3})$")
    cre_re = re.compile(r"^Credited Amount ([A-Z]{3})$")
    deb_map = {}
    cre_map = {}
    for c in columns:
        m = deb_re.match(c.strip())
        if m:
            deb_map[m.group(1)] = c
        m = cre_re.match(c.strip()) or m
        if not m:
            m = cre_re.match(c.strip())
        if m and c.startswith("Credited"):
            cre_map[m.group(1)] = c

    currencies = sorted(set(deb_map.keys()) | set(cre_map.keys()))
    pairs = []
    for cur in currencies:
        dcol = deb_map.get(cur)
        ccol = cre_map.get(cur)
        if dcol is None or ccol is None:
            # allow missing side but still include currency if either side exists
            dcol = dcol or f"Debited Amount {cur}"
            ccol = ccol or f"Credited Amount {cur}"
        pairs.append((cur, dcol, ccol))
    return currencies, pairs

def normalize_line_type_any_currency(debit_vals: List[float], credit_vals: List[float], account_name: Optional[str]) -> str:
    """
    Decide line type by inspecting all currencies:
    - 'debit'  if any debit>0 and all credits==0
    - 'credit' if any credit>0 and all debits==0
    - 'total'  if (any debit>0 and any credit>0) or account contains 'total'
    - else 'unknown'
    """
    dn = any((v or 0.0) > 0 for v in debit_vals)
    cn = any((v or 0.0) > 0 for v in credit_vals)
    acc = (account_name or "").strip().lower()
    if dn and not cn:
        return "debit"
    if cn and not dn:
        return "credit"
    if (dn and cn) or ("total" in acc):
        return "total"
    return "unknown"