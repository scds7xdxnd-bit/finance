import os

from finance_app import create_app, db
from finance_app.models.accounting_models import AccountSuggestionHint
from finance_app.services.ml_service import record_suggestion_hint

os.environ["DATABASE_URL"] = "sqlite:///:memory:"


def test_hint_decay_applies_on_update():
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    with app.app_context():
        db.create_all()
        user_id = 1
        record_suggestion_hint(user_id, "debit", "Coffee shop", "Cash", weight=5)
        first = AccountSuggestionHint.query.filter_by(user_id=user_id, token="coffee").first()
        assert first is not None
        initial = first.count
        record_suggestion_hint(user_id, "debit", "Coffee shop", "Cash", weight=1)
        updated = AccountSuggestionHint.query.filter_by(user_id=user_id, token="coffee").first()
        assert updated.count < initial + 1  # decay applied
