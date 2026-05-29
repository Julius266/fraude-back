from __future__ import annotations

import base64
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.integrations.gmail.service import GmailIngestionService

import logging

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
logger = logging.getLogger(__name__)


@router.post("/gmail/push")
async def gmail_push_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    payload = await request.json()
    message = payload.get("message", {})
    data = message.get("data")

    logger.info(
        "Pub/Sub webhook recibido message_id=%s publish_time=%s attributes=%s",
        message.get("messageId"),
        message.get("publishTime"),
        list(message.get("attributes", {}).keys()),
    )

    if not data:
        logger.warning("Pub/Sub webhook sin data en el mensaje")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Pub/Sub message data")

    decoded_payload = json.loads(base64.b64decode(data).decode("utf-8"))
    owner_email = str(decoded_payload.get("emailAddress", "") or "").strip().lower()
    logger.info(
        "Pub/Sub payload decodificado historyId=%s emailAddress=%s",
        decoded_payload.get("historyId"),
        owner_email or decoded_payload.get("emailAddress"),
    )
    if not owner_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing emailAddress in Pub/Sub payload")

    service = GmailIngestionService(db, owner_email=owner_email)
    try:
        result = service.process_push_notification(decoded_payload)
    except Exception:
        logger.exception("Fallo procesando notificacion Pub/Sub de Gmail")
        raise

    logger.info(
        "Webhook Gmail procesado historyId=%s resultado=%s",
        decoded_payload.get("historyId"),
        result,
    )

    return {
        "status": "processed",
        "notification": decoded_payload,
        "result": result,
    }
