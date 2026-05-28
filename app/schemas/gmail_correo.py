from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    fecha_registro: datetime
