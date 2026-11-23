"""Servicio público del módulo de archivos y evidencias (F3-1)."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import obtener_configuracion
from app.modulos.archivos import dominio, repositorio
from app.modulos.archivos.esquemas import ArchivoSalida, CategoriaArchivo, EvidenciaSalida
from app.modulos.archivos.modelos import Archivo, Evidencia


def _obtener_almacen() -> repositorio.AlmacenArchivos:
    config = obtener_configuracion()
    return repositorio.AlmacenLocal(config.archivos_dir)


def _a_archivo_salida(archivo: Archivo) -> ArchivoSalida:
    return ArchivoSalida(
        id=archivo.id,
        sede_id=archivo.sede_id,
        nombre_original=archivo.nombre_original,
        tipo_mime=archivo.tipo_mime,
        tamano=archivo.tamano,
        sha256=archivo.sha256,
        creado_en=archivo.creado_en,
    )


def _traducir_error(exc: dominio.ErrorDominioArchivo) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


async def leer_upload_con_limite(
    archivo: UploadFile, categoria: CategoriaArchivo
) -> bytes:
    config = obtener_configuracion()
    try:
        limite = dominio.calcular_limite_bytes(
            categoria, config.archivo_max_evidencia_mb, config.archivo_max_general_mb
        )
    except dominio.ErrorDominioArchivo as exc:
        raise _traducir_error(exc) from exc

    acumulado = bytearray()
    while True:
        bloque = await archivo.read(dominio.TAMANO_BLOQUE_LECTURA)
        if not bloque:
            break
        if len(acumulado) + len(bloque) > limite:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"El archivo excede el tamaño máximo permitido "
                    f"({limite // (1024 * 1024)} MiB)."
                ),
            )
        acumulado.extend(bloque)

    if not acumulado:
        raise HTTPException(status_code=400, detail="El archivo está vacío (0 bytes).")
    return bytes(acumulado)


def guardar_archivo(
    db: Session,
    *,
    sede_id: int,
    archivo_bytes: bytes,
    nombre: str,
    categoria: CategoriaArchivo = "evidencia",
    idempotency_key: str | None = None,
    subido_por_id: int,
) -> tuple[ArchivoSalida, bool]:
    config = obtener_configuracion()
    try:
        limite = dominio.calcular_limite_bytes(
            categoria, config.archivo_max_evidencia_mb, config.archivo_max_general_mb
        )
        if not archivo_bytes:
            raise dominio.ErrorDominioArchivo(400, "El archivo está vacío (0 bytes).")
        if len(archivo_bytes) > limite:
            raise dominio.ErrorDominioArchivo(
                413,
                f"El archivo excede el tamaño máximo permitido ({limite // (1024 * 1024)} MiB).",
            )
        nombre_seguro = dominio.sanitizar_nombre_archivo(nombre)
        tipo_mime = dominio.detectar_mime_por_magic_bytes(archivo_bytes, nombre_seguro)
        dominio.validar_mime_para_categoria(tipo_mime, categoria)
    except dominio.ErrorDominioArchivo as exc:
        raise _traducir_error(exc) from exc

    sha256_hex = dominio.calcular_sha256_hex(archivo_bytes)
    key_limpia = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
    if key_limpia and len(key_limpia) > 128:
        raise HTTPException(status_code=422, detail="Idempotency-Key excede 128 caracteres.")

    if key_limpia is not None:
        existente = repositorio.obtener_por_idempotency_key(db, sede_id, key_limpia)
        if existente is not None:
            if existente.sha256 != sha256_hex:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key ya fue utilizada con un contenido diferente.",
                )
            return _a_archivo_salida(existente), False

    ahora = datetime.now(UTC)
    ruta_relativa = dominio.construir_ruta_relativa(sede_id, sha256_hex, ahora)
    almacen = _obtener_almacen()
    almacen.guardar(ruta_relativa, archivo_bytes)

    nuevo = Archivo(
        id=uuid4(),
        sede_id=sede_id,
        nombre_original=nombre_seguro,
        tipo_mime=tipo_mime,
        tamano=len(archivo_bytes),
        sha256=sha256_hex,
        ruta=ruta_relativa,
        idempotency_key=key_limpia,
        creado_por=subido_por_id,
    )
    try:
        repositorio.crear_archivo(db, nuevo)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if key_limpia is not None:
            existente = repositorio.obtener_por_idempotency_key(db, sede_id, key_limpia)
            if existente is not None:
                if existente.sha256 != sha256_hex:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency-Key ya fue utilizada con un contenido diferente.",
                    ) from exc
                return _a_archivo_salida(existente), False
        raise
    db.refresh(nuevo)
    return _a_archivo_salida(nuevo), True


def obtener_metadatos_archivo(db: Session, sede_id: int, archivo_id: UUID) -> ArchivoSalida:
    archivo = repositorio.obtener_por_id(db, archivo_id)
    if archivo is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
    if archivo.sede_id != sede_id:
        raise HTTPException(status_code=403, detail="El archivo pertenece a otra sede.")
    return _a_archivo_salida(archivo)


def obtener_archivo_verificado(
    db: Session, sede_id: int, archivo_id: UUID
) -> tuple[ArchivoSalida, bytes]:
    archivo = repositorio.obtener_por_id(db, archivo_id)
    if archivo is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
    if archivo.sede_id != sede_id:
        raise HTTPException(status_code=403, detail="El archivo pertenece a otra sede.")
    almacen = _obtener_almacen()
    try:
        contenido = almacen.leer(archivo.ruta)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="El contenido del archivo no se encuentra disponible."
        ) from exc
    return _a_archivo_salida(archivo), contenido


def construir_cabeceras_descarga(meta: ArchivoSalida, descargar: bool) -> dict[str, str]:
    return {
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": dominio.construir_content_disposition(
            meta.nombre_original, meta.tipo_mime, descargar
        ),
        "ETag": f'"{meta.sha256}"',
        "Cache-Control": "private, max-age=3600",
    }


def registrar_evidencia(
    db: Session,
    *,
    sede_id: int,
    entidad: str,
    entidad_id: str,
    tipo: str,
    archivo_id: UUID,
    creado_por: int,
    latitud: float | None = None,
    longitud: float | None = None,
    capturada_en: datetime | None = None,
) -> EvidenciaSalida:
    archivo = repositorio.obtener_por_id(db, archivo_id)
    if archivo is None:
        raise HTTPException(status_code=404, detail="Archivo de evidencia no encontrado.")
    if archivo.sede_id != sede_id:
        raise HTTPException(status_code=403, detail="El archivo pertenece a otra sede.")

    if (latitud is None) != (longitud is None):
        raise HTTPException(
            status_code=422,
            detail="Debe proporcionar tanto latitud como longitud, o ninguna de las dos.",
        )

    geom_wkt: str | None = None
    if latitud is not None and longitud is not None:
        if not (-90.0 <= latitud <= 90.0 and -180.0 <= longitud <= 180.0):
            raise HTTPException(status_code=422, detail="Coordenadas geográficas fuera de rango.")
        geom_wkt = f"SRID=4326;POINT({longitud} {latitud})"

    evidencia = Evidencia(
        sede_id=sede_id,
        entidad=entidad,
        entidad_id=str(entidad_id),
        tipo=tipo,
        archivo_id=archivo_id,
        geom=geom_wkt,
        capturada_en=capturada_en,
        creado_por=creado_por,
    )
    repositorio.crear_evidencia(db, evidencia)
    db.commit()
    db.refresh(evidencia)
    return EvidenciaSalida(
        id=evidencia.id,
        sede_id=evidencia.sede_id,
        entidad=evidencia.entidad,
        entidad_id=evidencia.entidad_id,
        tipo=evidencia.tipo,
        archivo_id=evidencia.archivo_id,
        latitud=latitud,
        longitud=longitud,
        capturada_en=evidencia.capturada_en,
        creado_en=evidencia.creado_en,
    )
