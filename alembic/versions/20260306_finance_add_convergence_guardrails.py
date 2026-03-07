"""add_convergence_guardrails

Revision ID: 2d9f8c1a4b6e
Revises: 5c3f2b9c7a1d
Create Date: 2026-03-06 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d9f8c1a4b6e"
down_revision: Union[str, Sequence[str], None] = "5c3f2b9c7a1d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transaction_link_candidate",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=False, server_default="weak"),
        sa.Column("reason", sa.String(length=120), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending_review"),
        sa.Column("source", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entry.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["user.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transaction.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tx_link_candidate_user_status", "transaction_link_candidate", ["user_id", "status"], unique=False)
    op.create_index(op.f("ix_transaction_link_candidate_journal_entry_id"), "transaction_link_candidate", ["journal_entry_id"], unique=False)
    op.create_index(op.f("ix_transaction_link_candidate_transaction_id"), "transaction_link_candidate", ["transaction_id"], unique=False)
    op.create_index(op.f("ix_transaction_link_candidate_user_id"), "transaction_link_candidate", ["user_id"], unique=False)

    op.create_table(
        "csv_import_batch",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="processing"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "file_sha256", name="uq_csv_import_batch_user_file"),
    )
    op.create_index(op.f("ix_csv_import_batch_user_id"), "csv_import_batch", ["user_id"], unique=False)

    op.create_table(
        "csv_import_row",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("row_sha256", sa.String(length=64), nullable=False),
        sa.Column("row_dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("external_txn_id", sa.String(length=120), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=1), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("counterparty_norm", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="imported"),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.ForeignKeyConstraint(["batch_id"], ["csv_import_batch.id"]),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entry.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "account_id",
            "direction",
            "row_dedupe_key",
            name="uq_csv_import_row_user_account_direction_key",
        ),
    )
    op.create_index("ix_csv_import_row_user_status", "csv_import_row", ["user_id", "status"], unique=False)
    op.create_index(op.f("ix_csv_import_row_account_id"), "csv_import_row", ["account_id"], unique=False)
    op.create_index(op.f("ix_csv_import_row_batch_id"), "csv_import_row", ["batch_id"], unique=False)
    op.create_index(op.f("ix_csv_import_row_journal_entry_id"), "csv_import_row", ["journal_entry_id"], unique=False)
    op.create_index(op.f("ix_csv_import_row_user_id"), "csv_import_row", ["user_id"], unique=False)

    op.create_table(
        "tb_reset_snapshot",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("db_copy_path", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("created_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("restore_status", sa.String(length=20), nullable=False, server_default="created"),
        sa.Column("restored_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tb_reset_snapshot_user_id"), "tb_reset_snapshot", ["user_id"], unique=False)

    op.create_table(
        "admin_action_audit",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ok"),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_action_audit_actor_created", "admin_action_audit", ["actor_user_id", "created_at"], unique=False)
    op.create_index(op.f("ix_admin_action_audit_actor_user_id"), "admin_action_audit", ["actor_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_action_audit_actor_user_id"), table_name="admin_action_audit")
    op.drop_index("ix_admin_action_audit_actor_created", table_name="admin_action_audit")
    op.drop_table("admin_action_audit")

    op.drop_index(op.f("ix_tb_reset_snapshot_user_id"), table_name="tb_reset_snapshot")
    op.drop_table("tb_reset_snapshot")

    op.drop_index(op.f("ix_csv_import_row_user_id"), table_name="csv_import_row")
    op.drop_index(op.f("ix_csv_import_row_journal_entry_id"), table_name="csv_import_row")
    op.drop_index(op.f("ix_csv_import_row_batch_id"), table_name="csv_import_row")
    op.drop_index(op.f("ix_csv_import_row_account_id"), table_name="csv_import_row")
    op.drop_index("ix_csv_import_row_user_status", table_name="csv_import_row")
    op.drop_table("csv_import_row")

    op.drop_index(op.f("ix_csv_import_batch_user_id"), table_name="csv_import_batch")
    op.drop_table("csv_import_batch")

    op.drop_index(op.f("ix_transaction_link_candidate_user_id"), table_name="transaction_link_candidate")
    op.drop_index(op.f("ix_transaction_link_candidate_transaction_id"), table_name="transaction_link_candidate")
    op.drop_index(op.f("ix_transaction_link_candidate_journal_entry_id"), table_name="transaction_link_candidate")
    op.drop_index("ix_tx_link_candidate_user_status", table_name="transaction_link_candidate")
    op.drop_table("transaction_link_candidate")
