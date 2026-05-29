from __future__ import annotations

import logging
from datetime import date, timedelta
from difflib import SequenceMatcher

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.integrations.siniestros.ai_scoring import AIScoringService
from app.integrations.siniestros.scoring import FraudScoringService, ScoringContext
from app.models.siniestro import Siniestro
from app.schemas.scoring import (
    ScoringAiExplanation,
    ScoringContextData,
    ScoringSignals,
    SiniestroAIScoringResponse,
    SiniestroScoringRequest,
)

logger = logging.getLogger(__name__)

_18_MONTHS = timedelta(days=548)


class AutoScoringService:
    def __init__(self, db: Session):
        self.db = db
        self.rules_service = FraudScoringService()

    def audit_and_persist(
        self,
        siniestro: Siniestro,
        manual_signals: ScoringSignals | None = None,
    ) -> SiniestroAIScoringResponse:
        from datetime import datetime, timezone
        response = self.build_ai_response(siniestro, manual_signals=manual_signals)
        siniestro.scoring_payload = response.model_dump(mode="json")
        siniestro.scoring_audited_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(siniestro)
        logger.info(
            "Auditoría persistida id=%s score=%s band=%s",
            siniestro.id_siniestro, response.total_score, response.score_band,
        )
        return response

    def build_ai_response(
        self,
        siniestro: Siniestro,
        manual_signals: ScoringSignals | None = None,
    ) -> SiniestroAIScoringResponse:
        # 1. Métricas determinísticas que requieren BD
        context = self._compute_context(siniestro)

        # 2. Señales semánticas via IA
        ai_explanation: ScoringAiExplanation | None = None
        ai_signals: ScoringSignals | None = None
        try:
            ai_result = AIScoringService(self.db).analyze(siniestro)
            ai_signals = ai_result.signals
            ai_explanation = ai_result.explanation
        except Exception as exc:
            logger.warning("IA no disponible para id=%s: %s", siniestro.id_siniestro, exc)
            ai_explanation = ScoringAiExplanation(
                model="fallback-no-ai",
                summary=f"IA no disponible. Fallback determinístico aplicado. Detalle: {exc}",
                tools_called=[],
                signal_rationale={},
            )

        selected_signals = manual_signals or ai_signals or SiniestroScoringRequest().signals

        # 3. Motor de reglas con contexto de BD + señales de IA
        result = self.rules_service.calculate(siniestro, selected_signals, context)
        matched = [r.code for r in result.rules if r.matched]

        return SiniestroAIScoringResponse(
            id_siniestro=siniestro.id_siniestro,
            total_score=result.total_score,
            average_points=result.average_points,
            score_color=result.score_color,
            score_band=result.score_band,
            rules=result.rules,
            breakdown=result.breakdown,
            matched_rules=matched,
            version=self.rules_service.VERSION,
            ai=ai_explanation,
            signals=selected_signals,
            context_data=ScoringContextData(
                max_narrative_similarity=context.max_narrative_similarity,
                frecuencia_vehiculo=context.frecuencia_vehiculo,
                frecuencia_rc_previo=context.frecuencia_rc_previo,
            ),
        )

    def _compute_context(self, siniestro: Siniestro) -> ScoringContext:
        """Consultas a BD para las métricas determinísticas que no vienen en el modelo."""
        cutoff = date.today() - _18_MONTHS

        # Similitud narrativa máxima contra los últimos 50 siniestros
        recent = self.db.scalars(
            select(Siniestro)
            .where(Siniestro.id_siniestro != siniestro.id_siniestro)
            .order_by(Siniestro.fecha_reporte.desc())
            .limit(50)
        ).all()
        similarities = [
            SequenceMatcher(
                a=siniestro.descripcion.lower(),
                b=row.descripcion.lower(),
            ).ratio()
            for row in recent
        ]
        max_sim = max(similarities, default=0.0)

        # Frecuencia de siniestros del mismo vehículo/póliza en 18 meses
        freq_vehiculo = int(self.db.scalar(
            select(func.count()).select_from(Siniestro)
            .where(
                Siniestro.id_poliza == siniestro.id_poliza,
                Siniestro.id_siniestro != siniestro.id_siniestro,
                Siniestro.fecha_ocurrencia >= cutoff,
            )
        ) or 0)

        # Frecuencia de siniestros solo RC del mismo asegurado en 18 meses
        freq_rc = int(self.db.scalar(
            select(func.count()).select_from(Siniestro)
            .where(
                Siniestro.id_asegurado == siniestro.id_asegurado,
                Siniestro.id_siniestro != siniestro.id_siniestro,
                Siniestro.fecha_ocurrencia >= cutoff,
                or_(
                    Siniestro.cobertura.ilike("%responsabilidad%"),
                    Siniestro.cobertura.ilike("% rc%"),
                    Siniestro.cobertura.ilike("rc %"),
                ),
            )
        ) or 0)

        return ScoringContext(
            max_narrative_similarity=max_sim,
            frecuencia_vehiculo=freq_vehiculo,
            frecuencia_rc_previo=freq_rc,
        )

    @staticmethod
    def to_audit_summary(response: SiniestroAIScoringResponse) -> dict[str, object]:
        summary = response.ai.summary if response.ai else "Auditoría completada."
        return {
            "id_siniestro": response.id_siniestro,
            "total_score": response.total_score,
            "score_color": response.score_color,
            "score_band": response.score_band,
            "summary": summary,
        }
