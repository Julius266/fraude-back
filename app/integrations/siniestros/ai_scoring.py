from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from openai import OpenAI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.siniestros.fraud_rules_context import build_fraud_rules_prompt_section
from app.models.gmail_correo import GmailCorreo
from app.models.siniestro import Siniestro
from app.schemas.scoring import ScoringAiExplanation, ScoringSignals

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_BASE = """
Eres un analista antifraude de seguros de vehículos. Analizas expedientes de siniestros y decides
señales booleanas que luego alimentan un motor de scoring de fraude.

Debes decidir ÚNICAMENTE las siguientes señales. Lee cada definición con cuidado:

1. cobertura_involucra_robo
   TRUE si la cobertura contratada o el tipo de siniestro implica robo, hurto, sustracción,
   apropiación indebida o pérdida por cualquier acto de tercero con intención de apoderarse del
   vehículo o sus partes — sin importar el nombre exacto de la cobertura en la póliza.
   Ejemplos TRUE: "Pérdida Total por Robo", "Sustracción e Inutilización Total", "Hurto de
   autopartes", "Robo parcial", "PTxRB", "Robo con violencia", "Apropiación indebida".

2. proveedor_en_lista_restrictiva
   TRUE si el beneficiario, taller, perito o proveedor del siniestro figura en listas restrictivas
   o negras (compañía, CONDUSEF, OFAC, UNODC, etc.), según la evidencia disponible.

3. proveedor_recurrente_observado
   TRUE si el beneficiario o proveedor ha aparecido en más de 2 casos observados o con alertas
   en los últimos 12 meses, según el historial consultado via herramientas.

4. documentos_inconsistentes
   TRUE si existen: alteraciones confirmadas, fechas de facturas previas al evento, firmas
   ilegibles con datos contradictorios, o cualquier discrepancia material entre documentos
   (denuncia, factura, fotos, informe pericial).

5. dinamica_relato_ilogico
   TRUE si el relato del siniestro es físicamente incompatible con los daños reportados.
   Ejemplos: choque frontal pero daño solo lateral, volcadura sin marcas en techo,
   impacto severo en zona sin marca de frenado, dirección de colisión inconsistente.

6. dinamica_accidente_madrugada
   TRUE si el accidente involucra múltiples vehículos Y ocurrió entre las 00:00 y las 05:00,
   patrón asociado a simulaciones nocturnas.

7. sin_tercero_identificado
   TRUE si el vehículo asegurado muestra daño severo pero el tercero responsable se fugó sin
   dejar placa, datos, ni existe registro de cámaras, testigos o policía en escena.

IMPORTANTE:
- Usa las herramientas disponibles para obtener historial, documentos y similitud narrativa
  antes de decidir. No dejes de llamar herramientas cuando la información en el expediente sea
  insuficiente para decidir una señal.
- Para cobertura_involucra_robo: razona sobre el SIGNIFICADO de la cobertura, no sobre el texto
  literal. Si el concepto es robo/sustracción aunque el nombre sea distinto, activa la señal.
- Responde EXCLUSIVAMENTE en JSON con esta estructura exacta (sin bloques de código):
{
  "signals": {
    "cobertura_involucra_robo": false,
    "proveedor_en_lista_restrictiva": false,
    "proveedor_recurrente_observado": false,
    "documentos_inconsistentes": false,
    "dinamica_relato_ilogico": false,
    "dinamica_accidente_madrugada": false,
    "sin_tercero_identificado": false
  },
  "summary": "Resumen breve para el analista (2-3 oraciones).",
  "signal_rationale": {
    "cobertura_involucra_robo": "Justificación...",
    "proveedor_en_lista_restrictiva": "Justificación...",
    "proveedor_recurrente_observado": "Justificación...",
    "documentos_inconsistentes": "Justificación...",
    "dinamica_relato_ilogico": "Justificación...",
    "dinamica_accidente_madrugada": "Justificación...",
    "sin_tercero_identificado": "Justificación..."
  }
}
""".strip()


def build_system_prompt() -> str:
    return SYSTEM_PROMPT_BASE + build_fraud_rules_prompt_section()


@dataclass
class AIScoringResult:
    signals: ScoringSignals
    explanation: ScoringAiExplanation


class AIScoringService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.client = OpenAI(api_key=self.settings.openai_api_key)

    def analyze(self, siniestro: Siniestro) -> AIScoringResult:
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY no está configurada")

        base_context = {
            "siniestro": {
                "id_siniestro": siniestro.id_siniestro,
                "id_asegurado": siniestro.id_asegurado,
                "id_poliza": siniestro.id_poliza,
                "ramo": siniestro.ramo,
                "cobertura": siniestro.cobertura,
                "fecha_ocurrencia": str(siniestro.fecha_ocurrencia),
                "fecha_reporte": str(siniestro.fecha_reporte),
                "descripcion": siniestro.descripcion,
                "documentos_completos": siniestro.documentos_completos,
                "beneficiario": siniestro.beneficiario,
                "monto_reclamado": float(siniestro.monto_reclamado or 0),
                "monto_estimado": float(siniestro.monto_estimado or 0),
                "dias_desde_inicio_poliza": siniestro.dias_desde_inicio_poliza,
                "dias_desde_fin_poliza": siniestro.dias_desde_fin_poliza,
                "dias_entre_ocurrencia_reporte": siniestro.dias_entre_ocurrencia_reporte,
                "historial_siniestros_asegurado": siniestro.historial_siniestros_asegurado,
            }
        }

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt()},
            {
                "role": "user",
                "content": (
                    "Analiza este expediente. Llama las herramientas que necesites para obtener "
                    "evidencia adicional y luego decide las señales.\n"
                    + json.dumps(base_context, ensure_ascii=True)
                ),
            },
        ]

        tools = self._tool_specs()
        called_tools: list[str] = []

        for _ in range(5):
            response = self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0,
            )

            message = response.choices[0].message
            tool_calls = message.tool_calls or []

            if tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [tc.model_dump() for tc in tool_calls],
                })
                for tc in tool_calls:
                    called_tools.append(tc.function.name)
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = self._call_tool(tc.function.name, args, siniestro)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.function.name,
                        "content": json.dumps(result, ensure_ascii=True),
                    })
                continue

            payload = self._parse_json(message.content or "{}")
            signals = ScoringSignals(**payload.get("signals", {}))
            explanation = ScoringAiExplanation(
                model=self.settings.openai_model,
                summary=payload.get("summary", "Análisis generado por IA."),
                tools_called=called_tools,
                signal_rationale=payload.get("signal_rationale", {}),
            )
            return AIScoringResult(signals=signals, explanation=explanation)

        raise RuntimeError("La IA no devolvió una respuesta final válida tras 5 iteraciones")

    def _parse_json(self, value: str) -> dict[str, Any]:
        content = value.strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.lower().startswith("json"):
                content = content[4:].strip()
        return json.loads(content)

    def _tool_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_claim_history",
                    "description": "Obtiene historial de siniestros previos del mismo asegurado.",
                    "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "detect_narrative_similarity",
                    "description": (
                        "Calcula la similitud textual de la descripción del siniestro actual contra "
                        "siniestros recientes en la base de datos. Útil para detectar narrativas clonadas."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {"threshold": {"type": "number", "description": "Umbral mínimo de similitud, ej: 0.70"}},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_client_profile",
                    "description": "Perfil resumido del asegurado: total de siniestros, historial.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "retrieve_documents",
                    "description": "Metadatos del correo y adjuntos asociados al siniestro.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_fraud_rule_examples",
                    "description": "Casos de referencia de fraude confirmado y contraejemplos para calibrar señales.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def _call_tool(self, tool_name: str, args: dict[str, Any], siniestro: Siniestro) -> dict[str, Any]:
        if tool_name == "get_claim_history":
            return self._get_claim_history(siniestro, int(args.get("limit", 10)))
        if tool_name == "detect_narrative_similarity":
            return self._detect_narrative_similarity(siniestro, float(args.get("threshold", 0.70)))
        if tool_name == "get_client_profile":
            return self._get_client_profile(siniestro)
        if tool_name == "retrieve_documents":
            return self._retrieve_documents(siniestro)
        if tool_name == "get_fraud_rule_examples":
            return self._get_fraud_rule_examples()
        return {"error": f"Herramienta desconocida: {tool_name}"}

    def _get_claim_history(self, siniestro: Siniestro, limit: int) -> dict[str, Any]:
        rows = self.db.scalars(
            select(Siniestro)
            .where(Siniestro.id_asegurado == siniestro.id_asegurado,
                   Siniestro.id_siniestro != siniestro.id_siniestro)
            .order_by(Siniestro.fecha_reporte.desc())
            .limit(max(limit, 1))
        ).all()
        return {
            "count": len(rows),
            "claims": [
                {
                    "id_siniestro": r.id_siniestro,
                    "fecha_reporte": str(r.fecha_reporte),
                    "ramo": r.ramo,
                    "cobertura": r.cobertura,
                    "estado": r.estado,
                    "historial_siniestros_asegurado": r.historial_siniestros_asegurado,
                }
                for r in rows
            ],
        }

    def _get_client_profile(self, siniestro: Siniestro) -> dict[str, Any]:
        total = self.db.scalar(
            select(func.count()).select_from(Siniestro)
            .where(Siniestro.id_asegurado == siniestro.id_asegurado)
        )
        return {
            "id_asegurado": siniestro.id_asegurado,
            "historial_siniestros_asegurado": siniestro.historial_siniestros_asegurado,
            "total_siniestros_en_db": int(total or 0),
        }

    def _retrieve_documents(self, siniestro: Siniestro) -> dict[str, Any]:
        if not siniestro.gmail_correo_id:
            return {"has_email": False, "documents": []}
        correo = self.db.get(GmailCorreo, siniestro.gmail_correo_id)
        if not correo:
            return {"has_email": False, "documents": []}
        docs = []
        if correo.adjunto_nombre or correo.adjunto_ruta:
            docs.append({"name": correo.adjunto_nombre, "path": correo.adjunto_ruta, "source": "gmail"})
        return {"has_email": True, "subject": correo.asunto, "from": correo.remitente, "documents": docs}

    def _detect_narrative_similarity(self, siniestro: Siniestro, threshold: float) -> dict[str, Any]:
        rows = self.db.scalars(
            select(Siniestro)
            .where(Siniestro.id_siniestro != siniestro.id_siniestro)
            .order_by(Siniestro.fecha_reporte.desc())
            .limit(50)
        ).all()
        hits = []
        for row in rows:
            ratio = SequenceMatcher(a=siniestro.descripcion.lower(), b=row.descripcion.lower()).ratio()
            if ratio >= threshold:
                hits.append({"id_siniestro": row.id_siniestro, "similarity": round(ratio, 4),
                              "descripcion_preview": row.descripcion[:200]})
        hits.sort(key=lambda x: x["similarity"], reverse=True)
        return {
            "threshold": threshold,
            "hits": hits[:10],
            "max_similarity": hits[0]["similarity"] if hits else 0.0,
        }

    def _get_fraud_rule_examples(self) -> dict[str, Any]:
        from app.integrations.siniestros.fraud_rules_context import load_fraud_rules_examples
        content = load_fraud_rules_examples()
        return {
            "source": "reglas_fraude_ejemplos.md",
            "content": content,
            "available": bool(content.strip()),
        }
