"""harden_vnext_capabilities

Revision ID: 8a5d4f1c2b7e
Revises: 2d9f8c1a4b6e
Create Date: 2026-03-06 13:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a5d4f1c2b7e"
down_revision: Union[str, Sequence[str], None] = "2d9f8c1a4b6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    return table_name in set(sa.inspect(bind).get_table_names())


def _index_names(bind, table_name: str) -> set[str]:
    try:
        return {idx.get("name") for idx in sa.inspect(bind).get_indexes(table_name) if idx.get("name")}
    except Exception:
        return set()


def _unique_names(bind, table_name: str) -> set[str]:
    try:
        return {uq.get("name") for uq in sa.inspect(bind).get_unique_constraints(table_name) if uq.get("name")}
    except Exception:
        return set()


def _table_sql(bind, table_name: str) -> str:
    row = bind.execute(
        sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    ).fetchone()
    return (row[0] or "") if row and row[0] else ""


def _has_named_constraint(bind, table_name: str, constraint_name: str) -> bool:
    sql = _table_sql(bind, table_name).lower()
    needle = f"constraint {constraint_name.lower()}"
    return bool(sql and needle in sql)


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    if not _table_exists(bind, table_name):
        return
    if index_name in _index_names(bind, table_name):
        return
    op.create_index(index_name, table_name, columns, unique=False)


def _drop_index_if_exists(table_name: str, index_name: str) -> None:
    bind = op.get_bind()
    if not _table_exists(bind, table_name):
        return
    if index_name not in _index_names(bind, table_name):
        return
    op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "transaction_journal_link"):
        op.execute(
            sa.text(
                "UPDATE transaction_journal_link "
                "SET source='legacy_unknown' "
                "WHERE source IS NULL OR trim(source) = ''"
            )
        )
        needs_uq = "uq_tx_journal_link_user_journal_entry" not in _unique_names(bind, "transaction_journal_link")
        needs_ck = not _has_named_constraint(bind, "transaction_journal_link", "ck_tx_journal_link_source_nonempty")
        if needs_uq or needs_ck:
            with op.batch_alter_table(
                "transaction_journal_link",
                recreate="always",
                reflect_kwargs={"resolve_fks": False},
            ) as batch_op:
                if needs_uq:
                    batch_op.create_unique_constraint(
                        "uq_tx_journal_link_user_journal_entry",
                        ["user_id", "journal_entry_id"],
                    )
                if needs_ck:
                    batch_op.create_check_constraint(
                        "ck_tx_journal_link_source_nonempty",
                        "source IS NOT NULL AND length(trim(source)) > 0",
                    )
        _create_index_if_missing(
            "transaction_journal_link",
            "ix_tx_journal_link_user_source",
            ["user_id", "source"],
        )

    if _table_exists(bind, "transaction_link_candidate"):
        op.execute(
            sa.text(
                "UPDATE transaction_link_candidate "
                "SET source='backfill' "
                "WHERE source IS NULL OR trim(source) = ''"
            )
        )
        if not _has_named_constraint(bind, "transaction_link_candidate", "ck_tx_link_candidate_source_nonempty"):
            with op.batch_alter_table(
                "transaction_link_candidate",
                recreate="always",
                reflect_kwargs={"resolve_fks": False},
            ) as batch_op:
                batch_op.create_check_constraint(
                    "ck_tx_link_candidate_source_nonempty",
                    "source IS NOT NULL AND length(trim(source)) > 0",
                )
        _create_index_if_missing(
            "transaction_link_candidate",
            "ix_tx_link_candidate_user_tx_reason",
            ["user_id", "transaction_id", "reason"],
        )

    if _table_exists(bind, "csv_import_batch"):
        if not _has_named_constraint(bind, "csv_import_batch", "ck_csv_import_batch_status"):
            with op.batch_alter_table(
                "csv_import_batch",
                recreate="always",
                reflect_kwargs={"resolve_fks": False},
            ) as batch_op:
                batch_op.create_check_constraint(
                    "ck_csv_import_batch_status",
                    "status IN ('processing', 'applied', 'failed')",
                )

    if _table_exists(bind, "csv_import_row"):
        if not _has_named_constraint(bind, "csv_import_row", "ck_csv_import_row_direction"):
            with op.batch_alter_table(
                "csv_import_row",
                recreate="always",
                reflect_kwargs={"resolve_fks": False},
            ) as batch_op:
                batch_op.create_check_constraint(
                    "ck_csv_import_row_direction",
                    "direction IN ('D', 'C')",
                )

    if _table_exists(bind, "tb_reset_snapshot"):
        op.execute(
            sa.text(
                "UPDATE tb_reset_snapshot "
                "SET restore_status='created' "
                "WHERE restore_status IS NULL OR trim(restore_status) = ''"
            )
        )
        needs_uq = "uq_tb_reset_snapshot_user_path" not in _unique_names(bind, "tb_reset_snapshot")
        needs_ck_sha = not _has_named_constraint(bind, "tb_reset_snapshot", "ck_tb_reset_snapshot_sha256_len")
        needs_ck_size = not _has_named_constraint(bind, "tb_reset_snapshot", "ck_tb_reset_snapshot_file_size_nonneg")
        needs_ck_status = not _has_named_constraint(bind, "tb_reset_snapshot", "ck_tb_reset_snapshot_restore_status")
        if needs_uq or needs_ck_sha or needs_ck_size or needs_ck_status:
            with op.batch_alter_table(
                "tb_reset_snapshot",
                recreate="always",
                reflect_kwargs={"resolve_fks": False},
            ) as batch_op:
                if needs_uq:
                    batch_op.create_unique_constraint(
                        "uq_tb_reset_snapshot_user_path",
                        ["user_id", "db_copy_path"],
                    )
                if needs_ck_sha:
                    batch_op.create_check_constraint(
                        "ck_tb_reset_snapshot_sha256_len",
                        "length(sha256) = 64",
                    )
                if needs_ck_size:
                    batch_op.create_check_constraint(
                        "ck_tb_reset_snapshot_file_size_nonneg",
                        "file_size_bytes >= 0",
                    )
                if needs_ck_status:
                    batch_op.create_check_constraint(
                        "ck_tb_reset_snapshot_restore_status",
                        "restore_status IN ('created', 'restored', 'failed')",
                    )
        _create_index_if_missing(
            "tb_reset_snapshot",
            "ix_tb_reset_snapshot_user_created",
            ["user_id", "created_at"],
        )

    _create_index_if_missing(
        "journal_line",
        "ix_journal_line_journal_account_dc",
        ["journal_id", "account_id", "dc"],
    )
    _create_index_if_missing(
        "journal_line",
        "ix_journal_line_account_dc_journal",
        ["account_id", "dc", "journal_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()

    _drop_index_if_exists("journal_line", "ix_journal_line_account_dc_journal")
    _drop_index_if_exists("journal_line", "ix_journal_line_journal_account_dc")

    _drop_index_if_exists("tb_reset_snapshot", "ix_tb_reset_snapshot_user_created")
    if _table_exists(bind, "tb_reset_snapshot"):
        drop_uq = "uq_tb_reset_snapshot_user_path" in _unique_names(bind, "tb_reset_snapshot")
        drop_ck_sha = _has_named_constraint(bind, "tb_reset_snapshot", "ck_tb_reset_snapshot_sha256_len")
        drop_ck_size = _has_named_constraint(bind, "tb_reset_snapshot", "ck_tb_reset_snapshot_file_size_nonneg")
        drop_ck_status = _has_named_constraint(bind, "tb_reset_snapshot", "ck_tb_reset_snapshot_restore_status")
        if drop_uq or drop_ck_sha or drop_ck_size or drop_ck_status:
            with op.batch_alter_table(
                "tb_reset_snapshot",
                recreate="always",
                reflect_kwargs={"resolve_fks": False},
            ) as batch_op:
                if drop_uq:
                    batch_op.drop_constraint("uq_tb_reset_snapshot_user_path", type_="unique")
                if drop_ck_sha:
                    batch_op.drop_constraint("ck_tb_reset_snapshot_sha256_len", type_="check")
                if drop_ck_size:
                    batch_op.drop_constraint("ck_tb_reset_snapshot_file_size_nonneg", type_="check")
                if drop_ck_status:
                    batch_op.drop_constraint("ck_tb_reset_snapshot_restore_status", type_="check")

    if _table_exists(bind, "csv_import_row") and _has_named_constraint(bind, "csv_import_row", "ck_csv_import_row_direction"):
        with op.batch_alter_table(
            "csv_import_row",
            recreate="always",
            reflect_kwargs={"resolve_fks": False},
        ) as batch_op:
            batch_op.drop_constraint("ck_csv_import_row_direction", type_="check")

    if _table_exists(bind, "csv_import_batch") and _has_named_constraint(bind, "csv_import_batch", "ck_csv_import_batch_status"):
        with op.batch_alter_table(
            "csv_import_batch",
            recreate="always",
            reflect_kwargs={"resolve_fks": False},
        ) as batch_op:
            batch_op.drop_constraint("ck_csv_import_batch_status", type_="check")

    _drop_index_if_exists("transaction_link_candidate", "ix_tx_link_candidate_user_tx_reason")
    if _table_exists(bind, "transaction_link_candidate") and _has_named_constraint(
        bind,
        "transaction_link_candidate",
        "ck_tx_link_candidate_source_nonempty",
    ):
        with op.batch_alter_table(
            "transaction_link_candidate",
            recreate="always",
            reflect_kwargs={"resolve_fks": False},
        ) as batch_op:
            batch_op.drop_constraint("ck_tx_link_candidate_source_nonempty", type_="check")

    _drop_index_if_exists("transaction_journal_link", "ix_tx_journal_link_user_source")
    if _table_exists(bind, "transaction_journal_link"):
        drop_uq = "uq_tx_journal_link_user_journal_entry" in _unique_names(bind, "transaction_journal_link")
        drop_ck = _has_named_constraint(bind, "transaction_journal_link", "ck_tx_journal_link_source_nonempty")
        if drop_uq or drop_ck:
            with op.batch_alter_table(
                "transaction_journal_link",
                recreate="always",
                reflect_kwargs={"resolve_fks": False},
            ) as batch_op:
                if drop_uq:
                    batch_op.drop_constraint("uq_tx_journal_link_user_journal_entry", type_="unique")
                if drop_ck:
                    batch_op.drop_constraint("ck_tx_journal_link_source_nonempty", type_="check")
