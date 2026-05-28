"""create gmail_sync_state table

Revision ID: 20260527_0003
Revises: 20260527_0002
Create Date: 2026-05-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260527_0003"
down_revision: Union[str, Sequence[str], None] = "20260527_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gmail_sync_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("scope_key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("last_history_id", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_gmail_sync_state_scope_key", "gmail_sync_state", ["scope_key"])


def downgrade() -> None:
    op.drop_index("ix_gmail_sync_state_scope_key", table_name="gmail_sync_state")
    op.drop_table("gmail_sync_state")
