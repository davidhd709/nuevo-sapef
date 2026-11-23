"""Reglas puras de dominio para validación de archivos (magic bytes, límites, nombres)."""

import hashlib
import io
import re
import zipfile
from datetime import datetime
from urllib.parse import quote

TAMANO_BLOQUE_LECTURA = 1_048_576  # 1 MiB

MIMES_PERMITIDOS_POR_CATEGORIA: dict[str, frozenset[str]] = {
    "evidencia": frozenset(
        {
            "image/jpeg",
            "image/png",
            "image/webp",
            "application/pdf",
            "audio/mp4",
            "audio/ogg",
            "audio/webm",
            "audio/wav",
            "audio/mpeg",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/csv",
            "text/plain",
        }
    ),
    "adjunto": frozenset(
        {
            "image/jpeg",
            "image/png",
            "image/webp",
            "application/pdf",
            "audio/mp4",
            "audio/ogg",
            "audio/webm",
            "audio/wav",
            "audio/mpeg",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/csv",
            "text/plain",
        }
    ),
    "cargue": frozenset(
        {
            "text/plain",
            "text/csv",
            "application/x-compress",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel.sheet.macroEnabled.12",
            "application/vnd.ms-excel",
            "application/zip",
        }
    ),
}

MIMES_INLINE_SEGUROS = frozenset(
    {"image/jpeg", "image/png", "image/webp", "application/pdf"}
)

_EJECUTABLES_PREFIJOS = (
    b"MZ",
    b"\x7fELF",
    b"#!",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
)

_PATRONES_XSS_HTML = (
    b"<svg",
    b"<!doctype html",
    b"<html",
    b"<script",
    b"<iframe",
    b"javascript:",
)


class ErrorDominioArchivo(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def calcular_sha256_hex(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def calcular_limite_bytes(
    categoria: str, max_evidencia_mb: int, max_general_mb: int
) -> int:
    if categoria in ("evidencia", "adjunto"):
        return max_evidencia_mb * 1024 * 1024
    if categoria == "cargue":
        return max_general_mb * 1024 * 1024
    raise ErrorDominioArchivo(422, f"Categoría de archivo no válida: {categoria}.")


def sanitizar_nombre_archivo(nombre: str) -> str:
    base = nombre.replace("\\", "/").split("/")[-1]
    limpio = re.sub(r"[\x00-\x1f\x7f]+", "", base).strip()
    limpio = re.sub(r"\s+", " ", limpio)
    limpio = limpio.strip(". ")
    if not limpio:
        return "archivo"
    if len(limpio) > 255:
        if "." in limpio:
            stem, ext = limpio.rsplit(".", 1)
            ext = ext[:20]
            limpio = f"{stem[: 255 - len(ext) - 1]}.{ext}"
        else:
            limpio = limpio[:255]
    return limpio


def _es_contenido_peligroso(contenido: bytes) -> bool:
    for prefijo in _EJECUTABLES_PREFIJOS:
        if contenido.startswith(prefijo):
            return True
    muestra = contenido[:4096].lstrip().lower()
    if any(muestra.startswith(p) for p in _PATRONES_XSS_HTML):
        return True
    return bool(
        muestra.startswith(b"<?xml")
        and (b"<svg" in muestra or b"<html" in muestra or b"<script" in muestra)
    )


def _detectar_zip_ooxml(contenido: bytes, ext: str) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
            nombres = set(zf.namelist())
    except zipfile.BadZipFile as exc:
        raise ErrorDominioArchivo(
            415, "El archivo ZIP/Office está corrupto o no es válido."
        ) from exc

    tiene_content_types = "[Content_Types].xml" in nombres
    if tiene_content_types and any(n.startswith("xl/") for n in nombres):
        if ext == ".xlsm":
            return "application/vnd.ms-excel.sheet.macroEnabled.12"
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if ext == ".zip":
        return "application/zip"
    raise ErrorDominioArchivo(415, "Tipo de contenedor ZIP no permitido.")


def detectar_mime_por_magic_bytes(contenido: bytes, nombre: str) -> str:
    if not contenido:
        raise ErrorDominioArchivo(400, "El archivo está vacío (0 bytes).")
    if _es_contenido_peligroso(contenido):
        raise ErrorDominioArchivo(
            415, "El contenido del archivo corresponde a un formato bloqueado por seguridad."
        )

    ext = ""
    if "." in nombre:
        ext = "." + nombre.rsplit(".", 1)[-1].lower()

    if contenido.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contenido.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(contenido) >= 12 and contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "image/webp"
    if contenido.startswith(b"%PDF-"):
        return "application/pdf"
    if contenido.startswith(b"\x1f\x9d"):
        return "application/x-compress"
    if contenido.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        if ext == ".xls":
            return "application/vnd.ms-excel"
        raise ErrorDominioArchivo(415, "Archivo binario compuesto no permitido.")
    if contenido.startswith(b"PK\x03\x04"):
        return _detectar_zip_ooxml(contenido, ext)
    if contenido.startswith(b"OggS"):
        return "audio/ogg"
    if len(contenido) >= 12 and contenido[:4] == b"RIFF" and contenido[8:12] == b"WAVE":
        return "audio/wav"
    if contenido.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm"
    if contenido.startswith(b"ID3") or (
        len(contenido) >= 2 and contenido[0] == 0xFF and contenido[1] in (0xFB, 0xF3, 0xF2)
    ):
        return "audio/mpeg"
    if len(contenido) >= 12 and contenido[4:8] == b"ftyp":
        return "audio/mp4"

    # Texto plano / CSV únicamente con extensión explícita y sin bytes NUL ni etiquetas XSS
    if ext in (".csv", ".txt"):
        cabecera = contenido[:8192]
        if b"\x00" in cabecera:
            raise ErrorDominioArchivo(
                415, "El archivo de texto contiene bytes binarios no válidos."
            )
        cabecera_lower = cabecera.lower()
        if any(p in cabecera_lower for p in (b"<script", b"<svg", b"<html")):
            raise ErrorDominioArchivo(415, "Contenido HTML/script no permitido en texto.")
        return "text/csv" if ext == ".csv" else "text/plain"

    raise ErrorDominioArchivo(415, "Formato de archivo no soportado o no reconocido.")


def validar_mime_para_categoria(tipo_mime: str, categoria: str) -> None:
    permitidos = MIMES_PERMITIDOS_POR_CATEGORIA.get(categoria)
    if permitidos is None:
        raise ErrorDominioArchivo(422, f"Categoría de archivo no válida: {categoria}.")
    if tipo_mime not in permitidos:
        raise ErrorDominioArchivo(
            415,
            f"El tipo MIME '{tipo_mime}' no está permitido para la categoría '{categoria}'.",
        )


def construir_ruta_relativa(sede_id: int, sha256_hex: str, ahora: datetime) -> str:
    return f"sede_{sede_id}/{ahora:%Y}/{ahora:%m}/{sha256_hex[:2]}/{sha256_hex}"


def construir_content_disposition(
    nombre_original: str, tipo_mime: str, descargar: bool
) -> str:
    disposicion = (
        "inline"
        if (not descargar and tipo_mime in MIMES_INLINE_SEGUROS)
        else "attachment"
    )
    ascii_fallback = re.sub(r'[^A-Za-z0-9._ -]+', "_", nombre_original).strip() or "archivo"
    utf8_encoded = quote(nombre_original, safe="")
    return f'{disposicion}; filename="{ascii_fallback}"; filename*=UTF-8\'\'{utf8_encoded}'
