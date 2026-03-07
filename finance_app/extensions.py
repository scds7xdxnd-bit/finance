"""Shared application extensions."""

from flask_sqlalchemy import SQLAlchemy

# Single SQLAlchemy instance used across the app.
db = SQLAlchemy()
