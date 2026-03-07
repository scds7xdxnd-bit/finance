import datetime as dt
import json
import os

# Ensure an isolated in-memory database for these tests
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
from finance_app import User, create_app, db
from finance_app.models.accounting_models import AccountSuggestionHint, AccountSuggestionLog
from finance_app.services.ml_service import best_hint_suggestion, record_suggestion_hint


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def test_ml_suggestions_includes_latency_and_model_hash(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True, MLSUGGESTER_PREFER_USER_MODEL=False, MLSUGGESTER_USER_ONLY=False)
    with app.app_context():
        db.create_all()
        user = User(username="mlshape", password_hash="pw")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "currency": "USD",
                "top_k": 1,
                "model_version": "v1.2.3",
                "model_hash": "abc123hash",
                "results": [
                    {
                        "predictions": [
                            {"account_name": "Cash", "probability": 0.8},
                        ]
                    }
                ],
            }

    with app.test_client() as client:
        monkeypatch.setattr("finance_app.controllers.core.requests.post", lambda *a, **k: _Resp())
        _login(client, user_id)
        payload = {
            "lines": [
                {"line_id": "l1", "dc": "D", "amount": 50},
                {"line_id": "l2", "dc": "C", "amount": 50},
            ],
            "target_line_id": "l1",
            "description": "Shape check",
            "currency": "USD",
        }
        resp = client.post("/api/ml_suggestions", data=json.dumps(payload), content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["model_version"] == "v1.2.3"
        assert data["model_version_hash"] == "abc123hash"
        assert data["latency_ms"] >= 0
        assert data["fallback"] is False
        assert "request_id" in data


def test_logging_persists_latency_error_and_status(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        user = User(username="logger", password_hash="pw")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    with app.test_client() as client:
        _login(client, user_id)
        logs = [
            {
                "transaction_id": "t1",
                "line_id": "l1",
                "line_type": "debit",
                "currency": "USD",
                "model_version": "v1",
                "model_hash": "deadbeef",
                "predictions": [],
                "features": {},
                "responded_at": dt.datetime.utcnow().isoformat(),
                "request_id": "req-1",
                "latency_ms": 123,
                "fallback": True,
                "error": "timeout",
                "error_code": "Timeout",
                "status": "error",
                "description": "log check",
            }
        ]
        resp = client.post("/api/suggestions/log", data=json.dumps({"logs": logs}), content_type="application/json")
        assert resp.status_code == 200
        with app.app_context():
            rec = AccountSuggestionLog.query.first()
            assert rec is not None
            assert rec.raw_features["latency_ms"] == 123
            assert rec.raw_features["fallback"] is True
            assert rec.raw_features["error_code"] == "Timeout"
            assert rec.raw_features["status"] == "error"
            assert rec.raw_features["model_hash"] == "deadbeef"


def test_hint_decay_prefers_recent_hint(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        user_id = 1
        now = dt.datetime(2024, 1, 1, 12, 0, 0)
        # Old strong hint
        old_hint = AccountSuggestionHint(
            user_id=user_id, kind="debit", token="coffee", account_name="OldCash", count=30, updated_at=now - dt.timedelta(days=60)
        )
        db.session.add(old_hint)
        db.session.commit()

        # Patch utcnow to a newer time when adding a fresh hint
        monkeypatch.setattr("finance_app.services.ml_service.dt.datetime", type("dtm", (), {"utcnow": staticmethod(lambda: now)}))
        record_suggestion_hint(user_id, "debit", "Coffee shop", "FreshCash", weight=20)
        choice = best_hint_suggestion(user_id, "debit", "Coffee shop")
        assert choice == "FreshCash"
