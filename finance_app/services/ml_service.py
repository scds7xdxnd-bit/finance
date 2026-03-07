import datetime as dt
from collections import defaultdict
from typing import Dict, List, Tuple

from sqlalchemy import func

from finance_app.extensions import db
from finance_app.lib.dates import _normalize_date_for_ml
from finance_app.models.accounting_models import AccountSuggestionHint


def _desc_tokens(desc: str):
    try:
        import re

        raw = (desc or "").lower()
        toks = re.findall(r"[a-z0-9]+", raw)
        stopwords = {"and", "or", "the", "a", "of", "for", "to", "in", "on"}
        return [t for t in toks if len(t) >= 3 and t not in stopwords][:12]
    except Exception:
        return []


def record_suggestion_hint(user_id: int, kind: str, description: str, account_name: str, weight: int | float = 1):
    """Update suggestion hint counts used for lightweight ML-style recommendations."""
    try:
        try:
            w_int = int(round(float(weight)))
        except Exception:
            w_int = 1
        if w_int == 0:
            return
        tokens = _desc_tokens(description)
        if not tokens:
            return
        now = dt.datetime.utcnow()
        half_life_days = 14.0
        for tok in tokens[:8]:
            row = AccountSuggestionHint.query.filter_by(user_id=user_id, kind=kind, token=tok, account_name=account_name).first()
            if not row:
                if w_int > 0:
                    row = AccountSuggestionHint(
                        user_id=user_id,
                        kind=kind,
                        token=tok,
                        account_name=account_name,
                        count=w_int,
                        updated_at=now,
                    )
                    db.session.add(row)
                continue
            # Apply time-decay to keep hints fresh. Always apply a minimum decay factor for stability.
            age_days = 0.0
            try:
                age_days = max(0.0, (now - (row.updated_at or now)).total_seconds() / 86400.0)
            except Exception:
                age_days = 0.0
            decay_factor = 0.9 * (0.5 ** (age_days / half_life_days))
            decay_factor = max(decay_factor, 0.05)
            decayed = int((row.count or 0) * decay_factor)
            new_count = decayed + w_int
            if new_count <= 0:
                db.session.delete(row)
            else:
                row.count = new_count
                row.updated_at = now
        db.session.commit()
    except Exception:
        db.session.rollback()


def best_hint_suggestion(user_id: int, kind: str, description: str):
    tokens = _desc_tokens(description)
    if not tokens:
        return ""
    scores = defaultdict(int)
    now = dt.datetime.utcnow()
    half_life_days = 14.0
    for tok in tokens[:8]:
        rows = AccountSuggestionHint.query.filter_by(user_id=user_id, kind=kind, token=tok).all()
        for r in rows:
            age_days = 0.0
            try:
                age_days = max(0.0, (now - (r.updated_at or now)).total_seconds() / 86400.0)
            except Exception:
                age_days = 0.0
            recency_factor = 0.5 ** (age_days / half_life_days)
            hybrid_score = (r.count or 0) * (0.6 + 0.4 * recency_factor)
            scores[r.account_name] += hybrid_score
    if not scores:
        return ""
    return max(scores.items(), key=lambda kv: kv[1])[0]


def _compute_ml_line_features(
    date_str: str,
    description: str,
    currency: str,
    transaction_id: str,
    lines: List[Dict[str, object]],
    target_line_id: str,
    user_id: int | None = None,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    """Derive the feature payload expected by the ml-suggester for a specific line."""
    if not lines:
        raise ValueError("At least one line is required")
    account_cache = {}

    def _resolve_account(name: str):
        if not user_id or not name:
            return None
        key = (name or "").strip().lower()
        if not key:
            return None
        if key in account_cache:
            return account_cache[key]
        try:
            from finance_app.models.accounting_models import Account  # local import to avoid circular

            row = (
                Account.query.filter(Account.user_id == user_id)
                .filter(func.lower(Account.name) == key)
                .first()
            )
        except Exception:
            row = None
        account_cache[key] = row
        return row

    norm_lines = []
    known_account_ids = set()
    known_account_names = set()
    known_categories = set()
    known_currencies = set()
    for idx, raw in enumerate(lines):
        try:
            amount = float(raw.get("amount", 0.0) or 0.0)
        except Exception:
            amount = 0.0
        line_type = "debit" if (raw.get("dc") or "D").upper() == "D" else "credit"
        account_name = (raw.get("account") or "").strip()
        norm_entry = {
            "line_id": raw.get("line_id") or f"line-{idx}",
            "line_type": line_type,
            "amount": max(amount, 0.0),
            "account_name": account_name or None,
        }
        if account_name:
            known_account_names.add(account_name)
            acct = _resolve_account(account_name)
            if acct:
                norm_entry["account_id"] = acct.id
                norm_entry["account_category"] = acct.category.name if getattr(acct, "category", None) else None
                norm_entry["account_currency"] = acct.currency_code
                known_account_ids.add(acct.id)
                if getattr(acct, "category", None) and acct.category.name:
                    known_categories.add(acct.category.name)
                if getattr(acct, "currency_code", None):
                    known_currencies.add((acct.currency_code or "").upper())
        norm_lines.append(norm_entry)
    target = next((ln for ln in norm_lines if ln["line_id"] == target_line_id), None)
    if target is None:
        raise ValueError("target_line_id not found in lines")
    total_debit = sum(ln["amount"] for ln in norm_lines if ln["line_type"] == "debit")
    total_credit = sum(ln["amount"] for ln in norm_lines if ln["line_type"] == "credit")
    max_debit = max((ln["amount"] for ln in norm_lines if ln["line_type"] == "debit"), default=0.0)
    max_credit = max((ln["amount"] for ln in norm_lines if ln["line_type"] == "credit"), default=0.0)
    line_amount = target["amount"]
    if target["line_type"] == "debit":
        rel = (line_amount / total_debit) if total_debit else 0.0
        is_max = line_amount >= max_debit and max_debit > 0
    else:
        rel = (line_amount / total_credit) if total_credit else 0.0
        is_max = line_amount >= max_credit and max_credit > 0
    features = {
        "Transaction_ID": transaction_id,
        "Line_ID": target["line_id"],
        "Date": _normalize_date_for_ml(date_str),
        "Description": description or "",
        "Currency": (currency or "").upper(),
        "Line_Type": target["line_type"],
        "Amount": line_amount,
        "Transaction_Total_Debit": total_debit,
        "Transaction_Total_Credit": total_credit,
        "Relative_Amount": rel,
        "Is_Max_Line": bool(is_max),
        "Num_Debit_Lines": sum(1 for ln in norm_lines if ln["line_type"] == "debit"),
        "Num_Credit_Lines": sum(1 for ln in norm_lines if ln["line_type"] == "credit"),
        "Weekday": dt.date.fromisoformat(_normalize_date_for_ml(date_str)).weekday() if date_str else None,
        "Month": dt.date.fromisoformat(_normalize_date_for_ml(date_str)).month if date_str else None,
        "Description_Tokens": " ".join(_desc_tokens(description)),
    }
    features.update(
        {
            "Known_Account_Count": len(known_account_ids),
            "Known_Account_Names": ",".join(sorted(known_account_names)) if known_account_names else "",
            "Known_Account_Categories": ",".join(sorted(known_categories)) if known_categories else "",
            "Known_Account_Currencies": ",".join(sorted(known_currencies)) if known_currencies else "",
            "Target_Account_Name": target.get("account_name") or "",
            "Target_Account_Category": target.get("account_category"),
            "Target_Account_Currency": (target.get("account_currency") or currency or "").upper(),
            "Target_Account_Id": target.get("account_id"),
        }
    )
    if user_id:
        try:
            from finance_app.models.accounting_models import JournalEntry, JournalLine  # local import to avoid circular

            recent = (
                db.session.query(JournalLine.account_id)
                .join(JournalEntry, JournalEntry.id == JournalLine.journal_id)
                .filter(JournalEntry.user_id == user_id)
                .order_by(JournalEntry.id.desc())
                .limit(20)
                .all()
            )
            recent_account_ids = list({row[0] for row in recent if row[0] is not None})
            features["Recent_Account_Count"] = len(recent_account_ids)
            features["Recent_Accounts"] = ",".join(map(str, recent_account_ids[:10]))
        except Exception:
            features["Recent_Account_Count"] = 0
            features["Recent_Accounts"] = ""
    context = {
        "transaction_total_debit": total_debit,
        "transaction_total_credit": total_credit,
        "line_type": target["line_type"],
        "line_amount": line_amount,
        "known_accounts": list(known_account_ids),
        "known_categories": sorted(known_categories),
        "known_currencies": sorted(known_currencies),
    }
    return features, context
