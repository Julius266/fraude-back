"""create gmail_correos table

Revision ID: 20260527_0002
Revises: 20260527_0001
Create Date: 2026-05-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260527_0002"
down_revision: Union[str, Sequence[str], None] = "20260527_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gmail_correos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("gmail_message_id", sa.String(length=128), nullable=False, unique=True),
        sa.Column("thread_id", sa.String(length=128), nullable=True),
        sa.Column("remitente", sa.String(length=255), nullable=False),
        sa.Column("asunto", sa.String(length=500), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("adjunto_nombre", sa.String(length=255), nullable=True),
        sa.Column("adjunto_ruta", sa.String(length=500), nullable=True),
        sa.Column("tiene_adjunto", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fecha_correo", sa.DateTime(timezone=True), nullable=True),
        sa.Column("palabra_clave_detectada", sa.String(length=100), nullable=True),
        sa.Column("fecha_registro", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_gmail_correos_fecha_registro", "gmail_correos", ["fecha_registro"])
    op.create_index("ix_gmail_correos_asunto", "gmail_correos", ["asunto"])


def downgrade() -> None:
    op.drop_index("ix_gmail_correos_asunto", table_name="gmail_correos")
    op.drop_index("ix_gmail_correos_fecha_registro", table_name="gmail_correos")
    op.drop_table("gmail_correos")
