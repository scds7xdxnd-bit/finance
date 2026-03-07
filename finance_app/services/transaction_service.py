"""Transaction service helpers."""
from finance_app.extensions import db
from finance_app.models.accounting_models import Transaction


def delete_transaction_for_user(tx_id: int, user) -> bool:
    """
    Delete a transaction if the requesting user is authorized.

    Returns True if deleted, False if not found/unauthorized.
    """
    tx = db.session.get(Transaction, tx_id)
    if not tx:
        return False
    if not user or (not getattr(user, "is_admin", False) and tx.user_id != getattr(user, "id", None)):
        return False
    db.session.delete(tx)
    db.session.commit()
    return True
