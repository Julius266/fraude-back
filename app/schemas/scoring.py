from pydantic import BaseModel, Field


class ScoringSignals(BaseModel):
    evidencia_falsificacion_documental: bool = False
    coincidencia_lista_restrictiva: bool = False
    dinamica_accidente_imposible: bool = False
    demora_atipica_denuncia_robo: bool = False
    narrativa_clonada: bool = False


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


class SiniestroAIScoringResponse(SiniestroScoringResponse):
    ai: ScoringAiExplanation | None = None
    signals: ScoringSignals | None = None
