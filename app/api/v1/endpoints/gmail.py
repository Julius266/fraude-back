from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import logging

from app.db.session import get_db
from app.integrations.gmail.service import GmailIngestionService
from app.schemas.gmail_correo import GmailCorreoRead

router = APIRouter(prefix="/gmail", tags=["Gmail"])
logger = logging.getLogger(__name__)


@router.get("/config")
def gmail_config() -> dict[str, str]:
    """Muestra la config Gmail que usa este proceso (útil si hay varios uvicorn abiertos)."""
    from app.core.config import get_settings

    settings = get_settings()
    return {
        "gmail_watch_topic": settings.gmail_watch_topic,
        "gmail_client_secret_file": settings.gmail_client_secret_file,
        "gmail_token_file": settings.gmail_token_file,
    }


@router.post("/watch/register")
def register_watch(db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        service = GmailIngestionService(db)
        result = service.register_watch()
    except ValueError as exc:
        logger.warning("register_watch rechazado: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("Watch Gmail registrado result=%s", result)
    return {"status": "watch_registered", "result": result}


@router.post("/scan")
def scan_recent_messages(db: Session = Depends(get_db)) -> dict[str, int]:
    service = GmailIngestionService(db)
    result = service.process_recent_messages()
    logger.info("Scan manual de Gmail ejecutado result=%s", result)
    return result


@router.get("/correos", response_model=list[GmailCorreoRead])
def list_saved_emails(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[GmailCorreoRead]:
    service = GmailIngestionService(db)
    return service.list_saved_messages(limit=limit)
