from fastapi import Header, HTTPException

from app.integrations.gmail.oauth import load_valid_credentials, get_profile_from_credentials


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


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


def get_connected_gmail_email() -> str | None:
    creds = load_valid_credentials()
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
    oauth_email = get_connected_gmail_email()
    header_email = normalize_email(x_analyst_email)

    if oauth_email:
        if header_email and header_email != oauth_email:
            raise HTTPException(
                status_code=403,
                detail="La cuenta de Gmail conectada no coincide con tu sesión.",
            )
        return oauth_email

    if header_email:
        return header_email

    raise HTTPException(
        status_code=401,
        detail="Conecta tu cuenta de Gmail antes de continuar.",
    )
