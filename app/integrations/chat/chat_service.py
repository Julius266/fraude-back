from __future__ import annotations

from datetime import datetime, timedelta, timezone

from openai import OpenAI
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.chat.context_builder import ContextBuilder
from app.integrations.chat.embedding_service import EmbeddingService
from app.integrations.chat.vector_search import SearchHit, VectorSearchService
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession


SYSTEM_PROMPT = (
    "Eres un asistente de analisis antifraude para seguros. "
    "Responde en espanol y usa solo el contexto recuperado de siniestros. "
    "No acuses fraude, habla de posible riesgo y necesidad de revision humana. "
    "Si falta informacion, dilo claramente."
)

class ChatService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.embedding_service = EmbeddingService()
        self.vector_search = VectorSearchService(db)
        self.context_builder = ContextBuilder()
        self.client = OpenAI(api_key=self.settings.openai_api_key)
        self.model = self.settings.chat_model or self.settings.openai_model

    def clear_session(self, session_id: str) -> None:
        session = self._get_session(session_id)
        if session is None:
            return
        self.db.delete(session)
        self.db.commit()

    def answer(self, question: str, session_id: str, k: int | None = None) -> tuple[str, str, list[SearchHit]]:
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY no esta configurada")

        self._cleanup_expired_sessions()

        query_vector = self.embedding_service.embed_text(question)
        hits = self.vector_search.search(query_vector, k or self.settings.chat_k_results)

        context = self.context_builder.build(hits)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context:
            messages.append({"role": "system", "content": f"Contexto recuperado:\n{context}"})

        session = self._get_or_create_session(session_id)
        messages.extend(self._recent_messages(session))
        messages.append({"role": "user", "content": question})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
        )
        answer = (response.choices[0].message.content or "").strip()
        if not answer:
            answer = "No pude generar una respuesta con el contexto disponible."

        self._append_message(session, "user", question)
        self._append_message(session, "assistant", answer)
        session.updated_at = datetime.now(timezone.utc)
        self.db.commit()

        return answer, self.model, hits

    def _get_session(self, session_id: str) -> ChatSession | None:
        return self.db.scalar(select(ChatSession).where(ChatSession.session_id == session_id))

    def _get_or_create_session(self, session_id: str) -> ChatSession:
        session = self._get_session(session_id)
        if session is not None:
            return session

        session = ChatSession(session_id=session_id)
        self.db.add(session)
        self.db.flush()
        return session

    def _recent_messages(self, session: ChatSession) -> list[dict[str, str]]:
        limit = max(self.settings.chat_max_history * 2, 2)
        rows = self.db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_db_id == session.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        ).all()
        rows = list(reversed(rows))
        return [{"role": row.role, "content": row.content} for row in rows]

    def _append_message(self, session: ChatSession, role: str, content: str) -> None:
        self.db.add(
            ChatMessage(
                session_db_id=session.id,
                role=role,
                content=content,
            )
        )

    def _cleanup_expired_sessions(self) -> None:
        ttl = max(self.settings.chat_session_ttl_seconds, 60)
        threshold = datetime.now(timezone.utc) - timedelta(seconds=ttl)
        self.db.execute(delete(ChatSession).where(ChatSession.updated_at < threshold))
        self.db.commit()
