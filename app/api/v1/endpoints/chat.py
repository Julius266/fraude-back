from fastapi import APIRouter, Body, Depends, Path
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.integrations.chat.chat_service import ChatService
from app.integrations.chat.index_service import EmbeddingIndexService
from app.schemas.chat import (
    ChatIndexResponse,
    ChatIndexStatusResponse,
    ChatQueryRequest,
    ChatQueryResponse,
    ChatSource,
)

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post(
    "/query",
    response_model=ChatQueryResponse,
    summary="Consultar chat RAG de siniestros",
    description=(
        "Recupera siniestros relevantes por embeddings (vector search) y responde "
        "en lenguaje natural usando ese contexto."
    ),
)
def query_chat(
    payload: ChatQueryRequest = Body(
        ...,
        examples=[
            {
                "question": "Cuales son los casos mas riesgosos y por que?",
                "session_id": "demo-analista",
                "k": 8,
            }
        ],
    ),
    db: Session = Depends(get_db),
) -> ChatQueryResponse:
    chat = ChatService(db)
    answer, model, hits = chat.answer(
        question=payload.question,
        session_id=payload.session_id,
        k=payload.k,
    )

    sources = [
        ChatSource(
            id_siniestro=hit.siniestro.id_siniestro,
            ramo=hit.siniestro.ramo,
            cobertura=hit.siniestro.cobertura,
            estado=hit.siniestro.estado,
            similarity=hit.similarity,
        )
        for hit in hits
    ]

    return ChatQueryResponse(
        answer=answer,
        session_id=payload.session_id,
        model=model,
        sources=sources,
    )


@router.post(
    "/index",
    response_model=ChatIndexResponse,
    summary="Indexar embeddings pendientes",
    description="Genera embeddings para siniestros sin vector y los guarda en base de datos.",
)
def index_embeddings(db: Session = Depends(get_db)) -> ChatIndexResponse:
    indexed, skipped = EmbeddingIndexService(db).index_pending()
    return ChatIndexResponse(indexed=indexed, skipped=skipped)


@router.get(
    "/index/status",
    response_model=ChatIndexStatusResponse,
    summary="Ver estado de indexacion",
    description="Muestra total de siniestros, indexados y pendientes de embedding.",
)
def index_status(db: Session = Depends(get_db)) -> ChatIndexStatusResponse:
    total, indexed, pending = EmbeddingIndexService(db).status()
    return ChatIndexStatusResponse(total=total, indexed=indexed, pending=pending)


@router.delete(
    "/session/{session_id}",
    summary="Limpiar sesion de chat",
    description="Elimina el historial en memoria de una sesion para iniciar un chat limpio.",
)
def clear_session(
    session_id: str = Path(..., min_length=1, max_length=100, description="Identificador de sesion"),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    ChatService(db).clear_session(session_id)
    return {"status": "cleared", "session_id": session_id}
