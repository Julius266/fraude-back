from __future__ import annotations

import logging
from pathlib import Path

from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.gmail.client import GmailClient
from app.integrations.siniestros.pdf_parser import SiniestroPdfParser, ParsedSiniestroDraft
from app.models.siniestro import Siniestro
from app.models.gmail_correo import GmailCorreo
from app.models.gmail_sync_state import GmailSyncState

logger = logging.getLogger(__name__)


class GmailIngestionService:
    SYNC_SCOPE_KEY = "default"

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.client = GmailClient()
        self.pdf_parser = SiniestroPdfParser(enable_ocr=self.settings.enable_pdf_ocr)
        self.download_dir = Path(self.settings.gmail_download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def register_watch(self) -> dict:
        if not self.settings.gmail_watch_topic:
            raise ValueError("GMAIL_WATCH_TOPIC no esta configurado")
        logger.info("Registrando watch de Gmail topic=%s", self.settings.gmail_watch_topic)
        result = self.client.watch(self.settings.gmail_watch_topic)
        history_id = result.get("historyId")
        if history_id:
            logger.info("Watch de Gmail registrado historyId_inicial=%s", history_id)
            self._upsert_sync_state(history_id)
        else:
            logger.warning("Watch de Gmail respondio sin historyId result=%s", result)
        return result

    def process_recent_messages(self) -> dict[str, int]:
        query = self.client.build_query(self.settings.gmail_query_hours_back)
        logger.info("Iniciando scan manual de Gmail query=%s max_results=%s", query, self.settings.gmail_max_results)
        message_refs = self.client.list_recent_messages(query, self.settings.gmail_max_results)
        logger.info("Scan manual de Gmail devolvio %s referencias", len(message_refs))

        saved = 0
        ignored = 0

        for ref in message_refs:
            created = self._process_message(ref["id"])
            if created:
                saved += 1
            else:
                ignored += 1

        logger.info("Scan manual finalizado saved=%s ignored=%s", saved, ignored)

        return {"saved": saved, "ignored": ignored}

    def process_push_notification(self, notification_payload: dict[str, object]) -> dict[str, object]:
        notification_history_id = str(notification_payload.get("historyId", "")).strip()
        if not notification_history_id:
            raise ValueError("La notificacion de Gmail no contiene historyId")

        logger.info(
            "Procesando notificacion Pub/Sub historyId=%s payload_keys=%s",
            notification_history_id,
            list(notification_payload.keys()),
        )

        state = self._get_sync_state()
        if state is None:
            logger.warning("No existe estado de sincronizacion; no se puede procesar historyId=%s", notification_history_id)
            raise ValueError("No hay estado de sincronizacion. Ejecuta primero register_watch")

        logger.info(
            "Estado de sincronizacion actual scope=%s last_history_id=%s notification_history_id=%s",
            state.scope_key,
            state.last_history_id,
            notification_history_id,
        )

        if int(notification_history_id) <= int(state.last_history_id):
            logger.info(
                "Notificacion Pub/Sub ignorada por historyId antiguo notification=%s actual=%s",
                notification_history_id,
                state.last_history_id,
            )
            return {
                "status": "ignored",
                "reason": "old_history_id",
                "history_id": notification_history_id,
            }

        try:
            history_response = self.client.get_history_changes(state.last_history_id)
            logger.info(
                "History Gmail consultado desde=%s hasta_notificacion=%s keys=%s",
                state.last_history_id,
                notification_history_id,
                list(history_response.keys()),
            )
        except HttpError as exc:
            if self._is_history_not_found(exc):
                logger.warning(
                    "HistoryId expirado o no encontrado desde=%s; ejecutando fallback scan notification=%s",
                    state.last_history_id,
                    notification_history_id,
                )
                fallback = self.process_recent_messages()
                self._upsert_sync_state(notification_history_id)
                return {
                    "status": "fallback_scan",
                    "history_id": notification_history_id,
                    "result": fallback,
                }
            raise

        message_ids = self._extract_message_ids_from_history(history_response)
        logger.info(
            "History Gmail produjo %s mensajes para procesar historyId=%s message_ids=%s",
            len(message_ids),
            notification_history_id,
            message_ids,
        )
        saved = 0
        ignored = 0

        for message_id in message_ids:
            logger.info("Procesando mensaje Gmail message_id=%s", message_id)
            created = self._process_message(message_id)
            if created:
                saved += 1
            else:
                ignored += 1

        logger.info(
            "Procesamiento Pub/Sub finalizado historyId=%s saved=%s ignored=%s",
            notification_history_id,
            saved,
            ignored,
        )

        self._upsert_sync_state(notification_history_id)

        return {
            "status": "processed",
            "history_id": notification_history_id,
            "saved": saved,
            "ignored": ignored,
            "processed_message_ids": message_ids,
        }

    def process_message_by_id(self, message_id: str) -> bool:
        return self._process_message(message_id)

    def list_saved_messages(self, limit: int = 100) -> list[GmailCorreo]:
        statement = select(GmailCorreo).order_by(GmailCorreo.fecha_registro.desc()).limit(limit)
        return list(self.db.scalars(statement).all())

    def _process_message(self, message_id: str) -> bool:
        existing = self.db.scalar(select(GmailCorreo).where(GmailCorreo.gmail_message_id == message_id))
        if existing:
            logger.info("Mensaje Gmail ya estaba guardado message_id=%s", message_id)
            return False

        try:
            message = self.client.get_message(message_id, format_="full")
        except HttpError as exc:
            if getattr(getattr(exc, "resp", None), "status", None) == 404:
                logger.warning(
                    "Mensaje Gmail no encontrado al procesarlo message_id=%s; se omite para no romper el webhook",
                    message_id,
                )
                return False
            raise

        payload = message.get("payload", {})
        headers = self.client.extract_headers(payload)

        subject = headers.get("subject", "Sin asunto")
        sender = headers.get("from", "Desconocido")
        body_text = self.client.extract_body_text(payload)
        snippet = message.get("snippet", "")
        combined_text = "\n".join(part for part in [snippet, body_text] if part).strip()

        keyword = self._match_keyword(subject, combined_text)
        if not keyword:
            logger.info(
                "Mensaje Gmail descartado por no coincidir con palabras clave message_id=%s subject=%s",
                message_id,
                subject,
            )
            return False

        attachments = self.client.extract_attachments(message_id, payload)
        logger.info(
            "Mensaje Gmail coincide keyword=%s message_id=%s attachments=%s",
            keyword,
            message_id,
            [attachment.get("filename") for attachment in attachments],
        )
        attachment_name = None
        attachment_path = None
        has_attachment = False
        saved_attachments: list[tuple[dict[str, str], tuple[str, str]]] = []

        if attachments:
            for attachment in attachments:
                saved_attachment = self._save_attachment(message_id, attachment)
                if not saved_attachment:
                    continue

                saved_attachments.append((attachment, saved_attachment))

                if not has_attachment:
                    attachment_name, attachment_path = saved_attachment
                    has_attachment = True

                logger.info(
                    "Adjunto guardado message_id=%s filename=%s path=%s",
                    message_id,
                    saved_attachment[0],
                    saved_attachment[1],
                )

        correo = GmailCorreo(
            gmail_message_id=message_id,
            thread_id=message.get("threadId"),
            remitente=sender,
            asunto=subject,
            descripcion=combined_text or subject,
            adjunto_nombre=attachment_name,
            adjunto_ruta=attachment_path,
            tiene_adjunto=has_attachment,
            fecha_correo=self.client.parse_email_date(headers),
            palabra_clave_detectada=keyword,
        )

        self.db.add(correo)
        self.db.commit()
        self.db.refresh(correo)
        logger.info("Correo Gmail guardado message_id=%s keyword=%s", message_id, keyword)

        siniestros_creados = self._process_pdf_attachments(correo, saved_attachments)
        if siniestros_creados:
            logger.info("Siniestros creados desde correo correo_id=%s count=%s", correo.id, siniestros_creados)
        return True

    def _match_keyword(self, subject: str, content: str) -> str | None:
        subject_normalized = self.client.normalize_text(subject)
        content_normalized = self.client.normalize_text(content)

        for keyword in self.settings.gmail_keywords_list:
            normalized_keyword = self.client.normalize_text(keyword)
            if normalized_keyword and (normalized_keyword in subject_normalized or normalized_keyword in content_normalized):
                return keyword
        return None

    def _save_attachment(self, message_id: str, attachment: dict[str, str]) -> tuple[str, str] | None:
        filename = Path(attachment["filename"]).name
        safe_name = f"{message_id}_{filename}"
        file_path = self.download_dir / safe_name

        data = self.client.get_attachment(message_id, attachment["attachment_id"])
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(data)

        logger.info(
            "Escribiendo adjunto en disco message_id=%s attachment_id=%s file=%s bytes=%s",
            message_id,
            attachment["attachment_id"],
            file_path,
            len(data),
        )

        return filename, str(file_path)

    def _process_pdf_attachments(
        self,
        correo: GmailCorreo,
        saved_attachments: list[tuple[dict[str, str], tuple[str, str]]],
    ) -> int:
        siniestros_creados = 0

        for attachment, saved_attachment in saved_attachments:
            if not self._is_pdf_attachment(attachment):
                logger.info(
                    "Adjunto ignorado por no ser PDF correo_id=%s filename=%s mime_type=%s",
                    correo.id,
                    attachment.get("filename"),
                    attachment.get("mime_type"),
                )
                continue

            _, attachment_path = saved_attachment
            pdf_path = Path(attachment_path)
            try:
                parsed_siniestros = self.pdf_parser.parse(pdf_path)
            except Exception:
                logger.exception(
                    "Error parseando PDF para siniestros correo_id=%s pdf=%s",
                    correo.id,
                    pdf_path,
                )
                continue

            logger.info(
                "PDF parseado correo_id=%s pdf=%s siniestros_detectados=%s",
                correo.id,
                pdf_path,
                len(parsed_siniestros),
            )

            for parsed in parsed_siniestros:
                entity = self._build_siniestro_entity(correo.id, parsed)
                self.db.add(entity)
                siniestros_creados += 1

        if siniestros_creados:
            self.db.commit()

        return siniestros_creados

    def _is_pdf_attachment(self, attachment: dict[str, str]) -> bool:
        filename = (attachment.get("filename") or "").lower()
        mime_type = (attachment.get("mime_type") or "").lower()
        return filename.endswith(".pdf") or mime_type == "application/pdf"

    def _build_siniestro_entity(self, correo_id: int, parsed: ParsedSiniestroDraft) -> Siniestro:
        return Siniestro(
            gmail_correo_id=correo_id,
            id_siniestro=parsed.id_siniestro,
            id_poliza=parsed.id_poliza,
            id_asegurado=parsed.id_asegurado,
            ramo=parsed.ramo,
            cobertura=parsed.cobertura,
            fecha_ocurrencia=parsed.fecha_ocurrencia,
            fecha_reporte=parsed.fecha_reporte,
            monto_reclamado=parsed.monto_reclamado,
            monto_estimado=parsed.monto_estimado,
            monto_pagado=parsed.monto_pagado,
            estado=parsed.estado,
            sucursal=parsed.sucursal,
            descripcion=parsed.descripcion,
            documentos_completos=parsed.documentos_completos,
            beneficiario=parsed.beneficiario,
            dias_desde_inicio_poliza=parsed.dias_desde_inicio_poliza,
            dias_desde_fin_poliza=parsed.dias_desde_fin_poliza,
            dias_entre_ocurrencia_reporte=parsed.dias_entre_ocurrencia_reporte,
            historial_siniestros_asegurado=parsed.historial_siniestros_asegurado,
            etiqueta_fraude_simulada=parsed.etiqueta_fraude_simulada,
        )

    def _extract_message_ids_from_history(self, history_response: dict[str, object]) -> list[str]:
        message_ids: list[str] = []
        for history_item in history_response.get("history", []):
            for added in history_item.get("messagesAdded", []):
                message = added.get("message", {})
                message_id = message.get("id")
                if message_id and message_id not in message_ids:
                    message_ids.append(message_id)
        return message_ids

    def _get_sync_state(self) -> GmailSyncState | None:
        return self.db.scalar(select(GmailSyncState).where(GmailSyncState.scope_key == self.SYNC_SCOPE_KEY))

    def _upsert_sync_state(self, last_history_id: str) -> GmailSyncState:
        state = self._get_sync_state()
        if state is None:
            state = GmailSyncState(scope_key=self.SYNC_SCOPE_KEY, last_history_id=str(last_history_id))
            self.db.add(state)
            logger.info("Creando estado de sincronizacion scope=%s last_history_id=%s", self.SYNC_SCOPE_KEY, last_history_id)
        else:
            logger.info(
                "Actualizando estado de sincronizacion scope=%s old_history_id=%s new_history_id=%s",
                state.scope_key,
                state.last_history_id,
                last_history_id,
            )
            state.last_history_id = str(last_history_id)

        self.db.commit()
        self.db.refresh(state)
        logger.info("Estado de sincronizacion persistido scope=%s last_history_id=%s", state.scope_key, state.last_history_id)
        return state

    def _is_history_not_found(self, error: HttpError) -> bool:
        resp = getattr(error, "resp", None)
        return getattr(resp, "status", None) == 404
