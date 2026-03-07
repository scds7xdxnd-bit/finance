"""Trial balance related service helpers."""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Tuple

from sqlalchemy import and_, or_

from finance_app.extensions import db
from finance_app.models.accounting_models import (
    Account,
    AccountCategory,
    AccountOpeningBalance,
    TBResetSnapshot,
    TrialBalanceSetting,
)


def set_initialization(user_id: int, initialized_on: str) -> dict:
    """Set or update trial balance initialization date."""
    if not initialized_on:
        return {"ok": False, "error": "Initialization date required"}
    try:
        init_date = _dt.datetime.strptime(initialized_on.strip(), "%Y-%m-%d").date()
    except Exception:
        return {"ok": False, "error": "Invalid initialization date"}
    row = TrialBalanceSetting.query.filter_by(user_id=user_id).first()
    if not row:
        row = TrialBalanceSetting(user_id=user_id, initialized_on=init_date)
        db.session.add(row)
    else:
        row.initialized_on = init_date
    db.session.commit()
    return {"ok": True, "initialized_on": init_date.isoformat()}


def reset_data(user_id: int) -> dict:
    """Clear TB grouping and opening balances for the user."""
    AccountCategory.query.filter_by(user_id=user_id).update({AccountCategory.tb_group: None}, synchronize_session=False)
    AccountOpeningBalance.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    tbs = TrialBalanceSetting.query.filter_by(user_id=user_id).first()
    if tbs:
        tbs.first_month = None
        tbs.initialized_on = None
    db.session.commit()
    return {"ok": True}


def _prune_tb_snapshots(user_id: int, keep_max: int = 20, max_days: int = 30) -> None:
    cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=max_days)
    rows = (
        TBResetSnapshot.query.filter_by(user_id=user_id)
        .order_by(TBResetSnapshot.created_at.desc())
        .all()
    )
    for idx, row in enumerate(rows, start=1):
        too_old = bool(row.created_at and row.created_at < cutoff)
        over_limit = idx > keep_max
        if not (too_old or over_limit):
            continue
        try:
            path = Path(row.db_copy_path or "")
            if path.exists():
                path.unlink()
        except Exception:
            pass
        db.session.delete(row)


def create_tb_snapshot(user_id: int, reason: str | None = None, created_by_admin_id: int | None = None) -> dict:
    """Create a SQLite file snapshot and persist metadata for TB reset safety."""
    db_url = str(db.engine.url)
    if not db_url.startswith("sqlite:///"):
        return {"ok": False, "error": "TB snapshot currently supports SQLite only."}
    db_path = Path(db_url.replace("sqlite:///", "", 1))
    if not db_path.exists():
        return {"ok": False, "error": "Database file not found."}

    out_dir = Path("instance") / "backups" / "tb_reset"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{ts}_{user_id}.db"

    try:
        with sqlite3.connect(str(db_path)) as src_conn:
            with sqlite3.connect(str(out_path)) as dst_conn:
                src_conn.backup(dst_conn)
    except Exception as exc:
        return {"ok": False, "error": f"Failed to create snapshot: {exc}"}

    try:
        content = out_path.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        size = out_path.stat().st_size
    except Exception as exc:
        return {"ok": False, "error": f"Failed to verify snapshot: {exc}"}

    row = TBResetSnapshot(
        user_id=user_id,
        db_copy_path=str(out_path),
        sha256=sha,
        file_size_bytes=int(size),
        reason=(reason or "")[:255] or None,
        created_by_admin_id=created_by_admin_id,
        restore_status="created",
    )
    db.session.add(row)
    _prune_tb_snapshots(user_id=user_id, keep_max=20, max_days=30)
    db.session.commit()
    return {"ok": True, "snapshot_id": row.id, "db_copy_path": str(out_path), "sha256": sha, "file_size_bytes": int(size)}


def set_first_month(user_id: int, ym: str) -> dict:
    """Set the first trial balance month for the user."""
    if not ym:
        return {"ok": False, "error": "Month is required"}
    try:
        y, m = ym.split("-")
        first = _dt.date(int(y), int(m), 1)
    except Exception:
        return {"ok": False, "error": "Invalid month"}
    row = TrialBalanceSetting.query.filter_by(user_id=user_id).first()
    if not row:
        row = TrialBalanceSetting(user_id=user_id, first_month=first)
        db.session.add(row)
    else:
        row.first_month = first
    db.session.commit()
    return {"ok": True, "ym": ym}


def _parse_ym(ym: str) -> Tuple[str, _dt.date, _dt.date, str, str]:
    year_str, month_str = ym.split("-")
    year = int(year_str)
    month = int(month_str)
    first_day = _dt.date(year, month, 1)
    if month == 12:
        last_day = _dt.date(year + 1, 1, 1) - _dt.timedelta(days=1)
    else:
        last_day = _dt.date(year, month + 1, 1) - _dt.timedelta(days=1)
    first_str = f"{first_day.year}/{str(first_day.month).zfill(2)}/{str(first_day.day).zfill(2)}"
    last_str = f"{last_day.year}/{str(last_day.month).zfill(2)}/{str(last_day.day).zfill(2)}"
    return ym, first_day, last_day, first_str, last_str


def monthly(user_id: int, ym: str | None, currency: str | None = None) -> dict:
    """Compute monthly trial balance aggregates."""
    if not ym:
        today = _dt.date.today()
        ym = f"{today.year:04d}-{today.month:02d}"
    try:
        ym_norm, first_day, last_day, first_str, last_str = _parse_ym(ym.strip())
    except Exception:
        return {"ok": False, "error": "Invalid ym parameter. Use YYYY-MM."}

    try:
        from finance_app import JournalEntry, JournalLine  # local import to avoid circulars
    except Exception:
        return {"ok": False, "error": "Journal model not available"}

    tbs = TrialBalanceSetting.query.filter_by(user_id=user_id).first()
    init_date = None
    init_str = None
    if tbs and tbs.initialized_on:
        init_date = tbs.initialized_on
        try:
            init_str = f"{init_date.year}/{str(init_date.month).zfill(2)}/{str(init_date.day).zfill(2)}"
        except Exception:
            init_str = None
        if init_date and last_day < init_date:
            empty_groups = {k: [] for k in ("asset", "liability", "equity", "expense", "income")}
            empty_totals = {
                k: {"bd": 0.0, "balance": 0.0, "period_debit": 0.0, "period_credit": 0.0, "period_net": 0.0}
                for k in empty_groups.keys()
            }
            grand = {"bd": 0.0, "balance": 0.0, "period_debit": 0.0, "period_credit": 0.0, "period_net": 0.0}
            return {
                "ok": True,
                "ym": ym_norm,
                "groups": empty_groups,
                "totals": empty_totals,
                "grand_totals": grand,
                "initialized_on": init_date.isoformat(),
                "message": "Selected period is before your initialization date.",
            }

    period_start = first_day
    period_start_str = first_str
    if init_date and init_date > period_start:
        period_start = init_date
        period_start_str = f"{period_start.year}/{str(period_start.month).zfill(2)}/{str(period_start.day).zfill(2)}"

    cats = AccountCategory.query.filter_by(user_id=user_id).all()
    cat_by_id = {c.id: c for c in cats}
    acc_rows = Account.query.filter_by(user_id=user_id, active=True).all()
    if currency:
        currency = currency.upper()
        acc_rows = [a for a in acc_rows if (a.currency_code or "KRW").upper() == currency]
    acc_to_cat = {a.id: a.category_id for a in acc_rows}
    acc_name = {a.id: (a.name or "") for a in acc_rows}
    acc_code = {a.id: (a.code or "") for a in acc_rows}
    acc_ccy = {a.id: ((a.currency_code or "KRW").upper()) for a in acc_rows}

    ob_rows = AccountOpeningBalance.query.filter_by(user_id=user_id).all()
    ob_by_acc = {r.account_id: float(r.amount or 0.0) for r in ob_rows}

    jlq_eom = db.session.query(JournalLine, JournalEntry).join(JournalEntry, JournalLine.journal_id == JournalEntry.id)
    jlq_eom = jlq_eom.filter(JournalEntry.user_id == user_id)
    jlq_eom = jlq_eom.filter(
        or_(JournalEntry.date_parsed <= last_day, and_(JournalEntry.date_parsed == None, JournalEntry.date <= last_str))  # type: ignore # noqa: E711
    )
    if init_date:
        jlq_eom = jlq_eom.filter(
            or_(JournalEntry.date_parsed >= init_date, and_(JournalEntry.date_parsed == None, JournalEntry.date >= init_str))  # type: ignore # noqa: E711
        )
    rows_eom = jlq_eom.all()

    prev_last_day = first_day - _dt.timedelta(days=1)
    prev_last_str = f"{prev_last_day.year}/{str(prev_last_day.month).zfill(2)}/{str(prev_last_day.day).zfill(2)}"
    jlq_prev = db.session.query(JournalLine, JournalEntry).join(JournalEntry, JournalLine.journal_id == JournalEntry.id)
    jlq_prev = jlq_prev.filter(JournalEntry.user_id == user_id)
    jlq_prev = jlq_prev.filter(
        or_(
            JournalEntry.date_parsed <= prev_last_day,
            and_(JournalEntry.date_parsed == None, JournalEntry.date <= prev_last_str),
        )  # type: ignore # noqa: E711
    )
    if init_date:
        jlq_prev = jlq_prev.filter(
            or_(JournalEntry.date_parsed >= init_date, and_(JournalEntry.date_parsed == None, JournalEntry.date >= init_str))  # type: ignore # noqa: E711
        )
    rows_prev = jlq_prev.all()

    jlq_period = db.session.query(JournalLine, JournalEntry).join(JournalEntry, JournalLine.journal_id == JournalEntry.id)
    jlq_period = jlq_period.filter(JournalEntry.user_id == user_id)
    jlq_period = jlq_period.filter(
        or_(
            and_(JournalEntry.date_parsed >= period_start, JournalEntry.date_parsed <= last_day),
            and_(JournalEntry.date_parsed == None, JournalEntry.date >= period_start_str, JournalEntry.date <= last_str),
        )  # type: ignore # noqa: E711
    )
    rows_period = jlq_period.all()

    groups = {k: {} for k in ("asset", "liability", "equity", "expense", "income")}

    def _cat_group(cat_id):
        cat = cat_by_id.get(cat_id)
        return (cat.tb_group or "").strip().lower() if cat else ""

    def _add_amount(target_dict, acc_id, debit_amt, credit_amt):
        target_dict.setdefault(acc_id, {"debit": 0.0, "credit": 0.0})
        target_dict[acc_id]["debit"] += float(debit_amt or 0.0)
        target_dict[acc_id]["credit"] += float(credit_amt or 0.0)

    bd_balances = {}
    for line, entry in rows_prev:
        grp = _cat_group(acc_to_cat.get(line.account_id))
        if grp not in groups:
            continue
        debit = line.amount_base if (line.dc or "").upper() == "D" else 0.0
        credit = line.amount_base if (line.dc or "").upper() == "C" else 0.0
        _add_amount(bd_balances.setdefault(grp, {}), line.account_id, debit, credit)

    eom_balances = {}
    for line, entry in rows_eom:
        grp = _cat_group(acc_to_cat.get(line.account_id))
        if grp not in groups:
            continue
        debit = line.amount_base if (line.dc or "").upper() == "D" else 0.0
        credit = line.amount_base if (line.dc or "").upper() == "C" else 0.0
        _add_amount(eom_balances.setdefault(grp, {}), line.account_id, debit, credit)

    period_movements = {}
    for line, entry in rows_period:
        grp = _cat_group(acc_to_cat.get(line.account_id))
        if grp not in groups:
            continue
        debit = line.amount_base if (line.dc or "").upper() == "D" else 0.0
        credit = line.amount_base if (line.dc or "").upper() == "C" else 0.0
        _add_amount(period_movements.setdefault(grp, {}), line.account_id, debit, credit)

    groups_out = {k: {} for k in groups.keys()}  # grp -> cat_id -> payload
    totals = {
        k: {"bd": 0.0, "balance": 0.0, "period_debit": 0.0, "period_credit": 0.0, "period_net": 0.0}
        for k in groups.keys()
    }
    grand = {"bd": 0.0, "balance": 0.0, "period_debit": 0.0, "period_credit": 0.0, "period_net": 0.0}

    for acc_id, cat_id in acc_to_cat.items():
        grp = _cat_group(cat_id)
        if grp not in groups_out:
            continue
        if currency and acc_ccy.get(acc_id) != currency:
            continue
        bd_row = bd_balances.get(grp, {}).get(acc_id, {"debit": 0.0, "credit": 0.0})
        eom_row = eom_balances.get(grp, {}).get(acc_id, {"debit": 0.0, "credit": 0.0})
        period_row = period_movements.get(grp, {}).get(acc_id, {"debit": 0.0, "credit": 0.0})

        opening_balance = ob_by_acc.get(acc_id, 0.0)
        is_credit_nature = grp in ("liability", "equity", "income")

        period_debit = period_row["debit"]
        period_credit = period_row["credit"]
        if is_credit_nature:
            bd = opening_balance + bd_row["credit"] - bd_row["debit"]
            balance = opening_balance + eom_row["credit"] - eom_row["debit"]
            period_net = period_credit - period_debit
        else:
            bd = opening_balance + bd_row["debit"] - bd_row["credit"]
            balance = opening_balance + eom_row["debit"] - eom_row["credit"]
            period_net = period_debit - period_credit

        cat_payload = groups_out[grp].get(cat_id)
        if not cat_payload:
            cat_payload = {
                "category_id": cat_id,
                "category_name": (cat_by_id.get(cat_id).name if cat_by_id.get(cat_id) else ""),
                "currency": acc_ccy.get(acc_id, "KRW"),
                "bd": 0.0,
                "balance": 0.0,
                "period_debit": 0.0,
                "period_credit": 0.0,
                "period_net": 0.0,
                "accounts": [],
            }
            groups_out[grp][cat_id] = cat_payload

        cat_payload["bd"] += bd
        cat_payload["balance"] += balance
        cat_payload["period_debit"] += period_debit
        cat_payload["period_credit"] += period_credit
        cat_payload["period_net"] += period_net
        cat_payload.setdefault("accounts", []).append(
            {
                "id": acc_id,
                "name": acc_name.get(acc_id, ""),
                "code": acc_code.get(acc_id, ""),
                "currency": acc_ccy.get(acc_id, "KRW"),
                "bd": round(bd, 2),
                "balance": round(balance, 2),
                "period_debit": round(period_debit, 2),
                "period_credit": round(period_credit, 2),
                "period_net": round(period_net, 2),
            }
        )

        totals[grp]["bd"] += bd
        totals[grp]["balance"] += balance
        totals[grp]["period_debit"] += period_debit
        totals[grp]["period_credit"] += period_credit
        totals[grp]["period_net"] += period_net

        grand["bd"] += bd
        grand["balance"] += balance
        grand["period_debit"] += period_debit
        grand["period_credit"] += period_credit
        grand["period_net"] += period_net

    # Convert category maps to sorted lists and round folder totals
    for grp in groups_out:
        cat_map = groups_out[grp]
        cats_list = []
        for _, payload in cat_map.items():
            payload["bd"] = round(payload.get("bd", 0.0), 2)
            payload["balance"] = round(payload.get("balance", 0.0), 2)
            payload["period_debit"] = round(payload.get("period_debit", 0.0), 2)
            payload["period_credit"] = round(payload.get("period_credit", 0.0), 2)
            payload["period_net"] = round(payload.get("period_net", 0.0), 2)
            # Filter accounts by currency if requested (defensive even though acc_rows already filtered)
            accounts = payload.get("accounts", [])
            if currency:
                accounts = [a for a in accounts if (a.get("currency") or "").upper() == currency]
            payload["accounts"] = sorted(accounts, key=lambda row: (row.get("name") or ""))
            if payload["accounts"]:
                cats_list.append(payload)
        groups_out[grp] = sorted(cats_list, key=lambda row: (row.get("category_name") or ""))

    return {
        "ok": True,
        "ym": ym_norm,
        "groups": groups_out,
        "totals": {k: {kk: round(vv, 2) for kk, vv in totals[k].items()} for k in totals},
        "grand_totals": {k: round(v, 2) for k, v in grand.items()},
        "initialized_on": init_date.isoformat() if init_date else None,
    }
