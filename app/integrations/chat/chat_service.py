from __future__ import annotations

from datetime import datetime, timedelta, timezone

from openai import OpenAI
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.api.owner_scope import find_siniestro_for_owner
from app.integrations.chat.context_builder import ContextBuilder
from app.integrations.chat.embedding_service import EmbeddingService
from app.integrations.chat.vector_search import SearchHit, VectorSearchService
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.siniestro import Siniestro


SYSTEM_PROMPT = (
    "Eres un asistente de analisis antifraude para seguros. "
    "Responde en espanol y usa solo el contexto recuperado de siniestros. "
    "No acuses fraude, habla de posible riesgo y necesidad de revision humana. "
    "Si falta informacion, dilo claramente."
)

CASE_SYSTEM_PROMPT = (
    "Eres el copiloto del analista auditando UN expediente especifico. "
    "Responde SIEMPRE primero con datos del EXPEDIENTE EN AUDITORIA (beneficiario, asegurado, poliza, montos, relato). "
    "Los demas siniestros del contexto son solo referencia comparativa; no los confundas con el expediente activo. "
    "Si preguntan por el cliente o caso, usa exclusivamente el expediente activo. "
    "Para el puntaje de auditoria, copia EXACTAMENTE el valor total= de la linea "
    "'Score auditoria OFICIAL' y menciona TODAS las reglas del 'Desglose reglas activas'. "
    "No recalcules ni omitas reglas activas."
)


class ChatService:
    def __init__(self, db: Session, owner_email: str | None = None):
        self.db = db
        self.owner_email = (owner_email or "").strip().lower() or None
        self.settings = get_settings()
        self.embedding_service = EmbeddingService()
        self.vector_search = VectorSearchService(db, owner_email=self.owner_email)
        self.context_builder = ContextBuilder()
        self.client = OpenAI(api_key=self.settings.openai_api_key)
        self.model = self.settings.chat_model or self.settings.openai_model

    def clear_session(self, session_id: str) -> None:
        session = self._get_session(session_id)
        if session is None:
            return
        self.db.delete(session)
        self.db.commit()

    def answer(
        self,
        question: str,
        session_id: str,
        k: int | None = None,
        id_siniestro: str | None = None,
    ) -> tuple[str, str, list[SearchHit], Siniestro | None]:
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY no esta configurada")

        self._cleanup_expired_sessions()

        active_id = self._resolve_active_siniestro_id(session_id, id_siniestro)
        active_siniestro = self._load_siniestro(active_id) if active_id else None
        if active_siniestro is not None:
            self.db.refresh(active_siniestro)

        query_vector = self.embedding_service.embed_text(question)
        rag_k = k or self.settings.chat_k_results
        if active_siniestro is not None:
            rag_k = min(rag_k, 4)

        hits = self.vector_search.search(query_vector, rag_k)
        if active_siniestro is not None:
            hits = [hit for hit in hits if hit.siniestro.id_siniestro != active_siniestro.id_siniestro]

        context_parts: list[str] = []
        if active_siniestro is not None:
            context_parts.append(
                self.context_builder.build_siniestro_section(
                    active_siniestro,
                    header="EXPEDIENTE EN AUDITORIA (RESPONDE SOBRE ESTE CASO)",
                )
            )

        related_context = self.context_builder.build(hits)
        if related_context:
            context_parts.append("--- SINIESTROS RELACIONADOS (solo referencia) ---\n" + related_context)

        context = "\n\n".join(context_parts)
        system_prompt = CASE_SYSTEM_PROMPT if active_siniestro is not None else SYSTEM_PROMPT

        messages = [{"role": "system", "content": system_prompt}]
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

        return answer, self.model, hits, active_siniestro

    def _resolve_active_siniestro_id(self, session_id: str, id_siniestro: str | None) -> str | None:
        if id_siniestro and id_siniestro.strip():
            return id_siniestro.strip()
        if session_id.startswith("caso-"):
            return session_id.removeprefix("caso-")
        return None

    def _load_siniestro(self, id_siniestro: str) -> Siniestro | None:
        if self.owner_email:
            return find_siniestro_for_owner(self.db, id_siniestro, self.owner_email)

        siniestro = self.db.scalar(select(Siniestro).where(Siniestro.id_siniestro == id_siniestro))
        if siniestro is not None:
            return siniestro

        clean_id = id_siniestro.split("|")[0].strip()
        if clean_id != id_siniestro:
            clean_filters = [Siniestro.id_siniestro == clean_id]
            if self.owner_email:
                clean_filters.append(Siniestro.owner_email == self.owner_email)
            siniestro = self.db.scalar(select(Siniestro).where(*clean_filters))
            if siniestro is not None:
                return siniestro

        ilike_filters = [Siniestro.id_siniestro.ilike(f"{clean_id}%")]
        if self.owner_email:
            ilike_filters.append(Siniestro.owner_email == self.owner_email)
        return self.db.scalar(select(Siniestro).where(*ilike_filters).limit(1))

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
