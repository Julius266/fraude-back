from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.siniestro import Siniestro


@dataclass
class SearchHit:
    siniestro: Siniestro
    similarity: float


class VectorSearchService:
    def __init__(self, db: Session):
        self.db = db

    def search(self, query_vector: list[float], k: int = 8) -> list[SearchHit]:
        distance_expr = Siniestro.embedding.cosine_distance(query_vector).label("distance")
        rows = self.db.execute(
            select(Siniestro, distance_expr)
            .where(Siniestro.embedding.is_not(None))
            .order_by(distance_expr.asc())
            .limit(max(k, 1))
        ).all()

        hits: list[SearchHit] = []
        for siniestro, distance in rows:
            similarity = max(0.0, 1.0 - float(distance))
            hits.append(SearchHit(siniestro=siniestro, similarity=round(similarity, 4)))
        return hits
