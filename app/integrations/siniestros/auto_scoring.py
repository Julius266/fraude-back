from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.integrations.siniestros.ai_scoring import AIScoringService
from app.integrations.siniestros.scoring import FraudScoringService
from app.models.siniestro import Siniestro
from app.schemas.scoring import (
    ScoringAiExplanation,
    ScoringSignals,
    SiniestroAIScoringResponse,
    SiniestroScoringRequest,
)

logger = logging.getLogger(__name__)


class AutoScoringService:
    def __init__(self, db: Session):
        self.db = db
        self.rules_service = FraudScoringService()

    def audit_and_persist(
        self,
        siniestro: Siniestro,
        manual_signals: ScoringSignals | None = None,
    ) -> SiniestroAIScoringResponse:
        response = self.build_ai_response(siniestro, manual_signals=manual_signals)
        siniestro.scoring_payload = response.model_dump(mode="json")
        siniestro.scoring_audited_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(siniestro)
        logger.info(
            "Auditoría automática persistida id=%s score=%s color=%s",
            siniestro.id_siniestro,
            response.total_score,
            response.score_color,
        )
        return response

    def build_ai_response(
        self,
        siniestro: Siniestro,
        manual_signals: ScoringSignals | None = None,
    ) -> SiniestroAIScoringResponse:
        ai_explanation: ScoringAiExplanation | None = None
        ai_signals: ScoringSignals | None = None

        try:
            ai_result = AIScoringService(self.db).analyze(siniestro)
            ai_signals = ai_result.signals
            ai_explanation = ai_result.explanation
        except Exception as exc:
            logger.warning(
                "IA no disponible para id=%s; usando fallback deterministico: %s",
                siniestro.id_siniestro,
                exc,
            )
            ai_explanation = ScoringAiExplanation(
                model="fallback-no-ai",
                summary=f"No se pudo ejecutar IA. Se aplico fallback deterministico. detalle={exc}",
                tools_called=[],
                signal_rationale={},
            )

        selected_signals = manual_signals or ai_signals
        if not selected_signals:
            selected_signals = SiniestroScoringRequest().signals

        result = self.rules_service.calculate(siniestro, selected_signals)
        matched = [rule.code for rule in result.rules if rule.matched]

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
