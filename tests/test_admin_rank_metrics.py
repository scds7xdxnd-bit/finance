import datetime as dt
import os

import pytest

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from blueprints.admin import _aggregate_log_metrics  # noqa: E402
from finance_app import User, create_app, db  # noqa: E402
from finance_app.models.accounting_models import AccountSuggestionLog  # noqa: E402


def _login_admin(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def test_rank_metrics_from_logs_and_api():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
        admin = User(username="admin", password_hash="pw", is_admin=True)
        db.session.add(admin)
        db.session.commit()
        uid = admin.id
        now = dt.datetime.utcnow()
        logs = [
            AccountSuggestionLog(
                user_id=uid,
                currency="USD",
                transaction_id="t1",
                line_id="l1",
                line_type="debit",
                predictions=[],
                raw_features={"chosen_rank": 1, "reward": 1.0, "mrr": 1.0, "status": "ok", "latency_ms": 120, "model_hash": "m1"},
                created_at=now,
            ),
            AccountSuggestionLog(
                user_id=uid,
                currency="USD",
                transaction_id="t2",
                line_id="l2",
                line_type="credit",
                predictions=[],
                raw_features={"chosen_rank": 3, "reward": 0.2, "mrr": 1/3, "status": "fallback", "fallback": True, "latency_ms": 260, "model_version_hash": "m1"},
                created_at=now,
            ),
            AccountSuggestionLog(
                user_id=uid,
                currency="USD",
                transaction_id="t3",
                line_id="l3",
                line_type="debit",
                predictions=[],
                raw_features={"reward": -1.0, "mrr": 0.0, "status": "error", "error": "timeout", "latency_ms": 400, "model_hash": "m2"},
                created_at=now,
            ),
        ]
        db.session.add_all(logs)
        db.session.commit()

        metrics = _aggregate_log_metrics(uid_int=uid)
        assert metrics["coverage_total"] == 3
        assert metrics["rank_counts"].get(1) == 1
        assert metrics["rank_counts"].get(3) == 1
        assert metrics["rank_counts"].get("manual") == 1
        assert metrics["fallback_total"] == 1
        assert metrics["errors_total"] == 1
        assert metrics["model_hashes"].get("m1") == 2  # counts hash + version hash fallback
        assert metrics["avg_reward"] == pytest.approx(1 / 15)
        assert metrics["avg_mrr"] == pytest.approx((1 + (1/3) + 0.0) / 3)
        assert metrics["top1_rate"] == pytest.approx(1 / 3)

    with app.test_client() as client:
        _login_admin(client, uid)
        resp = client.get("/admin/api/suggestions/metrics")
        assert resp.status_code == 200
        data = resp.get_json()
        stats = data["stats"]
        assert stats["coverage_total"] == 3
        assert stats["rank_counts"]["1"] == 1
        assert stats["rank_counts"]["3"] == 1
        assert stats["rank_counts"]["manual"] == 1
