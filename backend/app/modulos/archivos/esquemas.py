"""Esquemas Pydantic v2 (DTOs) del módulo de archivos y evidencias."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

CategoriaArchivo = Literal["evidencia", "adjunto", "cargue"]


class ArchivoSalida(BaseModel):
    id: UUID
    sede_id: int
    nombre_original: str
    tipo_mime: str
    tamano: int
    sha256: str
    creado_en: datetime


class EvidenciaSalida(BaseModel):
    id: int
    sede_id: int
    entidad: str
    entidad_id: str
    tipo: str
    archivo_id: UUID
    latitud: float | None
    longitud: float | None
    capturada_en: datetime | None
    creado_en: datetime
