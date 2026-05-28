from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.chat.embedding_service import EmbeddingService
from app.models.siniestro import Siniestro

logger = logging.getLogger(__name__)


class EmbeddingIndexService:
    def __init__(self, db: Session):
        self.db = db
        self.embedding_service = EmbeddingService()

    def status(self) -> tuple[int, int, int]:
        total = int(self.db.scalar(select(func.count()).select_from(Siniestro)) or 0)
        indexed = int(
            self.db.scalar(
                select(func.count()).select_from(Siniestro).where(Siniestro.embedding.is_not(None))
            )
            or 0
        )
        return total, indexed, total - indexed

    def index_pending(self, limit: int = 1000) -> tuple[int, int]:
        pending = self.db.scalars(
            select(Siniestro)
            .where(Siniestro.embedding.is_(None))
            .order_by(Siniestro.fecha_reporte.desc())
            .limit(max(limit, 1))
        ).all()

        indexed = 0
        skipped = 0
        for siniestro in pending:
            try:
                vector = self.embedding_service.embed_siniestro(siniestro)
                siniestro.embedding = vector
                indexed += 1
            except Exception:
                skipped += 1
                logger.exception("No se pudo indexar siniestro id=%s", siniestro.id_siniestro)

        if indexed:
            self.db.commit()

        return indexed, skipped

    def index_one(self, siniestro: Siniestro, commit: bool = True) -> bool:
        try:
            siniestro.embedding = self.embedding_service.embed_siniestro(siniestro)
            if commit:
                self.db.commit()
            return True
        except Exception:
            logger.exception("No se pudo indexar siniestro id=%s", siniestro.id_siniestro)
            if commit:
                self.db.rollback()
            return False
