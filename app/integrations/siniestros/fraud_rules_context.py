from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _resolve_rules_path() -> Path:
    settings = get_settings()
    candidate = Path(settings.fraud_rules_examples_file)
    if candidate.is_file():
        return candidate

    project_root = Path(__file__).resolve().parents[3]
    return project_root / settings.fraud_rules_examples_file


@lru_cache(maxsize=1)
def load_fraud_rules_examples() -> str:
    path = _resolve_rules_path()
    if not path.is_file():
        logger.warning("Archivo de ejemplos de fraude no encontrado: %s", path)
        return ""
    return path.read_text(encoding="utf-8")


def build_fraud_rules_prompt_section() -> str:
    content = load_fraud_rules_examples().strip()
    if not content:
        return ""

    return (
        "\n\n## Biblioteca de casos y ejemplos de fraude (reglas_fraude_ejemplos.md)\n"
        "IMPORTANTE: lo siguiente NO es el siniestro que debes auditar. Son casos de "
        "referencia adicionales (positivos y negativos) para calibrar cada regla RF-01 a RF-07.\n"
        "- Cada regla incluye un CASO QUE NO ACTIVA y un CASO QUE SI ACTIVA con justificacion.\n"
        "- Usa estos ejemplos como un analista senior: compara hechos, fechas, cobertura, "
        "documentos y narrativa del expediente actual contra estos patrones.\n"
        "- Si el caso actual se alinea con un CASO QUE SI ACTIVA, activa la senal booleana "
        "correspondiente y explica la similitud en signal_rationale.\n"
        "- RF-07: activa narrativa_clonada si la similitud con otro siniestro distinto es >= 85%.\n"
        "- Las reglas ROJO (RF-01..RF-04) indican fraude probable; AMARILLO (RF-05..RF-07) son alertas.\n\n"
        f"{content}"
    )
