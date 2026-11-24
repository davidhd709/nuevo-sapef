"""Lectura de los archivos de los comercializadores (puro: bytes → filas).

- `.Z`: Unix compress (LZW, 9 a 16 bits, modo bloque), como los entrega Afinia.
- `.txt`: texto plano cp1252 (Afinia), separado por tabulador o `|`.
- `.xlsx`/`.xlsm`: libros de Excel; se rechazan los que traen fórmulas.
"""

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Any

from python_calamine import CalamineWorkbook

from app.modulos.comercial.dominio.comun import ErrorDominioComercial

MAGIA_Z = b"\x1f\x9d"
MAGIA_ZIP = b"PK\x03\x04"
_BINARIOS = (b"MZ", b"\x7fELF", b"%PDF", MAGIA_ZIP, b"\x89PNG", b"\xff\xd8\xff", b"GIF8")

EXTENSIONES_TEXTO = (".txt", ".csv")
EXTENSIONES_EXCEL = (".xlsx", ".xlsm")


@dataclass(frozen=True)
class ArchivoEntrada:
    nombre: str
    datos: bytes


def extension(nombre: str) -> str:
    """Extensión en minúsculas; `.txt.Z` cuenta como `.z`."""
    base = nombre.lower()
    return base[base.rfind(".") :] if "." in base else ""


def nombre_sin_compresion(nombre: str) -> str:
    return nombre[:-2] if nombre.lower().endswith(".z") else nombre


def validar_contenido(nombre: str, inicio: bytes, permitidas: tuple[str, ...]) -> None:
    """Extensión permitida y bytes iniciales coherentes con ella (415 si no)."""
    ext = extension(nombre)
    if ext not in permitidas:
        raise ErrorDominioComercial(
            415, f"Extensión no permitida en «{nombre}» (se aceptan {', '.join(permitidas)})."
        )
    if ext in EXTENSIONES_EXCEL and not inicio.startswith(MAGIA_ZIP):
        raise ErrorDominioComercial(415, f"«{nombre}» no es un libro de Excel válido.")
    if ext == ".z" and not inicio.startswith(MAGIA_Z):
        raise ErrorDominioComercial(415, f"«{nombre}» no es un archivo .Z (Unix compress).")
    if ext in EXTENSIONES_TEXTO and (inicio.startswith(_BINARIOS) or b"\x00" in inicio[:4096]):
        raise ErrorDominioComercial(415, f"«{nombre}» no es un archivo de texto.")


# --- .Z (LZW) -----------------------------------------------------------------------------------


def descomprimir_z(datos: bytes) -> bytes:
    """Descomprime Unix compress (.Z). Algoritmo de `unlzw` de Mark Adler: lee códigos de 9 a
    16 bits y, al cambiar de ancho o tras un CLEAR, descarta los bits hasta el borde del grupo
    de `bits` bytes (rasgo heredado del compress original)."""
    largo = len(datos)
    if largo < 3 or datos[:2] != MAGIA_Z:
        raise ErrorDominioComercial(422, "El archivo .Z no tiene la firma de Unix compress.")
    banderas = datos[2]
    if banderas & 0x60:
        raise ErrorDominioComercial(422, "El archivo .Z tiene una cabecera inválida.")
    maximo = banderas & 0x1F
    if not 9 <= maximo <= 16:
        raise ErrorDominioComercial(422, "El archivo .Z declara un ancho de código inválido.")
    if maximo == 9:
        maximo = 10  # en compress, 9 significa 10
    bloque = bool(banderas & 0x80)
    if largo == 3:
        return b""
    if largo == 4:
        raise ErrorDominioComercial(422, "El archivo .Z está incompleto.")

    prefijo = [0] * 65536
    sufijo = [0] * 65536
    bits, mascara = 9, 0x1FF
    fin = 256 if bloque else 255
    buffer = datos[3] | (datos[4] << 8)
    previo = final = buffer & mascara
    buffer >>= bits
    restantes = 16 - bits
    if previo > 255:
        raise ErrorDominioComercial(422, "El archivo .Z está dañado.")
    salida = bytearray([final])
    marca, siguiente = 3, 5

    def saltar_a_borde() -> int | None:
        resto = (siguiente - marca) % bits
        if resto:
            resto = bits - resto
            if resto > largo - siguiente:
                return None
            return siguiente + resto
        return siguiente

    while siguiente < largo:
        if fin >= mascara and bits < maximo:
            nuevo_pos = saltar_a_borde()
            if nuevo_pos is None or nuevo_pos >= largo:
                break
            siguiente = nuevo_pos
            buffer = restantes = 0
            marca = siguiente
            bits += 1
            mascara = (mascara << 1) | 1
        buffer |= datos[siguiente] << restantes
        siguiente += 1
        restantes += 8
        if restantes < bits:
            if siguiente == largo:
                raise ErrorDominioComercial(422, "El archivo .Z termina en medio de un código.")
            buffer |= datos[siguiente] << restantes
            siguiente += 1
            restantes += 8
        codigo = buffer & mascara
        buffer >>= bits
        restantes -= bits

        if codigo == 256 and bloque:
            nuevo_pos = saltar_a_borde()
            if nuevo_pos is None:
                break
            siguiente = nuevo_pos
            buffer = restantes = 0
            marca = siguiente
            bits, mascara = 9, 0x1FF
            fin = 255
            continue

        actual = codigo
        pila: list[int] = []
        if codigo > fin:
            if codigo != fin + 1 or previo > fin:
                raise ErrorDominioComercial(422, "El archivo .Z está dañado.")
            pila.append(final)
            codigo = previo
        while codigo >= 256:
            pila.append(sufijo[codigo])
            codigo = prefijo[codigo]
        pila.append(codigo)
        final = codigo
        if fin < mascara:
            fin += 1
            prefijo[fin] = previo
            sufijo[fin] = final
        previo = actual
        salida.extend(reversed(pila))
    return bytes(salida)


# --- Texto --------------------------------------------------------------------------------------


def decodificar(datos: bytes) -> str:
    """Afinia entrega cp1252; si el archivo ya viene en UTF-8 se respeta."""
    if datos.startswith(b"\xef\xbb\xbf"):
        return datos[3:].decode("utf-8")
    try:
        return datos.decode("utf-8")
    except UnicodeDecodeError:
        return datos.decode("cp1252")


def leer_delimitado(texto: str, separador: str) -> list[list[str]]:
    filas = []
    for linea in texto.splitlines():
        if not linea.strip():
            continue
        filas.append([c.strip() for c in linea.split(separador)])
    return filas


def detectar_separador(texto: str, preferido: str) -> str:
    primera = next((linea for linea in texto.splitlines() if linea.strip()), "")
    if primera.count(preferido) == 0:
        for alterno in ("\t", "|", ";"):
            if primera.count(alterno) > 0:
                return alterno
    return preferido


# --- Excel --------------------------------------------------------------------------------------

_FORMULA = re.compile(rb"<(?:\w+:)?f[\s>/]")


def tiene_formulas(datos: bytes) -> bool:
    """Busca celdas con fórmula (<f>) en las hojas del libro."""
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as libro:
            for nombre in libro.namelist():
                if nombre.startswith("xl/worksheets/") and nombre.endswith(".xml"):
                    with libro.open(nombre) as hoja:
                        resto = b""
                        while bloque := hoja.read(1 << 20):
                            if _FORMULA.search(resto + bloque):
                                return True
                            resto = bloque[-16:]
    except zipfile.BadZipFile as exc:
        raise ErrorDominioComercial(422, "El libro de Excel está dañado.") from exc
    return False


def leer_libro(datos: bytes) -> dict[str, list[list[Any]]]:
    """Hojas del libro → filas (las celdas vacías llegan como None)."""
    try:
        libro = CalamineWorkbook.from_filelike(io.BytesIO(datos))
    except Exception as exc:  # calamine no distingue tipos de error
        raise ErrorDominioComercial(422, "No se pudo leer el libro de Excel.") from exc
    hojas: dict[str, list[list[Any]]] = {}
    for nombre in libro.sheet_names:
        filas = libro.get_sheet_by_name(nombre).to_python(skip_empty_area=False)
        hojas[nombre] = [
            [None if (isinstance(c, str) and not c.strip()) else c for c in fila]
            for fila in filas
            if any(not (c is None or (isinstance(c, str) and not c.strip())) for c in fila)
        ]
    return hojas
