"""Reglas puras de dominio del módulo de seguridad (sin BD, HTTP ni cola)."""

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

CAMPOS_SENSIBLES_AUDITORIA = frozenset(
    {
        "hash_clave",
        "clave",
        "clave_actual",
        "clave_nueva",
        "token",
        "hash_token",
        "hash_token_renovacion",
        "token_cifrado_envio",
        "secreto",
    }
)


class ErrorDominioSeguridad(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class SedeEvaluacion:
    id: int
    codigo: str
    nombre: str
    activa: bool


def normalizar_identificador(valor: str) -> str:
    return valor.strip().lower()


def hash_sha256_hex(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def validar_fortaleza_clave(clave: str, nombre_usuario: str | None = None) -> None:
    if len(clave) < 8 or len(clave) > 128:
        raise ErrorDominioSeguridad(
            422, "La contraseña debe tener entre 8 y 128 caracteres."
        )
    tiene_mayus = any("A" <= c <= "Z" for c in clave)
    tiene_minus = any("a" <= c <= "z" for c in clave)
    tiene_digito = any("0" <= c <= "9" for c in clave)
    if not (tiene_mayus and tiene_minus and tiene_digito):
        raise ErrorDominioSeguridad(
            422,
            "La contraseña debe incluir al menos una letra mayúscula, una minúscula y un dígito.",
        )
    if nombre_usuario:
        usuario_norm = normalizar_identificador(nombre_usuario)
        if usuario_norm and usuario_norm in clave.lower():
            raise ErrorDominioSeguridad(
                422, "La contraseña no puede contener el nombre de usuario."
            )


def evaluar_bloqueo(bloqueado_hasta: datetime | None, ahora: datetime) -> bool:
    return bloqueado_hasta is not None and bloqueado_hasta > ahora


def calcular_estado_fallo_login(
    intentos_actuales: int,
    max_intentos: int,
    bloqueo_minutos: int,
    ahora: datetime,
) -> tuple[int, datetime | None]:
    nuevos_intentos = intentos_actuales + 1
    if nuevos_intentos >= max_intentos:
        return nuevos_intentos, ahora + timedelta(minutes=bloqueo_minutos)
    return nuevos_intentos, None


def evaluar_acceso_sede(
    sede_codigo_header: str | None,
    sede_encontrada: SedeEvaluacion | None,
    sedes_asignadas_ids: set[int],
) -> SedeEvaluacion:
    if sede_codigo_header is None or not sede_codigo_header.strip():
        raise ErrorDominioSeguridad(400, "La cabecera X-Sede es obligatoria.")
    if sede_encontrada is None or not sede_encontrada.activa:
        raise ErrorDominioSeguridad(403, "No tiene acceso a la sede solicitada.")
    if sede_encontrada.id not in sedes_asignadas_ids:
        raise ErrorDominioSeguridad(403, "No tiene acceso a la sede solicitada.")
    return sede_encontrada


def usuario_tiene_permiso(permisos_usuario: set[str], permiso_requerido: str) -> bool:
    return permiso_requerido in permisos_usuario


def usuario_tiene_algun_permiso(
    permisos_usuario: set[str], permisos_requeridos: tuple[str, ...]
) -> bool:
    return any(p in permisos_usuario for p in permisos_requeridos)


def filtrar_sedes_consolidado(
    sedes_asignadas_ids: list[int], permisos_usuario: set[str]
) -> list[int]:
    if "tablero.consolidado.ver" not in permisos_usuario:
        raise ErrorDominioSeguridad(
            403, "No tiene permiso para consultar el consolidado multi-sede."
        )
    return list(sedes_asignadas_ids)


def sanitizar_datos_auditoria(datos: Any) -> Any:
    if isinstance(datos, dict):
        resultado: dict[str, Any] = {}
        for clave, valor in datos.items():
            if str(clave).lower() in CAMPOS_SENSIBLES_AUDITORIA:
                continue
            resultado[clave] = sanitizar_datos_auditoria(valor)
        return resultado
    if isinstance(datos, list):
        return [sanitizar_datos_auditoria(item) for item in datos]
    return datos


def construir_diff_auditoria(
    antes: dict[str, Any] | None, despues: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    antes_limpio = sanitizar_datos_auditoria(antes) if antes is not None else None
    despues_limpio = sanitizar_datos_auditoria(despues) if despues is not None else None
    return antes_limpio, despues_limpio


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(texto: str) -> bytes:
    relleno = "=" * (-len(texto) % 4)
    return base64.urlsafe_b64decode((texto + relleno).encode("ascii"))


def firmar_token_acceso(payload: dict[str, Any], secreto: str) -> str:
    cabecera = _b64url_encode(
        json.dumps({"alg": "HS256", "typ": "SAPEF"}, separators=(",", ":")).encode("utf-8")
    )
    cuerpo = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    mensaje = f"{cabecera}.{cuerpo}".encode("ascii")
    firma = hmac.new(secreto.encode("utf-8"), mensaje, hashlib.sha256).digest()
    return f"{cabecera}.{cuerpo}.{_b64url_encode(firma)}"


def verificar_token_acceso(token: str, secreto: str, ahora_ts: int) -> dict[str, Any] | None:
    partes = token.split(".")
    if len(partes) != 3:
        return None
    cabecera_b64, cuerpo_b64, firma_b64 = partes
    try:
        mensaje = f"{cabecera_b64}.{cuerpo_b64}".encode("ascii")
        firma_esperada = hmac.new(secreto.encode("utf-8"), mensaje, hashlib.sha256).digest()
        firma_recibida = _b64url_decode(firma_b64)
        if not hmac.compare_digest(firma_esperada, firma_recibida):
            return None
        payload = json.loads(_b64url_decode(cuerpo_b64).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp <= ahora_ts:
        return None
    return payload


def _derivar_flujo(clave_raiz: bytes, nonce: bytes, longitud: int) -> bytes:
    bloques = bytearray()
    contador = 0
    while len(bloques) < longitud:
        bloque = hmac.new(
            clave_raiz,
            nonce + contador.to_bytes(4, "big"),
            hashlib.sha256,
        ).digest()
        bloques.extend(bloque)
        contador += 1
    return bytes(bloques[:longitud])


def cifrar_token_envio(raw_token: str, secreto: str) -> str:
    """Cifrado autenticado sin dependencias externas para persistencia temporal en worker."""
    clave_enc = hmac.new(secreto.encode("utf-8"), b"sapef-token-enc", hashlib.sha256).digest()
    clave_mac = hmac.new(secreto.encode("utf-8"), b"sapef-token-mac", hashlib.sha256).digest()
    nonce = secrets.token_bytes(16)
    plano = raw_token.encode("utf-8")
    flujo = _derivar_flujo(clave_enc, nonce, len(plano))
    cifrado = bytes(a ^ b for a, b in zip(plano, flujo, strict=True))
    tag = hmac.new(clave_mac, nonce + cifrado, hashlib.sha256).digest()
    return _b64url_encode(nonce + tag + cifrado)


def descifrar_token_envio(token_cifrado: str, secreto: str) -> str | None:
    try:
        datos = _b64url_decode(token_cifrado)
        if len(datos) < 48:
            return None
        nonce, tag, cifrado = datos[:16], datos[16:48], datos[48:]
        clave_enc = hmac.new(secreto.encode("utf-8"), b"sapef-token-enc", hashlib.sha256).digest()
        clave_mac = hmac.new(secreto.encode("utf-8"), b"sapef-token-mac", hashlib.sha256).digest()
        tag_esperado = hmac.new(clave_mac, nonce + cifrado, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, tag_esperado):
            return None
        flujo = _derivar_flujo(clave_enc, nonce, len(cifrado))
        plano = bytes(a ^ b for a, b in zip(cifrado, flujo, strict=True))
        return plano.decode("utf-8")
    except Exception:  # noqa: BLE001
        return None
