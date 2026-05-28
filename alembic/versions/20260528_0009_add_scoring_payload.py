"""add scoring_payload and scoring_audited_at to siniestros

Revision ID: 20260528_0009
Revises: 20260528_0008
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa

revision = "20260528_0009"
down_revision = "20260528_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("siniestros", sa.Column("scoring_payload", sa.JSON(), nullable=True))
    op.add_column("siniestros", sa.Column("scoring_audited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("siniestros", "scoring_audited_at")
    op.drop_column("siniestros", "scoring_payload")
