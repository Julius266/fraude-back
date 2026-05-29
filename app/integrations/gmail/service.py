from __future__ import annotations

import logging
from pathlib import Path

from googleapiclient.errors import HttpError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import validate_gmail_watch_topic
from app.integrations.chat.index_service import EmbeddingIndexService
from app.integrations.gmail.client import GmailClient
from app.integrations.gmail.oauth import GmailNotAuthenticatedError, display_name_from_email
from app.api.owner_scope import siniestro_scope
from app.integrations.siniestros.auto_scoring import AutoScoringService
from app.integrations.siniestros.pdf_parser import ParsedSiniestroDraft, SiniestroPdfParser
from app.models.siniestro import Siniestro
from app.models.gmail_correo import GmailCorreo
from app.models.gmail_sync_state import GmailSyncState

logger = logging.getLogger(__name__)


class GmailIngestionService:
    SYNC_SCOPE_KEY = "default"

    def __init__(self, db: Session, owner_email: str | None = None):
        self.db = db
        self.settings = get_settings()
        self.owner_email = (owner_email or "").strip().lower() or None
        self._client: GmailClient | None = None
        self.pdf_parser = SiniestroPdfParser(enable_ocr=self.settings.enable_pdf_ocr)
        self.download_dir = Path(self.settings.gmail_download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    @property
    def client(self) -> GmailClient:
        if self._client is None:
            if not self.owner_email:
                raise GmailNotAuthenticatedError(
                    "No hay analista asociado. Inicia sesión con Gmail."
                )
            self._client = GmailClient(owner_email=self.owner_email)
        return self._client

    @staticmethod
    def _display_name_from_email(email: str) -> str:
        return display_name_from_email(email)

    def get_connected_user(self) -> dict[str, str]:
        profile = self.client.get_profile()
        email = profile.get("emailAddress", "").strip()
        if not self.owner_email and email:
            self.owner_email = email.strip().lower()
        return {
            "email": email,
            "name": self._display_name_from_email(email),
            "role": "Analista de Fraude",
        }

    def _resolve_owner_email(self) -> str:
        if self.owner_email:
            return self.owner_email
        user = self.get_connected_user()
        email = user["email"].strip().lower()
        if not email:
            raise GmailNotAuthenticatedError("No se pudo determinar el analista conectado.")
        self.owner_email = email
        return email

    def register_watch(self) -> dict:
        if not self.settings.gmail_watch_topic:
            raise ValueError("GMAIL_WATCH_TOPIC no esta configurado")
        validate_gmail_watch_topic(
            self.settings.gmail_watch_topic,
            self.settings.gmail_client_secret_file,
        )
        logger.info("Registrando watch de Gmail topic=%s", self.settings.gmail_watch_topic)
        result = self.client.watch(self.settings.gmail_watch_topic)
        history_id = result.get("historyId")
        if history_id:
            logger.info("Watch de Gmail registrado historyId_inicial=%s", history_id)
            self._upsert_sync_state(history_id)
        else:
            logger.warning("Watch de Gmail respondio sin historyId result=%s", result)
        return result

    def process_recent_messages(self) -> dict[str, object]:
        query = self.client.build_query(self.settings.gmail_query_hours_back)
        logger.info("Iniciando scan manual de Gmail query=%s max_results=%s", query, self.settings.gmail_max_results)
        message_refs = self.client.list_recent_messages(query, self.settings.gmail_max_results)
        logger.info("Scan manual de Gmail devolvio %s referencias", len(message_refs))

        saved = 0
        ignored = 0
        audits: list[dict[str, object]] = []
        seen_ids: set[str] = set()

        for ref in message_refs:
            message_id = ref["id"]
            if message_id in seen_ids:
                ignored += 1
                continue
            seen_ids.add(message_id)

            created, message_audits = self._process_message(message_id)
            audits.extend(message_audits)
            if created:
                saved += 1
            else:
                ignored += 1

        pending_audits = self._audit_pending_siniestros()
        audits.extend(pending_audits)

        reprocess_audits = self._reprocess_unlinked_correos()
        audits.extend(reprocess_audits)

        logger.info(
            "Scan manual finalizado saved=%s ignored=%s audits=%s",
            saved,
            ignored,
            len(audits),
        )

        return {"saved": saved, "ignored": ignored, "audits": audits}

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
            created, _message_audits = self._process_message(message_id)
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
        created, _audits = self._process_message(message_id)
        return created

    def list_saved_messages(self, limit: int = 100, owner_email: str | None = None) -> list[GmailCorreo]:
        owner = (owner_email or self.owner_email or "").strip().lower()
        statement = select(GmailCorreo).order_by(GmailCorreo.fecha_registro.desc()).limit(limit)
        if owner:
            statement = statement.where(GmailCorreo.owner_email == owner)
        return list(self.db.scalars(statement).all())

    def _process_message(self, message_id: str) -> tuple[bool, list[dict[str, object]]]:
        if self._message_already_saved(message_id):
            logger.info("Mensaje Gmail ya estaba guardado message_id=%s", message_id)
            return False, []

        try:
            message = self.client.get_message(message_id, format_="full")
        except HttpError as exc:
            if getattr(getattr(exc, "resp", None), "status", None) == 404:
                logger.warning(
                    "Mensaje Gmail no encontrado al procesarlo message_id=%s; se omite para no romper el webhook",
                    message_id,
                )
                return False, []
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
            return False, []

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
            owner_email=self._resolve_owner_email(),
        )

        self.db.add(correo)
        try:
            self.db.commit()
            self.db.refresh(correo)
        except IntegrityError:
            self.db.rollback()
            logger.info("Mensaje Gmail duplicado al guardar message_id=%s", message_id)
            return False, []

        logger.info("Correo Gmail guardado message_id=%s keyword=%s", message_id, keyword)

        siniestros_to_audit = self._process_pdf_attachments(correo, saved_attachments)
        audits = self._auto_audit_siniestros(siniestros_to_audit)
        if siniestros_to_audit:
            logger.info(
                "Siniestros auditados desde correo correo_id=%s count=%s audits=%s",
                correo.id,
                len(siniestros_to_audit),
                len(audits),
            )
        else:
            try:
                self._send_auto_reply_template(correo)
            except Exception:
                logger.exception("Error al enviar auto-respuesta con la plantilla correo_id=%s", correo.id)
        return True, audits

    def _message_already_saved(self, message_id: str) -> bool:
        for obj in self.db.new:
            if isinstance(obj, GmailCorreo) and obj.gmail_message_id == message_id:
                return True

        existing = self.db.scalar(
            select(GmailCorreo).where(GmailCorreo.gmail_message_id == message_id)
        )
        if existing is not None:
            if not existing.owner_email:
                existing.owner_email = self._resolve_owner_email()
                self.db.commit()
            return True

        return False

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

    @staticmethod
    def _analyst_scoped_id(base_id: str, owner_email: str) -> str:
        clean = base_id.split("|")[0].strip()
        slug = owner_email.split("@")[0].replace(".", "")[:12]
        return f"{clean}|{slug}"[:50]

    @staticmethod
    def _correo_variant_id(base_id: str, owner_email: str, correo_id: int) -> str:
        clean = base_id.split("|")[0].strip()
        slug = owner_email.split("@")[0].replace(".", "")[:8]
        return f"{clean}|{slug}|c{correo_id}"[:50]

    def _siniestro_already_linked_to_correo(self, correo_id: int, base_id: str) -> Siniestro | None:
        clean = base_id.split("|")[0].strip()
        rows = list(
            self.db.scalars(select(Siniestro).where(Siniestro.gmail_correo_id == correo_id)).all()
        )
        for row in rows:
            if row.id_siniestro.split("|")[0].strip() == clean:
                return row
        return None

    def reprocess_correo_pdfs(self, correo: GmailCorreo) -> list[dict[str, object]]:
        if not correo.tiene_adjunto or not correo.adjunto_ruta:
            return []

        pdf_path = Path(correo.adjunto_ruta)
        if not pdf_path.exists():
            logger.warning("PDF no encontrado en disco correo_id=%s path=%s", correo.id, pdf_path)
            return []

        filename = correo.adjunto_nombre or pdf_path.name
        is_pdf = filename.lower().endswith(".pdf")
        is_txt = filename.lower().endswith(".txt")
        if not is_pdf and not is_txt:
            return []

        mime_type = "application/pdf" if is_pdf else "text/plain"
        attachment = {"filename": filename, "mime_type": mime_type}
        saved_attachment = (filename, str(pdf_path))
        to_audit = self._process_pdf_attachments(correo, [(attachment, saved_attachment)])
        return self._auto_audit_siniestros(to_audit)

    def _reprocess_unlinked_correos(self) -> list[dict[str, object]]:
        owner = self._resolve_owner_email()
        correos = list(
            self.db.scalars(
                select(GmailCorreo).where(
                    GmailCorreo.owner_email == owner,
                    GmailCorreo.tiene_adjunto.is_(True),
                    GmailCorreo.adjunto_ruta.isnot(None),
                )
            ).all()
        )

        audits: list[dict[str, object]] = []
        for correo in correos:
            linked_count = self.db.scalar(
                select(func.count())
                .select_from(Siniestro)
                .where(Siniestro.gmail_correo_id == correo.id)
            )
            if linked_count and linked_count > 0:
                continue
            logger.info("Reprocesando PDF pendiente correo_id=%s asunto=%s", correo.id, correo.asunto)
            audits.extend(self.reprocess_correo_pdfs(correo))
        return audits

    def _process_pdf_attachments(
        self,
        correo: GmailCorreo,
        saved_attachments: list[tuple[dict[str, str], tuple[str, str]]],
    ) -> list[Siniestro]:
        siniestros_creados = 0
        created_entities: list[Siniestro] = []
        entities_to_audit: list[Siniestro] = []

        for attachment, saved_attachment in saved_attachments:
            is_pdf = self._is_pdf_attachment(attachment)
            is_txt = self._is_txt_attachment(attachment)

            if not is_pdf and not is_txt:
                logger.info(
                    "Adjunto ignorado por no ser PDF ni TXT correo_id=%s filename=%s mime_type=%s",
                    correo.id,
                    attachment.get("filename"),
                    attachment.get("mime_type"),
                )
                continue

            _, attachment_path = saved_attachment
            file_path = Path(attachment_path)
            parsed_siniestros = []

            try:
                if is_pdf:
                    parsed_siniestros = self.pdf_parser.parse(file_path)
                elif is_txt:
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                    blocks = self.pdf_parser._split_claim_blocks(text)
                    parsed_siniestros = [
                        self.pdf_parser._parse_block(block, file_path, index + 1)
                        for index, block in enumerate(blocks)
                    ]
            except Exception:
                logger.exception(
                    "Error parseando adjunto para siniestros correo_id=%s file=%s",
                    correo.id,
                    file_path,
                )
                continue

            logger.info(
                "Adjunto parseado correo_id=%s file=%s siniestros_detectados=%s",
                correo.id,
                file_path,
                len(parsed_siniestros),
            )

            for parsed in parsed_siniestros:
                owner = self._resolve_owner_email()
                base_id = parsed.id_siniestro.split("|")[0].strip()
                target_id = parsed.id_siniestro.strip() or base_id

                linked = self._siniestro_already_linked_to_correo(correo.id, base_id)
                if linked is not None:
                    if linked.scoring_payload is None:
                        entities_to_audit.append(linked)
                    continue

                existing = self.db.scalar(
                    select(Siniestro).where(Siniestro.id_siniestro == target_id)
                )
                if existing is not None:
                    if not existing.owner_email:
                        existing.owner_email = owner
                        if existing.gmail_correo_id is None:
                            existing.gmail_correo_id = correo.id
                        self.db.commit()
                        self.db.refresh(existing)
                        logger.info(
                            "Siniestro legacy reclamado por analista id=%s owner=%s",
                            parsed.id_siniestro,
                            owner,
                        )
                        if existing.scoring_payload is None:
                            entities_to_audit.append(existing)
                        continue

                    if existing.owner_email == owner and existing.gmail_correo_id == correo.id:
                        if existing.scoring_payload is None:
                            entities_to_audit.append(existing)
                        continue

                    scoped_id = self._analyst_scoped_id(target_id, owner)
                    existing_clone = self.db.scalar(
                        select(Siniestro).where(Siniestro.id_siniestro == scoped_id)
                    )
                    if existing_clone is not None:
                        if existing_clone.gmail_correo_id is None:
                            existing_clone.gmail_correo_id = correo.id
                            self.db.commit()
                        if existing_clone.scoring_payload is None:
                            entities_to_audit.append(existing_clone)
                        continue

                    target_id = scoped_id

                    logger.info(
                        "Creando siniestro desde correo base=%s target=%s owner=%s correo_id=%s",
                        base_id,
                        target_id,
                        owner,
                        correo.id,
                    )
                    entity = self._build_siniestro_entity(
                        correo.id,
                        parsed,
                        id_siniestro=target_id,
                    )
                    self.db.add(entity)
                    created_entities.append(entity)
                    siniestros_creados += 1
                    continue

                entity = self._build_siniestro_entity(
                    correo.id,
                    parsed,
                    id_siniestro=target_id,
                )
                self.db.add(entity)
                created_entities.append(entity)
                siniestros_creados += 1

        if siniestros_creados:
            try:
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                logger.info("Siniestro duplicado al guardar desde PDF correo_id=%s", correo.id)
                return entities_to_audit
            index_service = EmbeddingIndexService(self.db)
            indexed = 0
            for entity in created_entities:
                if index_service.index_one(entity, commit=False):
                    indexed += 1
            self.db.commit()
            for entity in created_entities:
                self.db.refresh(entity)
            entities_to_audit.extend(created_entities)
            logger.info(
                "Embeddings generados para siniestros correo_id=%s indexed=%s total=%s",
                correo.id,
                indexed,
                siniestros_creados,
            )

        return entities_to_audit

    def _auto_audit_siniestros(self, siniestros: list[Siniestro]) -> list[dict[str, object]]:
        if not siniestros:
            return []

        service = AutoScoringService(self.db)
        audits: list[dict[str, object]] = []
        seen: set[str] = set()

        for siniestro in siniestros:
            if siniestro.id_siniestro in seen:
                continue
            seen.add(siniestro.id_siniestro)
            if siniestro.scoring_payload is not None and not AutoScoringService.payload_needs_reaudit(
                siniestro.scoring_payload
            ):
                continue
            try:
                self.db.refresh(siniestro)
                response = service.audit_and_persist(siniestro)
                audits.append(AutoScoringService.to_audit_summary(response))
            except Exception:
                logger.exception(
                    "Error en auditoría automática id=%s",
                    siniestro.id_siniestro,
                )
        return audits

    def _audit_pending_siniestros(self) -> list[dict[str, object]]:
        owner = self._resolve_owner_email()
        pending = list(
            self.db.scalars(
                siniestro_scope(owner).where(Siniestro.scoring_payload.is_(None))
            ).all()
        )
        return self._auto_audit_siniestros(pending)

    def _is_pdf_attachment(self, attachment: dict[str, str]) -> bool:
        filename = (attachment.get("filename") or "").lower()
        mime_type = (attachment.get("mime_type") or "").lower()
        return filename.endswith(".pdf") or mime_type == "application/pdf"

    def _is_txt_attachment(self, attachment: dict[str, str]) -> bool:
        filename = (attachment.get("filename") or "").lower()
        mime_type = (attachment.get("mime_type") or "").lower()
        return filename.endswith(".txt") or mime_type.startswith("text/")

    def _build_siniestro_entity(
        self,
        correo_id: int,
        parsed: ParsedSiniestroDraft,
        id_siniestro: str | None = None,
    ) -> Siniestro:
        return Siniestro(
            owner_email=self._resolve_owner_email(),
            gmail_correo_id=correo_id,
            id_siniestro=id_siniestro or parsed.id_siniestro,
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

    def _extract_email_address(self, sender_str: str) -> str:
        import re
        match = re.search(r"<([^>]+)>", sender_str)
        if match:
            return match.group(1).strip().lower()
        return sender_str.strip().lower()

    def _send_auto_reply_template(self, correo: GmailCorreo) -> None:
        from pathlib import Path
        try:
            connected = self.get_connected_user()
            connected_email = connected.get("email", "").strip().lower()
        except Exception:
            connected_email = ""

        sender_email = self._extract_email_address(correo.remitente)
        if not sender_email or (connected_email and sender_email == connected_email):
            logger.info("Auto-respuesta omitida: el remitente es el mismo analista conectado (%s)", sender_email)
            return

        normalized_subject = self.client.normalize_text(correo.asunto or "")
        normalized_desc = self.client.normalize_text(correo.descripcion or "")
        combined = f"{normalized_subject} {normalized_desc}"

        keywords = ["SINIESTRO", "RECLAMO", "PLANTILLA", "FORMULARIO", "DECLARACION", "REPORTAR", "ACCIDENTE", "CHOQUE", "ROBO", "AYUDA"]
        if not any(kw in combined for kw in keywords):
            logger.info("Auto-respuesta omitida: el correo no contiene palabras de intención de reporte")
            return

        logger.info("Enviando auto-respuesta con plantilla de siniestro a remitente=%s thread_id=%s", correo.remitente, correo.thread_id)

        template_text = (
            "======================================================================\n"
            "     ASEGURADORA DEL SUR - FORMULARIO DE DECLARACIÓN DE SINIESTRO\n"
            "======================================================================\n\n"
            "SINIESTRO: [Dejar en blanco para auto-generación]\n"
            "NUMERO DE POLIZA: [Escribir el código de póliza, Ej: POL-VEH-2025-9981]\n"
            "ASEGURADO TITULAR: [Escribir Nombre y Apellido del Asegurado]\n"
            "RAMO DEL SEGURO: [Escribir Ramo: Vehículos, Salud, Hogar, Incendios o Vida]\n"
            "COBERTURA: [Escribir tipo de Cobertura contratada, Ej: Cobertura Integral]\n"
            "BENEFICIARIOS DESIGNADOS: [Escribir Nombre del Beneficiario que reclama]\n"
            "SUCURSAL: [Escribir Sucursal: Guayaquil, Quito, Cuenca, Ambato o Manta]\n\n"
            "----------------------------------------------------------------------\n"
            "FECHAS DE CONTROL Y VIGENCIA\n"
            "----------------------------------------------------------------------\n"
            "FECHA INICIO POLIZA: [DD/MM/AAAA - Fecha de inicio de la cobertura]\n"
            "FECHA FIN POLIZA: [DD/MM/AAAA - Fecha de vencimiento de la cobertura]\n\n"
            "FECHA OCURRENCIA: EL DIA [Día en número] DE [Mes en letras, Ej: MAYO] DE [Año en número]\n"
            "FECHA REPORTE: [DD/MM/AAAA - Fecha del reporte]\n\n"
            "----------------------------------------------------------------------\n"
            "ANÁLISIS FINANCIERO Y SINIESTRALIDAD\n"
            "----------------------------------------------------------------------\n"
            "MONTO RECLAMADO: $[Escribir valor numérico con decimales, Ej: 8.400,00]\n"
            "MONTO ESTIMADO: $[Escribir valor estimado de daños, Ej: 8.000,00]\n"
            "MONTO PAGADO: $0,00\n"
            "SINIESTROS ANTERIORES: [Escribir número de reclamos previos, Ej: 0]\n\n"
            "----------------------------------------------------------------------\n"
            "NARRATIVA DE LOS HECHOS\n"
            "----------------------------------------------------------------------\n"
            "[Redacte de forma detallada y cronológica las circunstancias del siniestro,\n"
            "los hechos ocurridos, los daños percibidos y la ubicación. Esta sección será\n"
            "analizada lingüísticamente por la IA de ShieldMind.]\n\n"
            "----------------------------------------------------------------------\n"
            "CHECKLIST DE REQUISITOS Y DOCUMENTOS ENTREGADOS\n"
            "----------------------------------------------------------------------\n"
            "- Póliza Vigente: ENTREGADO\n"
            "- Cédula de Identidad: ENTREGADO\n"
            "- Denuncia Policial de Tránsito: ENTREGADO\n"
            "- Fotos del Siniestro: ENTREGADO\n\n"
            "======================================================================\n"
        )

        html_body = (
            f"<div style='font-family: sans-serif; color: #081f3f; padding: 20px; background-color: #f4f6f9;'>"
            f"  <div style='max-width: 650px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);'>"
            f"    <div style='background-color: #081f3f; padding: 20px; text-align: center; border-bottom: 4px solid #00adef;'>"
            f"      <h2 style='color: #ffffff; margin: 0; font-size: 18px; font-weight: 800; text-transform: uppercase;'>Aseguradora del Sur</h2>"
            f"      <p style='color: #00adef; margin: 4px 0 0 0; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;'>Asistente Virtual Antifraude • ShieldMind AI</p>"
            f"    </div>"
            f"    <div style='padding: 25px;'>"
            f"      <p style='font-size: 13.5px; line-height: 1.5; color: #1e293b;'>Estimado cliente / beneficiario,</p>"
            f"      <p style='font-size: 12.5px; line-height: 1.6; color: #475569;'>"
            f"        Hemos recibido su consulta e intención de declarar o reportar un siniestro. Para brindarle un servicio prioritario de "
            f"        auditoría y agilizar el procesamiento ético de su caso, requerimos que nos devuelva la información del siniestro estructurada."
            f"      </p>"
            f"      <p style='font-size: 12.5px; line-height: 1.6; color: #475569;'>"
            f"        Por favor, <strong>descargue el formato de plantilla oficial adjunto a este correo electrónico</strong>, rellene todos los campos estructurados "
            f"        y <strong>responda directamente a este correo</strong> adjuntando el documento completado."
            f"      </p>"
            f"      <div style='background-color: #f0fdf4; border-left: 4px solid #16a34a; padding: 12px; border-radius: 4px; margin: 20px 0;'>"
            f"        <strong style='font-size: 11px; color: #15803d; text-transform: uppercase; display: block;'>Requisito Indispensable:</strong>"
            f"        <p style='margin: 3px 0 0 0; font-size: 11px; color: #166534;'>"
            f"          Recuerde adjuntar las evidencias físicas necesarias (Cédula de Identidad, Póliza vigente, Denuncia policial y Fotos del siniestro)."
            f"        </p>"
            f"      </div>"
            f"      <p style='font-size: 11px; color: #64748b; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 15px; margin-top: 25px;'>"
            f"        Este es un correo automático generado por el motor de triaje virtual de Aseguradora del Sur.<br/>"
            f"        Complete los campos del documento adjunto sin modificar los títulos para asegurar su procesamiento inmediato."
            f"      </p>"
            f"    </div>"
            f"  </div>"
            f"</div>"
        )

        subject = f"Re: {correo.asunto or 'Solicitud de Reporte de Siniestro'}"
        
        templates_dir = Path(self.settings.gmail_download_dir).parent / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)

        docx_path = templates_dir / "plantilla_siniestro.docx"
        pdf_path = templates_dir / "plantilla_siniestro.pdf"

        attachments = []
        body_text_intro = ""

        if docx_path.is_file():
            logger.info("Plantilla de Word (.docx) encontrada para auto-respuesta: %s", docx_path)
            attachments.append(
                (
                    "plantilla_siniestro.docx",
                    docx_path.read_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            )
            body_text_intro = (
                "Hemos recibido su solicitud de siniestro. Por favor, descargue la plantilla Word adjunta "
                "('plantilla_siniestro.docx'), complete sus campos de información, guárdela y responda a este "
                "correo electrónico adjuntando el archivo completado."
            )
        elif pdf_path.is_file():
            logger.info("Plantilla PDF (.pdf) encontrada para auto-respuesta: %s", pdf_path)
            attachments.append(
                (
                    "plantilla_siniestro.pdf",
                    pdf_path.read_bytes(),
                    "application/pdf",
                )
            )
            body_text_intro = (
                "Hemos recibido su solicitud de siniestro. Por favor, descargue la plantilla PDF adjunta "
                "('plantilla_siniestro.pdf'), rellene los datos requeridos y responda a este correo electrónico "
                "con el archivo completado adjunto."
            )
        else:
            logger.warning("No se encontró plantilla Word (.docx) ni PDF (.pdf) en %s. Usando fallback de texto plano.", templates_dir)
            attachments.append(
                (
                    "plantilla_siniestro.txt",
                    template_text.encode("utf-8"),
                    "text/plain",
                )
            )
            body_text_intro = (
                "Hemos recibido su solicitud de siniestro. Por favor, descargue la plantilla adjunta "
                "'plantilla_siniestro.txt', rellene sus datos y responda a este correo adjuntándolo rellenado."
            )

        self.client.send_email(
            to=correo.remitente,
            subject=subject,
            body_text=f"Estimado cliente,\n\n{body_text_intro}",
            html_body=html_body,
            thread_id=correo.gmail_message_id,
            attachments=attachments,
        )
