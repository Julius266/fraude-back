from fastapi import APIRouter, Body, Depends, Path
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_analyst_email
from app.db.session import get_db
from app.integrations.chat.chat_service import ChatService
from app.integrations.chat.index_service import EmbeddingIndexService
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.schemas.chat import (
    ChatIndexResponse,
    ChatIndexStatusResponse,
    ChatMessageRead,
    ChatQueryRequest,
    ChatQueryResponse,
    ChatSessionRead,
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
    owner_email: str = Depends(get_analyst_email),
) -> ChatQueryResponse:
    chat = ChatService(db, owner_email=owner_email)
    answer, model, hits, active_siniestro = chat.answer(
        question=payload.question,
        session_id=payload.session_id,
        k=payload.k,
        id_siniestro=payload.id_siniestro,
    )

    sources = []
    if active_siniestro is not None:
        sources.append(
            ChatSource(
                id_siniestro=active_siniestro.id_siniestro,
                ramo=active_siniestro.ramo,
                cobertura=active_siniestro.cobertura,
                estado=active_siniestro.estado,
                similarity=1.0,
            )
        )

    sources.extend(
        ChatSource(
            id_siniestro=hit.siniestro.id_siniestro,
            ramo=hit.siniestro.ramo,
            cobertura=hit.siniestro.cobertura,
            estado=hit.siniestro.estado,
            similarity=hit.similarity,
        )
        for hit in hits
    )

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
def index_embeddings(
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> ChatIndexResponse:
    indexed, skipped = EmbeddingIndexService(db, owner_email=owner_email).index_pending()
    return ChatIndexResponse(indexed=indexed, skipped=skipped)


@router.get(
    "/index/status",
    response_model=ChatIndexStatusResponse,
    summary="Ver estado de indexacion",
    description="Muestra total de siniestros, indexados y pendientes de embedding.",
)
def index_status(
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> ChatIndexStatusResponse:
    total, indexed, pending = EmbeddingIndexService(db, owner_email=owner_email).status()
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


@router.get(
    "/sessions",
    response_model=list[ChatSessionRead],
    summary="Listar sesiones de chat",
    description="Devuelve sesiones activas con conteo de mensajes y ultima actividad.",
)
def list_sessions(db: Session = Depends(get_db)) -> list[ChatSessionRead]:
    statement = (
        select(
            ChatSession,
            func.count(ChatMessage.id).label("message_count"),
        )
        .outerjoin(ChatMessage, ChatMessage.session_db_id == ChatSession.id)
        .group_by(ChatSession.id)
        .order_by(ChatSession.updated_at.desc())
    )
    rows = db.execute(statement).all()
    return [
        ChatSessionRead(
            session_id=session.session_id,
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat(),
            message_count=message_count or 0,
        )
        for session, message_count in rows
    ]


@router.get(
    "/session/{session_id}/messages",
    response_model=list[ChatMessageRead],
    summary="Historial de mensajes de una sesion",
)
def session_messages(
    session_id: str = Path(..., min_length=1, max_length=100),
    db: Session = Depends(get_db),
) -> list[ChatMessageRead]:
    session = db.scalar(select(ChatSession).where(ChatSession.session_id == session_id))
    if not session:
        return []

    messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_db_id == session.id)
        .order_by(ChatMessage.created_at.asc())
    ).all()

    return [
        ChatMessageRead(
            role=msg.role,
            content=msg.content,
            created_at=msg.created_at.isoformat(),
        )
        for msg in messages
    ]
