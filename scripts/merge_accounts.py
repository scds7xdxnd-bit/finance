#!/usr/bin/env python3
"""
One-time script to merge duplicate Account rows by name (case-insensitive).

Usage:
  python3 scripts/merge_accounts.py [--dry-run]

Effect:
  - For each user, finds Accounts whose names only differ by case/spacing.
  - Picks the canonical account (lowest id) and updates Transaction rows to
    reference the canonical account.name for both debit and credit fields.
  - Deletes duplicate Account rows and keeps the canonical one.
  - Preserves canonical category and code; fills missing code if possible.

Safe to run multiple times; it’s idempotent.
"""
import sys
from contextlib import contextmanager

from finance_app import Account, Transaction, create_app, db


@contextmanager
def ctx():
    app = create_app()
    with app.app_context():
        yield


def merge_for_user(user_id: int, dry_run: bool = False):
    # Fetch active accounts for this user
    accounts = Account.query.filter_by(user_id=user_id, active=True).order_by(Account.id.asc()).all()
    buckets = {}
    for a in accounts:
        key = (a.name or '').strip().lower()
        if not key:
            continue
        buckets.setdefault(key, []).append(a)
    changes = 0
    for key, accs in buckets.items():
        if len(accs) <= 1:
            continue
        canonical = accs[0]
        # If canonical missing code but others have, take the first available
        if not canonical.code:
            for other in accs[1:]:
                if other.code:
                    canonical.code = other.code
                    break
        # Build set of duplicate names to rewrite in transactions
        dup_names = [a.name for a in accs[1:]]
        if dup_names:
            # Update Transactions to canonical name
            for dn in dup_names:
                if dry_run:
                    continue
                # Debit side
                Transaction.query.filter_by(user_id=user_id, debit_account=dn).update({Transaction.debit_account: canonical.name})
                # Credit side
                Transaction.query.filter_by(user_id=user_id, credit_account=dn).update({Transaction.credit_account: canonical.name})
        # Delete duplicate Account rows
        for d in accs[1:]:
            if not dry_run:
                db.session.delete(d)
        changes += len(accs) - 1
    if not dry_run:
        db.session.commit()
    return changes


def main():
    dry_run = '--dry-run' in sys.argv
    with ctx():
        # Determine all user IDs with accounts
        user_ids = [row.user_id for row in db.session.query(Account.user_id).distinct().all()]
        total = 0
        for uid in user_ids:
            merged = merge_for_user(uid, dry_run=dry_run)
            print(f"User {uid}: merged {merged} duplicates")
            total += merged
        print(f"Total merged: {total}")


if __name__ == '__main__':
    main()
