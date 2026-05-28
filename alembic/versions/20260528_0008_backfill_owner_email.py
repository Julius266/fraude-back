"""backfill owner_email on siniestros from gmail_correos

Revision ID: 20260528_0008
Revises: 20260528_0007
Create Date: 2026-05-28
"""

from alembic import op

revision = "20260528_0008"
down_revision = "20260528_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE siniestros AS s
        SET owner_email = gc.owner_email
        FROM gmail_correos AS gc
        WHERE s.gmail_correo_id = gc.id
          AND s.owner_email IS NULL
          AND gc.owner_email IS NOT NULL
        """
    )


def downgrade() -> None:
    pass
