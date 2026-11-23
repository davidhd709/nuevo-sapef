"""Proceso worker: ejecuta las tareas de la cola. Mismo código e imagen que la API.

Uso:  python -m app.worker
"""

import asyncio
import logging

from app.core.config import obtener_configuracion
from app.core.logs import configurar_logs
from app.core.tareas import app_tareas


async def principal() -> None:
    configurar_logs(obtener_configuracion().log_nivel)
    logging.getLogger("sapef.worker").info("worker iniciado")
    async with app_tareas.open_async():
        await app_tareas.run_worker_async(install_signal_handlers=True)


if __name__ == "__main__":
    asyncio.run(principal())
