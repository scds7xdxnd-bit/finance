from flask import Blueprint

bp = Blueprint("money_schedule", __name__, url_prefix="/money-schedule")

from . import routes  # noqa: E402,F401
