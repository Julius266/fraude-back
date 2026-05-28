"""add vector embeddings to siniestros

Revision ID: 20260528_0005
Revises: 20260527_0004
Create Date: 2026-05-28

"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260528_0005"
down_revision: Union[str, Sequence[str], None] = "20260527_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE siniestros ADD COLUMN embedding vector(1536)")
    op.execute(
        "CREATE INDEX ix_siniestros_embedding ON siniestros USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_siniestros_embedding")
    op.execute("ALTER TABLE siniestros DROP COLUMN IF EXISTS embedding")
