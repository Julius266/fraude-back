from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GmailCorreoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gmail_message_id: str
    thread_id: str | None = None
    remitente: str
    asunto: str
    descripcion: str
    adjunto_nombre: str | None = None
    adjunto_ruta: str | None = None
    tiene_adjunto: bool
    fecha_correo: datetime | None = None
    palabra_clave_detectada: str | None = None
    owner_email: str | None = None
    fecha_registro: datetime


class GmailScanUser(BaseModel):
    email: str
    name: str
    role: str


class GmailScanAuditSummary(BaseModel):
    id_siniestro: str
    total_score: int
    score_color: str
    score_band: str
    summary: str


class GmailScanResponse(BaseModel):
    saved: int
    ignored: int
    user: GmailScanUser
    audits: list[GmailScanAuditSummary] = Field(default_factory=list)


class GmailAuthStatus(BaseModel):
    credentials_configured: bool
    token_configured: bool
    connected: bool
    redirect_uri: str
    user: GmailScanUser | None = None


class GmailAuthUrlResponse(BaseModel):
    authorization_url: str
    state: str
