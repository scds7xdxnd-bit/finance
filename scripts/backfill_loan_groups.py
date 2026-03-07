"""
Backfill script for creating loan groups and principal links from receivable trackers.

Usage:
    python scripts/backfill_loan_groups.py --dry-run   # default
    python scripts/backfill_loan_groups.py --commit
"""

import datetime as dt
import math
import sys
from decimal import Decimal
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from finance_app import (
    Account,
    JournalEntry,
    JournalLine,
    LoanGroup,
    LoanGroupLink,
    ReceivableTracker,
    User,
    create_app,
    db,
    ensure_schema,
)


def _infer_direction(tracker):
    return 'receivable' if (tracker.category or '').lower() == 'receivable' else 'payable'


def _is_base_flow(direction, line):
    dc = (line.dc or '').upper()
    if direction == 'receivable':
        return dc == 'D'
    return dc == 'C'


def _default_currency(line, tracker, account):
    if tracker and tracker.currency_code:
        return tracker.currency_code.upper()
    if line and line.currency_code:
        return line.currency_code.upper()
    if account and account.currency_code:
        return (account.currency_code or 'KRW').upper()
    return 'KRW'


def _principal_amount(tracker, line):
    candidates = [
        tracker.transaction_value if tracker else None,
        tracker.remaining_amount if tracker else None,
        line.amount_tx if line and line.amount_tx not in (None, '') else None,
        line.amount_base if line else None,
    ]
    for value in candidates:
        if value in (None, ''):
            continue
        try:
            amount = Decimal(str(value)).copy_abs()
            if amount > 0:
                return amount
        except Exception:
            continue
    return Decimal('0')


def _start_date(entry):
    if entry and entry.date_parsed:
        return entry.date_parsed
    if entry and entry.date:
        raw = entry.date.replace('/', '-')
        parts = raw.split('-')
        try:
            year, month, day = [int(p) for p in parts]
            return dt.date(year, month, day)
        except Exception:
            return None
    return None


def process_user(user, commit=False):
    created = 0
    linked = 0
    trackers = (ReceivableTracker.query
                .filter_by(user_id=user.id, ignored=False)
                .order_by(ReceivableTracker.journal_line_id.asc())
                .all())
    for tracker in trackers:
        line = JournalLine.query.get(tracker.journal_line_id)
        entry = JournalEntry.query.get(tracker.journal_id) if tracker.journal_id else None
        account = Account.query.get(tracker.account_id) if tracker.account_id else None
        if not line or not account:
            continue
        direction = _infer_direction(tracker)
        if not _is_base_flow(direction, line):
            continue
        existing = LoanGroupLink.query.filter_by(user_id=user.id, journal_line_id=line.id).first()
        if existing:
            continue
        principal = _principal_amount(tracker, line)
        if principal <= 0 or math.isclose(float(principal), 0.0):
            continue
        currency = _default_currency(line, tracker, account)
        contact = (tracker.contact_name or '').strip() or 'Loan'
        name = f"{contact} {direction.title()} #{line.id}"
        start_date = _start_date(entry)
        if commit:
            group = LoanGroup(
                user_id=user.id,
                name=name,
                direction=direction,
                counterparty=tracker.contact_name,
                currency=currency,
                principal_amount=principal,
                start_date=start_date or entry.date_parsed or None,
                status='open'
            )
            db.session.add(group)
            db.session.flush()
            link = LoanGroupLink(
                user_id=user.id,
                loan_group_id=group.id,
                journal_line_id=line.id,
                linked_amount=principal
            )
            db.session.add(link)
        else:
            click.echo(f"[DRY-RUN] Would create group '{name}' for user {user.username}, principal {currency} {principal}")
        created += 1
        linked += 1
    if commit and created:
        db.session.commit()
    return created, linked


@click.command()
@click.option('--commit/--dry-run', default=False, help='Persist changes to the database.')
def main(commit):
    flask_app = create_app()
    with flask_app.app_context():
        ensure_schema()
        total_groups = 0
        total_links = 0
        for user in User.query.all():
            groups, links = process_user(user, commit=commit)
            total_groups += groups
            total_links += links
        if commit:
            click.echo(f"Created {total_groups} loan groups and {total_links} principal links.")
        else:
            click.echo(f"Dry-run complete. {total_groups} groups and {total_links} links would be created. Use --commit to apply changes.")


if __name__ == '__main__':
    main()
