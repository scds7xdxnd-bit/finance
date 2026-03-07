import datetime

from finance_app.extensions import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(120), unique=True)  # optional for legacy users
    is_admin = db.Column(db.Boolean, default=False)
    transactions = db.relationship("Transaction", backref="user", lazy=True)
    profile = db.relationship("UserProfile", backref="user", uselist=False)


class UserProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True)
    profile_pic = db.Column(db.String(256))  # path to image file
    notes = db.Column(db.Text)
    posts = db.relationship("UserPost", backref="profile", lazy=True)


class UserPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("user_profile.id"))
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class RateLimitBucket(db.Model):
    """Per-user token bucket for rate limiting."""

    __tablename__ = "rate_limit_bucket"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    bucket = db.Column(db.String(64), nullable=False, index=True)
    reset_at = db.Column(db.DateTime, nullable=False, index=True)
    count = db.Column(db.Integer, nullable=False, default=0)
