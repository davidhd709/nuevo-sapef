"""Paridad con OPainn (SPIKE-04, criterio de aceptación de la Fase 4).

Importa el almacén real de OPainn con el importador del sistema nuevo (HU-080), calcula con el
mismo servicio que usa la API y compara cifra a cifra con las instantáneas de OPainn
(`datos/golden/regresion/`). Afinia 202606 es además el golden cuadrado a mano por la oficina:
la instantánea de ese mes coincide con él en sus 472 celdas, así que pasar aquí también es
pasar contra la referencia humana.

Los datos de OPainn son privados (traen NIC y deudores): nunca se copian al repositorio. La prueba
se salta si no está `SAPEF_OPAINN_DIR` (ruta del repositorio de OPainn en este equipo):

    SAPEF_OPAINN_DIR=../../Opainn uv run pytest tests/paridad -q -s
"""

import json
import os
import subprocess
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.config import obtener_configuracion
from app.modulos.comercial import servicio as comercial
from app.modulos.seguridad.servicio import SedeResumen
from tests.conftest import crear_usuario_db

OPAINN = Path(os.environ.get("SAPEF_OPAINN_DIR", "")).resolve()
GOLDEN = OPAINN / "datos" / "golden" / "regresion"
ALMACEN = OPAINN / "datos" / "almacen"

pytestmark = pytest.mark.skipif(
    not os.environ.get("SAPEF_OPAINN_DIR") or not GOLDEN.is_dir(),
    reason="Defina SAPEF_OPAINN_DIR con el repositorio de OPainn (datos privados).",
)


def _num(valor: Any) -> Any:
    if isinstance(valor, Decimal):
        return float(valor)
    return valor


def coincide(esperado: Any, obtenido: Any) -> bool:
    """Dinero: un centavo. Razones y porcentajes (|x| < 1): 1e-6, el redondeo de OPainn."""
    if isinstance(obtenido, _Divergencia):
        return True
    if isinstance(esperado, str) or isinstance(obtenido, str) or esperado is None:
        return str(esperado).strip() == str(obtenido).strip()
    obtenido = _num(obtenido)
    if obtenido is None:
        return False
    tolerancia = 0.01 if abs(float(esperado)) >= 1 else 1e-6
    return abs(float(esperado) - float(obtenido)) <= tolerancia


@pytest.fixture
def entorno(db_configurado: Session, almacen_temporal: Path, monkeypatch) -> Iterator[Session]:
    monkeypatch.setenv("SAPEF_COMERCIAL_DIR", str(almacen_temporal / "comercial"))
    monkeypatch.setenv("SAPEF_COMERCIAL_IMPORTACION_DIR", str(ALMACEN))
    obtener_configuracion.cache_clear()
    crear_usuario_db(
        db_configurado,
        nombre_usuario="paridad",
        correo="paridad@sapef.local",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano", "alcala"],
    )
    yield db_configurado
    obtener_configuracion.cache_clear()


def _sede(db: Session, codigo: str) -> SedeResumen:
    from app.modulos.configuracion import servicio as configuracion

    s = next(x for x in configuracion.listar_sedes_activas_resumen(db) if x["codigo"] == codigo)
    return SedeResumen(id=s["id"], codigo=s["codigo"], nombre=s["nombre"])


def _usuario_id(db: Session) -> int:
    from sqlalchemy import text

    return int(
        db.execute(text("SELECT id FROM usuario WHERE nombre_usuario='paridad'")).scalar_one()
    )


def _importar_todo(db: Session, sede: SedeResumen, codigo: str) -> list[str]:
    """Importa cada periodo del almacén. Devuelve los publicados. Un periodo sin la familia
    principal (p. ej., Afinia 202510 sin facturación, que OPainn tampoco tiene) no se publica,
    igual que en OPainn."""
    usuario = _usuario_id(db)
    publicados = []
    for carpeta in sorted(p for p in (ALMACEN / codigo).iterdir() if p.is_dir()):
        resultado = comercial.procesar_importacion_opainn(
            db,
            sede_id=sede.id,
            comercializador=codigo,
            periodo=carpeta.name,
            ruta=str(carpeta),
            usuario_id=usuario,
        )
        if resultado == "no_publicable":
            origen = json.loads((carpeta / "manifest.json").read_text(encoding="utf-8"))
            assert origen.get("familias_faltantes"), (carpeta.name, resultado)
            print(
                f"\n  {codigo} {carpeta.name}: no publicable (OPainn: faltan "
                f"{origen['familias_faltantes']})"
            )
            continue
        assert "error" not in resultado, (carpeta.name, resultado)
        publicados.append(carpeta.name)
    return publicados


_REFERENCIA: dict[str, Any] | None = None


def _referencia_viva() -> dict[str, Any]:
    """Lo que calcula hoy el motor de OPainn sobre su almacén (con su propio Python). Si OPainn
    no tiene entorno, {} y se usan sus instantáneas guardadas."""
    global _REFERENCIA
    if _REFERENCIA is None:
        python = OPAINN / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        _REFERENCIA = {}
        if python.is_file():
            salida = subprocess.run(
                [str(python), str(Path(__file__).with_name("referencia_opainn.py")), str(OPAINN)],
                capture_output=True,
                check=True,
                cwd=OPAINN,
                timeout=1800,
            )
            _REFERENCIA = json.loads(salida.stdout.decode("utf-8"))
    return _REFERENCIA


def _golden(nombre: str) -> dict[str, Any] | None:
    viva = _referencia_viva()
    if nombre in viva:
        return viva[nombre]
    ruta = GOLDEN / f"{nombre}.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else None


INFORME = os.environ.get("SAPEF_PARIDAD_INFORME")  # archivo JSON con todas las diferencias
_DIFERENCIAS: dict[str, list[str]] = {}


def _informe(nombre: str, comparadas: int, fallas: list[str]) -> None:
    print(f"\n  {nombre}: {comparadas - len(fallas)}/{comparadas} coinciden")
    for f in fallas[:5]:
        print(f"    - {f}")
    if INFORME:
        _DIFERENCIAS[nombre] = fallas
        Path(INFORME).write_text(
            json.dumps(_DIFERENCIAS, ensure_ascii=False, indent=1), encoding="utf-8"
        )


def _td_afinia_plana(td: dict[str, Any]) -> dict[str, Any]:
    celdas: dict[str, Any] = {}
    for fila in td["filas"]:
        for col, val in fila.items():
            celdas[f"{col}[{fila['estrato_uso']}]"] = val
    for col, val in td["total"].items():
        celdas[f"{col}[TOTAL]"] = val
    return celdas


def test_paridad_afinia_tabla_dinamica_todos_los_cortes(entorno: Session) -> None:
    db = entorno
    sede = _sede(db, "montelibano")
    periodos = _importar_todo(db, sede, "afinia")
    total_fallas: dict[str, list[str]] = {}
    for periodo in periodos:
        golden = _golden(f"afinia_td_{periodo}")
        if golden is None:
            continue
        obtenido = _td_afinia_plana(comercial.tabla_dinamica(db, sede, "afinia", periodo))
        fallas = [
            f"{clave}: OPainn {esperado!r} · nuevo {_num(obtenido.get(clave))!r}"
            for clave, esperado in golden.items()
            if not coincide(esperado, obtenido.get(clave))
        ]
        _informe(f"afinia_td_{periodo}", len(golden), fallas)
        if fallas:
            total_fallas[periodo] = fallas
    # Golden humano: junio de 2026 cuadrado a mano por la oficina, por celda de Excel.
    humano = OPAINN / "datos" / "golden" / "td_202606.json"
    if humano.is_file() and "202606" in periodos:
        celdas = json.loads(humano.read_text(encoding="utf-8"))
        letras = _columnas_td_opainn()
        td = comercial.tabla_dinamica(db, sede, "afinia", "202606")
        fallas, comparadas = [], 0
        for indicador, letra in letras.items():
            valores = [
                (f"{letra}{6 + i}", fila.get(indicador)) for i, fila in enumerate(td["filas"])
            ]
            valores.append((f"{letra}19", td["total"].get(indicador)))
            for celda, obtenido in valores:
                # AG19: el consolidado humano quedó sin SUM (OPainn documenta esta divergencia).
                # E19 y F19 son el rótulo de la fila de totales («TOTALES»), no una cifra.
                if celda not in celdas or celda in ("AG19", "E19", "F19") or obtenido is None:
                    continue
                comparadas += 1
                esperado = celdas[celda]
                if indicador == "estrato_uso_catastro" and isinstance(esperado, str):
                    obtenido = str(obtenido)
                if not coincide(esperado, obtenido):
                    fallas.append(
                        f"{celda} {indicador}: humano {esperado!r} - nuevo {_num(obtenido)!r}"
                    )
        _informe("afinia_golden_humano_202606", comparadas, fallas)
        if fallas:
            total_fallas["golden_humano_202606"] = fallas
    assert not total_fallas, f"Periodos con diferencias: {sorted(total_fallas)}"


def _columnas_td_opainn() -> dict[str, str]:
    """Indicador → columna de Excel del consolidado, leído del código de OPainn (sin importarlo)."""
    import ast

    fuente = (OPAINN / "src" / "opainn" / "afinia" / "td.py").read_text(encoding="utf-8")
    for nodo in ast.parse(fuente).body:
        if isinstance(nodo, ast.Assign) and getattr(nodo.targets[0], "id", "") == "COLUMNAS_TD":
            return ast.literal_eval(nodo.value)
    raise AssertionError("No se encontró COLUMNAS_TD en OPainn.")


def _comparar_dic(
    nombre: str, esperado: dict[str, Any], obtenido: dict[str, Any], ignorar: tuple[str, ...] = ()
) -> list[str]:
    fallas = []
    comparadas = 0
    for clave, valor in esperado.items():
        if clave in ignorar or isinstance(valor, (dict, list)):
            continue
        comparadas += 1
        if clave not in obtenido:
            fallas.append(f"{clave}: OPainn {valor!r} - nuevo (no existe)")
        elif not coincide(valor, obtenido[clave]):
            fallas.append(f"{clave}: OPainn {valor!r} - nuevo {_num(obtenido[clave])!r}")
    _informe(nombre, comparadas, fallas)
    return fallas


def test_paridad_celsia(entorno: Session) -> None:
    db = entorno
    sede = _sede(db, "alcala")
    periodos = _importar_todo(db, sede, "celsia")
    todas: dict[str, list[str]] = {}
    for periodo in periodos:
        golden = _golden(f"celsia_td_{periodo}")
        if golden is None:
            continue
        td = comercial.tabla_dinamica(db, sede, "celsia", periodo)
        if INFORME:
            _DIFERENCIAS[f"_nuevo_celsia_td_{periodo}"] = [json.dumps(td, default=str)[:4000]]
        fallas = _comparar_dic(f"celsia_td_{periodo}.totales", golden["totales"], td["total"])
        por_clase = {f["clasificacion"]: f for f in td["filas"]}
        for fila in golden["filas"]:
            # La variación de OPainn siempre sale vacía (su consulta falla y la excepción se
            # traga): no hay referencia contra la cual comparar la del sistema nuevo.
            ignorar = ["variacion_facturacion", "variacion_recaudo"]
            if golden["totales"].get("nuevos_usuarios") is None:
                # Sin movimiento evaluable (primer corte) OPainn deja los totales vacíos pero
                # rellena las filas con 0 (`fillna`); el sistema nuevo deja ambos vacíos.
                ignorar += ["nuevos_usuarios", "usuarios_dejados_facturar", "usuarios_reintegrados"]
            fallas += _comparar_dic(
                f"celsia_td_{periodo}[{fila['clasificacion']}]",
                fila,
                por_clase.get(fila["clasificacion"], {}),
                ignorar=tuple(ignorar),
            )
        if fallas:
            todas[periodo] = fallas
    assert not todas, f"Periodos con diferencias: {sorted(todas)}"


def test_paridad_vatia(entorno: Session) -> None:
    db = entorno
    sede = _sede(db, "alcala")
    periodos = _importar_todo(db, sede, "vatia")
    todas: dict[str, list[str]] = {}
    for periodo in periodos:
        golden = _golden(f"vatia_td_{periodo}")
        if golden is None:
            continue
        td = comercial.tabla_dinamica(db, sede, "vatia", periodo)
        if INFORME:
            _DIFERENCIAS[f"_nuevo_vatia_td_{periodo}"] = [json.dumps(td, default=str)[:3000]]
        fallas = _comparar_dic(
            f"vatia_td_{periodo}.totales", golden["totales"], _nombres_vatia(td["total"])
        )
        clave = ("mercado", "submercado", "estrato", "nivel_tension")
        por_grupo = {tuple(f[c] for c in clave): _nombres_vatia(f) for f in td["filas"]}
        for fila in golden["filas"]:
            grupo = tuple(fila[c] for c in clave)
            fallas += _comparar_dic(
                f"vatia_td_{periodo}{list(grupo)}", fila, por_grupo.get(grupo, {})
            )
        if fallas:
            todas[periodo] = fallas
    assert not todas, f"Periodos con diferencias: {sorted(todas)}"


# Mismos indicadores, nombres del sistema nuevo (los que ya usa la pantalla Comercial).
_NOMBRES_VATIA = {
    "consumo_activa": "consumo_activa_kw",
    "eficiencia": "eficiencia_recaudo",
    "usuarios_con_cartera": "usuarios_cartera",
    "usuarios_con_recaudo": "usuarios_recaudo",
}


def _nombres_vatia(fila: dict[str, Any]) -> dict[str, Any]:
    salida = {_NOMBRES_VATIA.get(k, k): v for k, v in fila.items()}
    if salida.get("eficiencia_recaudo") is None and _num(salida.get("facturacion") or 0) <= 0:
        # Divergencia decidida (§11, Vatia): con notas, un corte con facturación negativa no se
        # interpreta; OPainn publica la razón igual (p. ej., -83,7 % en 202608).
        salida["eficiencia_recaudo"] = _DIVERGENCIA
    return salida


class _Divergencia:
    """Valor que coincide con cualquiera: divergencia documentada con OPainn."""

    def __eq__(self, otro: object) -> bool:
        return True

    __hash__ = object.__hash__

    def __repr__(self) -> str:
        return "divergencia documentada"


_DIVERGENCIA = _Divergencia()


_NOMBRES_RESUMEN = {
    "correctos": "CORRECTO",
    "correcto": "CORRECTO",
    "por_encima": "POR_ENCIMA",
    "por_debajo": "POR_DEBAJO",
    "no_validables": "NO_VALIDABLE",
    "no_validable": "NO_VALIDABLE",
    "requieren_revision": "REQUIERE_REVISION",
    "requiere_revision": "REQUIERE_REVISION",
}


def _paridad_control(db: Session, sede: SedeResumen, codigo: str, periodos: list[str]) -> None:
    from collections import Counter

    ctx = comercial.contexto(db, sede, codigo)
    todas: dict[str, list[str]] = {}
    for periodo in periodos:
        ref = _golden(f"{codigo}_control_{periodo}")
        if ref is None:
            continue
        filas, _ = comercial.filas_control(db, ctx, periodo)
        conteo = Counter(f.estado for f in filas)
        esperado = {
            _NOMBRES_RESUMEN[k]: int(v) for k, v in ref["resumen"].items() if k in _NOMBRES_RESUMEN
        }
        fallas = [
            f"{estado}: OPainn {n} - nuevo {conteo.get(estado, 0)}"
            for estado, n in esperado.items()
            if conteo.get(estado, 0) != n
        ]
        nuevos = {
            f.identificador: (f.estado, f.diferencia) for f in filas if f.estado != "CORRECTO"
        }
        for ident in sorted(set(ref["hallazgos"]) | set(nuevos)):
            estado_ref, dif_ref = ref["hallazgos"].get(ident, ["CORRECTO", None])
            estado_nuevo, dif_nuevo = nuevos.get(ident, ("CORRECTO", None))
            if estado_ref != estado_nuevo:
                fallas.append(f"{ident}: OPainn {estado_ref} - nuevo {estado_nuevo}")
            elif dif_ref is not None and not coincide(float(dif_ref), dif_nuevo):
                fallas.append(f"{ident} diferencia: OPainn {dif_ref} - nuevo {_num(dif_nuevo)}")
        _informe(f"{codigo}_control_{periodo}", len(esperado) + len(ref["hallazgos"]), fallas)
        if fallas:
            todas[periodo] = fallas
    assert not todas, f"Periodos con diferencias: {sorted(todas)}"


def test_paridad_control_tarifario_por_nic(entorno: Session) -> None:
    """Fase 4: «los mismos estados por NIC que OPainn» (acuerdos 2026 de la semilla)."""
    from app.modulos.configuracion import servicio as configuracion

    db = entorno
    montelibano, alcala = _sede(db, "montelibano"), _sede(db, "alcala")
    # Contribuyentes especiales de Afinia (RN-004): catálogo privado de OPainn, cargado con el
    # mismo servicio que usa `python -m app.semillas excepciones`.
    especiales = (
        OPAINN / "datos" / "catalogos" / "afinia" / "excepciones_tarifarias_afinia_2026.json"
    )
    if especiales.is_file():
        documento = json.loads(especiales.read_text(encoding="utf-8"))
        factores = documento["vigencias"]["2026"]["factores_uvt_por_nic"]
        configuracion.reemplazar_excepciones_acuerdo(
            db,
            sede_id=montelibano.id,
            comercializador_codigo="afinia",
            anio=2026,
            factores={str(k): Decimal(str(v)) for k, v in factores.items()},
            fuente="paridad OPainn",
            actor_id=None,
        )
        db.commit()
    _paridad_control(db, montelibano, "afinia", _importar_todo(db, montelibano, "afinia"))
    anexo = OPAINN / "datos" / "catalogos" / "celsia" / "excepciones_tarifarias_celsia_2026.json"
    if anexo.is_file():
        documento = json.loads(anexo.read_text(encoding="utf-8"))
        reglas = {str(c): dict(r) for c, r in documento.get("reglas_por_cuenta", {}).items()}
        for cuenta in documento.get("pendientes_revision") or []:
            reglas[str(cuenta)] = {"pendiente_revision": True}
        configuracion.reemplazar_excepciones_acuerdo(
            db,
            sede_id=alcala.id,
            comercializador_codigo="celsia",
            anio=2026,
            reglas=reglas,
            fuente="paridad OPainn",
            actor_id=None,
        )
        db.commit()
    _paridad_control(db, alcala, "celsia", _importar_todo(db, alcala, "celsia"))
