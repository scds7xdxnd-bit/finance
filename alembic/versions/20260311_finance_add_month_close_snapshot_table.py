"""Add month_close_snapshot table for optional month-close persistence.

Revision ID: c4f5a6b7c8d9
Revises: b1c2d3e4f5a6
Create Date: 2026-03-11 12:10:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "month_close_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ym", sa.String(length=7), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_mode", sa.String(length=30), nullable=True),
        sa.CheckConstraint(
            "length(ym) = 7 AND substr(ym, 5, 1) = '-'",
            name="ck_month_close_snapshot_ym_fmt",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_month_close_snapshot_ym_created_desc",
        "month_close_snapshot",
        ["ym", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_month_close_snapshot_ym_created_desc",
        table_name="month_close_snapshot",
    )
    op.drop_table("month_close_snapshot")
