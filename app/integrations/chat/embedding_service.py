from __future__ import annotations

from openai import OpenAI

from app.core.config import get_settings
from app.models.siniestro import Siniestro


class EmbeddingService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = OpenAI(api_key=self.settings.openai_api_key)
        self.model = self.settings.embedding_model

    def embed_text(self, text: str) -> list[float]:
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY no esta configurada")

        response = self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding

    def embed_siniestro(self, siniestro: Siniestro) -> list[float]:
        return self.embed_text(self._format_siniestro_text(siniestro))

    def _format_siniestro_text(self, siniestro: Siniestro) -> str:
        return (
            f"Siniestro {siniestro.id_siniestro}. "
            f"Ramo: {siniestro.ramo}. Cobertura: {siniestro.cobertura}. "
            f"Descripcion: {siniestro.descripcion}. "
            f"Asegurado: {siniestro.id_asegurado}. Poliza: {siniestro.id_poliza}. "
            f"Beneficiario: {siniestro.beneficiario}. Estado: {siniestro.estado}. "
            f"Monto reclamado: {siniestro.monto_reclamado}. "
            f"Dias desde inicio poliza: {siniestro.dias_desde_inicio_poliza}. "
            f"Dias desde fin poliza: {siniestro.dias_desde_fin_poliza}. "
            f"Dias entre ocurrencia y reporte: {siniestro.dias_entre_ocurrencia_reporte}. "
            f"Documentos completos: {siniestro.documentos_completos}."
        )
