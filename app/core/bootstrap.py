from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def bootstrap_runtime_files() -> None:
    settings = get_settings()

    creds_json = os.getenv("GOOGLE_OAUTH_CREDENTIALS_JSON", "").strip()
    if creds_json:
        creds_path = Path(settings.gmail_client_secret_file)
        if not creds_path.is_file():
            try:
                json.loads(creds_json)
            except json.JSONDecodeError:
                logger.error("GOOGLE_OAUTH_CREDENTIALS_JSON no es JSON valido")
            else:
                creds_path.parent.mkdir(parents=True, exist_ok=True)
                creds_path.write_text(creds_json, encoding="utf-8")
                logger.info("credentials.json creado desde GOOGLE_OAUTH_CREDENTIALS_JSON")

    Path(settings.gmail_download_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.gmail_token_file).parent.mkdir(parents=True, exist_ok=True)
