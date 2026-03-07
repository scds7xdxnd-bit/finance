from finance_app.services.ml_service import _compute_ml_line_features


def test_compute_ml_line_features_enriches_tokens_and_dates():
    features, ctx = _compute_ml_line_features(
        "2024-05-10",
        "Lunch with vendor ABC",
        "USD",
        "tx-1",
        [
            {"line_id": "l1", "dc": "D", "amount": 100},
            {"line_id": "l2", "dc": "C", "amount": 100},
        ],
        "l1",
        user_id=None,
    )
    assert features["Currency"] == "USD"
    assert features["Weekday"] is not None
    assert features["Month"] == 5
    assert "lunch" in features["Description_Tokens"]


def test_compute_ml_line_features_adds_account_signals():
    from finance_app import create_app, db
    from finance_app.models.accounting_models import Account, AccountCategory
    from finance_app.models.user_models import User

    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        user = User(username="acct_user", password_hash="pw")
        db.session.add(user)
        db.session.commit()
        cat = AccountCategory(user_id=user.id, name="Cash", side="debit")
        db.session.add(cat)
        acct = Account(user_id=user.id, name="Cash", category=cat, currency_code="USD")
        db.session.add(acct)
        db.session.commit()

        features, ctx = _compute_ml_line_features(
            "2024-01-01",
            "Vendor payment",
            "usd",
            "txn-1",
            [
                {"line_id": "d1", "dc": "D", "amount": 120, "account": "Cash"},
                {"line_id": "c1", "dc": "C", "amount": 120, "account": "Revenue"},
            ],
            "d1",
            user_id=user.id,
        )
        assert features["Target_Account_Name"] == "Cash"
        assert features["Target_Account_Category"] == "Cash"
        assert features["Known_Account_Count"] >= 1
        assert "Cash" in features["Known_Account_Names"]
        assert ctx["known_accounts"]
