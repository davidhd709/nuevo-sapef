"""Servicio público del módulo de migración (RF-110 a RF-112).

La API solo recibe los archivos, los guarda y encola la ejecución (`recibir`); el worker la
procesa (`procesar_ejecucion`). Cada fila (o cada PQRS / orden) va en su propia transacción
anidada: una fila inválida queda en el informe de errores y no detiene ni deshace el resto.

Importadores (todos repetibles por llave natural):
- `luminarias` (HU-025): plantilla nueva o `LUMINARIAS_LIST_DESCARGA` de SAPEF (CSV con `;`).
- `base` (IMP-6): zonas, barrios y usuarios sin contraseña.
- `pqrs` (HU-034): plantilla nueva o `LUMINARIAS_REPARAR` de SAPEF.
- `ordenes` (HU-046): las 4 exportaciones de SAPEF (o la plantilla nueva) → órdenes cerradas.
- `inventario` (HU-053): materiales, kárdex inicial y luminarias en bodega, con conciliación.
"""

import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.tareas import encolar
from app.modulos.activos import servicio as activos
from app.modulos.archivos import servicio as archivos
from app.modulos.atencion import servicio as atencion
from app.modulos.configuracion import servicio as configuracion
from app.modulos.inventario import servicio as inventario
from app.modulos.migracion import dominio, repositorio
from app.modulos.migracion.esquemas import EjecucionMigracionSalida
from app.modulos.migracion.modelos import EjecucionMigracion
from app.modulos.seguridad import servicio as seguridad
from app.modulos.seguridad.servicio import SedeResumen, UsuarioAutenticado
from app.modulos.trabajos import servicio as trabajos

log = logging.getLogger("sapef.migracion")

TAREA_PROCESAR = "migracion.procesar_ejecucion"
ZONA_COLOMBIA = timezone(timedelta(hours=-5), "America/Bogota")
MAX_DETALLES = 1000  # tope de errores y advertencias guardados por ejecución
COMMIT_CADA = 500  # filas entre confirmaciones (deja ver el avance y libera memoria)

PERMISOS: dict[str, str] = {
    "luminarias": "activos.luminaria.crear",
    "base": "seguridad.usuario.crear",
    "pqrs": "atencion.pqrs.crear",
    "ordenes": "trabajos.orden.cerrar",
    "inventario": "inventario.material.editar",
}
CAMPOS_ORDENES = ("mantenimientos", "expansiones", "modernizaciones", "reubicaciones")


# === Recepción (API) ============================================================================


def _a_salida(ej: EjecucionMigracion, tarea_id: int | None = None) -> EjecucionMigracionSalida:
    return EjecucionMigracionSalida(
        id=ej.id,
        ejecucion_id=ej.id,
        ejecucionId=ej.id,
        tarea_id=tarea_id,
        tareaId=tarea_id,
        tipo=ej.tipo,
        estado=ej.estado,
        archivos=[a.get("nombre", "") for a in ej.archivos],
        conciliacion={k: int(v) for k, v in ej.conciliacion.items()},
        errores=list(ej.errores),
        advertencias=list(ej.advertencias),
        creado_en=ej.creado_en,
        procesado_en=ej.procesado_en,
    )


async def recibir(
    db: Session,
    actor: UsuarioAutenticado,
    sede: SedeResumen,
    tipo: str,
    archivos_subidos: list[tuple[str, UploadFile]],
) -> EjecucionMigracionSalida:
    """Guarda los archivos (categoría «cargue»), crea la ejecución pendiente y la encola."""
    if not archivos_subidos:
        raise HTTPException(status_code=422, detail="Adjunte al menos un archivo.")
    guardados: list[dict[str, Any]] = []
    for campo_form, subido in archivos_subidos:
        contenido = await archivos.leer_upload_con_limite(subido, "cargue")
        nombre = subido.filename or f"{campo_form}.xlsx"
        meta, _ = archivos.guardar_archivo(
            db,
            sede_id=sede.id,
            archivo_bytes=contenido,
            nombre=nombre,
            categoria="cargue",
            subido_por_id=actor.id,
        )
        guardados.append({"campo": campo_form, "archivo_id": str(meta.id), "nombre": nombre})

    ejecucion = EjecucionMigracion(
        sede_id=sede.id,
        tipo=tipo,
        estado="pendiente",
        archivos=guardados,
        creado_por=actor.id,
    )
    repositorio.crear_ejecucion(db, ejecucion)
    seguridad.registrar_auditoria(
        db,
        usuario_id=actor.id,
        sede_id=sede.id,
        accion=f"importar_{tipo}",
        entidad="ejecucion_migracion",
        entidad_id=str(ejecucion.id),
        despues={"archivos": [g["nombre"] for g in guardados]},
    )
    db.commit()
    db.refresh(ejecucion)
    tarea_id = await encolar(TAREA_PROCESAR, ejecucion_id=ejecucion.id)
    return _a_salida(ejecucion, tarea_id=tarea_id)


def obtener_ejecucion(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, ejecucion_id: int
) -> EjecucionMigracionSalida:
    ej = repositorio.obtener_ejecucion(db, sede.id, ejecucion_id)
    if ej is None:
        raise HTTPException(status_code=404, detail="Ejecución de migración no encontrada.")
    seguridad.verificar_permiso(actor, PERMISOS.get(ej.tipo, "activos.luminaria.crear"))
    return _a_salida(ej)


def _puede(actor: UsuarioAutenticado, permiso: str) -> bool:
    try:
        seguridad.verificar_permiso(actor, permiso)
    except HTTPException:
        return False
    return True


def listar_ejecuciones(
    db: Session, actor: UsuarioAutenticado, sede: SedeResumen, limite: int = 50
) -> list[EjecucionMigracionSalida]:
    """Las últimas ejecuciones de la sede de los tipos que el usuario puede importar."""
    tipos = [t for t, permiso in PERMISOS.items() if _puede(actor, permiso)]
    if not tipos:
        raise HTTPException(status_code=403, detail="No tiene permiso para importar datos.")
    return [_a_salida(ej) for ej in repositorio.listar_ejecuciones(db, sede.id, tipos, limite)]


# === Procesamiento (worker) =====================================================================


@dataclass
class _Informe:
    conciliacion: dict[str, int] = field(default_factory=dict)
    errores: list[dict[str, Any]] = field(default_factory=list)
    advertencias: list[dict[str, Any]] = field(default_factory=list)
    n_errores: int = 0
    n_advertencias: int = 0

    def sumar(self, clave: str, n: int = 1) -> None:
        self.conciliacion[clave] = self.conciliacion.get(clave, 0) + n

    def error(self, fila: int | None, detalle: str, **extra: Any) -> None:
        self.n_errores += 1
        if len(self.errores) < MAX_DETALLES:
            self.errores.append({"fila": fila, "detalle": detalle, **extra})

    def advertir(self, fila: int | None, detalle: str, **extra: Any) -> None:
        self.n_advertencias += 1
        if len(self.advertencias) < MAX_DETALLES:
            self.advertencias.append({"fila": fila, "detalle": detalle, **extra})


class _FilaInvalida(Exception):
    def __init__(self, detalle: str) -> None:
        super().__init__(detalle)
        self.detalle = detalle


def _detalle_de(exc: Exception) -> str:
    if isinstance(exc, _FilaInvalida):
        return exc.detalle
    detalle = getattr(exc, "detail", None)
    if isinstance(detalle, str):
        return detalle
    if isinstance(exc, (ValueError, ArithmeticError)):
        return f"Dato inválido: {exc}"
    return f"Error inesperado al procesar la fila ({type(exc).__name__})."


@contextmanager
def _fila(ctx: "_Contexto", numero: int | None, **extra: Any) -> Iterator[None]:
    """Transacción anidada por fila: si falla, se deshace solo esa fila y se anota el error."""
    ctx.empezar_fila()
    try:
        with ctx.db.begin_nested():
            yield
    except Exception as exc:
        ctx.deshacer_fila()
        if not isinstance(exc, (_FilaInvalida, HTTPException, dominio.ErrorDominioMigracion)):
            log.warning(
                "fila de migración con error inesperado",
                extra={"fila": numero, "error": type(exc).__name__},
            )
        ctx.informe.error(numero, _detalle_de(exc), **extra)


def _con_zona(momento: datetime | None) -> datetime | None:
    if momento is None:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=ZONA_COLOMBIA)


def procesar_ejecucion(db: Session, ejecucion_id: int) -> str:
    ej = repositorio.obtener_ejecucion_por_id(db, ejecucion_id)
    if ej is None or ej.estado != "pendiente":
        return f"ejecucion:{ejecucion_id}:omitida"
    ej.estado = "procesando"
    db.commit()
    sede_id, tipo, actor_id = ej.sede_id, ej.tipo, ej.creado_por
    informe = _Informe()
    estado = "completado"
    try:
        hojas_por_campo: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for adjunto in ej.archivos:
            _, contenido = archivos.obtener_archivo_verificado(
                db, sede_id, uuid.UUID(adjunto["archivo_id"])
            )
            try:
                hojas_por_campo[adjunto["campo"]] = dominio.leer_tabla(contenido)
            except dominio.ErrorDominioMigracion as exc:
                raise _FilaInvalida(f"{adjunto['nombre']}: {exc.detail}") from exc
        importador = _IMPORTADORES[tipo]
        importador(_Contexto(db, sede_id, actor_id, informe), hojas_por_campo)
        if informe.n_errores:
            estado = "con_errores"
    except Exception as exc:
        db.rollback()
        estado = "error"
        if not isinstance(exc, (_FilaInvalida, HTTPException)):
            log.exception("ejecución de migración fallida", extra={"ejecucion_id": ejecucion_id})
        informe.error(None, _detalle_de(exc))

    ej = repositorio.obtener_ejecucion_por_id(db, ejecucion_id)
    assert ej is not None
    informe.conciliacion["errores"] = informe.n_errores
    informe.conciliacion["advertencias"] = informe.n_advertencias
    ej.estado = estado
    ej.conciliacion = informe.conciliacion
    ej.errores = informe.errores
    ej.advertencias = informe.advertencias
    ej.procesado_en = datetime.now(UTC)
    db.commit()
    log.info(
        "migración procesada",
        extra={"ejecucion_id": ejecucion_id, "tipo": tipo, "estado": estado},
    )
    return f"ejecucion:{ejecucion_id}:{estado}"


class _Contexto:
    """Sesión, sede, informe y catálogos con caché (consultados una vez por ejecución)."""

    def __init__(self, db: Session, sede_id: int, actor_id: int | None, informe: _Informe) -> None:
        self.db = db
        self.sede_id = sede_id
        self.actor_id = actor_id
        self.informe = informe
        self._estados: dict[str, dict[str, tuple[str, int]]] = {}
        self._maestros: dict[tuple[str, str], int | None] = {}
        self._barrios: dict[str, int | None] = {}
        self._luminarias: dict[str, int] | None = None
        self._filas_desde_commit = 0
        # Lo que se guardó en caché dentro de la fila en curso: si la fila se deshace, los
        # catálogos recién creados también se deshacen y no deben quedar en caché.
        self._cache_fila: list[tuple[dict[Any, Any], Any]] = []

    def empezar_fila(self) -> None:
        self._cache_fila = []

    def deshacer_fila(self) -> None:
        for cache, llave in self._cache_fila:
            cache.pop(llave, None)
        self._cache_fila = []

    def _recordar(self, cache: dict[Any, Any], llave: Any, valor: Any) -> None:
        cache[llave] = valor
        self._cache_fila.append((cache, llave))

    def avanzar(self) -> None:
        """Confirma cada COMMIT_CADA filas: lo ya importado queda aunque el resto falle."""
        self._filas_desde_commit += 1
        if self._filas_desde_commit >= COMMIT_CADA:
            self.db.commit()
            self._filas_desde_commit = 0

    def estado_con_id(self, proceso: str, valor: Any) -> tuple[str, int] | None:
        """(código, id) a partir del código («121») o del nombre («Bodega de baja»)."""
        if valor is None or str(valor).strip() == "":
            return None
        if proceso not in self._estados:
            mapa: dict[str, tuple[str, int]] = {}
            for e in configuracion.listar_estados(self.db, proceso):
                mapa[dominio.clave_texto(e.codigo)] = (e.codigo, e.id)
                mapa.setdefault(dominio.clave_texto(e.nombre), (e.codigo, e.id))
            self._estados[proceso] = mapa
        txt = str(int(valor)) if isinstance(valor, float) and valor.is_integer() else str(valor)
        return self._estados[proceso].get(dominio.clave_texto(txt))

    def estado(self, proceso: str, valor: Any) -> str | None:
        encontrado = self.estado_con_id(proceso, valor)
        return encontrado[0] if encontrado else None

    def maestro(self, clase: str, codigo: str | None, nombre: str | None = None) -> int | None:
        """Id del valor; si no existe lo crea (marcas, tecnologías y potencias de SAPEF)."""
        if not codigo:
            return None
        llave = (clase, codigo)
        if llave not in self._maestros:
            valor = configuracion.asegurar_valor_maestro(
                self.db, clase, codigo, nombre or codigo.title(), actor_id=self.actor_id
            )
            self._recordar(self._maestros, llave, valor["id"])
        return self._maestros[llave]

    def maestro_existente(self, clase: str, codigo: str | None) -> int | None:
        if not codigo:
            return None
        llave = (clase, codigo)
        if llave not in self._maestros:
            valor = configuracion.obtener_valor_maestro(self.db, clase, codigo=codigo)
            self._maestros[llave] = valor["id"] if valor else None
        return self._maestros[llave]

    def barrio(self, nombre: str | None, zona: str | None = None, *, crear: bool) -> int | None:
        if not nombre:
            return None
        llave = dominio.clave_texto(nombre)
        if llave in ("BODEGA", "SIN BARRIO", "N/A", "NA"):
            return None  # SAPEF usa «BODEGA» como barrio de las luminarias guardadas
        if llave not in self._barrios or (self._barrios[llave] is None and crear):
            encontrado = configuracion.resolver_barrio_por_nombre(self.db, self.sede_id, nombre)
            if encontrado is None and crear:
                encontrado = configuracion.asegurar_zona_y_barrio(
                    self.db, self.sede_id, zona or "General", nombre, actor_id=self.actor_id
                )
            self._recordar(self._barrios, llave, encontrado["id"] if encontrado else None)
        return self._barrios[llave]

    def luminaria(self, codigo: str | None) -> int | None:
        """Id por código (sin distinguir mayúsculas). Las luminarias de la sede se cargan una
        vez: los importadores que la usan no crean luminarias."""
        if not codigo:
            return None
        if self._luminarias is None:
            self._luminarias = activos.ids_luminarias_por_codigo(self.db, self.sede_id)
        return self._luminarias.get(codigo.strip().lower())


def _obligatorio(valor: Any, detalle: str) -> Any:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        raise _FilaInvalida(detalle)
    return valor


def _fecha(valor: Any) -> date | None:
    try:
        return dominio.normalizar_fecha_sapef(valor)
    except dominio.ErrorDominioMigracion as exc:
        raise _FilaInvalida(exc.detail) from exc


def _momento(valor: Any) -> datetime | None:
    try:
        return _con_zona(dominio.normalizar_fecha_hora_sapef(valor))
    except dominio.ErrorDominioMigracion as exc:
        raise _FilaInvalida(exc.detail) from exc


def _coords(
    ctx: _Contexto, n: int, fila: dict[str, Any], *, opcionales: bool = False
) -> tuple[float | None, float | None]:
    """Coordenadas de la fila. Con `opcionales` (historia de órdenes), unas coordenadas
    inválidas se descartan con advertencia en lugar de rechazar la fila."""
    try:
        lat, lng, aviso = dominio.coordenadas_colombia(
            dominio.campo(fila, "latitud", "lat"), dominio.campo(fila, "longitud", "lng", "lon")
        )
    except dominio.ErrorDominioMigracion as exc:
        if not opcionales:
            raise _FilaInvalida(exc.detail) from exc
        ctx.informe.advertir(n, f"{exc.detail} Se importó sin ubicación.")
        return None, None
    if aviso:
        ctx.informe.advertir(n, aviso)
    return lat, lng


def _numero_opcional(ctx: _Contexto, n: int, fila: dict[str, Any], columna: str) -> float | None:
    try:
        return dominio.numero(dominio.campo(fila, columna))
    except dominio.ErrorDominioMigracion as exc:
        ctx.informe.advertir(n, f"{columna}: {exc.detail} Se dejó vacío.")
        return None


# --- Luminarias (HU-025) -------------------------------------------------------------------------


def _importar_luminarias(ctx: _Contexto, hojas: dict[str, dict[str, list[dict[str, Any]]]]) -> None:
    filas = dominio.hoja(next(iter(hojas.values())), "Luminarias")
    inf = ctx.informe
    inf.conciliacion.update(leidas=len(filas), creadas=0, actualizadas=0)
    vistos: set[str] = set()
    for n, fila in enumerate(filas, start=2):
        codigo = dominio.texto(fila, "codigo", "codigo_luminaria")
        with _fila(ctx, n, codigo=codigo):
            codigo = _obligatorio(codigo, "Falta el código de luminaria.")
            if codigo.lower() in vistos:  # la base compara códigos sin mayúsculas
                inf.sumar("repetidas_en_archivo")
                inf.advertir(
                    n, "Código repetido en el archivo; se tomó la primera fila.", codigo=codigo
                )
                continue
            vistos.add(codigo.lower())
            estado_txt = dominio.campo(fila, "estado", "estado_codigo", "id_estado") or "121"
            estado = ctx.estado_con_id("luminaria", estado_txt)
            if estado is None:
                raise _FilaInvalida(f"Estado desconocido: {estado_txt}")
            zona = dominio.texto(fila, "zona")
            es_rural = dominio.campo(fila, "es_rural", "ind_rural")
            rural = (
                dominio.es_si(es_rural)
                if es_rural is not None
                else dominio.clave_texto(zona) in ("RURAL", "RURALES")
            )
            pot = dominio.normalizar_codigo_potencia(dominio.campo(fila, "potencia"))
            if dominio.potencia_atipica(pot):
                inf.sumar("potencia_atipica")
                inf.advertir(
                    n,
                    f"Potencia atípica ({pot} W > {dominio.POTENCIA_ATIPICA_W} W); revísela.",
                    codigo=codigo,
                )
            lat, lng = _coords(ctx, n, fila)
            if lat is None:
                inf.sumar("sin_coordenadas")
            tipo_int = dominio.texto(fila, "tipo_intervencion")
            tipo_int_cod = dominio.clave_texto(tipo_int).replace(" ", "_") if tipo_int else None
            tipo_int_id = ctx.maestro_existente("TIPO_INTERVENCION", tipo_int_cod)
            if tipo_int and tipo_int_id is None:
                inf.advertir(n, f"Tipo de intervención desconocido: {tipo_int}", codigo=codigo)
            marca = dominio.normalizar_codigo_marca(dominio.campo(fila, "marca"))
            tecnologia = dominio.normalizar_codigo_tecnologia(dominio.campo(fila, "tecnologia"))
            datos = {
                "barrio_id": ctx.barrio(dominio.texto(fila, "barrio"), zona, crear=True),
                "marca_id": ctx.maestro("LUMINARIA_MARCA", marca),
                "tecnologia_id": ctx.maestro("LUMINARIA_TECNOLOGIA", tecnologia),
                "potencia_id": ctx.maestro("LUMINARIA_POTENCIA", pot, f"{pot} W"),
            }
            _, creada = activos.asegurar_luminaria_importada(
                ctx.db,
                sede_id=ctx.sede_id,
                codigo=codigo,
                codigo_externo=dominio.texto(fila, "codigo_externo", "mac"),
                latitud=lat,
                longitud=lng,
                estado_id=estado[1],
                tipo_intervencion_id=tipo_int_id,
                fecha_instalacion=_fecha(dominio.campo(fila, "fecha_instalacion")),
                fecha_mision=_fecha(dominio.campo(fila, "fecha_mision")),
                fecha_baja=_fecha(dominio.campo(fila, "fecha_baja")),
                poste=dominio.texto(fila, "poste"),
                es_rural=rural,
                actor_id=ctx.actor_id,
                **datos,
            )
            inf.sumar("creadas" if creada else "actualizadas")
        ctx.avanzar()
    inf.conciliacion["distintas_en_archivo"] = len(vistos)


# --- Base: zonas, barrios y usuarios (IMP-6) ------------------------------------------------------


def _importar_base(ctx: _Contexto, hojas: dict[str, dict[str, list[dict[str, Any]]]]) -> None:
    libro = next(iter(hojas.values()))
    inf = ctx.informe
    sede = configuracion.listar_sedes_activas_resumen(ctx.db)
    codigo_sede = next((s["codigo"] for s in sede if s["id"] == ctx.sede_id), "")
    zb = dominio.hoja(libro, "ZonasBarrios", "Barrios") if len(libro) > 1 else []
    usuarios = dominio.hoja(libro, "Usuarios") if len(libro) > 1 else []
    if len(libro) == 1:  # un solo archivo: se decide por sus columnas
        unica = next(iter(libro.values()))
        if unica and "nombre_usuario" in unica[0]:
            usuarios = unica
        else:
            zb = unica
    inf.conciliacion.update(leidas=len(zb) + len(usuarios), creadas=0, actualizadas=0)

    for n, fila in enumerate(zb, start=2):
        with _fila(ctx, n, hoja="ZonasBarrios"):
            sede_fila = (dominio.texto(fila, "sede_codigo", "sede") or codigo_sede).lower()
            if sede_fila != codigo_sede:
                raise _FilaInvalida("La sede de la fila no coincide con X-Sede.")
            zona = _obligatorio(dominio.texto(fila, "zona"), "Falta la zona.")
            barrio = _obligatorio(dominio.texto(fila, "barrio", "nombre"), "Falta el barrio.")
            existia = configuracion.resolver_barrio_por_nombre(ctx.db, ctx.sede_id, barrio)
            configuracion.asegurar_zona_y_barrio(
                ctx.db, ctx.sede_id, zona, barrio, actor_id=ctx.actor_id
            )
            inf.sumar("actualizadas" if existia else "creadas")
            inf.sumar("barrios")

    ignoradas = dominio.columnas_clave(usuarios)
    if ignoradas:
        inf.advertir(
            None,
            "Se ignoraron las columnas de contraseña "
            f"({', '.join(ignoradas)}): cada usuario define la suya en el primer ingreso.",
            hoja="Usuarios",
        )
    for n, fila in enumerate(usuarios, start=2):
        usuario = dominio.texto(fila, "nombre_usuario", "usuario", "login")
        with _fila(ctx, n, hoja="Usuarios", usuario=usuario):
            correo = dominio.texto(fila, "correo", "email")
            rol = (dominio.texto(fila, "rol_codigo", "rol") or "").upper()
            if not (usuario and correo and rol):
                raise _FilaInvalida("Faltan datos obligatorios (usuario, correo y rol).")
            sede_ids: list[int] = []
            for codigo in (dominio.texto(fila, "sedes", "sede") or codigo_sede).split(","):
                info = configuracion.obtener_sede_por_codigo_publico(ctx.db, codigo.strip())
                if info is not None:
                    sede_ids.append(info["id"])
            _, creado = seguridad.crear_o_actualizar_usuario_importado(
                ctx.db,
                nombre_usuario=usuario,
                nombre_completo=dominio.texto(fila, "nombre_completo", "nombre") or usuario,
                identificacion=dominio.normalizar_identificacion(
                    dominio.campo(fila, "identificacion", "cedula")
                )
                or "0",
                correo=correo,
                rol_codigo=rol,
                sede_ids=sede_ids or [ctx.sede_id],
                actor_id=ctx.actor_id,
            )
            inf.sumar("creadas" if creado else "actualizadas")
            inf.sumar("usuarios")


# --- PQRS (HU-034) -------------------------------------------------------------------------------


_COL_NUMERO_PQRS = ("numero_origen", "numero_pqrs", "consecutivo", "numero_radicado")


def _importar_pqrs(ctx: _Contexto, hojas: dict[str, dict[str, list[dict[str, Any]]]]) -> None:
    filas = dominio.hoja(next(iter(hojas.values())), "PQRS", "Luminarias_reparar")
    inf = ctx.informe
    inf.conciliacion.update(leidas=len(filas), creadas=0, existentes=0, ciudadanos_nuevos=0)
    canal_sapef: int | None = None

    # SAPEF exporta una fila por PQRS × luminaria. Sin número de PQRS (LUMINARIAS_REPARAR) se
    # agrupan las filas del mismo solicitante registradas en el mismo instante.
    grupos: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for n, fila in enumerate(filas, start=2):
        numero = dominio.texto(fila, *_COL_NUMERO_PQRS)
        if numero is None:
            ident = dominio.normalizar_identificacion(
                dominio.campo(fila, "identificacion_solicitante", "identificacion_ciudadano")
            )
            creada = dominio.texto(fila, "fecha_creacion", "fecha_reporte", "fecha_registro")
            numero = f"{ident or 'anonimo'}|{creada or n}"
        grupos.setdefault(numero, []).append((n, fila))

    for llave, lineas in grupos.items():
        n0, f0 = lineas[0]
        rowids = [dominio.texto(f, "rowid_pqrs", "rowid") for _, f in lineas]
        id_origen = (
            llave
            if dominio.texto(f0, *_COL_NUMERO_PQRS)
            else f"SAPEF-{min((r for r in rowids if r), key=_orden_natural, default=llave)}"
        )
        with _fila(ctx, n0, pqrs=id_origen):
            if atencion.pqrs_importada(ctx.db, ctx.sede_id, id_origen) is not None:
                inf.sumar("existentes")
                continue
            canal_txt = dominio.texto(f0, "canal", "canal_codigo", "medio")
            if canal_txt:
                canal = ctx.maestro_existente("CANAL_PQRS", dominio.clave_texto(canal_txt))
                if canal is None:
                    raise _FilaInvalida(f"Canal de PQRS desconocido: {canal_txt}")
            else:
                if canal_sapef is None:
                    canal_sapef = ctx.maestro("CANAL_PQRS", "SAPEF", "Migrada de SAPEF")
                canal = canal_sapef
            luminarias: list[dict[str, Any]] = []
            for n, fila in lineas:
                codigo = dominio.texto(fila, "luminaria_codigo", "codigo", "codigo_luminaria")
                lum_id = ctx.luminaria(codigo)
                if lum_id is None:
                    inf.error(
                        n,
                        f"La luminaria {codigo or '(vacía)'} no existe en la sede.",
                        pqrs=id_origen,
                    )
                    continue
                reparacion = _momento(dominio.campo(fila, "fecha_reparacion"))
                reparada_txt = dominio.campo(fila, "reparada")
                luminarias.append(
                    {
                        "luminaria_id": lum_id,
                        "reparada": (
                            dominio.es_si(reparada_txt)
                            if reparada_txt is not None
                            else reparacion is not None
                        ),
                        "fecha_reparacion": reparacion,
                        "observacion_solicitante": dominio.texto(
                            fila, "observacion", "observacion_solicitante"
                        ),
                        "observacion_tecnico": dominio.texto(fila, "observacion_tecnico"),
                        "estado_reportado_codigo": ctx.estado(
                            "luminaria", dominio.campo(fila, "estado_reportado")
                        ),
                    }
                )
            if not luminarias:
                raise _FilaInvalida("Ninguna luminaria de la PQRS existe en la sede.")
            estado_txt = dominio.campo(f0, "estado_pqrs", "estado", "id_estado_pqrs")
            if estado_txt is not None:
                estado = ctx.estado("pqrs", estado_txt)
                if estado is None:
                    raise _FilaInvalida(f"Estado de PQRS desconocido: {estado_txt}")
            else:  # LUMINARIAS_REPARAR: pendientes, salvo que ya estén todas reparadas
                estado = "303" if all(lum["reparada"] for lum in luminarias) else "301"
            ciudadano_id = _ciudadano(ctx, f0)
            try:
                prioridad = dominio.normalizar_prioridad(dominio.campo(f0, "prioridad"))
            except dominio.ErrorDominioMigracion as exc:
                raise _FilaInvalida(exc.detail) from exc
            atencion.importar_pqrs_historica(
                ctx.db,
                sede_id=ctx.sede_id,
                id_origen=id_origen,
                canal_id=canal,
                fecha_solicitud=_momento(
                    dominio.campo(f0, "fecha_registro", "fecha_reporte", "fecha_creacion")
                ),
                prioridad=prioridad,
                estado_codigo=estado,
                ciudadano_id=ciudadano_id,
                observacion_solicitante=dominio.texto(
                    f0, "observacion_general_solicitante", "observacion_solicitante"
                ),
                luminarias=luminarias,
                actor_id=ctx.actor_id,
            )
            inf.sumar("creadas")
            inf.sumar("luminarias_reportadas", len(luminarias))
        ctx.avanzar()
    inf.conciliacion["pqrs_en_archivo"] = len(grupos)


def _orden_natural(valor: str) -> tuple[int, str]:
    return (int(valor), "") if valor.isdigit() else (1 << 62, valor)


def _ciudadano(ctx: _Contexto, fila: dict[str, Any]) -> int | None:
    ident = dominio.normalizar_identificacion(
        dominio.campo(fila, "identificacion_ciudadano", "identificacion_solicitante")
    )
    if ident is None:
        return None
    ciudadano_id, nuevo = atencion.asegurar_ciudadano_importado(
        ctx.db,
        sede_id=ctx.sede_id,
        identificacion=ident,
        nombre_completo=dominio.texto(fila, "nombre_ciudadano", "nombre_completo_solicitante")
        or ident,
        barrio_id=ctx.barrio(dominio.texto(fila, "barrio_solicitante"), crear=False),
        sector=dominio.texto(fila, "sector_solicitante", "sector"),
        telefono=dominio.texto(fila, "telefono", "telefono_solicitante"),
        celular=dominio.texto(fila, "celular", "celular_solicitante"),
        correo=dominio.texto(fila, "correo", "email_solicitante"),
        actor_id=ctx.actor_id,
    )
    if nuevo:
        ctx.informe.sumar("ciudadanos_nuevos")
    return ciudadano_id


# --- Órdenes históricas (HU-046) -----------------------------------------------------------------

_COMPONENTES = (
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
_TIPO_POR_CAMPO = {
    "mantenimientos": "mantenimiento",
    "expansiones": "expansion",
    "modernizaciones": "modernizacion",
    "reubicaciones": "reubicacion",
}


def _tipo_de_archivo(campo_form: str, filas: list[dict[str, Any]]) -> str | None:
    if campo_form in _TIPO_POR_CAMPO:
        return _TIPO_POR_CAMPO[campo_form]
    columnas = set(filas[0]) if filas else set()
    if "codigo_mantenimiento" in columnas or "fotocelda" in columnas:
        return "mantenimiento"
    if "destino" in columnas or "destino_desmontada" in columnas:
        return "reubicacion"
    if {"li_codigo", "luminaria_desmontada_codigo"} & columnas:
        return "modernizacion"
    if "rowid_luminaria" in columnas or "luminaria_instalada_codigo" in columnas:
        return "expansion"
    return None


def _subtipo(valor: str | None, prefijo: str) -> str | None:
    """«EXPANSION COMPLEMENTARIA» → «COMPLEMENTARIA»."""
    if not valor:
        return None
    limpio = dominio.clave_texto(valor)
    return limpio.removeprefix(prefijo).strip().replace(" ", "_") or None


def _importar_ordenes(ctx: _Contexto, hojas: dict[str, dict[str, list[dict[str, Any]]]]) -> None:
    inf = ctx.informe
    inf.conciliacion.update(leidas=0, creadas=0, existentes=0)
    for campo_form, libro in hojas.items():
        filas = dominio.hoja(libro, campo_form)
        tipo = _tipo_de_archivo(campo_form, filas)
        if tipo is None:
            inf.error(None, f"No se reconoce el tipo de órdenes del archivo «{campo_form}».")
            continue
        inf.sumar("leidas", len(filas))
        inf.sumar(f"leidas_{tipo}", len(filas))
        for n, fila in enumerate(filas, start=2):
            id_fila = dominio.texto(fila, "id_origen", "codigo_mantenimiento", "rowid")
            with _fila(ctx, n, archivo=campo_form, id_origen=id_fila):
                id_fila = _obligatorio(id_fila, "Falta el identificador de la orden en SAPEF.")
                if _importar_orden(ctx, n, tipo, f"{tipo}:{id_fila}", fila):
                    inf.sumar("creadas")
                    inf.sumar(f"creadas_{tipo}")
                else:
                    inf.sumar("existentes")
            ctx.avanzar()


def _luminaria_obligatoria(ctx: _Contexto, codigo: str | None, rol: str) -> int:
    lum_id = ctx.luminaria(codigo)
    if lum_id is None:
        raise _FilaInvalida(f"La luminaria {rol} {codigo or '(vacía)'} no existe en la sede.")
    return lum_id


def _importar_orden(
    ctx: _Contexto, n: int, tipo: str, id_origen: str, fila: dict[str, Any]
) -> bool:
    """Crea la orden histórica; False si ya existía (importador repetible)."""
    lat, lng = _coords(ctx, n, fila, opcionales=True)
    cierre = _momento(dominio.campo(fila, "fecha_cierre", "fecha", "fecha_creacion"))
    estado = ctx.estado_con_id("orden", dominio.campo(fila, "estado") or "203")
    if estado is None:
        raise _FilaInvalida(f"Estado de orden desconocido: {dominio.campo(fila, 'estado')}")
    mantenimiento: dict[str, Any] | None = None
    instalacion: dict[str, Any] | None = None
    comentario = dominio.texto(fila, "comentario", "observaciones", "descripcion")

    if tipo == "mantenimiento":
        luminarias = [
            (
                _luminaria_obligatoria(
                    ctx, dominio.texto(fila, "luminaria_codigo", "codigo"), "intervenida"
                ),
                "intervenida",
            )
        ]
        mantenimiento = {
            "sitio_arreglo": dominio.texto(fila, "sitio_arreglo"),
            "quien_recibe": dominio.texto(fila, "quien_recibe"),
            "observacion_tecnica": dominio.texto(fila, "observacion_tecnica", "observaciones"),
            "requiere_desmonte": dominio.es_si(dominio.campo(fila, "requiere_desmonte")),
            "causal_desmonte": dominio.texto(fila, "causal_desmonte", "desmonte"),
            "componentes": {c: dominio.es_si(dominio.campo(fila, c)) for c in _COMPONENTES},
        }
    else:
        instalada = _luminaria_obligatoria(
            ctx,
            dominio.texto(fila, "luminaria_instalada_codigo", "li_codigo", "codigo"),
            "instalada",
        )
        luminarias = [(instalada, "instalada")]
        if tipo in ("modernizacion", "reubicacion"):
            desmontada = _luminaria_obligatoria(
                ctx,
                dominio.texto(fila, "luminaria_desmontada_codigo", "ld_codigo"),
                "desmontada",
            )
            luminarias.append((desmontada, "desmontada"))
        clase = {"expansion": "TIPO_EXPANSION", "modernizacion": "TIPO_MODERNIZACION"}.get(tipo)
        subtipo_txt = dominio.texto(fila, f"tipo_{tipo}", "tipo")
        tipo_valor = None
        if clase:
            tipo_valor = ctx.maestro_existente(clase, _subtipo(subtipo_txt, tipo.upper()))
            if subtipo_txt and tipo_valor is None:
                ctx.informe.advertir(n, f"Tipo de {tipo} desconocido: {subtipo_txt}")
        destino_txt = dominio.texto(fila, "destino_desmontada", "destino")
        destino = ctx.estado("luminaria", destino_txt) if destino_txt else None
        if destino_txt and destino is None:
            comentario = "; ".join(x for x in (comentario, f"Destino en SAPEF: {destino_txt}") if x)
        brazo = _numero_opcional(ctx, n, fila, "longitud_brazo")
        instalacion = {
            "tipo_valor_id": tipo_valor,
            "barrio_id": ctx.barrio(dominio.texto(fila, "barrio"), crear=False),
            "marca_id": ctx.maestro(
                "LUMINARIA_MARCA", dominio.normalizar_codigo_marca(dominio.campo(fila, "marca"))
            ),
            "poste": dominio.texto(fila, "poste"),
            "longitud_brazo": Decimal(str(brazo)) if brazo else None,
            "referencia": dominio.texto(fila, "referencia"),
            "novedades": dominio.texto(fila, "novedades"),
            "destino_desmontada": destino,
            "comentario": comentario,
        }

    _, creada = trabajos.importar_orden_historica(
        ctx.db,
        sede_id=ctx.sede_id,
        id_origen=id_origen,
        tipo=tipo,
        estado_id=estado[1],
        luminarias=luminarias,
        fecha_programada=_fecha(dominio.campo(fila, "fecha_programada")),
        fecha_ejecucion=cierre,
        latitud=lat,
        longitud=lng,
        observaciones="Migrada de SAPEF." if not comentario else f"Migrada de SAPEF. {comentario}",
        mantenimiento=mantenimiento,
        instalacion=instalacion,
        actor_id=ctx.actor_id,
    )
    return creada


# --- Inventario (HU-053) -------------------------------------------------------------------------

_TIPOS_KARDEX = {
    "ENTRADA": "entrada",
    "ENTRADA_ALMACEN": "entrada",
    "SALIDA": "salida",
    "SALIDA_ALMACEN": "salida",
    "AJUSTE": "ajuste",
}
_ESPACIO_UUID = uuid.UUID("6f1d7c1e-4d0a-4a8e-9b1a-5a9e0c3b7d21")


def _uuid_migracion(sede_id: int, llave: str) -> uuid.UUID:
    return uuid.uuid5(_ESPACIO_UUID, f"{sede_id}:{llave}")


def _importar_inventario(ctx: _Contexto, hojas: dict[str, dict[str, list[dict[str, Any]]]]) -> None:
    libro = next(iter(hojas.values()))
    inf = ctx.informe
    materiales = dominio.hoja(libro, "Materiales", "Insumos")
    movimientos = dominio.hoja(libro, "Movimientos", "Kardex") if len(libro) > 1 else []
    bodega = dominio.hoja(libro, "Bodega", "Luminarias_bodega") if len(libro) > 1 else []
    inf.conciliacion.update(
        leidas=len(materiales) + len(movimientos) + len(bodega),
        creadas=0,
        actualizadas=0,
        movimientos_aplicados=0,
        luminarias_bodega=0,
    )

    esperado: dict[str, Decimal] = {}
    for n, fila in enumerate(materiales, start=2):
        codigo = dominio.texto(fila, "codigo", "codigo_material")
        with _fila(ctx, n, hoja="Materiales", codigo=codigo):
            codigo = _obligatorio(codigo, "Falta el código del material.")
            try:
                minimas = dominio.decimal_no_negativo(
                    dominio.campo(fila, "existencias_minimas", "minimo", "stock_minimo") or 0,
                    "las existencias mínimas",
                )
                cantidad_txt = dominio.campo(fila, "existencias", "cantidad", "stock")
                cantidad = (
                    dominio.decimal_no_negativo(cantidad_txt, "las existencias")
                    if cantidad_txt is not None
                    else None
                )
            except dominio.ErrorDominioMigracion as exc:
                raise _FilaInvalida(exc.detail) from exc
            _, creado = inventario.asegurar_material_importado(
                ctx.db,
                sede_id=ctx.sede_id,
                codigo=codigo,
                categoria=dominio.texto(fila, "categoria", "clase") or "GENERAL",
                descripcion=_obligatorio(
                    dominio.texto(fila, "descripcion", "nombre"), "Falta la descripción."
                ),
                unidad=dominio.texto(fila, "unidad", "unidad_medida") or "UND",
                existencias_minimas=minimas,
                actor_id=ctx.actor_id,
            )
            if cantidad is not None:
                esperado[codigo] = cantidad
            inf.sumar("creadas" if creado else "actualizadas")

    con_movimientos: set[str] = set()
    for n, fila in enumerate(movimientos, start=2):
        codigo = dominio.texto(fila, "material_codigo", "codigo_material", "codigo")
        with _fila(ctx, n, hoja="Movimientos", codigo=codigo):
            codigo = _obligatorio(codigo, "Falta el código del material.")
            tipo_txt = dominio.clave_texto(dominio.campo(fila, "tipo")).replace(" ", "_")
            tipo = _TIPOS_KARDEX.get(tipo_txt)
            if tipo is None:
                raise _FilaInvalida(f"Tipo de movimiento desconocido: {tipo_txt or '(vacío)'}")
            cantidad = dominio.numero(dominio.campo(fila, "cantidad"))
            if cantidad is None:
                raise _FilaInvalida("Falta la cantidad.")
            con_movimientos.add(codigo.lower())
            llave = dominio.texto(fila, "uuid_origen", "id_origen", "rowid") or f"fila{n}:{codigo}"
            aplicado = inventario.aplicar_movimiento_importado(
                ctx.db,
                sede_id=ctx.sede_id,
                material_codigo=codigo,
                tipo=tipo,
                cantidad=Decimal(str(cantidad)),
                descripcion=dominio.texto(fila, "descripcion") or "Migrado de SAPEF",
                uuid_origen=_uuid_migracion(ctx.sede_id, f"kardex:{llave}"),
                actor_id=ctx.actor_id,
            )
            inf.sumar("movimientos_aplicados" if aplicado else "movimientos_existentes")

    # Sin kárdex en el archivo, las existencias del material entran como saldo inicial.
    for codigo, cantidad in esperado.items():
        if codigo.lower() in con_movimientos or cantidad <= 0:
            continue
        with _fila(ctx, None, hoja="Materiales", codigo=codigo):
            if inventario.aplicar_movimiento_importado(
                ctx.db,
                sede_id=ctx.sede_id,
                material_codigo=codigo,
                tipo="entrada",
                cantidad=cantidad,
                descripcion="Saldo inicial migrado de SAPEF",
                uuid_origen=_uuid_migracion(ctx.sede_id, f"saldo:{codigo.lower()}"),
                actor_id=ctx.actor_id,
            ):
                inf.sumar("saldos_iniciales")

    for codigo, cantidad in esperado.items():
        final = inventario.existencias_material(ctx.db, ctx.sede_id, codigo)
        if final is None:
            continue
        if final == cantidad:
            inf.sumar("existencias_conciliadas")
        else:
            inf.sumar("existencias_con_diferencia")
            inf.advertir(
                None,
                f"Existencias de {codigo}: el archivo dice {cantidad.normalize():f} y el kárdex "
                f"da {final.normalize():f}.",
                hoja="Materiales",
                codigo=codigo,
            )

    for n, fila in enumerate(bodega, start=2):
        codigo = dominio.texto(fila, "luminaria_codigo", "codigo")
        with _fila(ctx, n, hoja="Bodega", codigo=codigo):
            lum_id = _luminaria_obligatoria(ctx, codigo, "de bodega")
            estado_txt = dominio.campo(fila, "estado_codigo", "estado") or "124"
            estado = ctx.estado("luminaria", estado_txt)
            if estado is None:
                raise _FilaInvalida(f"Estado desconocido: {estado_txt}")
            inventario.fijar_estado_bodega_importado(
                ctx.db,
                sede_id=ctx.sede_id,
                luminaria_id=lum_id,
                estado_codigo=estado,
                observacion=dominio.texto(fila, "observacion"),
                actor_id=ctx.actor_id,
            )
            inf.sumar("luminarias_bodega")


_IMPORTADORES: dict[
    str, Callable[[_Contexto, dict[str, dict[str, list[dict[str, Any]]]]], None]
] = {
    "luminarias": _importar_luminarias,
    "base": _importar_base,
    "pqrs": _importar_pqrs,
    "ordenes": _importar_ordenes,
    "inventario": _importar_inventario,
}
