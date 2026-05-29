from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.integrations.siniestros.scoring import ScoringContext
from app.models.siniestro import Siniestro

_18_MONTHS_DAYS = 548


def base_siniestro_id(id_siniestro: str) -> str:
    """Identificador canónico sin sufijos de variante (|fraudia3|c3, | ESTADO: ...)."""
    return id_siniestro.split("|")[0].strip().upper()


def normalize_narrative(text: str) -> str:
    """Reduce ruido para comparar narrativas sin inflar similitud por espacios."""
    cleaned = re.sub(r"\s+", " ", (text or "").lower()).strip()
    return cleaned[:3000]


def narrative_similarity(a: str, b: str) -> float:
    return SequenceMatcher(a=normalize_narrative(a), b=normalize_narrative(b)).ratio()


def compute_scoring_context(db: Session, siniestro: Siniestro) -> ScoringContext:
    """
    Métricas determinísticas para el motor de reglas.
    - Alcance por owner_email cuando existe.
    - Excluye variantes del mismo id base (duplicados de correo/PDF).
    """
    from datetime import date, timedelta

    cutoff = date.today() - timedelta(days=_18_MONTHS_DAYS)
    current_base = base_siniestro_id(siniestro.id_siniestro)
    owner = (siniestro.owner_email or "").strip().lower() or None

    def owner_clause():
        if not owner:
            return True
        return or_(Siniestro.owner_email == owner, Siniestro.owner_email.is_(None))

    recent = db.scalars(
        select(Siniestro)
        .where(
            Siniestro.id_siniestro != siniestro.id_siniestro,
            owner_clause(),
        )
        .order_by(Siniestro.fecha_reporte.desc())
        .limit(80)
    ).all()

    similarities: list[float] = []
    for row in recent:
        if base_siniestro_id(row.id_siniestro) == current_base:
            continue
        similarities.append(narrative_similarity(siniestro.descripcion, row.descripcion))

    max_sim = max(similarities, default=0.0)

    vehiculo_rows = db.scalars(
        select(Siniestro.id_siniestro)
        .where(
            Siniestro.id_poliza == siniestro.id_poliza,
            Siniestro.id_siniestro != siniestro.id_siniestro,
            Siniestro.fecha_ocurrencia >= cutoff,
            owner_clause(),
        )
    ).all()
    freq_vehiculo = len({base_siniestro_id(row_id) for row_id in vehiculo_rows})

    rc_rows = db.scalars(
        select(Siniestro.id_siniestro)
        .where(
            Siniestro.id_asegurado == siniestro.id_asegurado,
            Siniestro.id_siniestro != siniestro.id_siniestro,
            Siniestro.fecha_ocurrencia >= cutoff,
            owner_clause(),
            or_(
                Siniestro.cobertura.ilike("%responsabilidad%"),
                Siniestro.cobertura.ilike("% rc%"),
                Siniestro.cobertura.ilike("rc %"),
            ),
        )
    ).all()
    freq_rc = len({base_siniestro_id(row_id) for row_id in rc_rows})

    return ScoringContext(
        max_narrative_similarity=max_sim,
        frecuencia_vehiculo=freq_vehiculo,
        frecuencia_rc_previo=freq_rc,
    )
