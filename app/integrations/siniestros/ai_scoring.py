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
Eres un analista antifraude de seguros. Debes decidir UNICAMENTE estas senales booleanas:
- evidencia_falsificacion_documental
- coincidencia_lista_restrictiva
- dinamica_accidente_imposible
- demora_atipica_denuncia_robo
- narrativa_clonada

Debes usar las herramientas cuando haga falta y explicar por que activas o no cada senal.
Compara siempre el expediente actual con la biblioteca de casos de ejemplo incluida al final
de estas instrucciones (reglas_fraude_ejemplos.md): esos casos son referencias adicionales
de fraudes reales y sinteticos, no el siniestro en curso.
Responde EXCLUSIVAMENTE JSON con esta estructura:
{
  "signals": {
    "evidencia_falsificacion_documental": false,
    "coincidencia_lista_restrictiva": false,
    "dinamica_accidente_imposible": false,
    "demora_atipica_denuncia_robo": false,
    "narrativa_clonada": false
  },
  "summary": "texto breve para analista",
  "signal_rationale": {
    "evidencia_falsificacion_documental": "...",
    "coincidencia_lista_restrictiva": "...",
    "dinamica_accidente_imposible": "...",
    "demora_atipica_denuncia_robo": "...",
    "narrativa_clonada": "..."
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
            raise ValueError("OPENAI_API_KEY no esta configurada")

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
                "dias_desde_inicio_poliza": siniestro.dias_desde_inicio_poliza,
                "dias_desde_fin_poliza": siniestro.dias_desde_fin_poliza,
                "dias_entre_ocurrencia_reporte": siniestro.dias_entre_ocurrencia_reporte,
            }
        }

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt()},
            {
                "role": "user",
                "content": (
                    "Analiza este siniestro (expediente actual). Puedes llamar herramientas para "
                    "evidencias adicionales. Contrasta con los casos de ejemplo del system prompt.\n"
                    + json.dumps(base_context, ensure_ascii=True)
                ),
            },
        ]

        tools = self._tool_specs()
        called_tools: list[str] = []

        for _ in range(4):
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
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [tool_call.model_dump() for tool_call in tool_calls],
                    }
                )
                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    called_tools.append(tool_name)
                    raw_args = tool_call.function.arguments or "{}"
                    try:
                        tool_args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        tool_args = {}
                    tool_result = self._call_tool(tool_name, tool_args, siniestro)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": json.dumps(tool_result, ensure_ascii=True),
                        }
                    )
                continue

            raw_content = message.content or "{}"
            payload = self._parse_json(raw_content)
            signals = ScoringSignals(**payload.get("signals", {}))
            explanation = ScoringAiExplanation(
                model=self.settings.openai_model,
                summary=payload.get("summary", "Analisis generado por IA."),
                tools_called=called_tools,
                signal_rationale=payload.get("signal_rationale", {}),
            )
            return AIScoringResult(signals=signals, explanation=explanation)

        raise RuntimeError("La IA no devolvio una respuesta final valida")

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
                    "description": "Obtiene historial de siniestros del asegurado.",
                    "parameters": {
                        "type": "object",
                        "properties": {"limit": {"type": "integer"}},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_similar_claims",
                    "description": "Busca siniestros similares por texto de descripcion.",
                    "parameters": {
                        "type": "object",
                        "properties": {"limit": {"type": "integer"}},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_client_profile",
                    "description": "Perfil resumido del cliente/asegurado.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "retrieve_documents",
                    "description": "Datos de documentos y correo asociado al siniestro.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "detect_narrative_similarity",
                    "description": "Calcula similitud narrativa contra siniestros recientes.",
                    "parameters": {
                        "type": "object",
                        "properties": {"threshold": {"type": "number"}},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_fraud_rule_examples",
                    "description": (
                        "Devuelve casos de referencia RF-01..RF-07 de reglas_fraude_ejemplos.md "
                        "(fraudes confirmados y casos limpios) para calibrar las senales."
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "explain_alerts",
                    "description": "Devuelve contexto explicativo util para justificar alertas.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def _call_tool(self, tool_name: str, args: dict[str, Any], siniestro: Siniestro) -> dict[str, Any]:
        if tool_name == "get_claim_history":
            limit = int(args.get("limit", 10))
            return self._get_claim_history(siniestro, limit)
        if tool_name == "search_similar_claims":
            limit = int(args.get("limit", 10))
            return self._search_similar_claims(siniestro, limit)
        if tool_name == "get_client_profile":
            return self._get_client_profile(siniestro)
        if tool_name == "retrieve_documents":
            return self._retrieve_documents(siniestro)
        if tool_name == "detect_narrative_similarity":
            threshold = float(args.get("threshold", 0.85))
            return self._detect_narrative_similarity(siniestro, threshold)
        if tool_name == "get_fraud_rule_examples":
            return self._get_fraud_rule_examples()
        if tool_name == "explain_alerts":
            return self._explain_alerts(siniestro)
        return {"error": f"tool no soportada: {tool_name}"}

    def _get_claim_history(self, siniestro: Siniestro, limit: int) -> dict[str, Any]:
        rows = self.db.scalars(
            select(Siniestro)
            .where(Siniestro.id_asegurado == siniestro.id_asegurado, Siniestro.id_siniestro != siniestro.id_siniestro)
            .order_by(Siniestro.fecha_reporte.desc())
            .limit(max(limit, 1))
        ).all()
        return {
            "count": len(rows),
            "claims": [
                {
                    "id_siniestro": row.id_siniestro,
                    "fecha_reporte": str(row.fecha_reporte),
                    "ramo": row.ramo,
                    "estado": row.estado,
                    "historial_siniestros_asegurado": row.historial_siniestros_asegurado,
                }
                for row in rows
            ],
        }

    def _search_similar_claims(self, siniestro: Siniestro, limit: int) -> dict[str, Any]:
        rows = self.db.scalars(
            select(Siniestro)
            .where(Siniestro.id_siniestro != siniestro.id_siniestro)
            .order_by(Siniestro.fecha_reporte.desc())
            .limit(max(limit, 1))
        ).all()
        ranked = []
        for row in rows:
            similarity = SequenceMatcher(a=siniestro.descripcion.lower(), b=row.descripcion.lower()).ratio()
            ranked.append(
                {
                    "id_siniestro": row.id_siniestro,
                    "similarity": round(similarity, 4),
                    "descripcion": row.descripcion[:240],
                }
            )
        ranked.sort(key=lambda item: item["similarity"], reverse=True)
        return {"matches": ranked[:limit]}

    def _get_client_profile(self, siniestro: Siniestro) -> dict[str, Any]:
        total = self.db.scalar(
            select(func.count())
            .select_from(Siniestro)
            .where(Siniestro.id_asegurado == siniestro.id_asegurado)
        )
        return {
            "id_asegurado": siniestro.id_asegurado,
            "historial_siniestros_asegurado": siniestro.historial_siniestros_asegurado,
            "claims_in_db": int(total or 0),
        }

    def _retrieve_documents(self, siniestro: Siniestro) -> dict[str, Any]:
        if not siniestro.gmail_correo_id:
            return {"has_email": False, "documents": []}

        correo = self.db.get(GmailCorreo, siniestro.gmail_correo_id)
        if not correo:
            return {"has_email": False, "documents": []}

        documents = []
        if correo.adjunto_nombre or correo.adjunto_ruta:
            documents.append(
                {
                    "name": correo.adjunto_nombre,
                    "path": correo.adjunto_ruta,
                    "source": "gmail",
                }
            )

        return {
            "has_email": True,
            "subject": correo.asunto,
            "from": correo.remitente,
            "documents": documents,
        }

    def _detect_narrative_similarity(self, siniestro: Siniestro, threshold: float) -> dict[str, Any]:
        rows = self.db.scalars(
            select(Siniestro)
            .where(Siniestro.id_siniestro != siniestro.id_siniestro)
            .order_by(Siniestro.fecha_reporte.desc())
            .limit(30)
        ).all()

        hits = []
        for row in rows:
            ratio = SequenceMatcher(a=siniestro.descripcion.lower(), b=row.descripcion.lower()).ratio()
            if ratio >= threshold:
                hits.append({"id_siniestro": row.id_siniestro, "similarity": round(ratio, 4)})

        return {
            "threshold": threshold,
            "hits": hits,
            "max_similarity": max((item["similarity"] for item in hits), default=0.0),
        }

    def _get_fraud_rule_examples(self) -> dict[str, Any]:
        from app.integrations.siniestros.fraud_rules_context import load_fraud_rules_examples

        content = load_fraud_rules_examples()
        return {
            "source": "reglas_fraude_ejemplos.md",
            "purpose": "Casos adicionales de fraude y contraejemplos para calibrar RF-01..RF-07",
            "content": content,
            "available": bool(content.strip()),
        }

    def _explain_alerts(self, siniestro: Siniestro) -> dict[str, Any]:
        return {
            "dias_entre_ocurrencia_reporte": siniestro.dias_entre_ocurrencia_reporte,
            "dias_desde_inicio_poliza": siniestro.dias_desde_inicio_poliza,
            "dias_desde_fin_poliza": siniestro.dias_desde_fin_poliza,
            "ramo": siniestro.ramo,
            "cobertura": siniestro.cobertura,
            "fraud_examples_doc": "reglas_fraude_ejemplos.md",
        }
