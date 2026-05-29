from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.integrations.siniestros.ai_scoring import AIScoringService
from app.integrations.siniestros.scoring import FraudScoringService, ScoringContext
from app.integrations.siniestros.scoring_context import compute_scoring_context
from app.models.siniestro import Siniestro
from app.schemas.scoring import (
    ScoringAiExplanation,
    ScoringContextData,
    ScoringSignals,
    SiniestroAIScoringResponse,
    SiniestroScoringRequest,
)

logger = logging.getLogger(__name__)

_ROBO_KEYWORDS = (
    "robo", "hurto", "sustraccion", "sustracción", "apropiacion", "apropiación",
    "ptxrb", "perdida total por robo", "pérdida total por robo",
)
_MADRUGADA_PATTERN = re.compile(r"\b(0[0-4]|00)\s*:\s*\d{2}\b|madrugada|medianoche")
_COLISION_KEYWORDS = ("colision", "colisión", "choque", "impacto", "accidente")
_FUGA_KEYWORDS = ("fuga", "huyo", "huyó", "no dejo", "no dejó", "sin placa", "tercero desconocido")
_SEVERO_KEYWORDS = ("perdida total", "pérdida total", "inutilizacion", "inutilización", "severo", "destroz")


class AutoScoringService:
    VERSION = FraudScoringService.VERSION

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
            "Auditoría persistida id=%s score=%s band=%s",
            siniestro.id_siniestro, response.total_score, response.score_band,
        )
        return response

    def build_ai_response(
        self,
        siniestro: Siniestro,
        manual_signals: ScoringSignals | None = None,
    ) -> SiniestroAIScoringResponse:
        context = self._compute_context(siniestro)
        heuristic = self._heuristic_signals(siniestro, context)

        ai_explanation: ScoringAiExplanation | None = None
        ai_signals: ScoringSignals | None = None
        try:
            ai_result = AIScoringService(self.db).analyze(siniestro, context=context)
            ai_signals = ai_result.signals
            ai_explanation = ai_result.explanation
        except Exception as exc:
            logger.warning("IA no disponible para id=%s: %s", siniestro.id_siniestro, exc)
            ai_explanation = ScoringAiExplanation(
                model="fallback-heuristic",
                summary=(
                    f"IA no disponible; se aplicaron señales heurísticas determinísticas. "
                    f"Detalle: {exc}"
                ),
                tools_called=[],
                signal_rationale={},
            )

        if manual_signals is not None:
            selected_signals = manual_signals
        elif ai_signals is not None:
            selected_signals = self._merge_signals(ai_signals, heuristic)
        else:
            selected_signals = heuristic

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
        return compute_scoring_context(self.db, siniestro)

    @staticmethod
    def _heuristic_signals(siniestro: Siniestro, context: ScoringContext) -> ScoringSignals:
        cobertura = (siniestro.cobertura or "").lower()
        descripcion = (siniestro.descripcion or "").lower()

        cobertura_robo = any(kw in cobertura for kw in _ROBO_KEYWORDS)
        madrugada = bool(_MADRUGADA_PATTERN.search(descripcion))
        colision = any(kw in descripcion for kw in _COLISION_KEYWORDS)
        sin_tercero = any(kw in descripcion for kw in _FUGA_KEYWORDS) and any(
            kw in descripcion for kw in _SEVERO_KEYWORDS
        )

        docs_inconsistentes = False
        if not siniestro.documentos_completos and any(
            kw in descripcion for kw in ("fecha anterior", "alterad", "ilegible", "contradict")
        ):
            docs_inconsistentes = True

        return ScoringSignals(
            cobertura_involucra_robo=cobertura_robo,
            documentos_inconsistentes=docs_inconsistentes,
            dinamica_accidente_madrugada=madrugada and colision,
            sin_tercero_identificado=sin_tercero,
        )

    @staticmethod
    def _merge_signals(ai: ScoringSignals, heuristic: ScoringSignals) -> ScoringSignals:
        """La IA manda; las heurísticas solo rellenan señales obvias que el modelo omitió."""
        return ScoringSignals(
            cobertura_involucra_robo=ai.cobertura_involucra_robo or heuristic.cobertura_involucra_robo,
            proveedor_en_lista_restrictiva=ai.proveedor_en_lista_restrictiva,
            proveedor_recurrente_observado=ai.proveedor_recurrente_observado,
            documentos_inconsistentes=ai.documentos_inconsistentes or heuristic.documentos_inconsistentes,
            dinamica_relato_ilogico=ai.dinamica_relato_ilogico,
            dinamica_accidente_madrugada=ai.dinamica_accidente_madrugada or heuristic.dinamica_accidente_madrugada,
            sin_tercero_identificado=ai.sin_tercero_identificado or heuristic.sin_tercero_identificado,
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

    @staticmethod
    def payload_needs_reaudit(payload: dict | None) -> bool:
        if not isinstance(payload, dict):
            return True
        return payload.get("version") != FraudScoringService.VERSION
