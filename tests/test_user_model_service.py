import json
import os
import time

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from finance_app import User, create_app, db  # noqa: E402
from finance_app.models.accounting_models import AccountSuggestionLog  # noqa: E402
from finance_app.services.account_service import _BG_JOBS  # noqa: E402
from finance_app.services.user_model_service import (  # noqa: E402
    predict_user_model,
    start_background_user_model_training,
    train_user_model,
    user_model_status,
)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def test_user_models_are_isolated(tmp_path, monkeypatch):
    app = create_app()
    app.config.update(
        TESTING=True,
        MLSUGGESTER_USER_MODEL_DIR=str(tmp_path),
        MLSUGGESTER_USER_MODEL_MIN_ROWS=1,
        MLSUGGESTER_PREFER_USER_MODEL=True,
    )
    with app.app_context():
        db.create_all()
        ua = User(username="a", password_hash="pw")
        ub = User(username="b", password_hash="pw")
        db.session.add_all([ua, ub])
        db.session.commit()
        # User A prefers Cash
        db.session.add(
            AccountSuggestionLog(
                user_id=ua.id,
                currency="USD",
                transaction_id="t1",
                line_id="l1",
                line_type="debit",
                chosen_account="Cash",
                description="coffee shop purchase",
            )
        )
        # User B prefers Bank
        db.session.add(
            AccountSuggestionLog(
                user_id=ub.id,
                currency="USD",
                transaction_id="t2",
                line_id="l2",
                line_type="debit",
                chosen_account="Bank",
                description="coffee shop purchase",
            )
        )
        db.session.commit()
        train_user_model(ua.id, min_rows=1)
        train_user_model(ub.id, min_rows=1)
        preds_a, _ = predict_user_model(ua.id, "debit", "coffee at cafe", top_k=3)
        preds_b, _ = predict_user_model(ub.id, "debit", "coffee at cafe", top_k=3)
        assert preds_a and preds_a[0]["account_name"] == "Cash"
        assert preds_b and preds_b[0]["account_name"] == "Bank"


def test_ml_endpoint_uses_user_model_when_available(tmp_path, monkeypatch):
    app = create_app()
    app.config.update(
        TESTING=True,
        MLSUGGESTER_USER_MODEL_DIR=str(tmp_path),
        MLSUGGESTER_USER_MODEL_MIN_ROWS=1,
        MLSUGGESTER_PREFER_USER_MODEL=True,
        MLSUGGESTER_USER_ONLY=False,
    )
    with app.app_context():
        db.create_all()
        user = User(username="solo", password_hash="pw")
        db.session.add(user)
        db.session.commit()
        db.session.add(
            AccountSuggestionLog(
                user_id=user.id,
                currency="USD",
                transaction_id="t1",
                line_id="l1",
                line_type="debit",
                chosen_account="Supplies",
                description="office supplies",
            )
        )
        db.session.commit()
        train_user_model(user.id, min_rows=1)

    # Ensure we do not call the remote suggester if the user model answers
    def _fail_remote(*args, **kwargs):
        raise AssertionError("remote suggester should not be called when user model exists")

    monkeypatch.setattr("finance_app.controllers.core.requests.post", _fail_remote)

    with app.test_client() as client:
        _login(client, user.id)
        payload = {
            "lines": [
                {"line_id": "l1", "dc": "D", "amount": 50},
                {"line_id": "l2", "dc": "C", "amount": 50},
            ],
            "target_line_id": "l1",
            "description": "Office supplies purchase",
            "currency": "USD",
        }
        resp = client.post("/api/ml_suggestions", data=json.dumps(payload), content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "user_model"
        assert data["predictions"][0]["account_name"] == "Supplies"


def test_user_model_status_and_background_job(tmp_path):
    app = create_app()
    app.config.update(
        TESTING=True,
        MLSUGGESTER_USER_MODEL_DIR=str(tmp_path),
        MLSUGGESTER_USER_MODEL_MIN_ROWS=1,
    )
    with app.app_context():
        db.create_all()
        user = User(username="bg", password_hash="pw")
        db.session.add(user)
        db.session.commit()
        db.session.add(
            AccountSuggestionLog(
                user_id=user.id,
                currency="USD",
                transaction_id="t1",
                line_id="l1",
                line_type="debit",
                chosen_account="Cash",
                description="coffee",
            )
        )
        db.session.commit()
        train_user_model(user.id, min_rows=1)
        # Add another log to make status show needs_train
        db.session.add(
            AccountSuggestionLog(
                user_id=user.id,
                currency="USD",
                transaction_id="t2",
                line_id="l2",
                line_type="debit",
                chosen_account="Bank",
                description="coffee again",
            )
        )
        db.session.commit()
        status = user_model_status(user.id, min_rows=1)
        assert status["needs_train"] is True

    with app.app_context():
        job_id = start_background_user_model_training(user.id, min_rows=1)
        # Simulate admin API session
        admin = User(username="adminpoll", password_hash="pw", is_admin=True)
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id
    # Wait for job to finish
    for _ in range(20):
        if _BG_JOBS.get(job_id, {}).get("status") in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert _BG_JOBS.get(job_id, {}).get("status") == "completed"

    # Verify admin API returns statuses
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = admin_id
        resp = client.get("/admin/api/user-models/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert any(st["user_id"] == user.id for st in data["statuses"])
