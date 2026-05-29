from __future__ import annotations

import base64
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.integrations.gmail.oauth import GmailNotAuthenticatedError, load_valid_credentials

logger = logging.getLogger(__name__)


class GmailClient:
    def __init__(self, owner_email: str | None = None, credentials: Credentials | None = None) -> None:
        creds = credentials or load_valid_credentials(owner_email)
        if creds is None:
            raise GmailNotAuthenticatedError(
                "No hay sesión OAuth de Gmail. Conecta tu cuenta desde el login."
            )
        self.service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def get_profile(self) -> dict[str, str]:
        profile = self.service.users().getProfile(userId="me").execute()
        return {
            "emailAddress": profile.get("emailAddress", "") or "",
            "historyId": str(profile.get("historyId", "") or ""),
        }

    def watch(self, topic_name: str) -> dict[str, Any]:
        request_body = {"topicName": topic_name, "labelIds": ["INBOX"]}
        return self.service.users().watch(userId="me", body=request_body).execute()

    def list_recent_messages(self, query: str, max_results: int) -> list[dict[str, str]]:
        response = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        return response.get("messages", [])

    def get_history_changes(self, start_history_id: str) -> dict[str, Any]:
        response = self.service.users().history().list(
            userId="me",
            startHistoryId=start_history_id,
            historyTypes=["messageAdded"],
        ).execute()
        return response

    @staticmethod
    def is_history_not_found(error: Exception) -> bool:
        return isinstance(error, HttpError) and getattr(error, "status_code", None) == 404

    def get_message(self, message_id: str, format_: str = "full") -> dict[str, Any]:
        return (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format=format_)
            .execute()
        )

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        response = (
            self.service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        data = response.get("data", "")
        return base64.urlsafe_b64decode(self._pad_base64(data))

    def _pad_base64(self, value: str) -> str:
        return value + "=" * (-len(value) % 4)

    def extract_headers(self, payload: dict[str, Any]) -> dict[str, str]:
        headers = payload.get("headers", [])
        return {header.get("name", "").lower(): header.get("value", "") for header in headers}

    def extract_body_text(self, payload: dict[str, Any]) -> str:
        parts = payload.get("parts", [])
        mime_type = payload.get("mimeType", "")

        if mime_type == "text/plain":
            body_data = payload.get("body", {}).get("data")
            if body_data:
                return self._decode_body(body_data)

        if mime_type == "text/html":
            body_data = payload.get("body", {}).get("data")
            if body_data:
                return self._decode_body(body_data)

        collected: list[str] = []
        for part in parts:
            collected_text = self.extract_body_text(part)
            if collected_text:
                collected.append(collected_text)

        if collected:
            return "\n".join(collected)

        body_data = payload.get("body", {}).get("data")
        if body_data:
            return self._decode_body(body_data)

        return ""

    def extract_attachments(self, message_id: str, payload: dict[str, Any]) -> list[dict[str, str]]:
        attachments: list[dict[str, str]] = []
        for part in payload.get("parts", []):
            attachments.extend(self.extract_attachments(message_id, part))

        filename = payload.get("filename")
        body = payload.get("body", {})
        attachment_id = body.get("attachmentId")

        if filename and attachment_id:
            attachments.append(
                {
                    "filename": filename,
                    "attachment_id": attachment_id,
                    "mime_type": payload.get("mimeType", "application/octet-stream"),
                }
            )

        return attachments

    def _decode_body(self, encoded: str) -> str:
        raw = base64.urlsafe_b64decode(self._pad_base64(encoded))
        return raw.decode("utf-8", errors="ignore")

    def normalize_text(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        stripped = "".join(character for character in normalized if not unicodedata.combining(character))
        return re.sub(r"\s+", " ", stripped).upper().strip()

    def parse_email_date(self, headers: dict[str, str]) -> datetime | None:
        raw_date = headers.get("date")
        if not raw_date:
            return None

        try:
            parsed = parsedate_to_datetime(raw_date)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            logger.exception("No se pudo parsear la fecha del correo")
            return None

    def build_query(self, hours_back: int) -> str:
        since = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        return f"after:{int(since.timestamp())} in:inbox"

    def send_email(
        self,
        to: str,
        subject: str,
        body_text: str,
        html_body: str | None = None,
        thread_id: str | None = None,
        attachments: list[tuple[str, bytes, str]] | None = None,
    ) -> dict[str, Any]:
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders

        if attachments:
            message = MIMEMultipart("mixed")
        else:
            message = MIMEMultipart("alternative")

        message["to"] = to
        message["subject"] = subject
        if thread_id:
            message["In-Reply-To"] = thread_id
            message["References"] = thread_id

        if attachments:
            body_container = MIMEMultipart("alternative")
            message.attach(body_container)
        else:
            body_container = message

        body_container.attach(MIMEText(body_text, "plain", "utf-8"))

        if html_body:
            body_container.attach(MIMEText(html_body, "html", "utf-8"))

        if attachments:
            for filename, data, mime_type in attachments:
                maintype, subtype = mime_type.split("/", 1)
                part = MIMEBase(maintype, subtype)
                part.set_payload(data)
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=filename,
                )
                message.attach(part)

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        body = {"raw": raw_message}
        if thread_id:
            body["threadId"] = thread_id

        return (
            self.service.users()
            .messages()
            .send(userId="me", body=body)
            .execute()
        )
