"""Envío de correo por SMTP (credenciales solo en variables de entorno).

Lo llaman las tareas del worker, nunca una petición HTTP: un SMTP lento no debe frenar la API.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import obtener_configuracion

log = logging.getLogger("sapef.correo")


def enviar_correo(destinatario: str, asunto: str, cuerpo_html: str) -> bool:
    """Envía un correo HTML. Devuelve False (y no falla) si no hay SMTP configurado.

    El destinatario no se escribe en el log: es un dato personal.
    """
    config = obtener_configuracion()
    if not config.smtp_host:
        log.info("SMTP no configurado: correo omitido")
        return False
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = config.smtp_remitente
    mensaje["To"] = destinatario
    mensaje.set_content("Este mensaje requiere un cliente de correo con soporte HTML.")
    mensaje.add_alternative(cuerpo_html, subtype="html")
    with smtplib.SMTP(config.smtp_host, config.smtp_puerto, timeout=10) as smtp:
        if config.smtp_tls:
            smtp.starttls()
        if config.smtp_usuario and config.smtp_clave:
            smtp.login(config.smtp_usuario, config.smtp_clave.get_secret_value())
        smtp.send_message(mensaje)
    return True
