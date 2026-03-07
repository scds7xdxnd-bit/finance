"""Compat shim to access blueprints via finance_app.blueprints.*"""

from importlib import import_module

# Re-export transactions blueprint module
transactions = import_module("blueprints.transactions")
user = import_module("finance_app.blueprints.user")

__all__ = ["transactions", "user"]
