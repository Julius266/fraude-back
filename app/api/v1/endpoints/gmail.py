from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
import logging

from app.db.session import get_db
from app.integrations.gmail.service import GmailIngestionService
from app.schemas.gmail_correo import GmailCorreoRead

router = APIRouter(prefix="/gmail", tags=["Gmail"])
logger = logging.getLogger(__name__)


@router.post("/watch/register")
def register_watch(db: Session = Depends(get_db)) -> dict[str, object]:
    service = GmailIngestionService(db)
    result = service.register_watch()
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
