"""Respuesta paginada común (los módulos nuevos la usan en lugar de definir la suya)."""

from pydantic import BaseModel


class Pagina[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int


class TareaEncolada(BaseModel):
    """Respuesta 202 de un trabajo en segundo plano (`tareaId` es el id del job de la cola)."""

    id: int
    tareaId: int  # noqa: N815 - nombre del contrato público
    estado: str = "encolada"
    cargueId: int | None = None  # noqa: N815
