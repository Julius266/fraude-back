from dataclasses import dataclass

from app.models.siniestro import Siniestro
from app.schemas.scoring import ScoringBreakdownItem, ScoringSignals, ScoringRuleResult


@dataclass
class ScoreComputation:
    total_score: int
    average_points: float
    score_color: str
    score_band: str
    rules: list[ScoringRuleResult]
    breakdown: list[ScoringBreakdownItem]


class FraudScoringService:
    VERSION = "fraud-rules-v1"

    # Pesos alineados con la matriz de auditoría del frontend (Clarity Card / mockClaims)
    POINTS_RS01_CRITICAL = 8
    POINTS_RS01_MODERATE = 4
    POINTS_RF01 = 20
    POINTS_RF02 = 22
    POINTS_RF03 = 15
    POINTS_RF04 = 25
    POINTS_RF05 = 15
    POINTS_RF06 = 8
    POINTS_RF07 = 42

    SCORE_BAND_ALTO = 71
    SCORE_BAND_MEDIO = 36

    def calculate(self, siniestro: Siniestro, signals: ScoringSignals) -> ScoreComputation:
        rules: list[ScoringRuleResult] = []

        rules.append(self._rule_reclamo_borde_vigencia(siniestro))
        rules.append(self._rf_01_total_loss_robbery(siniestro))
        rules.append(self._rf_02_document_forgery(signals))
        rules.append(self._rf_03_restrictive_list(signals))
        rules.append(self._rf_04_physically_impossible(signals))
        rules.append(self._rf_05_extreme_border(siniestro))
        rules.append(self._rf_06_theft_report_delay(signals))
        rules.append(self._rf_07_cloned_narrative(signals))

        total_score = sum(item.points for item in rules)
        average_points = total_score / len(rules) if rules else 0.0
        breakdown = self._build_breakdown(rules)
        score_color = self._resolve_score_color(rules, total_score)
        score_band = self._resolve_score_band(total_score)

        return ScoreComputation(
            total_score=total_score,
            average_points=round(average_points, 2),
            score_color=score_color,
            score_band=score_band,
            rules=rules,
            breakdown=breakdown,
        )

    def _rule_reclamo_borde_vigencia(self, siniestro: Siniestro) -> ScoringRuleResult:
        nearest_days = self._policy_border_days(siniestro)
        if nearest_days is None:
            return ScoringRuleResult(
                code="RS-01",
                title="Reclamo cercano al borde de vigencia",
                classification="Amarillo",
                matched=False,
                points=0,
                reason="No hay fechas de vigencia de poliza suficientes para evaluar esta regla.",
            )

        if nearest_days <= 10:
            points = self.POINTS_RS01_CRITICAL
            matched = True
            reason = "Siniestro al borde de vigencia con <= 10 dias."
        elif nearest_days <= 30:
            points = self.POINTS_RS01_MODERATE
            matched = True
            reason = "Siniestro cercano al borde de vigencia entre 11 y 30 dias."
        else:
            points = 0
            matched = False
            reason = "Siniestro fuera de la ventana de riesgo de 30 dias."

        return ScoringRuleResult(
            code="RS-01",
            title="Reclamo cercano al borde de vigencia",
            classification="Amarillo",
            matched=matched,
            points=points,
            reason=reason,
        )

    def _rf_01_total_loss_robbery(self, siniestro: Siniestro) -> ScoringRuleResult:
        normalized = f"{siniestro.ramo} {siniestro.cobertura}".lower()
        matched = "robo" in normalized and "total" in normalized
        points = self.POINTS_RF01 if matched else 0
        return ScoringRuleResult(
            code="RF-01",
            title="Cobertura Perdida Total por Robo (PTxRB)",
            classification="Rojo",
            matched=matched,
            points=points,
            reason="Detectado por palabras clave en ramo/cobertura." if matched else "No se detecta PTxRB en ramo/cobertura.",
        )

    def _rf_02_document_forgery(self, signals: ScoringSignals) -> ScoringRuleResult:
        matched = signals.evidencia_falsificacion_documental
        points = self.POINTS_RF02 if matched else 0
        return ScoringRuleResult(
            code="RF-02",
            title="Evidencia de falsificacion o adulteracion documental",
            classification="Rojo",
            matched=matched,
            points=points,
            reason="Bandera de falsificacion activada por analista/sistema." if matched else "Sin evidencia de falsificacion reportada.",
        )

    def _rf_03_restrictive_list(self, signals: ScoringSignals) -> ScoringRuleResult:
        matched = signals.coincidencia_lista_restrictiva
        points = self.POINTS_RF03 if matched else 0
        return ScoringRuleResult(
            code="RF-03",
            title="Coincidencia exacta con lista restrictiva",
            classification="Rojo",
            matched=matched,
            points=points,
            reason="Existe coincidencia exacta en lista restrictiva." if matched else "Sin coincidencias exactas en lista restrictiva.",
        )

    def _rf_04_physically_impossible(self, signals: ScoringSignals) -> ScoringRuleResult:
        matched = signals.dinamica_accidente_imposible
        points = self.POINTS_RF04 if matched else 0
        return ScoringRuleResult(
            code="RF-04",
            title="Dinamica del accidente fisicamente imposible",
            classification="Rojo",
            matched=matched,
            points=points,
            reason="La dinamica fue marcada como fisicamente imposible." if matched else "Sin marca de imposibilidad fisica.",
        )

    def _rf_05_extreme_border(self, siniestro: Siniestro) -> ScoringRuleResult:
        nearest_days = self._policy_border_days(siniestro)
        if nearest_days is None:
            return ScoringRuleResult(
                code="RF-05",
                title="Siniestro extremo al borde de vigencia (<48 hrs)",
                classification="Amarillo",
                matched=False,
                points=0,
                reason="No hay fechas de vigencia de poliza suficientes para evaluar esta regla.",
            )

        matched = nearest_days <= 2
        points = self.POINTS_RF05 if matched else 0
        return ScoringRuleResult(
            code="RF-05",
            title="Siniestro extremo al borde de vigencia (<48 hrs)",
            classification="Amarillo",
            matched=matched,
            points=points,
            reason="Siniestro dentro de 48 horas del borde de vigencia." if matched else "No ocurre dentro de 48 horas del borde de vigencia.",
        )

    def _policy_border_days(self, siniestro: Siniestro) -> int | None:
        start_days = getattr(siniestro, "dias_desde_inicio_poliza", None)
        end_days = getattr(siniestro, "dias_desde_fin_poliza", None)

        if start_days is None or end_days is None:
            return None

        if start_days <= 0 and end_days <= 0:
            return None

        candidates = [value for value in [start_days, end_days] if value > 0]
        if not candidates:
            return None

        return min(candidates)

    def _rf_06_theft_report_delay(self, signals: ScoringSignals) -> ScoringRuleResult:
        matched = signals.demora_atipica_denuncia_robo
        points = self.POINTS_RF06 if matched else 0
        return ScoringRuleResult(
            code="RF-06",
            title="Demora atipica en denuncia de robo (> 4 dias)",
            classification="Amarillo",
            matched=matched,
            points=points,
            reason="Existe demora atipica en la denuncia del robo." if matched else "Sin demora atipica reportada.",
        )

    def _rf_07_cloned_narrative(self, signals: ScoringSignals) -> ScoringRuleResult:
        matched = signals.narrativa_clonada
        points = self.POINTS_RF07 if matched else 0
        return ScoringRuleResult(
            code="RF-07",
            title="Narrativa identica (clonada)",
            classification="Amarillo",
            matched=matched,
            points=points,
            reason="Se detecto narrativa clonada frente a otros casos." if matched else "No hay evidencia de narrativa clonada.",
        )

    def _resolve_score_color(self, rules: list[ScoringRuleResult], total_score: int) -> str:
        """Color derivado del puntaje total: a mayor score, mayor severidad."""
        if total_score >= self.SCORE_BAND_ALTO:
            return "Rojo"
        if total_score >= self.SCORE_BAND_MEDIO:
            return "Amarillo"
        return "Verde"

    def _resolve_score_band(self, total_score: int) -> str:
        if total_score >= self.SCORE_BAND_ALTO:
            return "Alto"
        if total_score >= self.SCORE_BAND_MEDIO:
            return "Medio"
        return "Bajo"

    def _build_breakdown(self, rules: list[ScoringRuleResult]) -> list[ScoringBreakdownItem]:
        breakdown: list[ScoringBreakdownItem] = []
        running_total = 0
        total_points = sum(rule.points for rule in rules) or 1

        for rule in rules:
            running_total += rule.points
            breakdown.append(
                ScoringBreakdownItem(
                    code=rule.code,
                    title=rule.title,
                    matched=rule.matched,
                    points=rule.points,
                    running_total=running_total,
                    percent_of_total=round((rule.points / total_points) * 100, 2),
                    reason=rule.reason,
                )
            )

        return breakdown
