"""Logs estructurados en JSON, con el identificador de la petición, usuario y sede."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

id_peticion: ContextVar[str | None] = ContextVar("id_peticion", default=None)
usuario_log: ContextVar[str | None] = ContextVar("usuario_log", default=None)
sede_log: ContextVar[str | None] = ContextVar("sede_log", default=None)


class FormatoJson(logging.Formatter):
    def format(self, registro: logging.LogRecord) -> str:
        datos = {
            "fecha": datetime.fromtimestamp(registro.created, UTC).isoformat(),
            "nivel": registro.levelname,
            "logger": registro.name,
            "mensaje": registro.getMessage(),
        }
        if (rid := id_peticion.get()) is not None:
            datos["id_peticion"] = rid
        if (usuario := usuario_log.get()) is not None:
            datos["usuario"] = usuario
        if (sede := sede_log.get()) is not None:
            datos["sede"] = sede
        for campo in ("metodo", "ruta", "estado", "duracion_ms"):
            if hasattr(registro, campo):
                datos[campo] = getattr(registro, campo)
        if registro.exc_info:
            datos["excepcion"] = self.formatException(registro.exc_info)
        return json.dumps(datos, ensure_ascii=False)


def configurar_logs(nivel: str) -> None:
    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(FormatoJson())
    raiz = logging.getLogger()
    raiz.handlers = [manejador]
    raiz.setLevel(nivel)
    # Los logs de acceso de uvicorn se reemplazan por el middleware de la app.
    logging.getLogger("uvicorn.access").disabled = True
