"""Adaptador de Afinia (Montelíbano): reconocer, validar y normalizar los archivos (§11.3).

Planos `.txt` sin encabezado (cp1252) o comprimidos `.Z`, y los cinco libros mensuales de
Montelíbano en Excel. Las familias normalizadas: catastro, facturacion, recaudo, refactura y
convenio.
"""

import datetime as dt
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from app.modulos.comercial.dominio import archivos as lectura
from app.modulos.comercial.dominio.comun import (
    MESES_ES,
    ErrorDominioComercial,
    como_fecha,
    dec,
    desplazar,
    entero,
    primer_dia,
    q4,
    sin_tildes,
    texto,
)
from app.modulos.comercial.dominio.modelo import ResultadoAdaptador, duplicados_exactos

VERSION = "afinia-1.0"
EXTENSIONES = (".txt", ".z", ".xlsx", ".xlsm")
FAMILIAS = ("catastro", "facturacion", "recaudo", "refactura", "convenio")
OBLIGATORIAS_PUBLICAR = ("facturacion",)

BASE = (
    "fecha_proc_reg",
    "cod_oper_cont",
    "nic",
    "nis_rad",
    "sec_nis",
    "sec_rec",
    "fecha_fact_lect",
    "tipo_cliente_uso",
    "tarifa",
    "estado_contrato",
    "concepto",
    "importe_trans",
    "fecha_trans",
    "valor_recibo",
    "sector_dpto",
    "cod_mpio",
    "cod_correg",
    "cod_dpto",
    "sv",
)
CATASTRO = (
    "tipo_serv",
    "desc_serv",
    "cod_tarifa",
    "desc_tar",
    "nic",
    "nis_rad",
    "nombre",
    "direccion",
    "consumo_facturado",
    "municipio",
    "barrio",
    "deuda_corriente",
    "deuda_cuota",
    "estado_suministro",
)
PLANTILLA_21 = (*BASE, "consumo_kwh", "valor_consumo_antes")
LAYOUTS: dict[str, tuple[str, ...]] = {
    "catastro": CATASTRO,
    "facturacion": PLANTILLA_21,
    "recaudo": BASE,
    "refactura": (*BASE, "valor_consumo_antes"),
    "convenio": BASE,
}
# Columnas que admite cada familia en Excel (los transaccionales comparten la plantilla de 21).
ANCHOS_EXCEL: dict[str, tuple[int, ...]] = {
    "catastro": (14,),
    "facturacion": (21,),
    "recaudo": (19, 21),
    "refactura": (20, 21),
    "convenio": (19, 21),
}

FECHAS = frozenset({"fecha_proc_reg", "fecha_fact_lect", "fecha_trans"})
DECIMALES = frozenset(
    {
        "importe_trans",
        "valor_recibo",
        "consumo_kwh",
        "valor_consumo_antes",
        "consumo_facturado",
        "deuda_corriente",
        "deuda_cuota",
    }
)
ENTEROS = frozenset(
    {
        "nic",
        "nis_rad",
        "sec_nis",
        "sec_rec",
        "estado_contrato",
        "sector_dpto",
        "cod_mpio",
        "cod_correg",
        "cod_dpto",
    }
)
AGREGADAS = ("periodo", "zona", "archivo", "fila_origen")

ENCABEZADOS: dict[str, str] = {
    "fecha_proc_reg": "FECHA PROC. REG.",
    "cod_oper_cont": "COD. OPER. CONT.",
    "nic": "NIC",
    "nis_rad": "NIS RAD",
    "sec_nis": "SEC. NIS",
    "sec_rec": "SEC. REC.",
    "fecha_fact_lect": "FECHA FACT.-LECT.",
    "tipo_cliente_uso": "TIPO CLIENTE-USO",
    "tarifa": "TARIFA",
    "estado_contrato": "ESTADO CONTRATO",
    "concepto": "CONCEPTO",
    "importe_trans": "IMPORTE TRANS.",
    "fecha_trans": "FECHA TRANS.",
    "valor_recibo": "VALOR RECIBO",
    "sector_dpto": "SECTOR-DPTO",
    "cod_mpio": "COD. MPIO",
    "cod_correg": "COD. CORREG.",
    "cod_dpto": "COD. DPTO",
    "sv": "SV",
    "consumo_kwh": "CONSUMO KWH",
    "valor_consumo_antes": "VALOR DEL CONSUMO ANTES DE TODO",
    "tipo_serv": "TIPO SERV",
    "desc_serv": "DESC SERV",
    "cod_tarifa": "COD TARIFA",
    "desc_tar": "DESC TAR",
    "nombre": "NOMBRE",
    "direccion": "DIRECCIÓN",
    "consumo_facturado": "CONSUMO FACTURADO",
    "municipio": "MUNICIPIO",
    "barrio": "BARRIO",
    "deuda_corriente": "DEUDA CORRIENTE",
    "deuda_cuota": "DEUDA CUOTA",
    "estado_suministro": "ESTADO SUMINISTRO",
    "periodo": "PERIODO",
    "zona": "ZONA",
}


# Columnas de cada familia en el almacén, con su tipo.
def esquema(familia: str) -> dict[str, str]:
    columnas: dict[str, str] = {"periodo": "texto", "zona": "texto"}
    for c in LAYOUTS[familia]:
        columnas[c] = (
            "fecha"
            if c in FECHAS
            else "decimal"
            if c in DECIMALES
            else "entero"
            if c in ENTEROS
            else "texto"
        )
    if familia == "catastro":
        columnas["tarifa"] = "texto"
    if familia == "recaudo":
        columnas["tipo_recaudo"] = "texto"
    columnas["archivo"] = "texto"
    columnas["fila_origen"] = "entero"
    return columnas


# --- Reconocimiento por nombre ----------------------------------------------------------------

_PREFIJOS: tuple[tuple[str, str | None], ...] = (
    ("CATASTRO_USUARIOS_SV500_", "catastro"),
    ("FACT_SV500_", "facturacion"),
    ("RECA_SV500_", "recaudo"),
    ("REFA_SV500_", "refactura"),
    ("CONV_SV500_", "convenio"),
    ("NOVEDADES_", None),
    ("IC_ALUMBRADO_", None),
    ("IC_SERVICIOS_", None),
    ("INFORME_CARTERA_", None),
)
_LIBRO = re.compile(
    r"^(CATASTRO|FACTURACION|RECAUDO|REFACTURACION|CONVENIO)_([A-Z]+)_([A-Z]+)_(\d{4})$"
)
_FAMILIA_LIBRO = {
    "CATASTRO": "catastro",
    "FACTURACION": "facturacion",
    "RECAUDO": "recaudo",
    "REFACTURACION": "refactura",
    "CONVENIO": "convenio",
}
_FECHA_FINAL = re.compile(r"(?:^|_)(?:ZONA_)?(\d+)_(\d{8})$|_(\d{8})$")


def reconocer(nombre: str) -> tuple[str | None, str | None, str | None]:
    """(familia, periodo, zona). Familia None y periodo None: archivo que se registra pero no se
    procesa. Lanza error si no se reconoce."""
    base = lectura.nombre_sin_compresion(nombre)
    tallo = sin_tildes(base.rsplit(".", 1)[0]).upper()
    libro = _LIBRO.match(tallo)
    if libro:
        mes = MESES_ES.get(libro.group(3))
        if mes is None:
            raise ErrorDominioComercial(422, f"«{nombre}»: mes «{libro.group(3)}» no reconocido.")
        return _FAMILIA_LIBRO[libro.group(1)], f"{libro.group(4)}{mes:02d}", None
    for prefijo, familia in _PREFIJOS:
        if tallo.startswith(prefijo):
            fecha = _FECHA_FINAL.search(tallo)
            if familia is None:
                return None, None, None
            if fecha is None:
                raise ErrorDominioComercial(
                    422, f"«{nombre}»: falta la fecha AAAAMMDD al final del nombre."
                )
            ymd = fecha.group(2) or fecha.group(3)
            try:
                dt.date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
            except ValueError as exc:
                raise ErrorDominioComercial(422, f"«{nombre}»: la fecha {ymd} no existe.") from exc
            return familia, ymd[:6], fecha.group(1)
    raise ErrorDominioComercial(
        422, f"No se reconoce el archivo «{nombre}» como un archivo de Afinia."
    )


# --- Normalización ----------------------------------------------------------------------------


def _clave_encabezado(valor: Any) -> str:
    return re.sub(r"\s+", " ", sin_tildes(str(valor or "")).upper()).strip()


_POR_ENCABEZADO = {_clave_encabezado(v): k for k, v in ENCABEZADOS.items()}


def _es_encabezado(fila: list[Any]) -> bool:
    textos = [c for c in fila if isinstance(c, str) and c.strip()]
    if not textos:
        return False
    conocidos = sum(1 for c in textos if _clave_encabezado(c) in _POR_ENCABEZADO)
    return conocidos >= max(2, len(textos) // 2)


def _columnas_de_encabezado(fila: list[Any], familia: str, nombre: str) -> list[str]:
    columnas = []
    for posicion, valor in enumerate(fila, start=1):
        clave = _POR_ENCABEZADO.get(_clave_encabezado(valor))
        if clave is None:
            raise ErrorDominioComercial(
                422,
                f"«{nombre}»: la columna {posicion} («{valor}») no corresponde al layout de "
                f"{familia}; no se aceptan columnas adicionales ni encabezados distintos.",
            )
        columnas.append(clave)
    return columnas


def _validar_columnas(columnas: list[str], familia: str, nombre: str) -> None:
    permitidas = {
        LAYOUTS[familia][:n] if n <= len(LAYOUTS[familia]) else PLANTILLA_21[:n]
        for n in ANCHOS_EXCEL[familia]
    }
    if tuple(columnas) not in permitidas:
        raise ErrorDominioComercial(
            422,
            f"«{nombre}»: los encabezados no coinciden con el layout de {familia} "
            f"(columnas incompatibles o en otro orden).",
        )


def _convertir(columna: str, valor: Any) -> Any:
    if columna in FECHAS:
        return como_fecha(valor)
    if columna in DECIMALES:
        numero = dec(valor)
        return q4(numero) if numero is not None else None
    if columna in ENTEROS:
        return entero(valor)
    return texto(valor)


def _normalizar_filas(
    filas: list[list[Any]],
    columnas: list[str],
    *,
    familia: str,
    periodo: str,
    zona: str | None,
    nombre: str,
    primera_fila: int,
    errores: list[str],
) -> list[dict[str, Any]]:
    salida = []
    destino = LAYOUTS[familia]
    corte_corriente = desplazar(primer_dia(periodo), -1)
    for i, fila in enumerate(filas):
        numero = primera_fila + i
        if len(fila) != len(columnas):
            errores.append(
                f"«{nombre}» fila {numero}: tiene {len(fila)} columnas; se esperaban "
                f"{len(columnas)}."
            )
            continue
        crudo = dict(zip(columnas, fila, strict=True))
        registro: dict[str, Any] = {"periodo": periodo, "zona": zona}
        try:
            for columna in destino:
                registro[columna] = _convertir(columna, crudo.get(columna))
        except ValueError as exc:
            errores.append(f"«{nombre}» fila {numero}: valor inválido «{exc}».")
            continue
        if familia == "catastro":
            registro["tarifa"] = (registro["desc_tar"] or "").replace(" ", "_") or None
        if familia == "recaudo":
            fecha = registro["fecha_fact_lect"]
            registro["tipo_recaudo"] = (
                "NO_CLASIFICADO"
                if fecha is None
                else "CORRIENTE"
                if fecha >= corte_corriente
                else "CARTERA"
            )
        registro["archivo"] = nombre
        registro["fila_origen"] = numero
        salida.append(registro)
        if len(errores) > 50:
            break
    return salida


def _leer_plano(datos: bytes, familia: str, nombre: str) -> tuple[list[list[Any]], list[str], int]:
    contenido = lectura.decodificar(datos)
    separador = lectura.detectar_separador(contenido, "|" if familia == "catastro" else "\t")
    filas = lectura.leer_delimitado(contenido, separador)
    if not filas:
        return [], list(LAYOUTS[familia]), 1
    if _es_encabezado(filas[0]):
        columnas = _columnas_de_encabezado(filas[0], familia, nombre)
        _validar_columnas(columnas, familia, nombre)
        return filas[1:], columnas, 2
    return filas, list(LAYOUTS[familia]), 1


def _hoja_de_familia(
    hojas: dict[str, list[list[Any]]], familia: str, nombre: str
) -> list[list[Any]]:
    alias = {familia, "refacturacion" if familia == "refactura" else familia}
    for titulo, filas in hojas.items():
        if sin_tildes(titulo).strip().lower() in alias:
            return filas
    con_datos = [f for f in hojas.values() if f]
    if len(con_datos) == 1:
        return con_datos[0]
    raise ErrorDominioComercial(
        422, f"«{nombre}»: el libro debe tener una hoja «{familia}» o una sola hoja con datos."
    )


def _leer_excel(datos: bytes, familia: str, nombre: str) -> tuple[list[list[Any]], list[str], int]:
    if lectura.tiene_formulas(datos):
        raise ErrorDominioComercial(
            422, f"«{nombre}»: el libro tiene celdas con fórmulas; cárguelo con valores."
        )
    filas = _hoja_de_familia(lectura.leer_libro(datos), familia, nombre)
    if not filas:
        return [], list(LAYOUTS[familia]), 1
    ancho = max(len(f) for f in filas)
    filas = [list(f) + [None] * (ancho - len(f)) for f in filas]
    if _es_encabezado(filas[0]):
        columnas = _columnas_de_encabezado(filas[0], familia, nombre)
        _validar_columnas(columnas, familia, nombre)
        return filas[1:], columnas, 2
    if ancho not in ANCHOS_EXCEL[familia]:
        raise ErrorDominioComercial(
            422,
            f"«{nombre}»: tiene {ancho} columnas; {familia} admite "
            f"{' o '.join(str(n) for n in ANCHOS_EXCEL[familia])}.",
        )
    columnas = list(LAYOUTS[familia] if ancho == len(LAYOUTS[familia]) else PLANTILLA_21[:ancho])
    return filas, columnas, 1


def procesar(
    archivos: list[lectura.ArchivoEntrada],
    periodo: str,
    *,
    corte_anterior: Callable[[str], list[dict[str, Any]]] | None = None,
) -> ResultadoAdaptador:
    resultado = ResultadoAdaptador(familias={f: [] for f in FAMILIAS})
    for archivo in archivos:
        try:
            familia, periodo_nombre, zona = reconocer(archivo.nombre)
            if familia is None:
                resultado.advertencias.append(
                    f"«{archivo.nombre}» se registró pero no se procesa (fuera del alcance)."
                )
                resultado.archivos.append({"nombre": archivo.nombre, "familia": None})
                continue
            if periodo_nombre != periodo:
                raise ErrorDominioComercial(
                    422,
                    f"«{archivo.nombre}» es del periodo {periodo_nombre}, no de {periodo}.",
                )
            datos = archivo.datos
            if lectura.extension(archivo.nombre) == ".z":
                datos = lectura.descomprimir_z(datos)
            if lectura.extension(archivo.nombre) in lectura.EXTENSIONES_EXCEL:
                filas, columnas, primera = _leer_excel(datos, familia, archivo.nombre)
            else:
                filas, columnas, primera = _leer_plano(datos, familia, archivo.nombre)
            errores_archivo: list[str] = []
            normalizadas = _normalizar_filas(
                filas,
                columnas,
                familia=familia,
                periodo=periodo,
                zona=zona,
                nombre=archivo.nombre,
                primera_fila=primera,
                errores=errores_archivo,
            )
            resultado.errores.extend(errores_archivo)
            resultado.familias[familia].extend(normalizadas)
            resultado.presentes.add(familia)
            resultado.archivos.append(
                {
                    "nombre": archivo.nombre,
                    "familia": familia,
                    "zona": zona,
                    "filas": len(normalizadas),
                }
            )
        except ErrorDominioComercial as exc:
            resultado.errores.append(exc.detail)

    for familia, filas in resultado.familias.items():
        repetidas = duplicados_exactos(filas, ignorar=("archivo", "fila_origen"))
        if repetidas:
            resultado.advertencias.append(
                f"{familia}: {repetidas} fila(s) duplicadas idénticas en todas sus columnas; se "
                "conservan (pueden ser pagos reales repetidos)."
            )
    faltan = [f for f in FAMILIAS if f not in resultado.presentes]
    resultado.completo = not faltan
    if faltan and not resultado.errores:
        resultado.advertencias.append(f"Corte incompleto: faltan {', '.join(faltan)}.")
    resultado.publicable = all(f in resultado.presentes for f in OBLIGATORIAS_PUBLICAR)
    if not resultado.publicable:
        resultado.motivo_no_publicable = (
            "Falta la facturación: un corte de Afinia sin ella no se publica."
        )
    return resultado


def decimal_o_cero(valor: Decimal | None) -> Decimal:
    return valor if valor is not None else Decimal(0)
