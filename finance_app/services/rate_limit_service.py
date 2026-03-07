"""Simple per-user rate limiting service for API endpoints."""
import datetime
from typing import Dict

from finance_app.extensions import db
from finance_app.models.user_models import RateLimitBucket


def is_rate_limited(user_id: int, bucket: str, limits: Dict[str, Dict[str, int]]) -> bool:
    """
    Enforce a token-bucket style rate limit for a given user/bucket pair.

    limits example:
    {
        "ml_suggestions": {"window": 60, "limit": 60},
        "ml_logs": {"window": 60, "limit": 120},
    }
    """
    cfg = limits.get(bucket, {"window": 60, "limit": 60})
    now = datetime.datetime.utcnow()
    window_reset = now + datetime.timedelta(seconds=cfg["window"])
    rec = (
        RateLimitBucket.query.filter_by(user_id=user_id, bucket=bucket)
        .with_for_update(of=RateLimitBucket)
        .first()
    )
    if not rec or rec.reset_at < now:
        if not rec:
            rec = RateLimitBucket(user_id=user_id, bucket=bucket, reset_at=window_reset, count=1)
            db.session.add(rec)
        else:
            rec.reset_at = window_reset
            rec.count = 1
        db.session.commit()
        return False
    rec.count += 1
    limited = rec.count > cfg["limit"]
    db.session.commit()
    return limited
