"""Accounting blueprint package surface.

Phase-0 guardrails require newly introduced route definitions to be owned under
``finance_app/blueprints``. Legacy implementation logic remains in
``blueprints.accounting`` and is delegated from here.
"""

from importlib import import_module

_mod = import_module("blueprints.accounting")
accounting_bp = _mod.accounting_bp


@accounting_bp.route("/accounting/month_close", methods=["GET"])
def month_close_foundation():
    return _mod.month_close_foundation()


@accounting_bp.route("/accounting/month_close/snapshot", methods=["POST"])
def month_close_snapshot_create():
    return _mod.month_close_snapshot_create()


@accounting_bp.route("/accounting/receivables/pdf", methods=["GET"])
def receivables_pdf():
    return _mod.receivables_pdf()


@accounting_bp.route("/accounting/payables/pdf", methods=["GET"])
def payables_pdf():
    return _mod.payables_pdf()


@accounting_bp.route("/accounting/loan_receipt/pdf", methods=["GET"])
def loan_receipt_pdf():
    return _mod.loan_receipt_pdf()


for _name in dir(_mod):
    if not _name.startswith("_") and _name not in globals():
        globals()[_name] = getattr(_mod, _name)

__all__ = [name for name in globals() if not name.startswith("_")]
