from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

import fitz
from pypdf import PdfReader

try:
    from rapidocr_onnxruntime import RapidOCR
except Exception:  # pragma: no cover - optional dependency fallback
    RapidOCR = None

logger = logging.getLogger(__name__)


@dataclass
class ParsedSiniestroDraft:
    id_siniestro: str
    id_poliza: str
    id_asegurado: str
    ramo: str
    cobertura: str
    fecha_ocurrencia: date
    fecha_reporte: date
    monto_reclamado: Decimal
    monto_estimado: Decimal
    monto_pagado: Decimal
    estado: str
    sucursal: str
    descripcion: str
    documentos_completos: bool
    beneficiario: str
    dias_desde_inicio_poliza: int
    dias_desde_fin_poliza: int
    dias_entre_ocurrencia_reporte: int
    historial_siniestros_asegurado: int
    etiqueta_fraude_simulada: bool


class SiniestroPdfParser:
    def __init__(self, enable_ocr: bool = True):
        self.enable_ocr = enable_ocr and RapidOCR is not None
        self.ocr = RapidOCR() if self.enable_ocr else None

    def parse(self, pdf_path: Path) -> list[ParsedSiniestroDraft]:
        logger.info("Leyendo PDF para extraccion path=%s enable_ocr=%s", pdf_path, self.enable_ocr)
        text = self._extract_text(pdf_path)
        if not text.strip():
            raise ValueError(f"No se pudo extraer texto del PDF: {pdf_path}")

        blocks = self._split_claim_blocks(text)
        logger.info("PDF separado en %s bloque(s) de siniestro path=%s", len(blocks), pdf_path)
        return [self._parse_block(block, pdf_path, index + 1) for index, block in enumerate(blocks)]

    def _extract_text(self, pdf_path: Path) -> str:
        text_parts: list[str] = []

        try:
            reader = PdfReader(str(pdf_path))
            for page in reader.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_parts.append(page_text)
        except Exception:
            logger.exception("Fallo la extraccion nativa de texto del PDF path=%s", pdf_path)

        if text_parts and len("\n".join(text_parts).strip()) >= 80:
            return "\n".join(text_parts)

        if not self.enable_ocr:
            logger.warning("PDF sin texto util y OCR deshabilitado path=%s", pdf_path)
            return "\n".join(text_parts)

        ocr_parts: list[str] = []
        doc = fitz.open(str(pdf_path))
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            result = self.ocr(pix.tobytes("png")) if self.ocr else None
            if not result:
                continue

            ocr_result = result[0] if isinstance(result, tuple) else result
            if not ocr_result:
                continue

            page_lines = [item[1] for item in ocr_result if len(item) > 1 and item[1]]
            if page_lines:
                ocr_parts.append("\n".join(page_lines))

        combined = "\n".join([part for part in text_parts + ocr_parts if part.strip()])
        logger.info("Extraccion OCR finalizada path=%s chars=%s", pdf_path, len(combined))
        return combined

    def _split_claim_blocks(self, text: str) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        start_indexes: list[int] = []

        for index, line in enumerate(lines):
            normalized = self._compact(line)
            if normalized.startswith("SINIESTRO:"):
                start_indexes.append(index)

        if not start_indexes:
            return [text]

        blocks: list[str] = []
        for position, start_index in enumerate(start_indexes):
            end_index = start_indexes[position + 1] if position + 1 < len(start_indexes) else len(lines)
            blocks.append("\n".join(lines[start_index:end_index]))

        return blocks

    def _parse_block(self, text: str, pdf_path: Path, sequence: int) -> ParsedSiniestroDraft:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        report_date = self._parse_report_date(text) or date.today()
        occurrence_date = self._parse_occurrence_date(text, report_date) or report_date
        score = self._parse_score(text)

        siniestro_id = self._extract_value(lines, ["SINIESTRO"], same_line_prefixes=["SINIESTRO:"])
        if not siniestro_id:
            siniestro_id = self._fallback_id(text, pdf_path, sequence, prefix="SIN")
            logger.warning("No se encontro id_siniestro, se genero uno de respaldo id=%s pdf=%s", siniestro_id, pdf_path)

        policy_id = self._extract_value(lines, ["NUMERO DE POLIZA", "POLIZA", "POLIZA NUMERO"])
        if not policy_id:
            policy_id = self._fallback_id(text, pdf_path, sequence, prefix="POL")
            logger.warning("No se encontro id_poliza, se genero uno de respaldo id=%s pdf=%s", policy_id, pdf_path)

        insured_name = self._extract_value(lines, ["ASEGURADO TITULAR", "ASEGURADO", "TITULAR"]) or "Desconocido"
        insured_id = self._anonymous_identifier(insured_name)

        ramo = self._extract_value(lines, ["RAMO DEL SEGURO", "RAMO"]) or "No especificado"
        cobertura = self._extract_value(lines, ["COBERTURA", "TIPO DE COBERTURA"]) or "No especificada"
        beneficiario = self._extract_value(lines, ["BENEFICIARIOS DESIGNADOS", "BENEFICIARIO", "BENEFICIARIOS"]) or insured_name
        beneficiario = self._clean_name(beneficiario)

        narrative = self._extract_section(
            lines,
            ["NARRATIVA DE LOS HECHOS", "NARRATIVADELOSHECHOS", "DECLARACION ORIGINAL"],
            ["CHECKLIST DE REQUISITOS Y DOCUMENTOS ENTREGADOS", "CHECKLISTDEREQUISITOSYDOCUMENTOSENTREGADOS"],
        )
        descripcion = narrative.strip() or text.strip()[:4000]

        amount_reclamado = self._parse_money(text, ["MONTO RECLAMADO", "VALOR SOLICITADO", "RECLAMADO"])
        amount_estimado = self._parse_money(text, ["MONTO ESTIMADO", "VALOR ESTIMADO", "ESTIMADO"])
        amount_pagado = self._parse_money(text, ["MONTO PAGADO", "VALOR PAGADO", "PAGADO"])

        documentos_completos = self._parse_documents_complete(text)
        historial_siniestros = self._parse_historial_siniestros(text)
        dias_entre = max((report_date - occurrence_date).days, 0)
        dias_inicio = self._parse_days_from_policy_dates(text, report_date, occurrence_date, ["FECHA INICIO POLIZA", "INICIO POLIZA", "FECHA DE INICIO"])
        dias_fin = self._parse_days_from_policy_dates(text, report_date, occurrence_date, ["FECHA FIN POLIZA", "FIN POLIZA", "FECHA DE FIN"])

        etiqueta_fraude = score >= 70 or self._contains_any(text, ["RIESGO CRITICO DE FRAUDE", "RIESGO CRÍTICO DE FRAUDE"])
        estado = "Pendiente de revision"
        sucursal = self._extract_value(lines, ["SUCURSAL", "OFICINA", "AGENCIA"]) or "No especificada"

        logger.info(
            "Bloque parseado pdf=%s sequence=%s siniestro=%s poliza=%s score=%s docs_ok=%s",
            pdf_path,
            sequence,
            siniestro_id,
            policy_id,
            score,
            documentos_completos,
        )

        return ParsedSiniestroDraft(
            id_siniestro=siniestro_id,
            id_poliza=policy_id,
            id_asegurado=insured_id,
            ramo=ramo,
            cobertura=cobertura,
            fecha_ocurrencia=occurrence_date,
            fecha_reporte=report_date,
            monto_reclamado=amount_reclamado,
            monto_estimado=amount_estimado,
            monto_pagado=amount_pagado,
            estado=estado,
            sucursal=sucursal,
            descripcion=descripcion,
            documentos_completos=documentos_completos,
            beneficiario=beneficiario,
            dias_desde_inicio_poliza=dias_inicio,
            dias_desde_fin_poliza=dias_fin,
            dias_entre_ocurrencia_reporte=dias_entre,
            historial_siniestros_asegurado=historial_siniestros,
            etiqueta_fraude_simulada=etiqueta_fraude,
        )

    def _extract_value(self, lines: list[str], labels: list[str], same_line_prefixes: list[str] | None = None) -> str | None:
        same_line_prefixes = same_line_prefixes or []
        compact_labels = [self._compact(label) for label in labels]
        compact_prefixes = [self._compact(prefix) for prefix in same_line_prefixes]

        for index, line in enumerate(lines):
            compact_line = self._compact(line)

            for prefix in compact_prefixes:
                if compact_line.startswith(prefix):
                    value = line.split(":", 1)[1].strip() if ":" in line else line[len(prefix):].strip()
                    if value:
                        return value

            for label in compact_labels:
                if label in compact_line:
                    value = self._value_from_line(line, label)
                    if value:
                        return value
                    next_value = self._next_non_label_line(lines, index + 1)
                    if next_value:
                        return next_value

        return None

    def _value_from_line(self, line: str, label_compact: str) -> str | None:
        compact_line = self._compact(line)
        if label_compact not in compact_line:
            return None

        if ":" in line:
            after_colon = line.split(":", 1)[1].strip()
            if after_colon:
                return after_colon

        cleaned = re.sub(re.escape(label_compact), "", compact_line, flags=re.IGNORECASE).strip()
        if cleaned:
            return self._restore_readable(cleaned)
        return None

    def _next_non_label_line(self, lines: list[str], start_index: int) -> str | None:
        for candidate in lines[start_index:]:
            if not candidate.strip():
                continue
            compact_candidate = self._compact(candidate)
            if compact_candidate.startswith("HTTP") or compact_candidate.startswith("LOCALHOST"):
                continue
            if len(compact_candidate) <= 4 and compact_candidate.isdigit():
                continue
            return candidate.strip()
        return None

    def _extract_section(self, lines: list[str], start_labels: list[str], end_labels: list[str]) -> str:
        start_index = None
        for index, line in enumerate(lines):
            compact_line = self._compact(line)
            if any(self._compact(label) in compact_line for label in start_labels):
                start_index = index + 1
                break

        if start_index is None:
            return ""

        section_lines: list[str] = []
        for line in lines[start_index:]:
            compact_line = self._compact(line)
            if any(self._compact(label) in compact_line for label in end_labels):
                break
            if line.strip():
                section_lines.append(line.strip())

        return "\n".join(section_lines)

    def _parse_report_date(self, text: str) -> date | None:
        normalized = self._normalize(text)
        for match in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", normalized):
            day, month, year = match.groups()
            return date(self._normalize_year(year), int(month), int(day))

        month_match = re.search(r"\b(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚÑ]+)\s*,?\s*(\d{2,4})?\b", normalized)
        if month_match:
            day, month_name, year = month_match.groups()
            month = self._month_number(month_name)
            if month:
                return date(self._normalize_year(year or str(datetime.now().year)), month, int(day))
        return None

    def _parse_occurrence_date(self, text: str, report_date: date) -> date | None:
        normalized = self._normalize(text)
        match = re.search(r"\bEL DIA\s+(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚÑ]+)(?:\s+DE\s+(\d{2,4}))?\b", normalized)
        if not match:
            match = re.search(r"\bDIA\s+(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚÑ]+)(?:\s+DE\s+(\d{2,4}))?\b", normalized)
        if not match:
            return None
        day, month_name, year = match.groups()
        month = self._month_number(month_name)
        if not month:
            return None
        return date(self._normalize_year(year or str(report_date.year)), month, int(day))

    def _parse_score(self, text: str) -> int:
        normalized = self._normalize(text)
        match = re.search(r"\bSCORE\s+(\d{1,3})\b", normalized)
        if match:
            return int(match.group(1))
        return 0

    def _parse_documents_complete(self, text: str) -> bool:
        normalized = self._normalize(text)
        if any(keyword in normalized for keyword in ["FALTANTE", "ILEGIBLE", "NO ENTREGADO", "PENDIENTE"]):
            return False
        if "ENTREGADO" in normalized:
            return True
        return False

    def _parse_historial_siniestros(self, text: str) -> int:
        normalized = self._normalize(text)
        match = re.search(r"(\d+)\s+SINIESTROS?\s+REPORTADOS\s+EN\s+LOS\s+ULTIMOS\s+12\s+MESES", normalized)
        if match:
            return int(match.group(1))
        match = re.search(r"SINIESTROS?\s+ANTERIORES\s*(\d+)", normalized)
        if match:
            return int(match.group(1))
        return 0

    def _parse_money(self, text: str, labels: list[str]) -> Decimal:
        value = self._extract_value_from_money_labels(text, labels)
        if not value:
            return Decimal("0")
        normalized = value.replace("$", "").replace(".", "").replace(",", ".")
        try:
            return Decimal(normalized)
        except InvalidOperation:
            logger.warning("No se pudo convertir monto value=%s", value)
            return Decimal("0")

    def _extract_value_from_money_labels(self, text: str, labels: list[str]) -> str | None:
        normalized = self._normalize(text)
        for label in labels:
            compact_label = self._compact(label)
            pattern = rf"{re.escape(compact_label)}\s*[:\-]?\s*([\$\d\.,]+)"
            match = re.search(pattern, self._compact(normalized))
            if match:
                return match.group(1)
        return None

    def _parse_days_from_policy_dates(self, text: str, report_date: date, occurrence_date: date, labels: list[str]) -> int:
        # Las fechas de póliza no están garantizadas en este documento; si no aparecen, dejamos 0.
        # Si más adelante el PDF las incluye, este parser ya queda preparado.
        value = self._extract_value([line.strip() for line in text.splitlines() if line.strip()], labels)
        if value:
            parsed = self._parse_any_date(value, default_year=report_date.year)
            if parsed:
                return max((occurrence_date - parsed).days, 0)
        return 0

    def _parse_any_date(self, value: str, default_year: int | None = None) -> date | None:
        normalized = self._normalize(value)
        numeric = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", normalized)
        if numeric:
            day, month, year = numeric.groups()
            return date(self._normalize_year(year), int(month), int(day))

        month_match = re.search(r"\b(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚÑ]+)\s*,?\s*(\d{2,4})?\b", normalized)
        if month_match:
            day, month_name, year = month_match.groups()
            month = self._month_number(month_name)
            if month:
                return date(self._normalize_year(year or str(default_year or datetime.now().year)), month, int(day))
        return None

    def _anonymous_identifier(self, value: str) -> str:
        normalized = self._normalize(value)
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12].upper()
        return f"ASEG-{digest}"

    def _fallback_id(self, text: str, pdf_path: Path, sequence: int, prefix: str) -> str:
        source = f"{pdf_path.name}:{sequence}:{self._normalize(text)}"
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12].upper()
        return f"{prefix}-{digest}"

    def _clean_name(self, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned.replace("(Titular)", "").strip()

    def _month_number(self, value: str) -> int | None:
        month_map = {
            "ENERO": 1,
            "FEBRERO": 2,
            "MARZO": 3,
            "ABRIL": 4,
            "MAYO": 5,
            "JUNIO": 6,
            "JULIO": 7,
            "AGOSTO": 8,
            "SEPTIEMBRE": 9,
            "SETIEMBRE": 9,
            "OCTUBRE": 10,
            "NOVIEMBRE": 11,
            "DICIEMBRE": 12,
        }
        return month_map.get(self._normalize(value))

    def _normalize_year(self, year: str) -> int:
        year_int = int(year)
        if year_int < 100:
            return 2000 + year_int
        return year_int

    def _normalize(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        stripped = "".join(character for character in normalized if not unicodedata.combining(character))
        return re.sub(r"\s+", " ", stripped).upper().strip()

    def _compact(self, value: str) -> str:
        return re.sub(r"[^A-Z0-9:/.-]", "", self._normalize(value))

    def _contains_any(self, text: str, needles: Iterable[str]) -> bool:
        normalized = self._normalize(text)
        return any(self._normalize(needle) in normalized for needle in needles)

    def _restore_readable(self, value: str) -> str:
        return value.replace("/", "/").strip()
