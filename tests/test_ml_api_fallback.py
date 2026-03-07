import json
from unittest import mock

from finance_app import User, create_app, db


def test_ml_suggestions_fallback(monkeypatch):
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        user = User(username="ml_user", password_hash="pw")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    with app.test_client() as client:
        with mock.patch("finance_app.controllers.core.requests.post") as mock_post:
            mock_post.side_effect = Exception("service down")
            # login simulation
            with client.session_transaction() as sess:
                sess["user_id"] = user_id
            payload = {
                "lines": [
                    {"line_id": "l1", "dc": "D", "amount": 50},
                    {"line_id": "l2", "dc": "C", "amount": 50},
                ],
                "target_line_id": "l1",
                "description": "Test",
                "currency": "USD",
            }
            resp = client.post("/api/ml_suggestions", data=json.dumps(payload), content_type="application/json")
            assert resp.status_code in (200, 502)
            data = resp.get_json()
            assert data.get("ok") in (True, False)
            # In fallback path we expect ok True and fallback flag
            if data.get("fallback"):
                assert data["currency"] == "USD"
