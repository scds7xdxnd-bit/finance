"""add_phase3_structures

Revision ID: 5c3f2b9c7a1d
Revises: 7ff76bbff8bf
Create Date: 2025-12-24 12:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c3f2b9c7a1d"
down_revision: Union[str, Sequence[str], None] = "7ff76bbff8bf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in set(sa.inspect(bind).get_table_names())


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    try:
        return index_name in {
            idx.get("name")
            for idx in sa.inspect(bind).get_indexes(table_name)
            if idx.get("name")
        }
    except Exception:
        return False


def _create_index_if_possible(table_name: str, index_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    if not _table_exists(bind, table_name):
        return
    if _index_exists(bind, table_name, index_name):
        return
    op.create_index(index_name, table_name, columns, unique=False)


def _drop_index_if_exists(table_name: str, index_name: str) -> None:
    bind = op.get_bind()
    if not _table_exists(bind, table_name):
        return
    if not _index_exists(bind, table_name, index_name):
        return
    op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    if not _table_exists(bind, "transaction_journal_link"):
        op.create_table(
            "transaction_journal_link",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("transaction_id", sa.Integer(), nullable=False),
            sa.Column("journal_entry_id", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entry.id"]),
            sa.ForeignKeyConstraint(["transaction_id"], ["transaction.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "transaction_id", name="uq_tx_journal_link_user_tx"),
        )
    _create_index_if_possible(
        "transaction_journal_link",
        "ix_tx_journal_link_user_journal",
        ["user_id", "journal_entry_id"],
    )

    if not _table_exists(bind, "money_schedule_account_link"):
        op.create_table(
            "money_schedule_account_link",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("money_schedule_account_id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("link_kind", sa.String(length=20), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
            sa.ForeignKeyConstraint(
                ["money_schedule_account_id"], ["money_schedule_accounts.id"]
            ),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id", "money_schedule_account_id", name="uq_ms_account_link_user_ms"
            ),
        )
    _create_index_if_possible(
        "money_schedule_account_link",
        "ix_ms_account_link_user_account",
        ["user_id", "account_id"],
    )

    _create_index_if_possible(
        "transaction",
        "ix_transaction_user_date_parsed",
        ["user_id", "date_parsed"],
    )
    _create_index_if_possible(
        "transaction",
        "ix_transaction_user_debit_account_id",
        ["user_id", "debit_account_id"],
    )
    _create_index_if_possible(
        "transaction",
        "ix_transaction_user_credit_account_id",
        ["user_id", "credit_account_id"],
    )
    _create_index_if_possible(
        "journal_entry",
        "ix_journal_entry_user_date_parsed",
        ["user_id", "date_parsed"],
    )
    _create_index_if_possible(
        "journal_entry",
        "ix_journal_entry_user_reference",
        ["user_id", "reference"],
    )
    _create_index_if_possible(
        "account",
        "ix_account_user_category_active",
        ["user_id", "category_id", "active"],
    )
    _create_index_if_possible(
        "account_category",
        "ix_account_category_user_tb_group",
        ["user_id", "tb_group"],
    )
    _create_index_if_possible(
        "account_opening_balance",
        "ix_account_opening_balance_user_account",
        ["user_id", "account_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    _drop_index_if_exists("account_opening_balance", "ix_account_opening_balance_user_account")
    _drop_index_if_exists("account_category", "ix_account_category_user_tb_group")
    _drop_index_if_exists("account", "ix_account_user_category_active")
    _drop_index_if_exists("journal_entry", "ix_journal_entry_user_reference")
    _drop_index_if_exists("journal_entry", "ix_journal_entry_user_date_parsed")
    _drop_index_if_exists("transaction", "ix_transaction_user_credit_account_id")
    _drop_index_if_exists("transaction", "ix_transaction_user_debit_account_id")
    _drop_index_if_exists("transaction", "ix_transaction_user_date_parsed")
    _drop_index_if_exists("money_schedule_account_link", "ix_ms_account_link_user_account")
    if _table_exists(bind, "money_schedule_account_link"):
        op.drop_table("money_schedule_account_link")
    _drop_index_if_exists("transaction_journal_link", "ix_tx_journal_link_user_journal")
    if _table_exists(bind, "transaction_journal_link"):
        op.drop_table("transaction_journal_link")
