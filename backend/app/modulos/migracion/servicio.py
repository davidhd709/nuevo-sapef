"""Servicio público del módulo de migración (IMP-1, IMP-6)."""

from typing import Any

from fastapi import HTTPException
from procrastinate.exceptions import AppNotOpen
from sqlalchemy.orm import Session

from app.core.tareas import app_tareas
from app.modulos.activos import servicio as activos_servicio
from app.modulos.configuracion import servicio as config_servicio
from app.modulos.migracion import dominio, repositorio
from app.modulos.migracion.esquemas import EjecucionMigracionSalida
from app.modulos.migracion.modelos import EjecucionMigracion
from app.modulos.seguridad import servicio as seguridad_servicio
from app.modulos.seguridad.servicio import SedeResumen, UsuarioAutenticado


def _traducir_error(exc: dominio.ErrorDominioMigracion) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _a_salida(
    ej: EjecucionMigracion, tarea_id: int | None = None
) -> EjecucionMigracionSalida:
    return EjecucionMigracionSalida(
        id=ej.id,
        ejecucion_id=ej.id,
        ejecucionId=ej.id,
        tarea_id=tarea_id,
        tareaId=tarea_id,
        tipo=ej.tipo,
        estado=ej.estado,
        conciliacion=dict(ej.conciliacion),
        errores=list(ej.errores),
        creado_en=ej.creado_en,
    )


async def _encolar_confirmacion(ejecucion_id: int) -> int:
    deferrer = app_tareas.configure_task(name="migracion.confirmar_ejecucion")
    try:
        return int(await deferrer.defer_async(ejecucion_id=ejecucion_id))
    except AppNotOpen:
        async with app_tareas.open_async():
            return int(await deferrer.defer_async(ejecucion_id=ejecucion_id))


async def importar_luminarias_excel(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    archivo_bytes: bytes,
) -> EjecucionMigracionSalida:
    try:
        hojas = dominio.leer_hojas_xlsx(archivo_bytes)
    except dominio.ErrorDominioMigracion as exc:
        raise _traducir_error(exc) from exc

    filas = hojas.get("Luminarias") or next(iter(hojas.values()), [])
    creadas = 0
    actualizadas = 0
    errores: list[dict[str, Any]] = []

    for idx, fila in enumerate(filas, start=2):
        codigo = str(fila.get("codigo") or "").strip()
        if not codigo:
            errores.append({"fila": idx, "detalle": "Falta el código de luminaria."})
            continue

        estado_cod = str(fila.get("estado") or "121").strip()
        estado = config_servicio.obtener_estado_por_id_o_codigo(
            db, "luminaria", codigo=estado_cod
        )
        if estado is None:
            errores.append({"fila": idx, "detalle": f"Estado desconocido: {estado_cod}"})
            continue

        barrio_id: int | None = None
        barrio_txt = str(fila.get("barrio") or "").strip()
        if barrio_txt:
            barrio = config_servicio.resolver_barrio_por_nombre(db, sede.id, barrio_txt)
            if barrio is None:
                barrio = config_servicio.asegurar_zona_y_barrio(
                    db, sede.id, "General", barrio_txt, actor_id=actor.id
                )
            barrio_id = barrio["id"]

        marca_id: int | None = None
        marca_cod = dominio.normalizar_codigo_marca(fila.get("marca"))
        if marca_cod:
            marca_id = config_servicio.asegurar_valor_maestro(
                db, "LUMINARIA_MARCA", marca_cod, marca_cod.title(), actor_id=actor.id
            )["id"]

        tecnologia_id: int | None = None
        tech_cod = dominio.normalizar_codigo_tecnologia(fila.get("tecnologia"))
        if tech_cod:
            tecnologia_id = config_servicio.asegurar_valor_maestro(
                db, "LUMINARIA_TECNOLOGIA", tech_cod, tech_cod.title(), actor_id=actor.id
            )["id"]

        potencia_id: int | None = None
        pot_cod = dominio.normalizar_codigo_potencia(fila.get("potencia"))
        if pot_cod:
            potencia_id = config_servicio.asegurar_valor_maestro(
                db, "LUMINARIA_POTENCIA", pot_cod, f"{pot_cod} W", actor_id=actor.id
            )["id"]

        tipo_int_id: int | None = None
        tipo_int_raw = str(fila.get("tipo_intervencion") or "").strip().upper().replace(" ", "_")
        if tipo_int_raw:
            t_val = config_servicio.obtener_valor_maestro(
                db, "TIPO_INTERVENCION", codigo=tipo_int_raw
            )
            if t_val is not None:
                tipo_int_id = t_val["id"]

        lat = float(fila["latitud"]) if fila.get("latitud") not in (None, "") else None
        lng = float(fila["longitud"]) if fila.get("longitud") not in (None, "") else None
        try:
            f_inst = dominio.normalizar_fecha_sapef(fila.get("fecha_instalacion"))
            f_mision = dominio.normalizar_fecha_sapef(fila.get("fecha_mision"))
            f_baja = dominio.normalizar_fecha_sapef(fila.get("fecha_baja"))
        except dominio.ErrorDominioMigracion as exc:
            errores.append({"fila": idx, "detalle": exc.detail})
            continue

        _, fue_creada = activos_servicio.asegurar_luminaria_importada(
            db,
            sede_id=sede.id,
            codigo=codigo,
            codigo_externo=(
                str(fila["codigo_externo"]).strip() if fila.get("codigo_externo") else None
            ),
            barrio_id=barrio_id,
            latitud=lat,
            longitud=lng,
            estado_id=estado["id"],
            tecnologia_id=tecnologia_id,
            potencia_id=potencia_id,
            marca_id=marca_id,
            tipo_intervencion_id=tipo_int_id,
            fecha_instalacion=f_inst,
            fecha_mision=f_mision,
            fecha_baja=f_baja,
            poste=str(fila["poste"]).strip() if fila.get("poste") else None,
            es_rural=dominio.normalizar_bool(fila.get("es_rural"), False),
            actor_id=actor.id,
        )
        if fue_creada:
            creadas += 1
        else:
            actualizadas += 1

    conciliacion = {
        "leidas": len(filas),
        "creadas": creadas,
        "actualizadas": actualizadas,
        "errores": len(errores),
    }
    ejecucion = EjecucionMigracion(
        sede_id=sede.id,
        tipo="luminarias",
        estado="completado" if not errores else "con_errores",
        conciliacion=conciliacion,
        errores=errores,
        creado_por=actor.id,
    )
    repositorio.crear_ejecucion(db, ejecucion)
    seguridad_servicio.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion="importar_luminarias",
        entidad="ejecucion_migracion",
        entidad_id=str(ejecucion.id),
        despues=conciliacion,
    )
    db.commit()
    db.refresh(ejecucion)
    tarea_id = await _encolar_confirmacion(ejecucion.id)
    return _a_salida(ejecucion, tarea_id=tarea_id)


async def importar_base_config_excel(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    archivo_bytes: bytes,
) -> EjecucionMigracionSalida:
    try:
        hojas = dominio.leer_hojas_xlsx(archivo_bytes)
    except dominio.ErrorDominioMigracion as exc:
        raise _traducir_error(exc) from exc

    creadas = 0
    actualizadas = 0
    errores: list[dict[str, Any]] = []

    zb_filas = hojas.get("ZonasBarrios") or []
    for idx, fila in enumerate(zb_filas, start=2):
        sede_cod = str(fila.get("sede_codigo") or sede.codigo).strip().lower()
        if sede_cod != sede.codigo:
            errores.append(
                {"hoja": "ZonasBarrios", "fila": idx, "detalle": "Sede no coincide con X-Sede."}
            )
            continue
        zona_txt = str(fila.get("zona") or "").strip()
        barrio_txt = str(fila.get("barrio") or "").strip()
        if zona_txt and barrio_txt:
            config_servicio.asegurar_zona_y_barrio(
                db, sede.id, zona_txt, barrio_txt, actor_id=actor.id
            )
            creadas += 1

    u_filas = hojas.get("Usuarios") or []
    for idx, fila in enumerate(u_filas, start=2):
        if any(k in fila for k in ("clave", "password", "hash_clave")):
            raise HTTPException(
                status_code=422,
                detail="El archivo de migración de usuarios no debe incluir contraseñas.",
            )
        usuario_txt = str(fila.get("nombre_usuario") or "").strip()
        correo_txt = str(fila.get("correo") or "").strip()
        rol_cod = str(fila.get("rol_codigo") or "").strip().upper()
        if not (usuario_txt and correo_txt and rol_cod):
            errores.append(
                {"hoja": "Usuarios", "fila": idx, "detalle": "Faltan datos obligatorios."}
            )
            continue
        sedes_raw = str(fila.get("sedes") or sede.codigo)
        sede_ids: list[int] = []
        for sc in sedes_raw.split(","):
            s_info = config_servicio.obtener_sede_por_codigo_publico(db, sc.strip())
            if s_info is not None:
                sede_ids.append(s_info["id"])
        if not sede_ids:
            sede_ids = [sede.id]

        _, fue_creado = seguridad_servicio.crear_o_actualizar_usuario_importado(
            db,
            nombre_usuario=usuario_txt,
            nombre_completo=str(fila.get("nombre_completo") or usuario_txt),
            identificacion=str(fila.get("identificacion") or "0"),
            correo=correo_txt,
            rol_codigo=rol_cod,
            sede_ids=sede_ids,
            actor_id=actor.id,
        )
        if fue_creado:
            creadas += 1
        else:
            actualizadas += 1

    conciliacion = {
        "leidas": len(zb_filas) + len(u_filas),
        "creadas": creadas,
        "actualizadas": actualizadas,
        "errores": len(errores),
    }
    ejecucion = EjecucionMigracion(
        sede_id=sede.id,
        tipo="base",
        estado="completado" if not errores else "con_errores",
        conciliacion=conciliacion,
        errores=errores,
        creado_por=actor.id,
    )
    repositorio.crear_ejecucion(db, ejecucion)
    db.commit()
    db.refresh(ejecucion)
    tarea_id = await _encolar_confirmacion(ejecucion.id)
    return _a_salida(ejecucion, tarea_id=tarea_id)


def obtener_ejecucion(
    db: Session, sede: SedeResumen, ejecucion_id: int
) -> EjecucionMigracionSalida:
    ej = repositorio.obtener_ejecucion(db, sede.id, ejecucion_id)
    if ej is None:
        raise HTTPException(status_code=404, detail="Ejecución de migración no encontrada.")
    return _a_salida(ej)
