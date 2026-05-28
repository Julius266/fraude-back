from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from app.db.base import Base


class Siniestro(Base):
    __tablename__ = "siniestros"

    id_siniestro = Column(String(50), primary_key=True, nullable=False)
    owner_email = Column(String(255), nullable=True, index=True)
    gmail_correo_id = Column(Integer, ForeignKey("gmail_correos.id", ondelete="SET NULL"), nullable=True)
    id_poliza = Column(String(50), nullable=False)
    id_asegurado = Column(String(50), nullable=False)
    ramo = Column(String(50), nullable=False)
    cobertura = Column(String(100), nullable=False)
    fecha_ocurrencia = Column(Date, nullable=False)
    fecha_reporte = Column(Date, nullable=False)
    monto_reclamado = Column(Numeric(18, 2), nullable=False)
    monto_estimado = Column(Numeric(18, 2), nullable=False)
    monto_pagado = Column(Numeric(18, 2), nullable=False, default=0)
    estado = Column(String(50), nullable=False)
    sucursal = Column(String(100), nullable=False)
    descripcion = Column(Text, nullable=False)
    documentos_completos = Column(Boolean, nullable=False, default=False)
    beneficiario = Column(String(100), nullable=False)
    dias_desde_inicio_poliza = Column(Integer, nullable=False)
    dias_desde_fin_poliza = Column(Integer, nullable=False)
    dias_entre_ocurrencia_reporte = Column(Integer, nullable=False)
    historial_siniestros_asegurado = Column(Integer, nullable=False, default=0)
    etiqueta_fraude_simulada = Column(Boolean, nullable=False, default=False)
    embedding = Column(Vector(1536), nullable=True)
    scoring_payload = Column(JSON, nullable=True)
    scoring_audited_at = Column(DateTime(timezone=True), nullable=True)
    correo = relationship("GmailCorreo", back_populates="siniestros")

    __table_args__ = (
        Index("ix_siniestros_gmail_correo_id", "gmail_correo_id"),
        Index("ix_siniestros_id_poliza", "id_poliza"),
        Index("ix_siniestros_id_asegurado", "id_asegurado"),
        Index("ix_siniestros_fecha_ocurrencia", "fecha_ocurrencia"),
        Index("ix_siniestros_estado", "estado"),
    )
