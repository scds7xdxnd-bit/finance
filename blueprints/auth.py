"""Compat shim to expose the auth blueprint through legacy imports."""

from importlib import import_module

_mod = import_module("finance_app.blueprints.auth")

# Re-export key symbol used by blueprint registration and tests.
auth_bp = _mod.auth_bp

for _name in dir(_mod):
    if not _name.startswith("_") and _name not in globals():
        globals()[_name] = getattr(_mod, _name)

__all__ = [name for name in globals() if not name.startswith("_")]
