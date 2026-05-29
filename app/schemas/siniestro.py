from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.scoring import (
    ScoringAiExplanation,
    ScoringBreakdownItem,
    ScoringRuleResult,
    ScoringSignals,
)


class SiniestroBase(BaseModel):
    id_siniestro: str = Field(..., max_length=50)
    id_poliza: str = Field(..., max_length=50)
    id_asegurado: str = Field(..., max_length=50)
    ramo: str = Field(..., max_length=50)
    cobertura: str = Field(..., max_length=100)
    fecha_ocurrencia: date
    fecha_reporte: date
    monto_reclamado: Decimal = Field(..., max_digits=18, decimal_places=2)
    monto_estimado: Decimal = Field(..., max_digits=18, decimal_places=2)
    monto_pagado: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=2)
    estado: str = Field(..., max_length=50)
    sucursal: str = Field(..., max_length=100)
    descripcion: str
    documentos_completos: bool = False
    beneficiario: str = Field(..., max_length=100)
    dias_desde_inicio_poliza: int
    dias_desde_fin_poliza: int
    dias_entre_ocurrencia_reporte: int
    historial_siniestros_asegurado: int = 0
    etiqueta_fraude_simulada: bool = False


class SiniestroCreate(SiniestroBase):
    pass


class SiniestroRead(SiniestroBase):
    model_config = ConfigDict(from_attributes=True)

    owner_email: str | None = None
    gmail_correo_id: int | None = None
    remitente_correo: str | None = None


class SiniestroWithScoreRead(SiniestroRead):
    total_score: int = 0
    average_points: float = 0.0
    score_color: str = "Verde"
    score_band: str = "Bajo"
    rules: list[ScoringRuleResult] | None = None
    breakdown: list[ScoringBreakdownItem] | None = None
    matched_rules: list[str] | None = None
    scoring_version: str | None = None
    ai: ScoringAiExplanation | None = None
    signals: ScoringSignals | None = None
    scoring_audited_at: datetime | None = None


class SiniestrosSummary(BaseModel):
    total: int
    by_color: dict[str, int]
    by_ramo: dict[str, int]
    pending_indexing: int


class SendEmailResponse(BaseModel):
    success: bool
    message: str
    htmlTemplate: str


class SendEmailRequest(BaseModel):
    id_siniestro: str = Field(..., min_length=1, max_length=50)


class SiniestroUpdateStatus(BaseModel):
    estado: str = Field(..., min_length=1, max_length=50)


class SendCustomEmailRequest(BaseModel):
    id_siniestro: str = Field(..., min_length=1, max_length=50)
    to_email: str = Field(..., min_length=1, max_length=255)
    subject: str = Field(..., min_length=1, max_length=255)
    body_html: str = Field(...)
