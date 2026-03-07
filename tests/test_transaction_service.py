import pytest
from finance_app import db
from finance_app.models.accounting_models import Transaction
from finance_app.models.user_models import User
from finance_app.services.transaction_service import delete_transaction_for_user
from flask import Flask


@pytest.fixture()
def isolated_app():
    """Provide an isolated app context bound to a fresh in-memory engine."""
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_delete_transaction_service(isolated_app):
    with isolated_app.app_context():
        admin = User(username="admin", password_hash="x", is_admin=True)
        user = User(username="user", password_hash="y", is_admin=False)
        db.session.add_all([admin, user])
        db.session.flush()

        tx = Transaction(user_id=user.id, description="Test", debit_amount=10, credit_amount=0)
        db.session.add(tx)
        db.session.commit()

        assert delete_transaction_for_user(tx.id, user) is True
        assert db.session.get(Transaction, tx.id) is None

        tx2 = Transaction(user_id=user.id, description="Test2", debit_amount=5, credit_amount=0)
        db.session.add(tx2)
        db.session.commit()

        assert delete_transaction_for_user(tx2.id, admin) is True
        assert db.session.get(Transaction, tx2.id) is None
