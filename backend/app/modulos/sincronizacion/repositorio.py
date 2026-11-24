"""Repositorio SQLAlchemy del módulo de sincronización."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.modulos.sincronizacion.modelos import OperacionCampo


def obtener(db: Session, operacion_uuid: UUID) -> OperacionCampo | None:
    return db.get(OperacionCampo, operacion_uuid)


def guardar(db: Session, operacion: OperacionCampo) -> None:
    db.add(operacion)


def listar(
    db: Session, sede_id: int, *, estado: str | None, page: int, size: int
) -> tuple[list[dict[str, Any]], int]:
    filtros: list[Any] = [OperacionCampo.sede_id == sede_id]
    if estado is not None:
        filtros.append(OperacionCampo.estado == estado)
    contar = select(func.count()).select_from(OperacionCampo).where(*filtros)
    total = int(db.execute(contar).scalar_one())
    filas = db.execute(
        text(
            """
            SELECT op.uuid, op.tipo, op.orden_id, o.numero AS orden_numero, op.estado, op.motivo,
                   op.intentos, op.creada_en, op.recibida_en, op.actualizada_en,
                   op.usuario_id, u.nombre_completo AS usuario_nombre
            FROM operacion_campo op
            JOIN usuario u ON u.id = op.usuario_id
            LEFT JOIN orden_trabajo o ON o.id = op.orden_id
            WHERE op.sede_id = :sede_id
              AND (CAST(:estado AS text) IS NULL OR op.estado = CAST(:estado AS text))
            ORDER BY op.actualizada_en DESC
            LIMIT :limite OFFSET :desplazamiento
            """
        ),
        {
            "sede_id": sede_id,
            "estado": estado,
            "limite": size,
            "desplazamiento": (page - 1) * size,
        },
    ).mappings()
    return [dict(f) for f in filas], total
