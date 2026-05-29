"""create gmail_oauth_tokens

Revision ID: 20260529_0010
Revises: 20260528_0009
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa

revision = "20260529_0010"
down_revision = "20260528_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gmail_oauth_tokens",
        sa.Column("owner_email", sa.String(length=255), nullable=False),
        sa.Column("token_json", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("owner_email"),
    )


def downgrade() -> None:
    op.drop_table("gmail_oauth_tokens")
