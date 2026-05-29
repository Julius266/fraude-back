import asyncio
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_analyst_email, get_gmail_owner_email, get_optional_analyst_email
from app.core.config import get_settings
from app.db.session import SessionLocal, get_db
from app.integrations.gmail.oauth import (
    GmailNotAuthenticatedError,
    clear_credentials,
    create_authorization_url,
    exchange_authorization_code,
    get_auth_status,
)
from app.integrations.gmail.service import GmailIngestionService
from app.models.gmail_correo import GmailCorreo
from app.schemas.gmail_correo import (
    GmailAuthStatus,
    GmailAuthUrlResponse,
    GmailCorreoRead,
    GmailScanAuditSummary,
    GmailScanResponse,
    GmailScanUser,
)

router = APIRouter(prefix="/gmail", tags=["Gmail"])
logger = logging.getLogger(__name__)
_gmail_scan_lock = asyncio.Lock()


def _run_gmail_scan(owner_email: str) -> tuple[dict[str, str], dict[str, object]]:
    db = SessionLocal()
    try:
        service = GmailIngestionService(db, owner_email=owner_email)
        user = service.get_connected_user()
        result = service.process_recent_messages()
        return user, result
    finally:
        db.close()


def _run_correo_procesar(correo_id: int, owner_email: str) -> tuple[int, list[dict[str, object]]]:
    db = SessionLocal()
    try:
        correo = db.scalar(
            select(GmailCorreo).where(
                GmailCorreo.id == correo_id,
                GmailCorreo.owner_email == owner_email,
            )
        )
        if correo is None:
            raise LookupError("Correo no encontrado para este analista.")

        service = GmailIngestionService(db, owner_email=owner_email)
        audits_raw = service.reprocess_correo_pdfs(correo)
        return correo_id, audits_raw
    finally:
        db.close()


@router.get("/config")
def gmail_config() -> dict[str, str]:
    """Muestra la config Gmail que usa este proceso (útil si hay varios uvicorn abiertos)."""
    settings = get_settings()
    return {
        "gmail_watch_topic": settings.gmail_watch_topic,
        "gmail_client_secret_file": settings.gmail_client_secret_file,
        "gmail_token_file": settings.gmail_token_file,
        "gmail_oauth_redirect_uri": settings.resolved_gmail_oauth_redirect_uri,
    }


@router.get("/auth/status", response_model=GmailAuthStatus)
def gmail_auth_status(
    owner_email: str | None = Depends(get_optional_analyst_email),
) -> GmailAuthStatus:
    status = get_auth_status(owner_email=owner_email)
    user = GmailScanUser(**status["user"]) if status.get("user") else None
    return GmailAuthStatus(
        credentials_configured=status["credentials_configured"],
        token_configured=status["token_configured"],
        connected=status["connected"],
        redirect_uri=status["redirect_uri"],
        user=user,
    )


@router.get("/auth/url", response_model=GmailAuthUrlResponse)
def gmail_auth_url(return_to: str = Query(default="/")) -> GmailAuthUrlResponse:
    try:
        payload = create_authorization_url(return_to=return_to)
        return GmailAuthUrlResponse(**payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("No se pudo generar URL OAuth de Gmail")
        raise HTTPException(status_code=502, detail=f"No se pudo iniciar OAuth de Gmail: {exc}") from exc


@router.get("/auth/callback")
def gmail_auth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    settings = get_settings()
    frontend = settings.frontend_url.rstrip("/")

    if error:
        message = quote(error)
        return RedirectResponse(url=f"{frontend}/login?gmail=error&message={message}")

    if not code or not state:
        return RedirectResponse(url=f"{frontend}/login?gmail=error&message=missing_code")

    try:
        return_to, connected_email = exchange_authorization_code(code, state)
        safe_return = quote(return_to if return_to.startswith("/") else "/")
        safe_email = quote(connected_email)
        return RedirectResponse(
            url=f"{frontend}/login?gmail=connected&returnTo={safe_return}&email={safe_email}"
        )
    except Exception as exc:
        logger.exception("Callback OAuth de Gmail falló")
        message = quote(str(exc))
        return RedirectResponse(url=f"{frontend}/login?gmail=error&message={message}")


@router.post("/auth/logout")
def gmail_auth_logout(owner_email: str = Depends(get_analyst_email)) -> dict[str, str]:
    clear_credentials(owner_email)
    return {"status": "token_cleared", "owner_email": owner_email}


@router.post("/watch/register")
def register_watch(
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_gmail_owner_email),
) -> dict[str, object]:
    try:
        service = GmailIngestionService(db, owner_email=owner_email)
        result = service.register_watch()
    except GmailNotAuthenticatedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        logger.warning("register_watch rechazado: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("Watch Gmail registrado result=%s", result)
    return {"status": "watch_registered", "result": result}


@router.post("/scan", response_model=GmailScanResponse)
async def scan_recent_messages(
    owner_email: str = Depends(get_gmail_owner_email),
) -> GmailScanResponse:
    try:
        async with _gmail_scan_lock:
            user, result = await asyncio.to_thread(_run_gmail_scan, owner_email)
        logger.info("Scan manual de Gmail ejecutado result=%s user=%s", result, user.get("email"))
        audits_raw = result.get("audits") or []
        audits = [GmailScanAuditSummary(**item) for item in audits_raw if isinstance(item, dict)]
        return GmailScanResponse(
            saved=int(result.get("saved", 0)),
            ignored=int(result.get("ignored", 0)),
            user=GmailScanUser(**user),
            audits=audits,
        )
    except GmailNotAuthenticatedError as exc:
        raise HTTPException(
            status_code=401,
            detail="Conecta tu cuenta de Gmail antes de escanear.",
        ) from exc
    except FileNotFoundError as exc:
        logger.warning("Scan Gmail sin credentials.json: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="Coloca credentials.json (OAuth Client) en la raíz del backend.",
        ) from exc
    except Exception as exc:
        logger.exception("Error en scan de Gmail")
        raise HTTPException(status_code=502, detail=f"No se pudo escanear Gmail: {exc}") from exc


@router.get("/correos", response_model=list[GmailCorreoRead])
def list_saved_emails(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    owner_email: str = Depends(get_analyst_email),
) -> list[GmailCorreoRead]:
    service = GmailIngestionService(db, owner_email=owner_email)
    return service.list_saved_messages(limit=limit, owner_email=owner_email)


@router.post("/correos/{correo_id}/procesar")
async def process_correo_to_bandeja(
    correo_id: int,
    owner_email: str = Depends(get_analyst_email),
) -> dict[str, object]:
    try:
        async with _gmail_scan_lock:
            processed_id, audits_raw = await asyncio.to_thread(
                _run_correo_procesar,
                correo_id,
                owner_email,
            )
    except LookupError:
        raise HTTPException(status_code=404, detail="Correo no encontrado para este analista.") from None
    except Exception as exc:
        logger.exception("Error procesando correo id=%s", correo_id)
        raise HTTPException(status_code=502, detail=f"No se pudo procesar el correo: {exc}") from exc

    audits = [GmailScanAuditSummary(**item) for item in audits_raw if isinstance(item, dict)]
    return {
        "correo_id": processed_id,
        "audits": audits,
        "processed": len(audits),
    }
