from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_analyst_email
from app.api.owner_scope import find_siniestro_for_owner, siniestro_owner_filter, siniestro_scope
from app.db.session import get_db
from app.integrations.chat.index_service import EmbeddingIndexService
from app.integrations.siniestros.auto_scoring import AutoScoringService
from app.integrations.siniestros.email_template import build_confirmation_email
from app.integrations.siniestros.scoring import FraudScoringService, ScoreComputation, ScoringContext
from app.integrations.chat.context_builder import (
    _context_from_payload,
    _signals_from_payload,
    score_from_persisted_payload,
)
from app.integrations.siniestros.scoring_context import compute_scoring_context
from app.schemas.scoring import ScoringSignals
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
    SiniestroUpdateStatus,
    SendCustomEmailRequest,
)

router = APIRouter(prefix="/siniestros", tags=["Siniestros"])
scoring_service = FraudScoringService()


def _preview_score(siniestro: Siniestro, db: Session | None) -> ScoreComputation:
    """Scoring determinístico sin IA: contexto BD + señales vacías."""
    context = compute_scoring_context(db, siniestro) if db is not None else ScoringContext()
    return scoring_service.calculate(siniestro, ScoringSignals(), context)


def _enrich_with_score(siniestro: Siniestro, db: Session | None = None) -> SiniestroWithScoreRead:
    base = SiniestroRead.model_validate(siniestro)

    if siniestro.scoring_payload:
        payload = siniestro.scoring_payload
        if AutoScoringService.payload_needs_reaudit(payload):
            signals = _signals_from_payload(payload)
            context = compute_scoring_context(db, siniestro) if db is not None else _context_from_payload(payload)
            result = scoring_service.calculate(siniestro, signals, context)
        else:
            result = score_from_persisted_payload(payload)
            if result is None:
                signals = _signals_from_payload(payload)
                context = _context_from_payload(payload)
                result = scoring_service.calculate(siniestro, signals, context)
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

    result = _preview_score(siniestro, db)
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
    )


def _score_color_for_summary(siniestro: Siniestro, db: Session | None = None) -> str:
    if siniestro.scoring_payload:
        persisted = score_from_persisted_payload(siniestro.scoring_payload)
        if persisted is not None:
            return persisted.score_color
    return _preview_score(siniestro, db).score_color


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
        score_color = _score_color_for_summary(siniestro, db)
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
    return [_enrich_with_score(s, db) for s in siniestros]


@router.post("/reaudit-stale")
def reaudit_stale_siniestros(
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> dict[str, object]:
    """Re-ejecuta auditoría IA en siniestros con scoring desactualizado (p. ej. tras cambio de reglas)."""
    service = AutoScoringService(db)
    rows = list(db.scalars(siniestro_scope(owner_email)).all())
    audits: list[dict[str, object]] = []

    for siniestro in rows:
        if len(audits) >= limit:
            break
        if not AutoScoringService.payload_needs_reaudit(siniestro.scoring_payload):
            continue
        try:
            response = service.audit_and_persist(siniestro)
            audits.append(AutoScoringService.to_audit_summary(response))
        except Exception as exc:
            audits.append({
                "id_siniestro": siniestro.id_siniestro,
                "error": str(exc),
            })

    return {"reaudited": len(audits), "audits": audits}


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
    return _enrich_with_score(siniestro, db)


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
    return _enrich_with_score(siniestro, db)


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

    context = compute_scoring_context(db, siniestro)
    signals = payload.signals
    if siniestro.scoring_payload and not any(
        getattr(signals, field) for field in ScoringSignals.model_fields
    ):
        signals = _signals_from_payload(siniestro.scoring_payload)

    result = scoring_service.calculate(siniestro, signals, context)
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


@router.patch("/{id_siniestro}/status", response_model=SiniestroWithScoreRead)
def update_siniestro_status(
    id_siniestro: str,
    payload: SiniestroUpdateStatus,
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> SiniestroWithScoreRead:
    siniestro = _find_siniestro(db, id_siniestro, owner_email=owner_email)
    if not siniestro:
        raise HTTPException(status_code=404, detail=f"Siniestro no encontrado: {id_siniestro}")

    siniestro.estado = payload.estado
    db.commit()
    db.refresh(siniestro)

    # Re-index claim to update status in vector database
    try:
        EmbeddingIndexService(db, owner_email=owner_email).index_one(siniestro)
    except Exception:
        pass

    return _enrich_with_score(siniestro, db)


@router.post("/send-custom-email", response_model=SendEmailResponse)
def send_custom_siniestro_email(
    payload: SendCustomEmailRequest,
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> SendEmailResponse:
    from app.integrations.gmail.client import GmailClient
    from app.integrations.gmail.oauth import load_valid_credentials
    from app.core.config import get_settings

    # 1. Buscar el siniestro
    siniestro = _find_siniestro(db, payload.id_siniestro, owner_email=owner_email)
    if not siniestro:
        raise HTTPException(status_code=404, detail=f"Siniestro no encontrado: {payload.id_siniestro}")

    # 2. Cargar credenciales y cliente de Gmail
    try:
        settings = get_settings()
        creds = load_valid_credentials(owner_email)
        if not creds:
            raise HTTPException(status_code=401, detail="No se encontraron credenciales de Gmail válidas.")
        client = GmailClient(owner_email=owner_email, credentials=creds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al cargar el cliente de Gmail: {str(e)}")

    # 3. Enviar el correo real por la API de Google Gmail
    try:
        thread_id = None
        if siniestro.correo:
            thread_id = siniestro.correo.gmail_message_id

        client.send_email(
            to=payload.to_email,
            subject=payload.subject,
            body_text="Favor revisar el formato de Ficha Registral HTML adjunto.",
            html_body=payload.body_html,
            thread_id=thread_id
        )

        return SendEmailResponse(
            success=True,
            message=f"Correo enviado exitosamente por Gmail a {payload.to_email}.",
            htmlTemplate=payload.body_html
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al transmitir correo vía Gmail API: {str(e)}")


@router.delete("/{id_siniestro}", status_code=200)
def delete_siniestro(
    id_siniestro: str,
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> dict[str, str]:
    siniestro = _find_siniestro(db, id_siniestro, owner_email=owner_email)
    if not siniestro:
        raise HTTPException(status_code=404, detail=f"Siniestro no encontrado: {id_siniestro}")

    # 1. Borrar sesiones de chat asociadas a este siniestro
    from app.models.chat_session import ChatSession
    from sqlalchemy import delete
    
    clean_id = siniestro.id_siniestro.split("|")[0].strip()
    session_pattern = f"%{clean_id}%"
    db.execute(delete(ChatSession).where(ChatSession.session_id.like(session_pattern)))
    
    # 2. Borrar el siniestro
    db.delete(siniestro)
    db.commit()

    return {"success": "true", "message": f"Siniestro {id_siniestro} y sus datos asociados eliminados exitosamente."}
