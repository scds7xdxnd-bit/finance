"""journal_integrity_enforcement

Revision ID: b1c2d3e4f5a6
Revises: 8a5d4f1c2b7e
Create Date: 2026-03-09 19:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "8a5d4f1c2b7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_JOURNAL_TRIGGER_NAMES = (
    "trg_journal_line_ai_balance",
    "trg_journal_line_au_balance",
    "trg_journal_line_ad_balance",
    "trg_journal_entry_bi_post_balance_guard",
    "trg_journal_entry_bu_post_balance_guard",
)


def _table_exists(bind, table_name: str) -> bool:
    return table_name in set(sa.inspect(bind).get_table_names())


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    try:
        return column_name in {c.get("name") for c in sa.inspect(bind).get_columns(table_name)}
    except Exception:
        return False


def _table_sql(bind, table_name: str) -> str:
    row = bind.execute(
        sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    ).fetchone()
    return (row[0] or "") if row and row[0] else ""


def _has_named_check(bind, table_name: str, constraint_name: str) -> bool:
    sql = _table_sql(bind, table_name).lower()
    return bool(sql and f"constraint {constraint_name.lower()} check" in sql)


def _trigger_exists(bind, trigger_name: str) -> bool:
    row = bind.execute(
        sa.text("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=:name"),
        {"name": trigger_name},
    ).fetchone()
    return bool(row)


def _drop_trigger_if_exists(bind, trigger_name: str) -> None:
    if _trigger_exists(bind, trigger_name):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger_name}"))


def _assert_detect_block_preconditions(bind) -> None:
    if _table_exists(bind, "journal_line"):
        invalid_dc_count = int(
            bind.execute(
                sa.text(
                    "SELECT COUNT(*) FROM journal_line "
                    "WHERE dc IS NULL OR dc NOT IN ('D','C')"
                )
            ).scalar()
            or 0
        )
        if invalid_dc_count > 0:
            raise RuntimeError(
                "journal_integrity precheck failed: invalid journal_line.dc rows detected "
                f"(count={invalid_dc_count}). Remediate per SSOT 90.8 and retry migration."
            )

    if _table_exists(bind, "journal_entry") and _table_exists(bind, "journal_line") and _column_exists(bind, "journal_entry", "posted_at"):
        unbalanced_finalized_count = int(
            bind.execute(
                sa.text(
                    "SELECT COUNT(*) FROM ("
                    "SELECT j.id "
                    "FROM journal_entry j "
                    "LEFT JOIN journal_line l ON l.journal_id = j.id "
                    "WHERE j.posted_at IS NOT NULL "
                    "GROUP BY j.id "
                    "HAVING ROUND(COALESCE(SUM(CASE WHEN l.dc='D' THEN l.amount_base ELSE 0 END), 0), 2) "
                    "     != ROUND(COALESCE(SUM(CASE WHEN l.dc='C' THEN l.amount_base ELSE 0 END), 0), 2)"
                    ")"
                )
            ).scalar()
            or 0
        )
        if unbalanced_finalized_count > 0:
            raise RuntimeError(
                "journal_integrity precheck failed: unbalanced finalized journal_entry rows detected "
                f"(count={unbalanced_finalized_count}). Remediate per SSOT 90.8 and retry migration."
            )


def _create_journal_entry_balance(bind) -> None:
    if _table_exists(bind, "journal_entry_balance"):
        return
    op.create_table(
        "journal_entry_balance",
        sa.Column("journal_entry_id", sa.Integer(), nullable=False),
        sa.Column("debit_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("credit_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entry.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("journal_entry_id"),
    )


def _rebuild_journal_entry_balance(bind) -> None:
    if not _table_exists(bind, "journal_entry_balance"):
        return
    if not _table_exists(bind, "journal_entry") or not _table_exists(bind, "journal_line"):
        return

    op.execute(sa.text("DELETE FROM journal_entry_balance"))
    op.execute(
        sa.text(
            "INSERT INTO journal_entry_balance (journal_entry_id, debit_total, credit_total) "
            "SELECT j.id, "
            "       ROUND(COALESCE(SUM(CASE WHEN l.dc='D' THEN COALESCE(l.amount_base, 0) ELSE 0 END), 0), 2) AS debit_total, "
            "       ROUND(COALESCE(SUM(CASE WHEN l.dc='C' THEN COALESCE(l.amount_base, 0) ELSE 0 END), 0), 2) AS credit_total "
            "FROM journal_entry j "
            "LEFT JOIN journal_line l ON l.journal_id = j.id "
            "GROUP BY j.id"
        )
    )


def _create_balance_triggers(bind) -> None:
    if not (_table_exists(bind, "journal_line") and _table_exists(bind, "journal_entry") and _table_exists(bind, "journal_entry_balance")):
        return

    for trigger_name in _JOURNAL_TRIGGER_NAMES:
        _drop_trigger_if_exists(bind, trigger_name)

    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_journal_line_ai_balance
            AFTER INSERT ON journal_line
            BEGIN
                INSERT INTO journal_entry_balance (journal_entry_id, debit_total, credit_total)
                SELECT
                    NEW.journal_id,
                    ROUND(COALESCE(SUM(CASE WHEN dc = 'D' THEN COALESCE(amount_base, 0) ELSE 0 END), 0), 2),
                    ROUND(COALESCE(SUM(CASE WHEN dc = 'C' THEN COALESCE(amount_base, 0) ELSE 0 END), 0), 2)
                FROM journal_line
                WHERE journal_id = NEW.journal_id
                GROUP BY journal_id
                ON CONFLICT(journal_entry_id) DO UPDATE SET
                    debit_total = excluded.debit_total,
                    credit_total = excluded.credit_total;
            END;
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_journal_line_au_balance
            AFTER UPDATE ON journal_line
            BEGIN
                INSERT INTO journal_entry_balance (journal_entry_id, debit_total, credit_total)
                SELECT
                    NEW.journal_id,
                    ROUND(COALESCE(SUM(CASE WHEN dc = 'D' THEN COALESCE(amount_base, 0) ELSE 0 END), 0), 2),
                    ROUND(COALESCE(SUM(CASE WHEN dc = 'C' THEN COALESCE(amount_base, 0) ELSE 0 END), 0), 2)
                FROM journal_line
                WHERE journal_id = NEW.journal_id
                GROUP BY journal_id
                ON CONFLICT(journal_entry_id) DO UPDATE SET
                    debit_total = excluded.debit_total,
                    credit_total = excluded.credit_total;

                INSERT INTO journal_entry_balance (journal_entry_id, debit_total, credit_total)
                SELECT
                    OLD.journal_id,
                    ROUND(COALESCE(SUM(CASE WHEN dc = 'D' THEN COALESCE(amount_base, 0) ELSE 0 END), 0), 2),
                    ROUND(COALESCE(SUM(CASE WHEN dc = 'C' THEN COALESCE(amount_base, 0) ELSE 0 END), 0), 2)
                FROM journal_line
                WHERE journal_id = OLD.journal_id
                GROUP BY journal_id
                ON CONFLICT(journal_entry_id) DO UPDATE SET
                    debit_total = excluded.debit_total,
                    credit_total = excluded.credit_total;

                DELETE FROM journal_entry_balance
                WHERE journal_entry_id = NEW.journal_id
                  AND NOT EXISTS (SELECT 1 FROM journal_line WHERE journal_id = NEW.journal_id);

                DELETE FROM journal_entry_balance
                WHERE journal_entry_id = OLD.journal_id
                  AND NOT EXISTS (SELECT 1 FROM journal_line WHERE journal_id = OLD.journal_id);
            END;
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_journal_line_ad_balance
            AFTER DELETE ON journal_line
            BEGIN
                INSERT INTO journal_entry_balance (journal_entry_id, debit_total, credit_total)
                SELECT
                    OLD.journal_id,
                    ROUND(COALESCE(SUM(CASE WHEN dc = 'D' THEN COALESCE(amount_base, 0) ELSE 0 END), 0), 2),
                    ROUND(COALESCE(SUM(CASE WHEN dc = 'C' THEN COALESCE(amount_base, 0) ELSE 0 END), 0), 2)
                FROM journal_line
                WHERE journal_id = OLD.journal_id
                GROUP BY journal_id
                ON CONFLICT(journal_entry_id) DO UPDATE SET
                    debit_total = excluded.debit_total,
                    credit_total = excluded.credit_total;

                DELETE FROM journal_entry_balance
                WHERE journal_entry_id = OLD.journal_id
                  AND NOT EXISTS (SELECT 1 FROM journal_line WHERE journal_id = OLD.journal_id);
            END;
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_journal_entry_bi_post_balance_guard
            BEFORE INSERT ON journal_entry
            FOR EACH ROW
            WHEN NEW.posted_at IS NOT NULL
             AND ROUND(COALESCE((SELECT debit_total FROM journal_entry_balance WHERE journal_entry_id = NEW.id), 0), 2)
                 != ROUND(COALESCE((SELECT credit_total FROM journal_entry_balance WHERE journal_entry_id = NEW.id), 0), 2)
            BEGIN
                SELECT RAISE(ABORT, 'journal_entry_not_balanced: finalized journal_entry requires equal debit_total and credit_total');
            END;
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_journal_entry_bu_post_balance_guard
            BEFORE UPDATE ON journal_entry
            FOR EACH ROW
            WHEN NEW.posted_at IS NOT NULL
             AND ROUND(COALESCE((SELECT debit_total FROM journal_entry_balance WHERE journal_entry_id = NEW.id), 0), 2)
                 != ROUND(COALESCE((SELECT credit_total FROM journal_entry_balance WHERE journal_entry_id = NEW.id), 0), 2)
            BEGIN
                SELECT RAISE(ABORT, 'journal_entry_not_balanced: finalized journal_entry requires equal debit_total and credit_total');
            END;
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "journal_entry") and not _column_exists(bind, "journal_entry", "posted_at"):
        op.add_column("journal_entry", sa.Column("posted_at", sa.DateTime(), nullable=True))

    _assert_detect_block_preconditions(bind)

    if _table_exists(bind, "journal_line") and not _has_named_check(bind, "journal_line", "ck_journal_line_dc"):
        with op.batch_alter_table(
            "journal_line",
            recreate="always",
            reflect_kwargs={"resolve_fks": False},
        ) as batch_op:
            batch_op.create_check_constraint(
                "ck_journal_line_dc",
                "dc IS NOT NULL AND dc IN ('D','C')",
            )

    _create_journal_entry_balance(bind)
    _rebuild_journal_entry_balance(bind)
    _assert_detect_block_preconditions(bind)
    _create_balance_triggers(bind)


def downgrade() -> None:
    bind = op.get_bind()

    for trigger_name in _JOURNAL_TRIGGER_NAMES:
        _drop_trigger_if_exists(bind, trigger_name)

    if _table_exists(bind, "journal_entry_balance"):
        op.drop_table("journal_entry_balance")

    if _table_exists(bind, "journal_line") and _has_named_check(bind, "journal_line", "ck_journal_line_dc"):
        with op.batch_alter_table(
            "journal_line",
            recreate="always",
            reflect_kwargs={"resolve_fks": False},
        ) as batch_op:
            batch_op.drop_constraint("ck_journal_line_dc", type_="check")
