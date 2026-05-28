"""create siniestros table

Revision ID: 20260527_0001
Revises: 
Create Date: 2026-05-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260527_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "siniestros",
        sa.Column("id_siniestro", sa.String(length=50), primary_key=True, nullable=False),
        sa.Column("id_poliza", sa.String(length=50), nullable=False),
        sa.Column("id_asegurado", sa.String(length=50), nullable=False),
        sa.Column("ramo", sa.String(length=50), nullable=False),
        sa.Column("cobertura", sa.String(length=100), nullable=False),
        sa.Column("fecha_ocurrencia", sa.Date(), nullable=False),
        sa.Column("fecha_reporte", sa.Date(), nullable=False),
        sa.Column("monto_reclamado", sa.Numeric(18, 2), nullable=False),
        sa.Column("monto_estimado", sa.Numeric(18, 2), nullable=False),
        sa.Column("monto_pagado", sa.Numeric(18, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("estado", sa.String(length=50), nullable=False),
        sa.Column("sucursal", sa.String(length=100), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("documentos_completos", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("beneficiario", sa.String(length=100), nullable=False),
        sa.Column("dias_desde_inicio_poliza", sa.Integer(), nullable=False),
        sa.Column("dias_desde_fin_poliza", sa.Integer(), nullable=False),
        sa.Column("dias_entre_ocurrencia_reporte", sa.Integer(), nullable=False),
        sa.Column("historial_siniestros_asegurado", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("etiqueta_fraude_simulada", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_index("ix_siniestros_id_poliza", "siniestros", ["id_poliza"])
    op.create_index("ix_siniestros_id_asegurado", "siniestros", ["id_asegurado"])
    op.create_index("ix_siniestros_fecha_ocurrencia", "siniestros", ["fecha_ocurrencia"])
    op.create_index("ix_siniestros_estado", "siniestros", ["estado"])


def downgrade() -> None:
    op.drop_index("ix_siniestros_estado", table_name="siniestros")
    op.drop_index("ix_siniestros_fecha_ocurrencia", table_name="siniestros")
    op.drop_index("ix_siniestros_id_asegurado", table_name="siniestros")
    op.drop_index("ix_siniestros_id_poliza", table_name="siniestros")
    op.drop_table("siniestros")
