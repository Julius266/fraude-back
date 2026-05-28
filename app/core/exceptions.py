from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from googleapiclient.errors import HttpError

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def cors_headers(request: Request) -> dict[str, str]:
    settings = get_settings()
    origin = request.headers.get("origin")
    if origin and origin in settings.allowed_origins_list:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return {}


def google_http_error_detail(error: HttpError) -> str:
    try:
        payload = json.loads(error.content.decode("utf-8"))
        message = payload.get("error", {}).get("message")
        if message:
            return message
    except Exception:
        pass
    return str(error)


def validate_gmail_watch_topic(topic_name: str, credentials_file: str) -> None:
    creds_path = Path(credentials_file)
    if not creds_path.is_file():
        return

    data = json.loads(creds_path.read_text(encoding="utf-8"))
    project_id = data.get("installed", {}).get("project_id") or data.get("web", {}).get("project_id")
    if not project_id:
        return

    expected_prefix = f"projects/{project_id}/topics/"
    if not topic_name.startswith(expected_prefix):
        raise ValueError(
            f"GMAIL_WATCH_TOPIC debe pertenecer al proyecto Google '{project_id}'. "
            f"Ejemplo: {expected_prefix}<nombre-del-topico>. "
            f"Valor actual: {topic_name}"
        )


async def http_error_handler(request: Request, exc: HttpError) -> JSONResponse:
    status = getattr(getattr(exc, "resp", None), "status", None) or 502
    detail = google_http_error_detail(exc)
    logger.error("Google API error status=%s detail=%s", status, detail)
    return JSONResponse(
        status_code=int(status) if isinstance(status, int) else 502,
        content={"detail": detail, "source": "google_api"},
        headers=cors_headers(request),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    settings = get_settings()
    if settings.app_env == "development":
        detail = str(exc)
    else:
        detail = "Error interno del servidor"
    return JSONResponse(
        status_code=500,
        content={"detail": detail},
        headers=cors_headers(request),
    )
