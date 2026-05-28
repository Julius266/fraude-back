from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GmailCorreo(Base):
    __tablename__ = "gmail_correos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gmail_message_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remitente: Mapped[str] = mapped_column(String(255), nullable=False)
    asunto: Mapped[str] = mapped_column(String(500), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    adjunto_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    adjunto_ruta: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tiene_adjunto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fecha_correo: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    palabra_clave_detectada: Mapped[str | None] = mapped_column(String(100), nullable=True)
    owner_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    fecha_registro: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    siniestros = relationship("Siniestro", back_populates="correo")

    __table_args__ = (
        Index("ix_gmail_correos_fecha_registro", "fecha_registro"),
        Index("ix_gmail_correos_asunto", "asunto"),
    )
