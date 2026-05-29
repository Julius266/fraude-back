from pydantic import BaseModel, Field


class ScoringSignals(BaseModel):
    # IA clasifica el tipo de cobertura/evento
    cobertura_involucra_robo: bool = False        # robo, hurto, sustracción, apropiación

    # IA evalúa proveedor / beneficiario
    proveedor_en_lista_restrictiva: bool = False  # figura en lista negra/restrictiva
    proveedor_recurrente_observado: bool = False  # aparece en >2 casos observados este año

    # IA evalúa documentación
    documentos_inconsistentes: bool = False       # fechas previas al evento, alteraciones, ilegibles

    # IA evalúa dinámica del siniestro
    dinamica_relato_ilogico: bool = False         # relato incompatible con tipo de impacto/daño
    dinamica_accidente_madrugada: bool = False    # accidente múltiple entre 00:00 y 05:00
    sin_tercero_identificado: bool = False        # daño severo sin rastro del tercero ni cámaras


class SiniestroScoringRequest(BaseModel):
    signals: ScoringSignals = Field(default_factory=ScoringSignals)


class SiniestroAIScoringRequest(BaseModel):
    manual_signals: ScoringSignals | None = None
    force_ai: bool = True


class ScoringRuleResult(BaseModel):
    code: str
    title: str
    classification: str
    matched: bool
    points: int
    reason: str


class ScoringBreakdownItem(BaseModel):
    code: str
    title: str
    matched: bool
    points: int
    running_total: int
    percent_of_total: float
    reason: str


class SiniestroScoringResponse(BaseModel):
    id_siniestro: str
    total_score: int
    average_points: float
    score_color: str
    score_band: str
    rules: list[ScoringRuleResult]
    breakdown: list[ScoringBreakdownItem]
    matched_rules: list[str]
    version: str


class ScoringAiExplanation(BaseModel):
    model: str
    summary: str
    tools_called: list[str] = Field(default_factory=list)
    signal_rationale: dict[str, str] = Field(default_factory=dict)


class ScoringContextData(BaseModel):
    """Métricas de contexto BD persistidas junto al scoring para poder recalcular sin BD."""
    max_narrative_similarity: float = 0.0
    frecuencia_vehiculo: int = 0
    frecuencia_rc_previo: int = 0


class SiniestroAIScoringResponse(SiniestroScoringResponse):
    ai: ScoringAiExplanation | None = None
    signals: ScoringSignals | None = None
    context_data: ScoringContextData | None = None
