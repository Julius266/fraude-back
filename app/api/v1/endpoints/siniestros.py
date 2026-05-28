from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_analyst_email
from app.api.owner_scope import find_siniestro_for_owner, siniestro_owner_filter, siniestro_scope
from app.db.session import get_db
from app.integrations.chat.index_service import EmbeddingIndexService
from app.integrations.siniestros.auto_scoring import AutoScoringService
from app.integrations.siniestros.email_template import build_confirmation_email
from app.integrations.siniestros.scoring import FraudScoringService
from app.integrations.chat.context_builder import official_score_for_siniestro
from app.models.siniestro import Siniestro
from app.schemas.scoring import (
    SiniestroAIScoringRequest,
    SiniestroAIScoringResponse,
    SiniestroScoringRequest,
    SiniestroScoringResponse,
)
from app.schemas.siniestro import (
    SendEmailRequest,
    SendEmailResponse,
    SiniestroCreate,
    SiniestroRead,
    SiniestrosSummary,
    SiniestroWithScoreRead,
)

router = APIRouter(prefix="/siniestros", tags=["Siniestros"])
scoring_service = FraudScoringService()


def _enrich_with_score(siniestro: Siniestro) -> SiniestroWithScoreRead:
    base = SiniestroRead.model_validate(siniestro)

    if siniestro.scoring_payload:
        payload = siniestro.scoring_payload
        result = official_score_for_siniestro(siniestro, scoring_service)
        matched = [rule.code for rule in result.rules if rule.matched]
        return SiniestroWithScoreRead(
            **base.model_dump(),
            total_score=result.total_score,
            average_points=result.average_points,
            score_color=result.score_color,
            score_band=result.score_band,
            rules=result.rules,
            breakdown=result.breakdown,
            matched_rules=matched,
            scoring_version=payload.get("version"),
            ai=payload.get("ai"),
            signals=payload.get("signals"),
            scoring_audited_at=siniestro.scoring_audited_at,
        )

    result = scoring_service.calculate(siniestro, SiniestroScoringRequest().signals)
    return SiniestroWithScoreRead(
        **base.model_dump(),
        total_score=result.total_score,
        average_points=result.average_points,
        score_color=result.score_color,
        score_band=result.score_band,
    )


def _score_color_for_summary(siniestro: Siniestro) -> str:
    if siniestro.scoring_payload:
        return official_score_for_siniestro(siniestro, scoring_service).score_color
    result = scoring_service.calculate(siniestro, SiniestroScoringRequest().signals)
    return result.score_color


def _find_siniestro(db: Session, id_siniestro: str, owner_email: str | None = None) -> Siniestro | None:
    if owner_email:
        return find_siniestro_for_owner(db, id_siniestro, owner_email)

    siniestro = db.scalar(select(Siniestro).where(Siniestro.id_siniestro == id_siniestro))
    if siniestro is not None:
        return siniestro

    clean_id = id_siniestro.split("|")[0].strip()
    if clean_id != id_siniestro:
        siniestro = db.scalar(select(Siniestro).where(Siniestro.id_siniestro == clean_id))
        if siniestro is not None:
            return siniestro

    return db.scalar(select(Siniestro).where(Siniestro.id_siniestro.ilike(f"{clean_id}%")).limit(1))


@router.get("/status")
def siniestros_module_status() -> dict[str, str]:
    return {"status": "ready", "module": "siniestros"}


@router.get("/summary", response_model=SiniestrosSummary)
def siniestros_summary(
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> SiniestrosSummary:
    siniestros = list(db.scalars(siniestro_scope(owner_email)).all())
    by_color: dict[str, int] = {"Rojo": 0, "Amarillo": 0, "Verde": 0}
    by_ramo: dict[str, int] = {}

    for siniestro in siniestros:
        score_color = _score_color_for_summary(siniestro)
        by_color[score_color] = by_color.get(score_color, 0) + 1
        by_ramo[siniestro.ramo] = by_ramo.get(siniestro.ramo, 0) + 1

    _total, _indexed, pending = EmbeddingIndexService(db, owner_email=owner_email).status()
    return SiniestrosSummary(
        total=len(siniestros),
        by_color=by_color,
        by_ramo=by_ramo,
        pending_indexing=pending,
    )


@router.get("", response_model=list[SiniestroWithScoreRead])
def list_siniestros(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> list[SiniestroWithScoreRead]:
    statement = (
        siniestro_scope(owner_email)
        .order_by(Siniestro.fecha_reporte.desc())
        .offset(offset)
        .limit(limit)
    )
    siniestros = list(db.scalars(statement).all())
    return [_enrich_with_score(s) for s in siniestros]


@router.post("", response_model=SiniestroWithScoreRead, status_code=201)
def create_siniestro(
    payload: SiniestroCreate,
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> SiniestroWithScoreRead:
    existing = db.scalar(
        select(Siniestro).where(
            Siniestro.id_siniestro == payload.id_siniestro,
            Siniestro.owner_email == owner_email,
        )
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un siniestro con id: {payload.id_siniestro}",
        )

    siniestro = Siniestro(**payload.model_dump(), owner_email=owner_email)
    db.add(siniestro)
    db.commit()
    db.refresh(siniestro)

    try:
        EmbeddingIndexService(db).index_one(siniestro)
    except Exception:
        pass

    try:
        AutoScoringService(db).audit_and_persist(siniestro)
    except Exception:
        pass

    db.refresh(siniestro)
    return _enrich_with_score(siniestro)


def _send_email_for_siniestro(db: Session, id_siniestro: str, owner_email: str) -> SendEmailResponse:
    siniestro = _find_siniestro(db, id_siniestro, owner_email=owner_email)
    if not siniestro:
        raise HTTPException(status_code=404, detail=f"Siniestro no encontrado: {id_siniestro}")
    html_template, message = build_confirmation_email(siniestro)
    return SendEmailResponse(success=True, message=message, htmlTemplate=html_template)


@router.post("/send-email", response_model=SendEmailResponse)
def send_siniestro_email_body(
    payload: SendEmailRequest,
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> SendEmailResponse:
    return _send_email_for_siniestro(db, payload.id_siniestro, owner_email)


@router.get("/{id_siniestro}", response_model=SiniestroWithScoreRead)
def get_siniestro(
    id_siniestro: str,
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> SiniestroWithScoreRead:
    siniestro = _find_siniestro(db, id_siniestro, owner_email=owner_email)
    if not siniestro:
        raise HTTPException(status_code=404, detail=f"Siniestro no encontrado: {id_siniestro}")
    return _enrich_with_score(siniestro)


@router.post("/{id_siniestro}/send-email", response_model=SendEmailResponse)
def send_siniestro_email(
    id_siniestro: str,
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> SendEmailResponse:
    return _send_email_for_siniestro(db, id_siniestro, owner_email)


@router.post("/{id_siniestro}/score", response_model=SiniestroScoringResponse)
def score_siniestro(
    id_siniestro: str,
    payload: SiniestroScoringRequest,
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> SiniestroScoringResponse:
    siniestro = db.scalar(
        siniestro_scope(owner_email).where(Siniestro.id_siniestro == id_siniestro)
    )
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
    owner_email: str = Depends(get_analyst_email),
) -> SiniestroAIScoringResponse:
    siniestro = db.scalar(
        siniestro_scope(owner_email).where(Siniestro.id_siniestro == id_siniestro)
    )
    if not siniestro:
        raise HTTPException(status_code=404, detail=f"Siniestro no encontrado: {id_siniestro}")

    return AutoScoringService(db).audit_and_persist(
        siniestro,
        manual_signals=payload.manual_signals,
    )
