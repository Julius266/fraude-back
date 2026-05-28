"""add owner_email to gmail_correos and siniestros

Revision ID: 20260528_0007
Revises: 20260528_0006
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa

revision = "20260528_0007"
down_revision = "20260528_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gmail_correos", sa.Column("owner_email", sa.String(length=255), nullable=True))
    op.create_index("ix_gmail_correos_owner_email", "gmail_correos", ["owner_email"])

    op.add_column("siniestros", sa.Column("owner_email", sa.String(length=255), nullable=True))
    op.create_index("ix_siniestros_owner_email", "siniestros", ["owner_email"])


def downgrade() -> None:
    op.drop_index("ix_siniestros_owner_email", table_name="siniestros")
    op.drop_column("siniestros", "owner_email")
    op.drop_index("ix_gmail_correos_owner_email", table_name="gmail_correos")
    op.drop_column("gmail_correos", "owner_email")
