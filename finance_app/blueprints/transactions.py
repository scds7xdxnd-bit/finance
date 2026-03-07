"""Compat shim to expose the transactions blueprint through finance_app.blueprints."""

from importlib import import_module

_mod = import_module("blueprints.transactions")

# Re-export symbols
for _name in dir(_mod):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_mod, _name)

__all__ = [name for name in globals() if not name.startswith("_")]
