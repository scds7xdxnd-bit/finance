"""CLI management commands."""
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

import click
from flask.cli import with_appcontext
from sqlalchemy import text

try:
    from alembic import command as alembic_command
    from alembic.config import Config
except ImportError:  # pragma: no cover - only hits when alembic is not installed
    alembic_command = None

    class Config:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise RuntimeError("Alembic is not installed; install it to run migration commands.")

from finance_app.extensions import db
from finance_app.lib.dates import _parse_date_tuple
from finance_app.models.accounting_models import (
    Account,
    AccountSuggestionHint,
    TBResetSnapshot,
    JournalEntry,
    Transaction,
)
from finance_app.services.ledger_convergence_service import (
    backfill_links,
    compute_convergence_metrics,
    reconcile_ledger,
)
from finance_app.services.schema_guard_service import capability_report, guard_capabilities, required_capabilities
from finance_app.services.account_service import assign_codes_for_user, ensure_account
from finance_app.services.journal_service import (
    JournalBalanceError,
    JournalLinePayload,
    _validate_balanced,
    create_journal_entry,
)


def _alembic_config(db_url: str | None = None) -> Config:
    """Build an Alembic Config anchored to the repository root."""
    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    env_url = os.environ.get("ALEMBIC_DATABASE_URL")
    if db_url:
        cfg.set_main_option("sqlalchemy.url", db_url)
    elif env_url:
        cfg.set_main_option("sqlalchemy.url", env_url)
    return cfg


def _schema_revision_status() -> dict:
    current = None
    try:
        row = db.session.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        current = row[0] if row else None
    except Exception:
        current = None

    heads = []
    try:
        from alembic.script import ScriptDirectory

        cfg = _alembic_config()
        script = ScriptDirectory.from_config(cfg)
        heads = list(script.get_heads())
    except Exception:
        heads = []

    return {"current_revision": current, "heads": heads, "at_head": bool(current and heads and current in heads)}


@click.command("migrate-to-journal")
@click.option("--user-id", type=int, default=None, help="Only migrate transactions for this user id")
@click.option("--dry-run", is_flag=True, default=False, help="Do not write, only print a summary")
@click.option("--limit", type=int, default=None, help="Limit number of transactions to migrate")
@with_appcontext
def migrate_to_journal_cli(user_id, dry_run, limit):
    """Create JournalEntry + JournalLine rows from existing simple Transaction rows."""
    from decimal import ROUND_HALF_UP, Decimal

    q = Transaction.query
    if user_id is not None:
        q = q.filter(Transaction.user_id == int(user_id))
    q = q.order_by(Transaction.id.asc())
    if limit is not None:
        q = q.limit(int(limit))
    rows = q.all()
    created = 0
    skipped = 0
    imbalanced = 0
    for t in rows:
        ref = f"TX:{t.id}"
        exists = JournalEntry.query.filter_by(user_id=t.user_id, reference=ref).first()
        if exists:
            skipped += 1
            continue
        date_parsed = None
        try:
            if t.date_parsed:
                date_parsed = t.date_parsed
            else:
                y, m, d = _parse_date_tuple(t.date)
                if y and m and d:
                    import datetime as _dt

                    date_parsed = _dt.date(y, m, d)
        except Exception:
            date_parsed = None
        line_payloads: list[JournalLinePayload] = []
        if (t.debit_amount or 0) != 0:
            acc = Account.query.get(t.debit_account_id) if t.debit_account_id else None
            if not acc:
                acc = ensure_account(t.user_id, t.debit_account or "Unknown")
            amt = Decimal(str(t.debit_amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            line_payloads.append(JournalLinePayload(account_id=acc.id, dc="D", amount=amt, line_no=1))
        if (t.credit_amount or 0) != 0:
            acc = Account.query.get(t.credit_account_id) if t.credit_account_id else None
            if not acc:
                acc = ensure_account(t.user_id, t.credit_account or "Unknown")
            amt = Decimal(str(t.credit_amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            line_payloads.append(JournalLinePayload(account_id=acc.id, dc="C", amount=amt, line_no=2))
        try:
            _validate_balanced(line_payloads)
        except JournalBalanceError:
            imbalanced += 1
            continue
        if dry_run:
            created += 1
            continue
        try:
            create_journal_entry(
                user_id=t.user_id,
                date=t.date,
                date_parsed=date_parsed,
                description=t.description,
                reference=ref,
                lines=line_payloads,
            )
            created += 1
        except JournalBalanceError:
            imbalanced += 1
            db.session.rollback()
            continue
    if not dry_run:
        db.session.commit()
    click.echo(f"Journal migration: created={created}, skipped={skipped}, imbalanced={imbalanced}, total_considered={len(rows)}")


@click.command("merge-accounts")
@click.option("--dry-run", is_flag=True, default=False, help="Analyze and report without modifying the DB")
@with_appcontext
def merge_accounts_cli(dry_run):
    """Merge duplicate Account rows by name (case-insensitive) per user and update transactions."""
    user_ids = [row[0] for row in db.session.query(Account.user_id).distinct().all()]
    for uid in user_ids:
        accounts = Account.query.filter_by(user_id=uid, active=True).order_by(Account.id.asc()).all()
        buckets = {}
        for a in accounts:
            key = (a.name or "").strip().lower()
            if key:
                buckets.setdefault(key, []).append(a)
        for key, accs in buckets.items():
            if len(accs) <= 1:
                continue
            canonical = accs[0]
            if not canonical.code:
                for other in accs[1:]:
                    if other.code:
                        canonical.code = other.code
                        break
            dup_names = [a.name for a in accs[1:]]
            if not dry_run:
                for dn in dup_names:
                    Transaction.query.filter_by(user_id=uid, debit_account=dn).update(
                        {Transaction.debit_account: canonical.name, Transaction.debit_account_id: canonical.id}
                    )
                    Transaction.query.filter_by(user_id=uid, credit_account=dn).update(
                        {Transaction.credit_account: canonical.name, Transaction.credit_account_id: canonical.id}
                    )
                for d in accs[1:]:
                    db.session.delete(d)
        if not dry_run:
            db.session.commit()
    click.echo("Merge complete" + (" (dry-run)" if dry_run else ""))


@click.command("upgrade-schema")
@click.option("--backfill", is_flag=True, default=False, help="Populate new columns for existing data")
@click.option(
    "--db-url",
    default=None,
    help="Optional DB URL override for Alembic (defaults to alembic.ini or ALEMBIC_DATABASE_URL).",
)
@with_appcontext
def upgrade_schema_cli(backfill, db_url):
    """Run Alembic upgrade to head and optionally backfill legacy Transaction columns."""
    if alembic_command is None:
        raise click.ClickException("Alembic is not installed. Install alembic to run migrations.")
    cfg = _alembic_config(db_url)
    alembic_command.upgrade(cfg, "head")
    click.echo("Alembic upgrade to head completed.")

    if backfill:
        txs = Transaction.query.all()
        updated = 0
        for t in txs:
            try:
                y, m, d = _parse_date_tuple(t.date or "")
                t.date_parsed = datetime.date(y, m, d) if y and m and d else None
            except Exception:
                t.date_parsed = None
            if t.debit_account:
                acc = ensure_account(t.user_id, t.debit_account)
                if acc:
                    t.debit_account_id = acc.id
            if t.credit_account:
                acc = ensure_account(t.user_id, t.credit_account)
                if acc:
                    t.credit_account_id = acc.id
            updated += 1
        db.session.commit()
        click.echo(f"Backfilled {updated} transactions")


@click.command("schema-status")
@with_appcontext
def schema_status_cli():
    """Print schema capability and revision status."""
    revision = _schema_revision_status()
    capabilities = capability_report()
    payload = {
        "ok": bool(capabilities.get("ok")),
        "revision": revision,
        "required_capabilities": required_capabilities(),
        "capabilities": capabilities,
    }
    if not bool(revision.get("at_head")):
        payload["revision_warning"] = "Database revision is not at alembic head; capability checks are authoritative for guarded operations."
    click.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
    if not bool(capabilities.get("ok")):
        raise click.exceptions.Exit(2)


@click.command("sqlite-backup")
@click.option("--out-path", default=None, help="Optional output path for the backup .db file")
@click.option("--checkpoint/--no-checkpoint", default=True, help="Run WAL checkpoint before backup")
@with_appcontext
def sqlite_backup_cli(out_path, checkpoint):
    """Create a SQLite file backup with checksum metadata."""
    db_url = str(db.engine.url)
    if not db_url.startswith("sqlite:///"):
        raise click.ClickException("sqlite-backup currently supports SQLite only")
    source_path = Path(db_url.replace("sqlite:///", "", 1))
    if not source_path.exists():
        raise click.ClickException(f"Source database not found: {source_path}")

    if out_path:
        dest_path = Path(out_path)
    else:
        out_dir = Path("instance") / "backups" / "sqlite"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        dest_path = out_dir / f"{source_path.stem}_{ts}.db"

    if dest_path.exists():
        raise click.ClickException(f"Backup path already exists: {dest_path}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    db.session.remove()
    db.engine.dispose()
    try:
        with sqlite3.connect(str(source_path)) as src_conn:
            if checkpoint:
                try:
                    src_conn.execute("PRAGMA wal_checkpoint(FULL)")
                except Exception:
                    pass
            with sqlite3.connect(str(dest_path)) as dst_conn:
                src_conn.backup(dst_conn)
    except Exception as exc:
        raise click.ClickException(f"Failed to create SQLite backup: {exc}")

    try:
        content = dest_path.read_bytes()
        payload = {
            "ok": True,
            "source_db": str(source_path),
            "backup_path": str(dest_path),
            "sha256": hashlib.sha256(content).hexdigest(),
            "file_size_bytes": int(dest_path.stat().st_size),
            "checkpoint": bool(checkpoint),
        }
    except Exception as exc:
        raise click.ClickException(f"Backup created but metadata read failed: {exc}")
    click.echo(json.dumps(payload, indent=2, sort_keys=True))


@click.command("ledger-convergence-metrics")
@click.option("--user-id", type=int, default=None, help="Restrict metrics to a user id")
@with_appcontext
def ledger_convergence_metrics_cli(user_id):
    """Show convergence and coverage metrics."""
    ok, payload, status = guard_capabilities(["tx_linking"], enforce=False)
    _ = ok, status  # informational for metrics
    metrics = compute_convergence_metrics(user_id=user_id)
    click.echo(
        json.dumps(
            {
                "capabilities": (payload or {}).get("capabilities", {}),
                "metrics": metrics,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )


@click.command("backfill-transaction-links")
@click.option("--user-id", type=int, default=None, help="Restrict backfill to a user id")
@click.option("--dry-run/--apply", default=True, help="Dry-run by default")
@click.option("--max-rows", type=int, default=None, help="Optional max rows to scan")
@with_appcontext
def backfill_transaction_links_cli(user_id, dry_run, max_rows):
    """Backfill transaction->journal links using exact/strong criteria only."""
    enforce = bool(os.environ.get("SCHEMA_GUARD_ENFORCE", "true").lower() in ("1", "true", "yes"))
    ok, payload, status = guard_capabilities(["tx_linking", "link_candidates", "csv_idempotency"], enforce=enforce)
    if not ok:
        click.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        raise click.exceptions.Exit(2 if status == 503 else 1)

    summary = backfill_links(user_id=user_id, dry_run=dry_run, max_rows=max_rows)
    click.echo(json.dumps(summary, indent=2, sort_keys=True, default=str))


@click.command("ledger-reconcile")
@click.option("--user-id", type=int, default=None, help="Restrict checks to a user id")
@click.option("--fail-on-mismatch/--no-fail-on-mismatch", default=True)
@click.option(
    "--coverage-count-min",
    type=float,
    default=lambda: float(os.environ.get("LEDGER_COVERAGE_COUNT_MIN", "0.99")),
    show_default="env LEDGER_COVERAGE_COUNT_MIN or 0.99",
)
@click.option(
    "--coverage-amount-min",
    type=float,
    default=lambda: float(os.environ.get("LEDGER_COVERAGE_AMOUNT_MIN", "0.995")),
    show_default="env LEDGER_COVERAGE_AMOUNT_MIN or 0.995",
)
@click.option(
    "--unlinked-recent-max",
    type=int,
    default=lambda: int(os.environ.get("LEDGER_UNLINKED_RECENT_MAX", "0")),
    show_default="env LEDGER_UNLINKED_RECENT_MAX or 0",
)
@with_appcontext
def ledger_reconcile_cli(user_id, fail_on_mismatch, coverage_count_min, coverage_amount_min, unlinked_recent_max):
    """Run reconciliation checks for legacy/journal convergence."""
    enforce = bool(os.environ.get("SCHEMA_GUARD_ENFORCE", "true").lower() in ("1", "true", "yes"))
    ok, payload, status = guard_capabilities(["tx_linking"], enforce=enforce)
    if not ok:
        click.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        raise click.exceptions.Exit(2 if status == 503 else 1)

    summary = reconcile_ledger(user_id=user_id)
    metrics = compute_convergence_metrics(user_id=user_id)
    gates = {
        "coverage_count": bool(float(metrics.get("coverage_count") or 0.0) >= float(coverage_count_min)),
        "coverage_amount": bool(float(metrics.get("coverage_amount") or 0.0) >= float(coverage_amount_min)),
        "unlinked_recent_90d_count": bool(int(metrics.get("unlinked_recent_90d_count") or 0) <= int(unlinked_recent_max)),
    }
    gate_ok = all(gates.values())
    output = {
        "ok": bool(summary.get("ok")) and bool(gate_ok),
        "reconcile": summary,
        "coverage": metrics,
        "gate_thresholds": {
            "coverage_count_min": float(coverage_count_min),
            "coverage_amount_min": float(coverage_amount_min),
            "unlinked_recent_max": int(unlinked_recent_max),
        },
        "gates": gates,
    }
    click.echo(json.dumps(output, indent=2, sort_keys=True, default=str))
    if fail_on_mismatch and not output["ok"]:
        raise click.exceptions.Exit(1)


@click.command("tb-reset-restore")
@click.option("--snapshot-id", required=True, help="Snapshot id from tb_reset_snapshot")
@click.option("--dry-run", is_flag=True, default=False, help="Validate only; do not restore")
@with_appcontext
def tb_reset_restore_cli(snapshot_id, dry_run):
    """Restore DB from a TB reset snapshot (SQLite)."""
    snap = db.session.get(TBResetSnapshot, snapshot_id)
    if not snap:
        raise click.ClickException("Snapshot not found")
    path = Path(snap.db_copy_path or "")
    if not path.exists():
        raise click.ClickException(f"Snapshot file missing: {path}")

    content = path.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    if sha != (snap.sha256 or ""):
        raise click.ClickException("Snapshot checksum mismatch")

    if dry_run:
        click.echo(f"Dry-run ok for snapshot {snapshot_id}")
        return

    uri = db.engine.url
    if not str(uri).startswith("sqlite:///"):
        raise click.ClickException("tb-reset-restore currently supports SQLite only")
    db_path = Path(str(uri).replace("sqlite:///", "", 1))
    db.session.remove()
    db.engine.dispose()

    backup_path = db_path.with_name(
        f"{db_path.stem}_pre_restore_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{db_path.suffix}"
    )
    if db_path.exists():
        shutil.copy2(db_path, backup_path)

    with sqlite3.connect(str(path)) as src_conn:
        with sqlite3.connect(str(db_path)) as dst_conn:
            src_conn.backup(dst_conn)

    snap.restore_status = "restored"
    snap.restored_at = datetime.datetime.utcnow()
    db.session.add(snap)
    db.session.commit()
    click.echo(f"Restored snapshot {snapshot_id}. Pre-restore backup: {backup_path}")


@click.command("prune-hints")
@click.option("--min-count", default=2, show_default=True, help="Delete hint tokens with count lower than this threshold")
@click.option("--dry-run", is_flag=True, default=False, help="Analyze only; do not delete")
@with_appcontext
def prune_hints_cli(min_count, dry_run):
    """Prune low-signal AccountSuggestionHint tokens to keep the table lean."""
    q = AccountSuggestionHint.query.filter((AccountSuggestionHint.count == None) | (AccountSuggestionHint.count < int(min_count)))
    to_delete = q.count()
    if dry_run:
        click.echo(f"Would delete {to_delete} hint rows with count < {min_count}")
        return
    q.delete(synchronize_session=False)
    db.session.commit()
    click.echo(f"Deleted {to_delete} hint rows with count < {min_count}")


@click.command("assign-account-ids")
@click.option("--user-id", type=int, default=None, help="Restrict to a specific user id")
@with_appcontext
def assign_account_ids_cli(user_id):
    """Assign debit/credit account FK ids for transactions based on names for all users or a specific user."""
    q = Transaction.query
    if user_id is not None:
        q = q.filter(Transaction.user_id == int(user_id))
    rows = q.all()
    updated = 0
    for t in rows:
        try:
            if t.debit_account and not t.debit_account_id:
                acc = ensure_account(t.user_id, t.debit_account)
                if acc:
                    t.debit_account_id = acc.id
            if t.credit_account and not t.credit_account_id:
                acc = ensure_account(t.user_id, t.credit_account)
                if acc:
                    t.credit_account_id = acc.id
            updated += 1
        except Exception:
            continue
    db.session.commit()
    click.echo(f"Assigned account ids for {updated} transactions")


@click.command("assign-codes")
@click.option("--user-id", type=int, default=None, help="Restrict to a specific user id")
@click.option("--refresh", is_flag=True, default=False, help="Recompute and overwrite existing codes")
@with_appcontext
def assign_codes_cli(user_id, refresh):
    """Assign or refresh account codes across all users or a specific user."""
    if user_id is not None:
        assign_codes_for_user(int(user_id), refresh=bool(refresh))
        click.echo(f"Codes assigned for user {user_id} (refresh={bool(refresh)})")
    else:
        uids = [row[0] for row in db.session.query(Account.user_id).distinct().all()]
        for uid in uids:
            assign_codes_for_user(int(uid), refresh=bool(refresh))
        click.echo(f"Codes assigned for {len(uids)} users (refresh={bool(refresh)})")


@click.command("money-schedule-fill")
@click.argument("start")
@click.argument("end")
@click.option("--user-id", type=int, required=True, help="User id to scope the schedule rows.")
@with_appcontext
def money_schedule_fill_cli(start: str, end: str, user_id: int) -> None:
    """Fill money schedule rows between two dates inclusive with zeroed placeholders."""
    from finance_app.services.money_schedule_service import ensure_row, recompute_from

    start_date = datetime.date.fromisoformat(start)
    end_date = datetime.date.fromisoformat(end)
    if end_date < start_date:
        raise click.BadParameter("end must be on or after start")

    current = start_date
    added = 0
    while current <= end_date:
        ensure_row(current, user_id)
        added += 1
        current += datetime.timedelta(days=1)
    db.session.commit()
    recompute_from(start_date, user_id)
    click.echo(f"Ensured {added} schedule rows between {start_date} and {end_date} for user {user_id}.")
