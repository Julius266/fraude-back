"""link siniestros to gmail correos

Revision ID: 20260527_0004
Revises: 20260527_0003
Create Date: 2026-05-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260527_0004"
down_revision: Union[str, Sequence[str], None] = "20260527_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("siniestros", sa.Column("gmail_correo_id", sa.Integer(), nullable=True))
    op.create_index("ix_siniestros_gmail_correo_id", "siniestros", ["gmail_correo_id"])
    op.create_foreign_key(
        "fk_siniestros_gmail_correo_id_gmail_correos",
        "siniestros",
        "gmail_correos",
        ["gmail_correo_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_siniestros_gmail_correo_id_gmail_correos", "siniestros", type_="foreignkey")
    op.drop_index("ix_siniestros_gmail_correo_id", table_name="siniestros")
    op.drop_column("siniestros", "gmail_correo_id")
