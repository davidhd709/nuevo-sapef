"""Repositorio de archivos y evidencias + almacenamiento físico local intercambiable."""

import os
import tempfile
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modulos.archivos.modelos import Archivo, Evidencia


class AlmacenArchivos(Protocol):
    def guardar(self, ruta_relativa: str, contenido: bytes) -> None: ...
    def leer(self, ruta_relativa: str) -> bytes: ...
    def existe(self, ruta_relativa: str) -> bool: ...
    def eliminar(self, ruta_relativa: str) -> None: ...


class AlmacenLocal:
    """Implementación en disco local bajo SAPEF_ARCHIVOS_DIR con escritura atómica."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz.resolve()

    def _resolver_seguro(self, ruta_relativa: str) -> Path:
        if not ruta_relativa or ruta_relativa.startswith(("/", "\\")):
            raise ValueError("Ruta relativa inválida.")
        destino = (self.raiz / ruta_relativa).resolve()
        if not destino.is_relative_to(self.raiz) or destino == self.raiz:
            raise ValueError("Intento de path traversal detectado.")
        return destino

    def guardar(self, ruta_relativa: str, contenido: bytes) -> None:
        destino = self._resolver_seguro(ruta_relativa)
        destino.parent.mkdir(parents=True, exist_ok=True)
        if destino.exists():
            return
        fd, tmp_nombre = tempfile.mkstemp(prefix=".tmp_", dir=str(destino.parent))
        tmp_path = Path(tmp_nombre)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(contenido)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, destino)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def leer(self, ruta_relativa: str) -> bytes:
        destino = self._resolver_seguro(ruta_relativa)
        return destino.read_bytes()

    def existe(self, ruta_relativa: str) -> bool:
        destino = self._resolver_seguro(ruta_relativa)
        return destino.is_file()

    def eliminar(self, ruta_relativa: str) -> None:
        destino = self._resolver_seguro(ruta_relativa)
        destino.unlink(missing_ok=True)


def obtener_por_id(db: Session, archivo_id: UUID) -> Archivo | None:
    return db.execute(select(Archivo).where(Archivo.id == archivo_id)).scalar_one_or_none()


def obtener_por_idempotency_key(
    db: Session, sede_id: int, idempotency_key: str
) -> Archivo | None:
    return db.execute(
        select(Archivo).where(
            Archivo.sede_id == sede_id,
            Archivo.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()


def crear_archivo(db: Session, archivo: Archivo) -> Archivo:
    db.add(archivo)
    db.flush()
    return archivo


def listar_evidencias(
    db: Session, sede_id: int, entidad: str, entidad_id: str
) -> list[Evidencia]:
    return list(
        db.execute(
            select(Evidencia)
            .where(
                Evidencia.sede_id == sede_id,
                Evidencia.entidad == entidad,
                Evidencia.entidad_id == entidad_id,
            )
            .order_by(Evidencia.id)
        ).scalars()
    )


def crear_evidencia(db: Session, evidencia: Evidencia) -> Evidencia:
    db.add(evidencia)
    db.flush()
    return evidencia
