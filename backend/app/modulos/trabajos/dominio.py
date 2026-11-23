"""Reglas puras del módulo de trabajos (sin BD, HTTP ni cola)."""

import io
from dataclasses import dataclass
from typing import Any

from openpyxl import Workbook, load_workbook


class ErrorDominioTrabajos(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


TIPOS = ("mantenimiento", "modernizacion", "expansion", "reubicacion")
TIPOS_INSTALACION = ("modernizacion", "expansion", "reubicacion")

# Estados de la orden [SUPUESTO §9.5]: 201 → 202 → 205 → 203 · 204.
CREADA, ASIGNADA, EN_EJECUCION, CERRADA, ANULADA = "201", "202", "205", "203", "204"
ABIERTOS = (CREADA, ASIGNADA, EN_EJECUCION)

# Luminaria: en operación, con PQRS, bodega buena; destinos válidos de una desmontada.
LUM_OPERACION, LUM_ACTIVO_PQR, LUM_BODEGA_BUENA, LUM_DESMONTADA = "121", "122", "124", "112"
LUM_EN_SITIO = (LUM_OPERACION, LUM_ACTIVO_PQR)
DESTINOS_DESMONTADA = ("124", "123", "125", "112", "126")

# Checklist del mantenimiento (12 componentes de SAPEF, RF-030).
COMPONENTES = (
    "conexion_red",
    "conexion_interna",
    "base_fotocelda",
    "fotocelda",
    "bombillo",
    "socket",
    "arrancador",
    "condensador",
    "balasta",
    "tubo",
    "collarin",
    "conectores_perforacion",
)

# Tipo de intervención que queda en la luminaria instalada.
INTERVENCION_POR_TIPO = {
    "expansion": "EXPANSION",
    "modernizacion": "MODERNIZACION",
    "reubicacion": "REUBICADA",
}


def validar_luminarias(tipo: str, roles: list[str]) -> None:
    """RN-013: modernización y reubicación llevan siempre instalada y desmontada."""
    if not roles:
        raise ErrorDominioTrabajos(422, "La orden debe tener al menos una luminaria.")
    permitidos = {"mantenimiento": {"intervenida"}, "expansion": {"instalada"}}.get(
        tipo, {"instalada", "desmontada"}
    )
    ajenos = set(roles) - permitidos
    if ajenos:
        raise ErrorDominioTrabajos(
            422, f"Una orden de {tipo} no lleva luminarias con rol {', '.join(sorted(ajenos))}."
        )
    if tipo in ("modernizacion", "reubicacion") and {"instalada", "desmontada"} - set(roles):
        raise ErrorDominioTrabajos(
            422, f"Una {tipo} registra siempre la luminaria instalada y la desmontada (RN-013)."
        )
    if tipo in ("modernizacion", "reubicacion") and (
        roles.count("instalada") != roles.count("desmontada")
    ):
        raise ErrorDominioTrabajos(422, "Cada luminaria instalada necesita su desmontada.")


def validar_abierta(estado: str) -> None:
    if estado == CERRADA:
        raise ErrorDominioTrabajos(409, "La orden ya está cerrada.")
    if estado == ANULADA:
        raise ErrorDominioTrabajos(409, "La orden está anulada.")


def validar_componentes(componentes: dict[str, Any] | None) -> dict[str, bool]:
    if not isinstance(componentes, dict):
        raise ErrorDominioTrabajos(422, "El checklist de 12 componentes es obligatorio.")
    faltan = [c for c in COMPONENTES if c not in componentes]
    sobran = [c for c in componentes if c not in COMPONENTES]
    if faltan or sobran:
        partes = []
        if faltan:
            partes.append(f"faltan {', '.join(faltan)}")
        if sobran:
            partes.append(f"no se reconocen {', '.join(sobran)}")
        raise ErrorDominioTrabajos(422, f"Checklist incompleto: {'; '.join(partes)}.")
    if any(not isinstance(componentes[c], bool) for c in COMPONENTES):
        raise ErrorDominioTrabajos(422, "Cada componente del checklist es sí o no.")
    return {c: bool(componentes[c]) for c in COMPONENTES}


def validar_destino(destino: str | None, por_defecto: str = LUM_DESMONTADA) -> str:
    valor = (destino or por_defecto).strip()
    if valor not in DESTINOS_DESMONTADA:
        raise ErrorDominioTrabajos(
            422,
            f"Destino no válido para la desmontada: {valor} ({', '.join(DESTINOS_DESMONTADA)}).",
        )
    return valor


def validar_mantenimiento(
    requiere_desmonte: bool, causal: str | None, reemplazo_id: int | None
) -> None:
    if reemplazo_id is not None and not requiere_desmonte:
        raise ErrorDominioTrabajos(422, "Reemplazar la luminaria implica desmontar la anterior.")
    if requiere_desmonte and not (causal and causal.strip()):
        raise ErrorDominioTrabajos(422, "Indique la causal del desmonte.")


# --- Cargue masivo y plantillas ------------------------------------------------------------------

COLUMNAS_CARGUE = {
    "expansion": ("luminaria_codigo", "tipo_expansion", "barrio", "poste", "latitud", "longitud"),
    "modernizacion": (
        "luminaria_instalada_codigo",
        "luminaria_desmontada_codigo",
        "tipo",
        "barrio",
        "poste",
        "destino_desmontada",
    ),
}
COLUMNAS_CARGUE["reubicacion"] = COLUMNAS_CARGUE["modernizacion"]
OBLIGATORIAS_CARGUE = {
    "expansion": ("luminaria_codigo", "barrio", "latitud", "longitud"),
    "modernizacion": ("luminaria_instalada_codigo", "luminaria_desmontada_codigo", "barrio"),
}
OBLIGATORIAS_CARGUE["reubicacion"] = OBLIGATORIAS_CARGUE["modernizacion"]
MAX_FILAS_CARGUE = 2000


@dataclass(frozen=True)
class FilaCargue:
    fila: int
    datos: dict[str, str]


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def generar_plantilla(tipo: str) -> bytes:
    if tipo not in COLUMNAS_CARGUE:
        raise ErrorDominioTrabajos(404, f"No hay plantilla de cargue para {tipo}.")
    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = tipo.capitalize()
    hoja.append(list(COLUMNAS_CARGUE[tipo]))
    ayuda = libro.create_sheet("Instrucciones")
    ayuda.append(["Columna", "Obligatoria"])
    for columna in COLUMNAS_CARGUE[tipo]:
        ayuda.append([columna, "Sí" if columna in OBLIGATORIAS_CARGUE[tipo] else "No"])
    ayuda.append([])
    ayuda.append(["Si una fila tiene un error, no se carga ninguna (todo o nada)."])
    buf = io.BytesIO()
    libro.save(buf)
    return buf.getvalue()


def leer_cargue(tipo: str, contenido: bytes) -> tuple[list[FilaCargue], list[dict[str, Any]]]:
    if tipo not in COLUMNAS_CARGUE:
        raise ErrorDominioTrabajos(422, f"No hay cargue masivo para {tipo}.")
    try:
        libro = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception as exc:
        raise ErrorDominioTrabajos(422, "El archivo no es un Excel (.xlsx) válido.") from exc
    filas_hoja = libro.worksheets[0].iter_rows(values_only=True)
    encabezado = [_texto(c).lower() for c in next(filas_hoja, ())]
    faltan = [c for c in OBLIGATORIAS_CARGUE[tipo] if c not in encabezado]
    if faltan:
        raise ErrorDominioTrabajos(422, f"Faltan columnas: {', '.join(faltan)}.")
    indices = {c: encabezado.index(c) for c in COLUMNAS_CARGUE[tipo] if c in encabezado}

    filas: list[FilaCargue] = []
    errores: list[dict[str, Any]] = []
    for n, valores in enumerate(filas_hoja, start=2):
        if not any(v not in (None, "") for v in valores):
            continue
        if len(filas) >= MAX_FILAS_CARGUE:
            raise ErrorDominioTrabajos(422, f"Máximo {MAX_FILAS_CARGUE} filas por cargue.")
        datos = {c: _texto(valores[i]) if i < len(valores) else "" for c, i in indices.items()}
        vacias = [c for c in OBLIGATORIAS_CARGUE[tipo] if not datos.get(c)]
        if vacias:
            errores.append({"fila": n, "registro": n - 1, "error": f"Faltan: {', '.join(vacias)}"})
            continue
        filas.append(FilaCargue(n, datos))
    return filas, errores


def coordenadas_de_fila(datos: dict[str, str]) -> tuple[float, float]:
    try:
        return float(datos["latitud"].replace(",", ".")), float(datos["longitud"].replace(",", "."))
    except (KeyError, ValueError) as exc:
        raise ErrorDominioTrabajos(422, "Latitud o longitud no son números.") from exc
