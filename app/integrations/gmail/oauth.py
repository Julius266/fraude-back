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
from app.db.session import SessionLocal
from app.models.gmail_oauth_token import GmailOAuthToken

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

_pending_flows: dict[str, tuple[Flow, str, datetime]] = {}


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


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


def _token_path() -> Path:
    return Path(get_settings().gmail_token_file)


def _credentials_to_dict(creds: Credentials) -> dict[str, object]:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }


def _credentials_from_dict(data: dict[str, object]) -> Credentials:
    return Credentials.from_authorized_user_info(data, SCOPES)


def _load_legacy_credentials_file() -> Credentials | None:
    token_path = _token_path()
    if not token_path.is_file():
        return None
    try:
        with token_path.open("r", encoding="utf-8") as token_file:
            return _credentials_from_dict(json.load(token_file))
    except Exception:
        logger.exception("No se pudo leer token.json legacy")
        return None


def _load_credentials_row(owner_email: str) -> Credentials | None:
    email = normalize_email(owner_email)
    if not email:
        return None

    db = SessionLocal()
    try:
        row = db.get(GmailOAuthToken, email)
        if row is None:
            return None
        return _credentials_from_dict(json.loads(row.token_json))
    except Exception:
        logger.exception("No se pudo leer token OAuth de BD para %s", email)
        return None
    finally:
        db.close()


def token_exists_for_owner(owner_email: str | None) -> bool:
    email = normalize_email(owner_email)
    if not email:
        return False

    db = SessionLocal()
    try:
        return db.get(GmailOAuthToken, email) is not None
    finally:
        db.close()


def save_credentials(creds: Credentials, owner_email: str) -> None:
    email = normalize_email(owner_email)
    if not email:
        raise ValueError("owner_email es requerido para guardar credenciales OAuth")

    payload = json.dumps(_credentials_to_dict(creds))
    db = SessionLocal()
    try:
        row = db.get(GmailOAuthToken, email)
        if row is None:
            db.add(GmailOAuthToken(owner_email=email, token_json=payload))
        else:
            row.token_json = payload
        db.commit()
        logger.info("Token OAuth guardado para %s", email)
    finally:
        db.close()


def clear_credentials(owner_email: str | None = None) -> None:
    email = normalize_email(owner_email)
    if not email:
        return

    db = SessionLocal()
    try:
        row = db.get(GmailOAuthToken, email)
        if row is not None:
            db.delete(row)
            db.commit()
            logger.info("Token OAuth eliminado para %s", email)
    finally:
        db.close()


def migrate_legacy_token_file() -> None:
    creds = _load_legacy_credentials_file()
    if creds is None:
        return

    try:
        profile = get_profile_from_credentials(creds)
        email = normalize_email(profile.get("emailAddress"))
        if not email:
            return
        if token_exists_for_owner(email):
            return
        save_credentials(creds, email)
        logger.info("Token legacy migrado a BD para %s", email)
    except Exception:
        logger.exception("No se pudo migrar token.json legacy a BD")


def load_valid_credentials(owner_email: str | None = None) -> Credentials | None:
    if not credentials_file_exists():
        return None

    email = normalize_email(owner_email)
    if not email:
        return None

    creds = _load_credentials_row(email)
    if creds is None:
        return None

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_credentials(creds, email)
            return creds
        except Exception:
            logger.exception("No se pudo refrescar el token de Gmail para %s", email)
            clear_credentials(email)
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
        redirect_uri=settings.resolved_gmail_oauth_redirect_uri,
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


def exchange_authorization_code(code: str, state: str) -> tuple[str, str]:
    pending = _pending_flows.pop(state, None)
    if pending is None:
        raise ValueError("La sesión OAuth expiró o es inválida. Vuelve a conectar Gmail.")

    flow, return_to, _ = pending
    flow.fetch_token(code=code)
    creds = flow.credentials
    if creds is None:
        raise ValueError("Google no devolvió credenciales válidas.")

    profile = get_profile_from_credentials(creds)
    email = normalize_email(profile.get("emailAddress"))
    if not email:
        raise ValueError("Google no devolvió el email de la cuenta conectada.")

    save_credentials(creds, email)
    return return_to, email


def get_profile_from_credentials(creds: Credentials) -> dict[str, str]:
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    return {
        "emailAddress": profile.get("emailAddress", "") or "",
        "historyId": str(profile.get("historyId", "") or ""),
    }


def get_auth_status(owner_email: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    email = normalize_email(owner_email)
    status: dict[str, Any] = {
        "credentials_configured": credentials_file_exists(),
        "token_configured": token_exists_for_owner(email) if email else False,
        "connected": False,
        "user": None,
        "redirect_uri": settings.resolved_gmail_oauth_redirect_uri,
    }

    if not email:
        return status

    creds = load_valid_credentials(email)
    if creds is None:
        return status

    try:
        profile = get_profile_from_credentials(creds)
        profile_email = normalize_email(profile.get("emailAddress"))
        if profile_email and profile_email == email:
            status["connected"] = True
            status["user"] = {
                "email": profile_email,
                "name": display_name_from_email(profile_email),
                "role": "Analista de Fraude",
            }
    except Exception as exc:
        logger.warning("Token presente pero Gmail no respondió para %s: %s", email, exc)

    return status
