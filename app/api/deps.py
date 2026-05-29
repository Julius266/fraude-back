from fastapi import Header, HTTPException

from app.integrations.gmail.oauth import (
    get_profile_from_credentials,
    load_valid_credentials,
    normalize_email,
)


async def get_analyst_email(
    x_analyst_email: str | None = Header(default=None, alias="X-Analyst-Email"),
) -> str:
    email = normalize_email(x_analyst_email)
    if not email:
        raise HTTPException(
            status_code=401,
            detail="Sesión de analista requerida. Inicia sesión con Gmail.",
        )
    return email


async def get_optional_analyst_email(
    x_analyst_email: str | None = Header(default=None, alias="X-Analyst-Email"),
) -> str | None:
    email = normalize_email(x_analyst_email)
    return email or None


def get_connected_gmail_email(owner_email: str | None = None) -> str | None:
    email = normalize_email(owner_email)
    if not email:
        return None

    creds = load_valid_credentials(email)
    if creds is None:
        return None
    try:
        profile = get_profile_from_credentials(creds)
        return normalize_email(profile.get("emailAddress"))
    except Exception:
        return None


async def get_gmail_owner_email(
    x_analyst_email: str | None = Header(default=None, alias="X-Analyst-Email"),
) -> str:
    header_email = normalize_email(x_analyst_email)
    if not header_email:
        raise HTTPException(
            status_code=401,
            detail="Conecta tu cuenta de Gmail antes de continuar.",
        )

    oauth_email = get_connected_gmail_email(header_email)
    if oauth_email is None:
        raise HTTPException(
            status_code=401,
            detail="Conecta tu cuenta de Gmail antes de continuar.",
        )

    if oauth_email != header_email:
        raise HTTPException(
            status_code=403,
            detail="La cuenta de Gmail conectada no coincide con tu sesión.",
        )

    return oauth_email
