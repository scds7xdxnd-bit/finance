"""Compat shim to expose the user blueprint through finance_app.blueprints."""

from importlib import import_module

_mod = import_module("blueprints.user")

# Re-export key symbols
user_bp = _mod.user_bp
profile_picture_file = _mod.profile_picture_file

# Phase 0 guardrails require new route registration in finance_app/blueprints.
if not getattr(user_bp, "_profile_picture_route_registered", False):
    user_bp.add_url_rule("/profile_pics/<path:filename>", view_func=profile_picture_file)
    user_bp._profile_picture_route_registered = True

for _name in dir(_mod):
    if not _name.startswith("_") and _name not in globals():
        globals()[_name] = getattr(_mod, _name)

__all__ = [name for name in globals() if not name.startswith("_")]
