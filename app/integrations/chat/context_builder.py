from __future__ import annotations

from app.integrations.chat.vector_search import SearchHit
from app.integrations.siniestros.scoring import FraudScoringService, ScoreComputation, ScoringContext
from app.schemas.scoring import ScoringBreakdownItem, ScoringRuleResult, ScoringSignals


def _signals_from_payload(payload: dict | None) -> ScoringSignals:
    if not isinstance(payload, dict):
        return ScoringSignals()
    signals_raw = payload.get("signals")
    if not signals_raw:
        return ScoringSignals()
    try:
        return ScoringSignals(**signals_raw)
    except Exception:
        return ScoringSignals()


def _context_from_payload(payload: dict | None) -> ScoringContext:
    """Restaura el ScoringContext guardado en el scoring_payload del AI audit."""
    if not isinstance(payload, dict):
        return ScoringContext()
    ctx = payload.get("context_data") or {}
    if not isinstance(ctx, dict):
        return ScoringContext()
    return ScoringContext(
        max_narrative_similarity=float(ctx.get("max_narrative_similarity", 0.0)),
        frecuencia_vehiculo=int(ctx.get("frecuencia_vehiculo", 0)),
        frecuencia_rc_previo=int(ctx.get("frecuencia_rc_previo", 0)),
    )


def score_from_persisted_payload(payload: dict | None) -> ScoreComputation | None:
    """Devuelve el scoring persistido por audit_and_persist sin recalcular reglas."""
    if not isinstance(payload, dict):
        return None
    if payload.get("total_score") is None:
        return None

    rules: list[ScoringRuleResult] = []
    for rule in payload.get("rules") or []:
        if isinstance(rule, dict):
            try:
                rules.append(ScoringRuleResult(**rule))
            except Exception:
                continue

    breakdown: list[ScoringBreakdownItem] = []
    for item in payload.get("breakdown") or []:
        if isinstance(item, dict):
            try:
                breakdown.append(ScoringBreakdownItem(**item))
            except Exception:
                continue

    total = int(payload.get("total_score", 0) or 0)
    average = float(payload.get("average_points", 0) or 0)
    color = str(payload.get("score_color") or resolve_score_color_from_total(total))
    band = str(payload.get("score_band") or resolve_score_band_from_total(total))

    return ScoreComputation(
        total_score=total,
        average_points=average,
        score_color=color,
        score_band=band,
        rules=rules,
        breakdown=breakdown,
    )


def reconcile_total_score(payload: dict) -> int:
    rules = payload.get("rules") or []
    if isinstance(rules, list) and rules:
        matched_total = sum(
            int(rule.get("points", 0) or 0)
            for rule in rules
            if isinstance(rule, dict) and rule.get("matched")
        )
        if matched_total > 0:
            return matched_total
        legacy_total = sum(int(rule.get("points", 0) or 0) for rule in rules if isinstance(rule, dict))
        if legacy_total > 0:
            return legacy_total
    return int(payload.get("total_score", 0) or 0)


def official_score_for_siniestro(
    siniestro,
    scoring_service: FraudScoringService | None = None,
) -> ScoreComputation:
    """
    Fuente de verdad del scoring. Restaura signals y context_data del payload
    persistido por el AI audit para que RS-04, RS-06 y RS-13 se muestren correctos.
    """
    service = scoring_service or FraudScoringService()
    payload = getattr(siniestro, "scoring_payload", None)

    if isinstance(payload, dict):
        persisted = score_from_persisted_payload(payload)
        if persisted is not None and payload.get("signals"):
            return persisted

    if not isinstance(payload, dict):
        return service.calculate(siniestro, ScoringSignals())

    signals = _signals_from_payload(payload)
    context = _context_from_payload(payload)
    result = service.calculate(siniestro, signals, context)

    if payload.get("signals"):
        return result

    if payload.get("rules"):
        reconciled = reconcile_total_score(payload)
        if reconciled > result.total_score:
            rule_count = len(payload.get("rules") or []) or 8
            return ScoreComputation(
                total_score=reconciled,
                average_points=round(reconciled / rule_count, 2),
                score_color=resolve_score_color_from_total(reconciled),
                score_band=resolve_score_band_from_total(reconciled),
                rules=result.rules,
                breakdown=result.breakdown,
            )

    return result


def resolve_score_color_from_total(total_score: int) -> str:
    if total_score >= FraudScoringService.SCORE_BAND_ALTO:
        return "Rojo"
    if total_score >= FraudScoringService.SCORE_BAND_MEDIO:
        return "Amarillo"
    return "Verde"


def resolve_score_band_from_total(total_score: int) -> str:
    if total_score >= FraudScoringService.SCORE_BAND_ALTO:
        return "Alto"
    if total_score >= FraudScoringService.SCORE_BAND_MEDIO:
        return "Medio"
    return "Bajo"


def _rules_text_from_score(rules: list[ScoringRuleResult]) -> str:
    matched = [rule for rule in rules if rule.matched and rule.points > 0]
    if not matched:
        return "Sin reglas de fraude activadas."
    return "; ".join(f"{rule.code} (+{rule.points} pts): {rule.reason}" for rule in matched[:8])


class ContextBuilder:
    def __init__(self) -> None:
        self.scoring_service = FraudScoringService()

    def _score_for_siniestro(self, siniestro) -> ScoreComputation:
        return official_score_for_siniestro(siniestro, self.scoring_service)

    def build_siniestro_section(
        self,
        siniestro,
        *,
        header: str = "EXPEDIENTE EN AUDITORIA",
        similarity: float | None = None,
    ) -> str:
        score = self._score_for_siniestro(siniestro)
        total_score = score.total_score
        score_color = score.score_color
        score_band = score.score_band
        average_points = score.average_points
        rules_text = _rules_text_from_score(score.rules)

        payload = getattr(siniestro, "scoring_payload", None)
        ai_summary = ""
        if isinstance(payload, dict):
            ai_block = payload.get("ai") or {}
            if isinstance(ai_block, dict) and ai_block.get("summary"):
                ai_summary = str(ai_block["summary"]).strip()

        lines = [
            f"=== {header}: {siniestro.id_siniestro} ===",
            f"Ramo: {siniestro.ramo} | Cobertura: {siniestro.cobertura}",
            f"Asegurado (id): {siniestro.id_asegurado} | Poliza: {siniestro.id_poliza}",
            f"Beneficiario: {siniestro.beneficiario} | Estado: {siniestro.estado} | Sucursal: {siniestro.sucursal}",
            (
                "Montos: "
                f"reclamado={siniestro.monto_reclamado}, "
                f"estimado={siniestro.monto_estimado}, "
                f"pagado={siniestro.monto_pagado}"
            ),
            (
                "Fechas/dias: "
                f"ocurrencia={siniestro.fecha_ocurrencia}, "
                f"reporte={siniestro.fecha_reporte}, "
                f"dx_inicio={siniestro.dias_desde_inicio_poliza}, "
                f"dx_fin={siniestro.dias_desde_fin_poliza}, "
                f"dx_reporte={siniestro.dias_entre_ocurrencia_reporte}"
            ),
            (
                f"Score auditoria OFICIAL (suma de reglas activas): "
                f"color={score_color}, banda={score_band}, "
                f"total={total_score}, promedio={average_points}"
            ),
            f"Desglose reglas activas: {rules_text}",
            f"Relato/descripcion: {siniestro.descripcion}",
            f"Documentos completos: {'Si' if siniestro.documentos_completos else 'No'}",
        ]
        if ai_summary:
            lines.append(f"Resumen auditoria IA: {ai_summary}")
        if similarity is not None:
            lines.append(f"Similitud pregunta-contexto: {similarity}")
        return "\n".join(lines)

    def build(self, hits: list[SearchHit]) -> str:
        sections: list[str] = []
        for hit in hits:
            sections.append(
                self.build_siniestro_section(
                    hit.siniestro,
                    header="SINIESTRO RELACIONADO",
                    similarity=hit.similarity,
                )
            )
        return "\n\n".join(sections)
