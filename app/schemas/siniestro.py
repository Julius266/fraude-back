from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SiniestroBase(BaseModel):
    id_siniestro: str = Field(..., max_length=50)
    id_poliza: str = Field(..., max_length=50)
    id_asegurado: str = Field(..., max_length=50)
    ramo: str = Field(..., max_length=50)
    cobertura: str = Field(..., max_length=100)
    fecha_ocurrencia: date
    fecha_reporte: date
    monto_reclamado: Decimal = Field(..., max_digits=18, decimal_places=2)
    monto_estimado: Decimal = Field(..., max_digits=18, decimal_places=2)
    monto_pagado: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=2)
    estado: str = Field(..., max_length=50)
    sucursal: str = Field(..., max_length=100)
    descripcion: str
    documentos_completos: bool = False
    beneficiario: str = Field(..., max_length=100)
    dias_desde_inicio_poliza: int
    dias_desde_fin_poliza: int
    dias_entre_ocurrencia_reporte: int
    historial_siniestros_asegurado: int = 0
    etiqueta_fraude_simulada: bool = False


class SiniestroCreate(SiniestroBase):
    pass


class SiniestroRead(SiniestroBase):
    model_config = ConfigDict(from_attributes=True)

    gmail_correo_id: int | None = None
