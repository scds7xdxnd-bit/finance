"""Transactions blueprint package surface.

Route definitions should live under ``finance_app/blueprints`` for phase-0 guardrail
compliance. Legacy implementation details remain sourced from ``blueprints.transactions``.
"""

from importlib import import_module

from finance_app.lib.auth import csrf_token_valid, current_user
from flask import flash, redirect, request, session, url_for

_mod = import_module("blueprints.transactions")
transactions_bp = _mod.transactions_bp


@transactions_bp.route("/transactions/import_result/dismiss", methods=["POST"])
def dismiss_last_import_result():
    user = current_user()
    if not user:
        flash("Login required.")
        return redirect(url_for("auth_bp.login"))
    if not csrf_token_valid():
        flash("CSRF token missing or invalid.")
        return redirect(url_for("transactions_bp.transactions"))
    session.pop("last_import_result_v1", None)
    preserved_params = _mod._extract_preserved_filter_params(request.args)
    if not preserved_params:
        preserved_params = _mod._extract_preserved_filter_params(request.form)
    return redirect(url_for("transactions_bp.transactions", **preserved_params))

# Re-export symbols
for _name in dir(_mod):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_mod, _name)

__all__ = [name for name in globals() if not name.startswith("_")]
