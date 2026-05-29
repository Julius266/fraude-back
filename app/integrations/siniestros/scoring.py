from dataclasses import dataclass, field

from app.models.siniestro import Siniestro
from app.schemas.scoring import ScoringBreakdownItem, ScoringRuleResult, ScoringSignals


@dataclass
class ScoringContext:
    """Métricas pre-calculadas desde la BD antes de evaluar reglas."""
    max_narrative_similarity: float = 0.0  # 0.0–1.0, SequenceMatcher contra siniestros recientes
    frecuencia_vehiculo: int = 0            # siniestros del mismo id_poliza en últimos 18 meses
    frecuencia_rc_previo: int = 0           # siniestros solo RC del mismo asegurado en 18 meses


@dataclass
class ScoreComputation:
    total_score: int
    average_points: float
    score_color: str
    score_band: str
    rules: list[ScoringRuleResult]
    breakdown: list[ScoringBreakdownItem]


class FraudScoringService:
    VERSION = "fraud-rules-v2.1"

    SCORE_BAND_ALTO = 50
    SCORE_BAND_MEDIO = 25

    def calculate(
        self,
        siniestro: Siniestro,
        signals: ScoringSignals,
        context: ScoringContext | None = None,
    ) -> ScoreComputation:
        ctx = context or ScoringContext()
        rules: list[ScoringRuleResult] = [
            self._rs01_borde_vigencia(siniestro),
            self._rs02_demora_denuncia_robo(siniestro, signals),
            self._rs03_frecuencia_asegurado(siniestro),
            self._rs04_frecuencia_vehiculo(ctx),
            self._rs06_frecuencia_rc(ctx),
            self._rs07_proveedor_recurrente(signals),
            self._rs08_documentos_incompletos(siniestro),
            self._rs09_dinamica_sospechosa(signals),
            self._rs10_sin_tercero(signals),
            self._rs11_documentos_inconsistentes(signals),
            self._rs12_reporte_tardio(siniestro),
            self._rs13_narrativas_similares(ctx),
            self._rs14_monto_cercano_suma(siniestro),
        ]

        total_score = sum(r.points for r in rules)
        average_points = total_score / len(rules) if rules else 0.0

        return ScoreComputation(
            total_score=total_score,
            average_points=round(average_points, 2),
            score_color=self._resolve_score_color(total_score),
            score_band=self._resolve_score_band(total_score),
            rules=rules,
            breakdown=self._build_breakdown(rules),
        )

    # ── RS-01: Reclamo cercano al borde de vigencia (max 8 pts) ─────────────
    def _rs01_borde_vigencia(self, siniestro: Siniestro) -> ScoringRuleResult:
        nearest = self._policy_border_days(siniestro)
        if nearest is None:
            return self._rule("RS-01", "Reclamo cercano al borde de vigencia", "Amarillo",
                              False, 0, "Sin fechas de vigencia suficientes para evaluar.")
        if nearest <= 10:
            return self._rule("RS-01", "Reclamo cercano al borde de vigencia", "Amarillo",
                              True, 8, f"Siniestro a {nearest} días del borde de vigencia (≤ 10 días).")
        if nearest <= 30:
            return self._rule("RS-01", "Reclamo cercano al borde de vigencia", "Amarillo",
                              True, 4, f"Siniestro a {nearest} días del borde de vigencia (11–30 días).")
        return self._rule("RS-01", "Reclamo cercano al borde de vigencia", "Amarillo",
                          False, 0, f"Siniestro a {nearest} días del borde de vigencia (> 30 días, fuera de ventana).")

    # ── RS-02: Demora denuncia por robo (max 8 pts) ──────────────────────────
    # Solo aplica cuando la IA detecta que la cobertura involucra robo/sustracción
    def _rs02_demora_denuncia_robo(self, siniestro: Siniestro, signals: ScoringSignals) -> ScoringRuleResult:
        if not signals.cobertura_involucra_robo:
            return self._rule("RS-02", "Demora en denuncia de robo", "Amarillo",
                              False, 0, "La cobertura no involucra robo/sustracción; regla no aplica.")
        days = siniestro.dias_entre_ocurrencia_reporte
        if days > 2:
            return self._rule("RS-02", "Demora en denuncia de robo", "Amarillo",
                              True, 8, f"Denuncia con {days} días de demora (> 48 h).")
        if days >= 1:
            return self._rule("RS-02", "Demora en denuncia de robo", "Amarillo",
                              True, 4, f"Denuncia con {days} días de demora (24–48 h).")
        return self._rule("RS-02", "Demora en denuncia de robo", "Amarillo",
                          False, 0, "Denuncia realizada en menos de 24 horas.")

    # ── RS-03: Alta frecuencia de reclamos – Asegurado (max 8 pts) ───────────
    def _rs03_frecuencia_asegurado(self, siniestro: Siniestro) -> ScoringRuleResult:
        n = siniestro.historial_siniestros_asegurado or 0
        if n >= 3:
            return self._rule("RS-03", "Alta frecuencia de reclamos – Asegurado", "Amarillo",
                              True, 8, f"Asegurado con {n} siniestros en últimos 18 meses (≥ 3).")
        if n == 2:
            return self._rule("RS-03", "Alta frecuencia de reclamos – Asegurado", "Amarillo",
                              True, 4, "Asegurado con 2 siniestros en últimos 18 meses.")
        return self._rule("RS-03", "Alta frecuencia de reclamos – Asegurado", "Amarillo",
                          False, 0, f"Asegurado con {n} siniestro(s) previo(s); frecuencia normal.")

    # ── RS-04: Alta frecuencia de reclamos – Vehículo/Póliza (max 6 pts) ─────
    def _rs04_frecuencia_vehiculo(self, ctx: ScoringContext) -> ScoringRuleResult:
        n = ctx.frecuencia_vehiculo
        if n >= 3:
            return self._rule("RS-04", "Alta frecuencia de reclamos – Vehículo", "Amarillo",
                              True, 6, f"Póliza con {n} siniestros en últimos 18 meses (≥ 3).")
        if n == 2:
            return self._rule("RS-04", "Alta frecuencia de reclamos – Vehículo", "Amarillo",
                              True, 3, "Póliza con 2 siniestros en últimos 18 meses.")
        return self._rule("RS-04", "Alta frecuencia de reclamos – Vehículo", "Amarillo",
                          False, 0, f"Póliza con {n} siniestro(s) previo(s); frecuencia normal.")

    # ── RS-06: Alta frecuencia reclamos solo RC (max 6 pts) ──────────────────
    def _rs06_frecuencia_rc(self, ctx: ScoringContext) -> ScoringRuleResult:
        n = ctx.frecuencia_rc_previo
        if n > 2:
            return self._rule("RS-06", "Alta frecuencia reclamos solo RC", "Amarillo",
                              True, 6, f"Asegurado con {n} eventos previos de solo RC en 18 meses (> 2).")
        if n == 1:
            return self._rule("RS-06", "Alta frecuencia reclamos solo RC", "Amarillo",
                              True, 3, "Asegurado con 1 evento previo de solo RC en 18 meses.")
        return self._rule("RS-06", "Alta frecuencia reclamos solo RC", "Amarillo",
                          False, 0, "Sin frecuencia atípica de reclamos de solo RC.")

    # ── RS-07: Beneficiario / Proveedor recurrente (max 10 pts) ──────────────
    def _rs07_proveedor_recurrente(self, signals: ScoringSignals) -> ScoringRuleResult:
        if signals.proveedor_en_lista_restrictiva:
            return self._rule("RS-07", "Beneficiario / Proveedor recurrente", "Rojo",
                              True, 10, "Beneficiario o proveedor figura en lista restrictiva.")
        if signals.proveedor_recurrente_observado:
            return self._rule("RS-07", "Beneficiario / Proveedor recurrente", "Rojo",
                              True, 5, "Proveedor/beneficiario recurrente en > 2 casos observados este año.")
        return self._rule("RS-07", "Beneficiario / Proveedor recurrente", "Rojo",
                          False, 0, "Sin alertas de proveedor o beneficiario recurrente.")

    # ── RS-08: Documentos incompletos (max 4 pts) ─────────────────────────────
    def _rs08_documentos_incompletos(self, siniestro: Siniestro) -> ScoringRuleResult:
        matched = not siniestro.documentos_completos
        return self._rule("RS-08", "Documentos incompletos", "Amarillo",
                          matched, 4 if matched else 0,
                          "Expediente marcado como documentación incompleta." if matched else "Documentación completa.")

    # ── RS-09: Dinámica sospechosa (max 6 pts) ────────────────────────────────
    def _rs09_dinamica_sospechosa(self, signals: ScoringSignals) -> ScoringRuleResult:
        if signals.dinamica_relato_ilogico:
            return self._rule("RS-09", "Dinámica sospechosa", "Rojo",
                              True, 6, "Relato ilógico o incompatible con el tipo de impacto/daño.")
        if signals.dinamica_accidente_madrugada:
            return self._rule("RS-09", "Dinámica sospechosa", "Rojo",
                              True, 3, "Accidente múltiple en horario de madrugada (00:00–05:00).")
        return self._rule("RS-09", "Dinámica sospechosa", "Rojo",
                          False, 0, "Sin indicadores de dinámica sospechosa.")

    # ── RS-10: Evento sin tercero identificado (max 5 pts) ───────────────────
    def _rs10_sin_tercero(self, signals: ScoringSignals) -> ScoringRuleResult:
        matched = signals.sin_tercero_identificado
        return self._rule("RS-10", "Evento sin tercero identificado", "Amarillo",
                          matched, 5 if matched else 0,
                          "Daño severo sin rastro del tercero ni cámaras." if matched else "Tercero identificado o no aplica.")

    # ── RS-11: Documentos inconsistentes (max 10 pts) ────────────────────────
    def _rs11_documentos_inconsistentes(self, signals: ScoringSignals) -> ScoringRuleResult:
        matched = signals.documentos_inconsistentes
        return self._rule("RS-11", "Documentos inconsistentes", "Rojo",
                          matched, 10 if matched else 0,
                          "Alteración confirmada, fechas previas al evento o datos contradictorios." if matched else "Sin inconsistencias documentales detectadas.")

    # ── RS-12: Reporte tardío (max 5 pts) ────────────────────────────────────
    def _rs12_reporte_tardio(self, siniestro: Siniestro) -> ScoringRuleResult:
        days = siniestro.dias_entre_ocurrencia_reporte
        if days > 7:
            return self._rule("RS-12", "Reporte tardío", "Amarillo",
                              True, 5, f"Reporte con {days} días de demora (> 7 días).")
        if days >= 4:
            return self._rule("RS-12", "Reporte tardío", "Amarillo",
                              True, 3, f"Reporte con {days} días de demora (4–7 días).")
        return self._rule("RS-12", "Reporte tardío", "Amarillo",
                          False, 0, f"Reporte dentro del plazo normal ({days} días).")

    # ── RS-13: Narrativas similares (max 8 pts) ───────────────────────────────
    def _rs13_narrativas_similares(self, ctx: ScoringContext) -> ScoringRuleResult:
        sim = ctx.max_narrative_similarity
        if sim >= 0.85:
            return self._rule("RS-13", "Narrativas similares", "Amarillo",
                              True, 8, f"Narrativa con {sim:.0%} de similitud textual con otro reclamo (> 85%).")
        if sim >= 0.70:
            return self._rule("RS-13", "Narrativas similares", "Amarillo",
                              True, 4, f"Narrativa con {sim:.0%} de similitud textual (70–84%).")
        return self._rule("RS-13", "Narrativas similares", "Amarillo",
                          False, 0, f"Similitud narrativa máxima {sim:.0%} — dentro de rango normal.")

    # ── RS-14: Monto cercano o superior a suma asegurada (max 4 pts) ─────────
    def _rs14_monto_cercano_suma(self, siniestro: Siniestro) -> ScoringRuleResult:
        estimado = float(siniestro.monto_estimado or 0)
        reclamado = float(siniestro.monto_reclamado or 0)
        if estimado <= 0:
            return self._rule("RS-14", "Monto cercano o superior a suma asegurada", "Amarillo",
                              False, 0, "Sin monto estimado/reserva disponible para calcular proporción.")
        # Reserva operativa igual al reclamo es habitual en expedientes; no es alerta por sí sola.
        if abs(reclamado - estimado) < max(estimado * 0.01, 1.0):
            return self._rule("RS-14", "Monto cercano o superior a suma asegurada", "Amarillo",
                              False, 0,
                              "Monto reclamado coincide con la reserva/estimado (operación normal).")
        if reclamado > estimado:
            return self._rule("RS-14", "Monto cercano o superior a suma asegurada", "Amarillo",
                              True, 4,
                              f"Monto reclamado (${reclamado:,.0f}) supera la reserva/estimado (${estimado:,.0f}).")
        ratio = reclamado / estimado
        if ratio >= 0.95:
            return self._rule("RS-14", "Monto cercano o superior a suma asegurada", "Amarillo",
                              True, 4,
                              f"Monto reclamado representa el {ratio:.0%} de la reserva/estimado (≥ 95%).")
        return self._rule("RS-14", "Monto cercano o superior a suma asegurada", "Amarillo",
                          False, 0,
                          f"Monto reclamado ({ratio:.0%} de la reserva) dentro de rango normal.")

    # ── helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _rule(code: str, title: str, classification: str, matched: bool, points: int, reason: str) -> ScoringRuleResult:
        return ScoringRuleResult(code=code, title=title, classification=classification,
                                 matched=matched, points=points, reason=reason)

    def _policy_border_days(self, siniestro: Siniestro) -> int | None:
        start = getattr(siniestro, "dias_desde_inicio_poliza", None)
        end = getattr(siniestro, "dias_desde_fin_poliza", None)
        if start is None or end is None:
            return None
        candidates = [v for v in [start, end] if v > 0]
        return min(candidates) if candidates else None

    def _resolve_score_color(self, total: int) -> str:
        if total >= self.SCORE_BAND_ALTO:
            return "Rojo"
        if total >= self.SCORE_BAND_MEDIO:
            return "Amarillo"
        return "Verde"

    def _resolve_score_band(self, total: int) -> str:
        if total >= self.SCORE_BAND_ALTO:
            return "Alto"
        if total >= self.SCORE_BAND_MEDIO:
            return "Medio"
        return "Bajo"

    def _build_breakdown(self, rules: list[ScoringRuleResult]) -> list[ScoringBreakdownItem]:
        breakdown = []
        running = 0
        total_pts = sum(r.points for r in rules) or 1
        for rule in rules:
            running += rule.points
            breakdown.append(ScoringBreakdownItem(
                code=rule.code, title=rule.title, matched=rule.matched,
                points=rule.points, running_total=running,
                percent_of_total=round((rule.points / total_pts) * 100, 2),
                reason=rule.reason,
            ))
        return breakdown
