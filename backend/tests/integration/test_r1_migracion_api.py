"""R1: importadores en el worker con las exportaciones de SAPEF (formato real, datos inventados).

Cubre: la API solo encola (202 «pendiente»); el worker procesa; filas inválidas quedan en el
informe sin 500 y sin deshacer el resto; idempotencia; potencias atípicas; columnas de clave
ignoradas; PQRS agrupadas desde LUMINARIAS_REPARAR; las 4 tablas de órdenes; inventario con
conciliación; aislamiento por sede de las ejecuciones.
"""

import io
from typing import Any

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modulos.migracion import servicio as migracion
from tests.conftest import crear_usuario_db, iniciar_sesion_cliente

MT = {"X-Sede": "montelibano"}
CSV = "text/csv"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _csv(*lineas: str, sep: str = "\t", bom: bool = False) -> bytes:
    cuerpo = "\r\n".join(lineas) + "\r\n"
    if sep == ";":
        cuerpo = "sep=;\r\n" + cuerpo
    return (("﻿" if bom else "") + cuerpo).encode()


def _xlsx(hojas: dict[str, list[list[Any]]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for nombre, filas in hojas.items():
        ws = wb.create_sheet(nombre)
        for fila in filas:
            ws.append(fila)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _importar(
    cliente: TestClient, db: Session, ruta: str, files: Any, sede: dict[str, str] = MT
) -> dict[str, Any]:
    r = cliente.post(f"/api/v1/migracion/{ruta}", headers=sede, files=files)
    assert r.status_code == 202, r.text
    cuerpo = r.json()
    assert cuerpo["estado"] == "pendiente"
    assert isinstance(cuerpo["tareaId"], int)
    args = db.execute(
        text("SELECT task_name, args FROM procrastinate_jobs WHERE id = :i"),
        {"i": cuerpo["tareaId"]},
    ).one()
    assert args.task_name == migracion.TAREA_PROCESAR
    assert args.args == {"ejecucion_id": cuerpo["ejecucion_id"]}  # solo ids en la cola
    migracion.procesar_ejecucion(db, cuerpo["ejecucion_id"])
    final = cliente.get(f"/api/v1/migracion/ejecuciones/{cuerpo['ejecucion_id']}", headers=sede)
    assert final.status_code == 200
    return final.json()


def _luminarias_sapef() -> bytes:
    return _csv(
        "codigo;barrio;fecha_instalacion;tipo_intervencion;potencia;marca;tecnologia;estado;zona;"
        "latitud;longitud",
        "R1-001;R1 Barrio Norte;18/02/2019;RECIBO INICIAL;70;SILVANIA;SODIO;"
        "Activo en operación;Norte;7.98195;-75.41606",
        # Repetida (SAPEF duplica la fila cuando el barrio está en dos zonas)
        "R1-001;R1 Barrio Norte;18/02/2019;RECIBO INICIAL;70;SILVANIA;SODIO;"
        "Activo en operación;Sur;7.98195;-75.41606",
        "R1-002;BODEGA;22/01/2020;MODERNIZACION PRIORITARIA;4893;KUNIX;MH;Bodega de baja;;;",
        "R1-003;R1 Vereda;01/01/1900;EXPANSION;100;;LED;Activo en operación;Rurales;7.97;-75.42",
        "R1-004;R1 Barrio Norte;fecha-mala;BODEGA;70;;LED;Activo en operación;Norte;;",
        "R1-005;R1 Barrio Norte;18/02/2019;BODEGA;70;;LED;Estado inexistente;Norte;;",
        ";R1 Barrio Norte;18/02/2019;BODEGA;70;;LED;Activo en operación;Norte;;",
        "R1-006;R1 Barrio Norte;18/02/2019;BODEGA;70;;LED;Bodega buena;Norte;;",
        "R1-007;R1 Barrio Norte;18/02/2019;BODEGA;70;;LED;Bodega buena;Norte;;",
        "R1-008;R1 Barrio Norte;18/02/2019;RECIBO INICIAL;70;;LED;Activo en operación;Norte;;",
        "R1-009;R1 Barrio Norte;18/02/2019;RECIBO INICIAL;70;;LED;Activo en operación;Norte;;",
        "R1-010;R1 Barrio Norte;18/02/2019;RECIBO INICIAL;70;;LED;Activo en operación;Norte;;",
        "R1-011;R1 Barrio Norte;18/02/2019;RECIBO INICIAL;70;;LED;Activo en operación;Norte;;",
        sep=";",
        bom=True,
    )


def _preparar(cliente: TestClient, db: Session) -> None:
    crear_usuario_db(
        db,
        nombre_usuario="admin_r1",
        correo="admin_r1@sapef.local",
        rol_codigo="ADMIN",
        sede_codigos=["montelibano", "alcala"],
    )
    iniciar_sesion_cliente(cliente, "admin_r1")


def test_luminarias_desde_csv_de_sapef_filas_invalidas_sin_500_e_idempotente(
    cliente: TestClient, db_configurado: Session
) -> None:
    _preparar(cliente, db_configurado)
    res = _importar(
        cliente,
        db_configurado,
        "luminarias",
        {"archivo": ("LUMINARIAS_LIST_DESCARGA.csv", _luminarias_sapef(), CSV)},
    )
    assert res["estado"] == "con_errores", res
    c = res["conciliacion"]
    assert c["leidas"] == 13
    assert c["creadas"] == 9
    assert c["errores"] == 3  # fecha inválida, estado desconocido, código vacío
    assert c["repetidas_en_archivo"] == 1
    assert c["potencia_atipica"] == 1
    detalles = " ".join(e["detalle"] for e in res["errores"])
    assert "fecha" in detalles.lower() and "Estado desconocido" in detalles
    assert any("atípica" in a["detalle"] for a in res["advertencias"])

    lum = cliente.get("/api/v1/luminarias", headers=MT, params={"texto": "R1-002"}).json()
    item = lum["items"][0]
    assert item["estado_codigo"] == "123"
    assert item["barrio_id"] is None  # «BODEGA» no es un barrio
    rural = cliente.get("/api/v1/luminarias", headers=MT, params={"texto": "R1-003"}).json()
    assert rural["items"][0]["es_rural"] is True
    assert rural["items"][0]["fecha_instalacion"] is None  # 01/01/1900

    # Se crea el barrio con la zona de SAPEF
    barrios = cliente.get("/api/v1/barrios", headers=MT).json()
    assert any(b["nombre"].upper() == "R1 BARRIO NORTE" for b in barrios)

    # Repetir: nada nuevo
    res2 = _importar(
        cliente,
        db_configurado,
        "luminarias",
        {"archivo": ("LUMINARIAS_LIST_DESCARGA.csv", _luminarias_sapef(), CSV)},
    )
    assert res2["conciliacion"]["creadas"] == 0
    assert res2["conciliacion"]["actualizadas"] == 9


def test_archivo_ilegible_termina_en_error_y_no_en_500(
    cliente: TestClient, db_configurado: Session
) -> None:
    _preparar(cliente, db_configurado)
    roto = b"PK\x03\x04esto-no-es-un-xlsx" + b"x" * 100
    r = cliente.post(
        "/api/v1/migracion/luminarias",
        headers=MT,
        files={"archivo": ("roto.xlsx", roto, XLSX)},
    )
    if r.status_code == 202:  # el control de archivos lo aceptó: el worker lo marca en error
        migracion.procesar_ejecucion(db_configurado, r.json()["ejecucion_id"])
        final = cliente.get(
            f"/api/v1/migracion/ejecuciones/{r.json()['ejecucion_id']}", headers=MT
        ).json()
        assert final["estado"] == "error"
        assert final["errores"][0]["detalle"]
    else:
        assert r.status_code in (400, 415, 422), r.text


def test_pqrs_desde_luminarias_reparar_agrupa_por_solicitante_y_deduplica_ciudadano(
    cliente: TestClient, db_configurado: Session
) -> None:
    _preparar(cliente, db_configurado)
    _importar(
        cliente, db_configurado, "luminarias", {"archivo": ("lums.csv", _luminarias_sapef(), CSV)}
    )
    encabezado = (
        "rowid_pqrs\trowid_luminaria\tidentificacion_solicitante\tnombre_completo_solicitante\t"
        "barrio_solicitante\tsector_solicitante\ttelefono_solicitante\tcelular_solicitante\t"
        "email_solicitante\tobservacion_general_solicitante\tobservacion\tprioridad\tid_estado\t"
        "codigo\testado_reportado\tfecha_reporte\tfecha_reparacion\tobservacion_tecnico\t"
        "fecha_creacion"
    )
    reparar = _csv(
        encabezado,
        "9001\t1\t11.222.333\tSolicitante Uno\tR1 Barrio Norte\t\t\t3000000001\t\t\tApagada\t"
        "MEDIA\t121\tR1-001\tActivo PQR\t03/09/2026 08:59:37\t1/1/1900 12:00:00 AM\t\t"
        "03/09/2026 08:59:37",
        "9002\t2\t11.222.333\tSolicitante Uno\tR1 Barrio Norte\t\t\t3000000001\t\t\tApagada\t"
        "MEDIA\t121\tR1-008\tActivo PQR\t03/09/2026 08:59:37\t1/1/1900 12:00:00 AM\t\t"
        "03/09/2026 08:59:37",
        # Mismo solicitante, otra PQRS (otro instante), con una luminaria que no existe
        "9003\t3\t11222333\tSolicitante Uno\t\t\t\t3000000001\t\t\tIntermitente\tALTA\t121\t"
        "NO-EXISTE\tActivo PQR\t04/09/2026 10:00:00\t1/1/1900 12:00:00 AM\t\t04/09/2026 10:00:00",
        "9004\t4\t99.888.777\tSolicitante Dos\t\t\t\t\t\t\tColgando\tBAJA\t121\tR1-009\t"
        "Activo PQR\t05/09/2026 07:00:00\t9/6/2026 3:00:00 PM\tSe ajustó\t05/09/2026 07:00:00",
    )
    res = _importar(
        cliente, db_configurado, "pqrs", {"archivo": ("LUMINARIAS_REPARAR.csv", reparar, CSV)}
    )
    c = res["conciliacion"]
    assert c["pqrs_en_archivo"] == 3
    assert c["creadas"] == 2  # la de NO-EXISTE no tiene ninguna luminaria válida
    assert c["ciudadanos_nuevos"] == 2  # 11.222.333 y 11222333 son el mismo
    assert c["luminarias_reportadas"] == 3
    assert res["estado"] == "con_errores"

    pqrs = cliente.get("/api/v1/pqrs", headers=MT, params={"desde": "2026-01-01"}).json()["items"]
    assert len(pqrs) == 2
    atendida = next(p for p in pqrs if p["estado_codigo"] == "303")
    pendiente = next(p for p in pqrs if p["estado_codigo"] == "301")
    assert len(pendiente["luminarias"]) == 2
    assert atendida["luminarias"][0]["reparada"] is True

    again = _importar(
        cliente, db_configurado, "pqrs", {"archivo": ("LUMINARIAS_REPARAR.csv", reparar, CSV)}
    )
    assert again["conciliacion"]["creadas"] == 0
    assert again["conciliacion"]["existentes"] == 2


def test_ordenes_desde_las_4_exportaciones_de_sapef(
    cliente: TestClient, db_configurado: Session
) -> None:
    _preparar(cliente, db_configurado)
    _importar(
        cliente, db_configurado, "luminarias", {"archivo": ("lums.csv", _luminarias_sapef(), CSV)}
    )
    componentes = (
        "conexion_red\tconexion_interna\tbase_fotocelda\tfotocelda\tbombillo\tsocket\t"
        "arrancador\tcondensador\tbalasta\trequiere_desmonte\tconectores_perforacion\ttubo\t"
        "collarin"
    )
    mant = _csv(
        f"codigo\tbarrio\tcodigo mantenimiento\t{componentes}\tdesmonte\tsitio_arreglo\t"
        "observaciones\tquien_recibe\tlatitud\tlongitud\tfecha_creacion",
        "R1-001\tR1 Barrio Norte\t17068\tFalse\tFalse\tFalse\tTrue\tFalse\tFalse\tFalse\tFalse\t"
        "False\tTrue\tFalse\tFalse\tFalse\tReem.Led.Sodio\tCAMPO\tReemplazo\tVecino\t7.979938\t"
        "75.434805\t19/11/2026 11:41:51",
        "NO-EXISTE\tR1 Barrio Norte\t17069\tFalse\tFalse\tFalse\tFalse\tFalse\tFalse\tFalse\t"
        "False\tFalse\tFalse\tFalse\tFalse\tFalse\t\tCAMPO\t\t\t7.97\t-75.43\t19/11/2026 12:00:00",
    )
    exp = _csv(
        "rowid\trowid_luminaria\ttipo\tfecha\tbarrio\tmarca\tposte\tcomentario\tlatitud\t"
        "longitud\tcodigo\tpotencia\ttecnologia\ttipo_intervencion",
        "2011\t12162\tEXPANSION COMPLEMENTARIA\t11/11/2026\tR1 Barrio Norte\tSYLVANIA\t\t\t"
        "7.981521\t-75.411284\tR1-010\t100\tLED\tEXPANSION",
    )
    modern = _csv(
        "rowid\ttipo\tfecha\tbarrio\tmarca\tposte\tlongitud_brazo\tcomentario\tlatitud\tlongitud"
        "\tli_codigo\tld_codigo",
        "4238\tMODERNIZACION COMPLEMENTARIA\t19/11/2026 00:00:00\tR1 Barrio Norte\tSYLVANIA\t\t"
        "1.5\t\t7.973531\t-75.410218\tR1-011\tR1-008",
    )
    reub = _csv(
        "rowid\ttipo\tfecha\tbarrio\treferencia\tnovedades\tlatitud\tlongitud\tdestino\tli_codigo"
        "\tld_codigo",
        "7204\tMONTAJE\t19/11/2026\tR1 Barrio Norte\tReemplazo\tReem.Led.Sodio\t7.979938\t"
        "-75.434805\tCAMPO\tR1-009\tR1-001",
    )
    archivos = [
        ("mantenimientos", ("MANTENIMIENTOS_EXPORTAR.csv", mant, CSV)),
        ("expansiones", ("EXPANSIONES.csv", exp, CSV)),
        ("modernizaciones", ("MODERNIZACIONES.csv", modern, CSV)),
        ("reubicaciones", ("REUBICACIONES.csv", reub, CSV)),
    ]
    res = _importar(cliente, db_configurado, "ordenes", archivos)
    c = res["conciliacion"]
    assert c["leidas"] == 5
    assert c["creadas"] == 4
    assert c["errores"] == 1
    assert {k: c[k] for k in c if k.startswith("creadas_")} == {
        "creadas_mantenimiento": 1,
        "creadas_expansion": 1,
        "creadas_modernizacion": 1,
        "creadas_reubicacion": 1,
    }
    assert any("Longitud" in a["detalle"] for a in res["advertencias"])

    ordenes = cliente.get("/api/v1/ordenes", headers=MT).json()["items"]
    assert len(ordenes) == 4
    assert {o["estado_codigo"] for o in ordenes} == {"203"}
    mant_orden = next(o for o in ordenes if o["tipo"] == "mantenimiento")
    detalle = cliente.get(f"/api/v1/ordenes/{mant_orden['id']}", headers=MT).json()
    assert detalle["mantenimiento"]["componentes"]["fotocelda"] is True
    assert detalle["mantenimiento"]["requiere_desmonte"] is True

    # Históricas: no cambian el estado de las luminarias
    lum = cliente.get("/api/v1/luminarias", headers=MT, params={"texto": "R1-008"}).json()
    assert lum["items"][0]["estado_codigo"] == "121"

    again = _importar(cliente, db_configurado, "ordenes", archivos)
    assert again["conciliacion"]["creadas"] == 0
    assert again["conciliacion"]["existentes"] == 4


def test_inventario_concilia_existencias_y_bodega(
    cliente: TestClient, db_configurado: Session
) -> None:
    _preparar(cliente, db_configurado)
    _importar(
        cliente, db_configurado, "luminarias", {"archivo": ("lums.csv", _luminarias_sapef(), CSV)}
    )
    libro = _xlsx(
        {
            "Materiales": [
                [
                    "codigo",
                    "categoria",
                    "descripcion",
                    "unidad",
                    "existencias",
                    "existencias_minimas",
                ],
                ["R1-MAT-01", "ELECTRICO", "Fotocelda", "UND", 25, 10],
                ["R1-MAT-02", "CABLE", "Cable 2x12", "MTS", 100, 30],
                ["R1-MAT-03", "CABLE", "Cinta", "UND", 7, 0],  # sin kárdex: saldo inicial
                ["R1-MAT-04", "CABLE", "", "UND", 7, 0],  # sin descripción: error de fila
            ],
            "Movimientos": [
                ["material_codigo", "tipo", "cantidad", "descripcion", "uuid_origen"],
                ["R1-MAT-01", "ENTRADA_ALMACEN", 25, "Saldo", "K-1"],
                ["R1-MAT-02", "ENTRADA_ALMACEN", 120, "Saldo", "K-2"],
                ["R1-MAT-02", "SALIDA_ALMACEN", 500, "No alcanza", "K-3"],  # error: negativo
            ],
            "Bodega": [
                ["luminaria_codigo", "estado_codigo", "observacion"],
                ["R1-006", "125", "En garantía"],
                ["R1-007", "Disposición final", ""],
                ["R1-001", "121", ""],  # 121 no es estado de bodega
            ],
        }
    )
    res = _importar(
        cliente, db_configurado, "inventario", {"archivo": ("inventario.xlsx", libro, XLSX)}
    )
    c = res["conciliacion"]
    assert c["creadas"] == 3
    assert c["movimientos_aplicados"] == 2
    assert c["saldos_iniciales"] == 1
    assert c["existencias_conciliadas"] == 2
    assert c["existencias_con_diferencia"] == 1  # R1-MAT-02: 100 vs 120
    assert c["luminarias_bodega"] == 2
    assert c["errores"] == 3

    mats = cliente.get("/api/v1/materiales", headers=MT, params={"buscar": "R1-MAT"}).json()
    existencias = {m["codigo"]: float(m["existencias"]) for m in mats["items"]}
    assert existencias == {"R1-MAT-01": 25.0, "R1-MAT-02": 120.0, "R1-MAT-03": 7.0}

    again = _importar(
        cliente, db_configurado, "inventario", {"archivo": ("inventario.xlsx", libro, XLSX)}
    )
    assert again["conciliacion"]["movimientos_aplicados"] == 0
    assert again["conciliacion"].get("saldos_iniciales", 0) == 0
    mats2 = cliente.get("/api/v1/materiales", headers=MT, params={"buscar": "R1-MAT-01"}).json()
    assert float(mats2["items"][0]["existencias"]) == 25.0


def test_base_ignora_columnas_de_clave_y_aisla_ejecuciones_por_sede(
    cliente: TestClient, db_configurado: Session
) -> None:
    _preparar(cliente, db_configurado)
    libro = _xlsx(
        {
            "ZonasBarrios": [["sede_codigo", "zona", "barrio"], ["alcala", "R1 Zona", "R1 Barrio"]],
            "Usuarios": [
                [
                    "nombre_usuario",
                    "nombre_completo",
                    "identificacion",
                    "correo",
                    "rol_codigo",
                    "sedes",
                    "password",
                ],
                [
                    "r1_tecnico",
                    "Técnico R1",
                    "123",
                    "r1.tecnico@sapef.local",
                    "TECNICO",
                    "alcala",
                    "no-se-importa",
                ],
                ["", "", "", "", "", "", ""],
                ["r1_sin_rol", "Sin rol", "124", "r1.sinrol@sapef.local", "", "alcala", ""],
            ],
        }
    )
    al = {"X-Sede": "alcala"}
    res = _importar(
        cliente, db_configurado, "base", {"archivo": ("base.xlsx", libro, XLSX)}, sede=al
    )
    assert res["conciliacion"]["creadas"] == 2  # un barrio y un usuario
    assert res["conciliacion"]["errores"] == 1
    assert any("contraseña" in a["detalle"] for a in res["advertencias"])
    usuarios = cliente.get("/api/v1/usuarios", params={"buscar": "r1_tecnico"}).json()["items"]
    assert usuarios[0]["debe_cambiar_clave"] is True
    assert "no-se-importa" not in str(res)

    # La ejecución es de Alcalá: desde Montelíbano no existe
    otra = cliente.get(f"/api/v1/migracion/ejecuciones/{res['id']}", headers=MT)
    assert otra.status_code == 404
    lista = cliente.get("/api/v1/migracion/ejecuciones", headers=al).json()
    assert [e["id"] for e in lista] == [res["id"]]


def test_sin_permiso_de_importar_da_403(cliente: TestClient, db_configurado: Session) -> None:
    crear_usuario_db(
        db_configurado,
        nombre_usuario="tec_r1",
        correo="tec_r1@sapef.local",
        rol_codigo="TECNICO",
        sede_codigos=["montelibano"],
    )
    iniciar_sesion_cliente(cliente, "tec_r1")
    r = cliente.post(
        "/api/v1/migracion/pqrs",
        headers=MT,
        files={"archivo": ("x.csv", b"a;b\n1;2\n", CSV)},
    )
    assert r.status_code == 403
    assert cliente.get("/api/v1/migracion/ejecuciones", headers=MT).status_code == 403
