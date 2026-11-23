"""Tareas en segundo plano de seguridad (Procrastinate, solo argumentos primitivos)."""

from app.core.tareas import app_tareas
from app.modulos.seguridad.servicio import procesar_envio_correo_recuperacion


@app_tareas.task(name="seguridad.enviar_correo_recuperacion")
def enviar_correo_recuperacion(usuario_id: int, token_id: str) -> None:
    """Despacha la recuperación usando exclusivamente IDs (nunca PII ni tokens en la cola)."""
    procesar_envio_correo_recuperacion(usuario_id=usuario_id, token_id=token_id)
