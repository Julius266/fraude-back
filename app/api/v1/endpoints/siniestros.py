from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.integrations.siniestros.ai_scoring import AIScoringService
from app.integrations.siniestros.scoring import FraudScoringService
from app.models.siniestro import Siniestro
from app.schemas.scoring import (
    ScoringAiExplanation,
    SiniestroAIScoringRequest,
    SiniestroAIScoringResponse,
    SiniestroScoringRequest,
    SiniestroScoringResponse,
)
from app.schemas.siniestro import SiniestroRead

router = APIRouter(prefix="/siniestros", tags=["Siniestros"])
scoring_service = FraudScoringService()


@router.get("/status")
def siniestros_module_status() -> dict[str, str]:
    return {"status": "ready", "module": "siniestros"}


@router.get("", response_model=list[SiniestroRead])
def list_siniestros(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[SiniestroRead]:
    statement = select(Siniestro).order_by(Siniestro.fecha_reporte.desc()).offset(offset).limit(limit)
    return list(db.scalars(statement).all())


@router.get("/{id_siniestro}", response_model=SiniestroRead)
def get_siniestro(
    id_siniestro: str,
    db: Session = Depends(get_db),
) -> SiniestroRead:
    siniestro = db.scalar(select(Siniestro).where(Siniestro.id_siniestro == id_siniestro))
    if not siniestro:
        raise HTTPException(status_code=404, detail=f"Siniestro no encontrado: {id_siniestro}")
    return siniestro


@router.post("/{id_siniestro}/score", response_model=SiniestroScoringResponse)
def score_siniestro(
    id_siniestro: str,
    payload: SiniestroScoringRequest,
    db: Session = Depends(get_db),
) -> SiniestroScoringResponse:
    siniestro = db.scalar(select(Siniestro).where(Siniestro.id_siniestro == id_siniestro))
    if not siniestro:
        raise HTTPException(status_code=404, detail=f"Siniestro no encontrado: {id_siniestro}")

    result = scoring_service.calculate(siniestro, payload.signals)
    matched = [rule.code for rule in result.rules if rule.matched]

    return SiniestroScoringResponse(
        id_siniestro=id_siniestro,
        total_score=result.total_score,
        average_points=result.average_points,
        score_color=result.score_color,
        score_band=result.score_band,
        rules=result.rules,
        breakdown=result.breakdown,
        matched_rules=matched,
        version=scoring_service.VERSION,
    )


@router.post("/{id_siniestro}/score/ai", response_model=SiniestroAIScoringResponse)
def score_siniestro_with_ai(
    id_siniestro: str,
    payload: SiniestroAIScoringRequest,
    db: Session = Depends(get_db),
) -> SiniestroAIScoringResponse:
    siniestro = db.scalar(select(Siniestro).where(Siniestro.id_siniestro == id_siniestro))
    if not siniestro:
        raise HTTPException(status_code=404, detail=f"Siniestro no encontrado: {id_siniestro}")

    ai_explanation: ScoringAiExplanation | None = None
    ai_signals = None

    try:
        ai_result = AIScoringService(db).analyze(siniestro)
        ai_signals = ai_result.signals
        ai_explanation = ai_result.explanation
    except Exception as exc:
        ai_explanation = ScoringAiExplanation(
            model="fallback-no-ai",
            summary=f"No se pudo ejecutar IA. Se aplico fallback deterministico. detalle={exc}",
            tools_called=[],
            signal_rationale={},
        )

    selected_signals = payload.manual_signals or ai_signals
    if not selected_signals:
        selected_signals = SiniestroScoringRequest().signals

    result = scoring_service.calculate(siniestro, selected_signals)
    matched = [rule.code for rule in result.rules if rule.matched]

    return SiniestroAIScoringResponse(
        id_siniestro=id_siniestro,
        total_score=result.total_score,
        average_points=result.average_points,
        score_color=result.score_color,
        score_band=result.score_band,
        rules=result.rules,
        breakdown=result.breakdown,
        matched_rules=matched,
        version=scoring_service.VERSION,
        ai=ai_explanation,
        signals=selected_signals,
    )
