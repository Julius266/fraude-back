from __future__ import annotations

from app.integrations.chat.vector_search import SearchHit
from app.integrations.siniestros.scoring import FraudScoringService
from app.schemas.scoring import ScoringSignals


class ContextBuilder:
    def __init__(self) -> None:
        self.scoring_service = FraudScoringService()

    def build(self, hits: list[SearchHit]) -> str:
        sections: list[str] = []
        for hit in hits:
            siniestro = hit.siniestro
            score = self.scoring_service.calculate(siniestro, ScoringSignals())
            sections.append(
                "\n".join(
                    [
                        f"=== SINIESTRO {siniestro.id_siniestro} ===",
                        f"Ramo: {siniestro.ramo} | Cobertura: {siniestro.cobertura}",
                        f"Asegurado: {siniestro.id_asegurado} | Poliza: {siniestro.id_poliza}",
                        f"Beneficiario: {siniestro.beneficiario} | Estado: {siniestro.estado}",
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
                        f"Score base actual: color={score.score_color}, banda={score.score_band}, total={score.total_score}",
                        f"Descripcion: {siniestro.descripcion}",
                        f"Similitud pregunta-contexto: {hit.similarity}",
                    ]
                )
            )
        return "\n\n".join(sections)
