from pydantic import BaseModel, Field


class ChatQueryRequest(BaseModel):
    question: str = Field(min_length=3, description="Pregunta en lenguaje natural para el asistente antifraude")
    session_id: str = Field(default="default", min_length=1, max_length=100, description="Id de sesion para mantener contexto")
    id_siniestro: str | None = Field(
        default=None,
        max_length=50,
        description="Expediente abierto en auditoria; obligatorio para copiloto por caso",
    )
    k: int | None = Field(default=None, ge=1, le=20, description="Cantidad de siniestros a recuperar para contexto RAG")


class ChatSource(BaseModel):
    id_siniestro: str
    ramo: str
    cobertura: str
    estado: str
    similarity: float = Field(description="Similitud semantica entre la pregunta y el siniestro (0 a 1)")


class ChatQueryResponse(BaseModel):
    answer: str
    session_id: str
    model: str
    sources: list[ChatSource] = Field(default_factory=list)


class ChatIndexResponse(BaseModel):
    indexed: int
    skipped: int


class ChatIndexStatusResponse(BaseModel):
    total: int
    indexed: int
    pending: int


class ChatSessionRead(BaseModel):
    session_id: str
    created_at: str
    updated_at: str
    message_count: int


class ChatMessageRead(BaseModel):
    role: str
    content: str
    created_at: str
