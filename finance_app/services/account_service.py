import secrets
import threading
from typing import Optional

from flask import current_app
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from finance_app.extensions import db
from finance_app.models.accounting_models import Account, AccountCategory, Transaction

_BG_JOBS: dict[str, dict] = {}


def _name_natural_key(name: str):
    try:
        import re

        parts = re.findall(r"\d+|\D+", (name or "").strip().lower())
        key = []
        for p in parts:
            if p.isdigit():
                key.append(int(p))
            else:
                key.append(p)
        return tuple(key)
    except Exception:
        return ((name or "").strip().lower(),)


def _account_sort_key(acc):
    code = (acc.code or "").strip()
    if code.isdigit():
        return (0, int(code), "")
    return (1,) + _name_natural_key(acc.name)


def get_canonical_account(user_id: int, name: Optional[str]):
    if not name:
        return None
    name = name.strip()
    if not name:
        return None
    return (
        Account.query.filter(
            Account.user_id == user_id, func.lower(Account.name) == name.lower(), Account.active.is_(True)
        )
        .order_by(Account.id.asc())
        .first()
    )


def ensure_account(user_id: int, name: Optional[str]):
    acc = get_canonical_account(user_id, name)
    if acc:
        return acc
    last = (
        Account.query.filter_by(user_id=user_id, category_id=None, active=True)
        .order_by(Account.order.desc())
        .first()
    )
    next_order = (last.order + 1) if last else 0
    acc = Account(user_id=user_id, name=(name or "").strip(), side="both", order=next_order)
    db.session.add(acc)
    db.session.commit()
    return acc


def _assign_missing_tx_account_ids(limit: int | None = None):
    """Assign debit/credit account FK ids for transactions missing them, based on names."""
    try:
        q = Transaction.query.filter(
            ((Transaction.debit_account_id == None) & (Transaction.debit_account != None))
            | ((Transaction.credit_account_id == None) & (Transaction.credit_account != None))
        )  # type: ignore
        if limit is not None:
            q = q.limit(int(limit))
        rows = q.all()
        updated = 0
        for t in rows:
            if t.debit_account and not t.debit_account_id:
                acc = ensure_account(t.user_id, t.debit_account)
                if acc:
                    t.debit_account_id = acc.id
            if t.credit_account and not t.credit_account_id:
                acc = ensure_account(t.user_id, t.credit_account)
                if acc:
                    t.credit_account_id = acc.id
            updated += 1
        if updated:
            db.session.commit()
    except Exception:
        db.session.rollback()


def start_background_assign_account_ids(user_id: int | None = None, chunk_size: int = 1000):
    """Kick off a background job to fill in missing account ids."""
    app = current_app._get_current_object()
    job_id = secrets.token_hex(8)
    _BG_JOBS[job_id] = {"status": "running", "processed": 0, "kind": "assign_account_ids"}

    def worker():
        try:
            with app.app_context():
                SessionLocal = sessionmaker(bind=db.engine)
                session = SessionLocal()
                try:
                    q = session.query(Transaction)
                    if user_id is not None:
                        q = q.filter(Transaction.user_id == int(user_id))
                    total = q.count()
                    _BG_JOBS[job_id]["total"] = total
                    offset = 0
                    while True:
                        batch = q.offset(offset).limit(chunk_size).all()
                        if not batch:
                            break
                        for t in batch:
                            try:
                                def _get_acc(u_id, acc_name):
                                    if not acc_name:
                                        return None
                                    return (
                                        session.query(Account)
                                        .filter(
                                            Account.user_id == u_id,
                                            func.lower(Account.name) == (acc_name or "").strip().lower(),
                                            Account.active == True,
                                        )
                                        .order_by(Account.id.asc())
                                        .first()
                                    )

                                def _ensure_acc(u_id, acc_name):
                                    acc = _get_acc(u_id, acc_name)
                                    if acc:
                                        return acc
                                    last = (
                                        session.query(Account)
                                        .filter_by(user_id=u_id, category_id=None, active=True)
                                        .order_by(Account.order.desc())
                                        .first()
                                    )
                                    next_order = (last.order + 1) if last else 0
                                    acc = Account(user_id=u_id, name=(acc_name or "").strip(), side="both", order=next_order)
                                    session.add(acc)
                                    session.flush()
                                    return acc

                                if t.debit_account and not t.debit_account_id:
                                    acc = _ensure_acc(t.user_id, t.debit_account)
                                    if acc:
                                        t.debit_account_id = acc.id
                                if t.credit_account and not t.credit_account_id:
                                    acc = _ensure_acc(t.user_id, t.credit_account)
                                    if acc:
                                        t.credit_account_id = acc.id
                            except Exception:
                                continue
                        session.commit()
                        offset += len(batch)
                        _BG_JOBS[job_id]["processed"] = offset
                    _BG_JOBS[job_id]["status"] = "completed"
                finally:
                    session.close()
        except Exception as e:
            _BG_JOBS[job_id]["status"] = "failed"
            _BG_JOBS[job_id]["error"] = str(e)

    threading.Thread(target=worker, daemon=True).start()
    return job_id


def _category_prefix(cat_id: int | None) -> str:
    return f"F{int(cat_id or 0):02d}"


def generate_account_code(cat_id: int | None, position: int, acc_id: int, currency_code: str | None = "KRW") -> str:
    """Construct an account code using folder and position with a stable suffix."""
    ccy = (currency_code or "KRW").upper()
    return f"{ccy}-{_category_prefix(cat_id)}-{int(position):03d}-A{int(acc_id):04d}"


def assign_codes_for_user(user_id: int, refresh: bool = False):
    """Assign or refresh codes to accounts for a specific user."""
    groups = [None] + [
        c.id for c in AccountCategory.query.filter_by(user_id=user_id).order_by(AccountCategory.order.asc(), AccountCategory.id.asc()).all()
    ]
    for gid in groups:
        accs = Account.query.filter_by(user_id=user_id, category_id=gid, active=True).all()
        accs.sort(key=_account_sort_key)
        for idx, a in enumerate(accs, start=1):
            if refresh or not (a.code or "").strip():
                a.code = generate_account_code(gid, idx, a.id, getattr(a, "currency_code", "KRW"))
    db.session.commit()


def create_account(user_id: int, name: str, code: str | None = None, category_id: int | None = None):
    """Create an account for a user with ordering and optional category validation."""
    name = (name or "").strip()
    code = (code or "").strip() or None
    if not name:
        return None, "Invalid inputs"
    if category_id:
        cat = AccountCategory.query.get(category_id)
        if not cat or cat.user_id != user_id:
            return None, "Category not found"
    last = (
        Account.query.filter_by(user_id=user_id, category_id=category_id)
        .order_by(Account.order.desc())
        .first()
    )
    next_order = (last.order + 1) if last else 0
    acc = Account(user_id=user_id, name=name, side="both", code=code, category_id=category_id, order=next_order)
    db.session.add(acc)
    db.session.commit()
    if not (acc.code or "").strip():
        try:
            assign_codes_for_user(user_id, refresh=False)
        except Exception:
            db.session.rollback()
            return acc, "Failed to assign code"
    return acc, None


def add_category(user_id: int, name: str):
    """Create an account category for a user."""
    name = (name or "").strip()
    if not name:
        return None, "Invalid inputs"
    last = (
        AccountCategory.query.filter_by(user_id=user_id)
        .order_by(AccountCategory.order.desc())
        .first()
    )
    next_order = (last.order + 1) if last else 0
    cat = AccountCategory(user_id=user_id, name=name, side="both", order=next_order)
    db.session.add(cat)
    db.session.commit()
    return cat, None


def move_account_to_category(user_id: int, account_id: int, to_category_id: int | None, order_hint: int | None = None):
    """Move an account to a category and re-sequence orders."""
    acc = db.session.get(Account, account_id)
    if not acc or acc.user_id != user_id:
        return {"ok": False, "error": "Account not found"}, 404
    if to_category_id:
        cat = db.session.get(AccountCategory, to_category_id)
        if not cat or cat.user_id != user_id:
            return {"ok": False, "error": "Target category invalid"}, 400
    old_category_id = acc.category_id
    acc.category_id = to_category_id

    # Resort source and target groups
    def _resort(cat_id: int | None):
        sibs = Account.query.filter_by(user_id=user_id, category_id=cat_id, active=True).all()
        sibs.sort(key=_account_sort_key)
        for i, s in enumerate(sibs):
            s.order = i

    _resort(old_category_id)
    _resort(to_category_id)

    db.session.commit()
    return {"ok": True}


def bulk_move_accounts(user_id: int, account_ids: list[int], to_category_id: int | None):
    """Bulk move accounts to a category and resort."""
    if to_category_id:
        cat = db.session.get(AccountCategory, to_category_id)
        if not cat or cat.user_id != user_id:
            return {"ok": False, "error": "Target category invalid"}, 400
    moved: list[int] = []
    for aid in account_ids:
        acc = db.session.get(Account, int(aid))
        if not acc or acc.user_id != user_id:
            continue
        acc.category_id = to_category_id
        moved.append(acc.id)
    # Resort all groups for this user
    cats = [c.id for c in AccountCategory.query.filter_by(user_id=user_id).all()] + [None]
    for cid in cats:
        sibs = Account.query.filter_by(user_id=user_id, category_id=cid, active=True).all()
        sibs.sort(key=_account_sort_key)
        for i, s in enumerate(sibs):
            s.order = i
    db.session.commit()
    return {"ok": True, "moved": moved, "category_id": to_category_id}


def bulk_unassign_accounts(user_id: int, account_ids: list[int]):
    """Bulk unassign accounts (set category to None) and resort unassigned group."""
    updated: list[int] = []
    for aid in account_ids:
        acc = db.session.get(Account, int(aid))
        if not acc or acc.user_id != user_id:
            continue
        acc.category_id = None
        updated.append(acc.id)
    sibs = Account.query.filter_by(user_id=user_id, category_id=None, active=True).all()
    sibs.sort(key=_account_sort_key)
    for i, s in enumerate(sibs):
        s.order = i
    db.session.commit()
    return {"ok": True, "updated": updated}
