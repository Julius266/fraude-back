from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

_pending_flows: dict[str, tuple[Flow, str, datetime]] = {}


def display_name_from_email(email: str) -> str:
    if not email or "@" not in email:
        return "Analista"
    local = email.split("@", 1)[0]
    parts = [part for part in re.split(r"[._+\-]+", local) if part]
    if not parts:
        return email
    return " ".join(part.capitalize() for part in parts)


class GmailNotAuthenticatedError(Exception):
    """No hay token OAuth válido para Gmail."""


def credentials_file_exists() -> bool:
    settings = get_settings()
    return Path(settings.gmail_client_secret_file).is_file()


def token_file_exists() -> bool:
    settings = get_settings()
    return Path(settings.gmail_token_file).is_file()


def _token_path() -> Path:
    return Path(get_settings().gmail_token_file)


def _load_credentials_file() -> Credentials | None:
    token_path = _token_path()
    if not token_path.is_file():
        return None
    try:
        with token_path.open("r", encoding="utf-8") as token_file:
            return Credentials.from_authorized_user_info(json.load(token_file), SCOPES)
    except Exception:
        logger.exception("No se pudo leer token.json")
        return None


def save_credentials(creds: Credentials) -> None:
    token_path = _token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    with token_path.open("w", encoding="utf-8") as token_file:
        json.dump(
            {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": list(creds.scopes or SCOPES),
            },
            token_file,
        )


def clear_credentials() -> None:
    token_path = _token_path()
    if token_path.is_file():
        token_path.unlink()


def load_valid_credentials() -> Credentials | None:
    if not credentials_file_exists():
        return None

    creds = _load_credentials_file()
    if creds is None:
        return None

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_credentials(creds)
            return creds
        except Exception:
            logger.exception("No se pudo refrescar el token de Gmail")
            return None

    return None


def _cleanup_pending_flows() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    expired = [state for state, (_, _, created_at) in _pending_flows.items() if created_at < cutoff]
    for state in expired:
        _pending_flows.pop(state, None)


def _build_flow() -> Flow:
    settings = get_settings()
    if not credentials_file_exists():
        raise FileNotFoundError(
            f"No se encontró {settings.gmail_client_secret_file}. Descarga OAuth Client desde Google Cloud."
        )

    return Flow.from_client_secrets_file(
        settings.gmail_client_secret_file,
        scopes=SCOPES,
        redirect_uri=settings.gmail_oauth_redirect_uri,
    )


def create_authorization_url(return_to: str = "/") -> dict[str, str]:
    _cleanup_pending_flows()
    flow = _build_flow()
    state = secrets.token_urlsafe(24)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    _pending_flows[state] = (flow, return_to, datetime.now(timezone.utc))
    return {"authorization_url": authorization_url, "state": state}


def exchange_authorization_code(code: str, state: str) -> str:
    pending = _pending_flows.pop(state, None)
    if pending is None:
        raise ValueError("La sesión OAuth expiró o es inválida. Vuelve a conectar Gmail.")

    flow, return_to, _ = pending
    flow.fetch_token(code=code)
    creds = flow.credentials
    if creds is None:
        raise ValueError("Google no devolvió credenciales válidas.")

    save_credentials(creds)
    logger.info("Token OAuth de Gmail guardado correctamente")
    return return_to


def get_profile_from_credentials(creds: Credentials) -> dict[str, str]:
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    return {
        "emailAddress": profile.get("emailAddress", "") or "",
        "historyId": str(profile.get("historyId", "") or ""),
    }


def get_auth_status() -> dict[str, Any]:
    settings = get_settings()
    status: dict[str, Any] = {
        "credentials_configured": credentials_file_exists(),
        "token_configured": token_file_exists(),
        "connected": False,
        "user": None,
        "redirect_uri": settings.gmail_oauth_redirect_uri,
    }

    creds = load_valid_credentials()
    if creds is None:
        return status

    try:
        profile = get_profile_from_credentials(creds)
        email = profile.get("emailAddress", "").strip()
        if email:
            status["connected"] = True
            status["user"] = {
                "email": email,
                "name": display_name_from_email(email),
                "role": "Analista de Fraude",
            }
    except Exception as exc:
        logger.warning("Token presente pero Gmail no respondió: %s", exc)

    return status
