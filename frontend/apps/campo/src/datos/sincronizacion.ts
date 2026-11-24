// Motor de sincronización de la app de campo (§9.7).
//
// Subida: primero los archivos (cada uno con su uuid como Idempotency-Key, así un reintento no
// duplica nada), después el lote de operaciones. El servidor responde por operación: aplicada o
// ya_aplicada salen de la bandeja; conflicto o error pasan a «conflictos» para que el técnico
// los vea. Sin señal no se pierde nada: todo queda en la bandeja y se reintenta.
//
// Bajada: paquete completo la primera vez; después solo los cambios desde el cursor.
//
// iOS no tiene sincronización en segundo plano: se sincroniza al abrir, al volver la señal,
// al volver a la app, cada minuto con señal y con el botón «Sincronizar ahora».
import { api, cabeceraSede, mensajeError, pedir, SesionVencida, SinConexion } from "./api";
import {
  db,
  guardarMeta,
  leerMeta,
  type ArchivoLocal,
  type OperacionPendiente,
  type Paquete,
} from "./db";

export const CACHE_MAPA = "sapef-mapa";
const MAX_LOTE = 50;
const RENOVAR_MAPA_MS = 7 * 24 * 3600 * 1000;

export interface Sesion {
  usuarioId: number;
  sede: string;
}

export interface EstadoSincronizacion {
  enCurso: boolean;
  ultimaSincronizacion: string | null;
  ultimoError: string | null;
  sesionVencida: boolean;
}

// --- Estado observable (para la barra de estado) ----------------------------------------------

let estado: EstadoSincronizacion = {
  enCurso: false,
  ultimaSincronizacion: null,
  ultimoError: null,
  sesionVencida: false,
};
const escuchas = new Set<() => void>();

function cambiar(parcial: Partial<EstadoSincronizacion>): void {
  estado = { ...estado, ...parcial };
  escuchas.forEach((f) => f());
}

export function suscribirEstado(f: () => void): () => void {
  escuchas.add(f);
  return () => escuchas.delete(f);
}

export function leerEstado(): EstadoSincronizacion {
  return estado;
}

// --- Sesión activa ----------------------------------------------------------------------------

let sesion: Sesion | null = null;
const alTerminar = new Set<() => void>();

export function fijarSesion(nueva: Sesion | null): void {
  sesion = nueva;
  cambiar({ sesionVencida: false, ultimoError: null });
}

/** Se llama después de cada sincronización correcta (p. ej., para aplicar una actualización). */
export function despuesDeSincronizar(f: () => void): () => void {
  alTerminar.add(f);
  return () => alTerminar.delete(f);
}

// --- Subida -----------------------------------------------------------------------------------

async function subirArchivo(archivo: ArchivoLocal, sede: string): Promise<void> {
  const datos = new FormData();
  datos.append("archivo", new File([archivo.datos], archivo.nombre, { type: archivo.mime }));
  datos.append("categoria", "evidencia");
  const respuesta = await pedir(
    new Request(new URL("/api/v1/archivos", window.location.origin), {
      method: "POST",
      body: datos,
      credentials: "same-origin",
      headers: { ...cabeceraSede(sede), "Idempotency-Key": archivo.uuid },
    }),
  );
  if (respuesta.status === 401) throw new SesionVencida();
  const cuerpo = (await respuesta.json().catch(() => ({}))) as { id?: string };
  if (respuesta.ok && cuerpo.id) {
    await db.archivos.update(archivo.uuid, { archivoId: cuerpo.id, error: undefined });
    return;
  }
  if (respuesta.status >= 500) throw new Error(`El servidor falló (${respuesta.status}).`);
  // 4xx: el servidor rechazó el archivo (tipo o tamaño). Reintentar no cambia nada.
  await db.archivos.update(archivo.uuid, {
    error: mensajeError(cuerpo, `Archivo rechazado (${respuesta.status}).`),
  });
}

/** Sube los archivos pendientes de la operación. Devuelve el motivo si alguno fue rechazado. */
async function prepararArchivos(op: OperacionPendiente): Promise<string | null> {
  const archivos = await db.archivos.where("opUuid").equals(op.uuid).toArray();
  for (const archivo of archivos) {
    if (!archivo.archivoId && !archivo.error) await subirArchivo(archivo, op.sede);
  }
  const rechazado = (await db.archivos.where("opUuid").equals(op.uuid).toArray()).find(
    (a) => a.error,
  );
  return rechazado ? `No se pudo enviar ${rechazado.nombre}: ${rechazado.error}` : null;
}

async function aConflicto(
  op: OperacionPendiente,
  estadoOp: "conflicto" | "error",
  motivo: string,
): Promise<void> {
  await db.transaction("rw", db.outbox, db.conflictos, async () => {
    await db.conflictos.put({ ...op, estado: estadoOp, motivo, recibidoEn: new Date().toISOString() });
    await db.outbox.delete(op.uuid);
  });
}

async function confirmar(op: OperacionPendiente): Promise<void> {
  await db.transaction("rw", [db.outbox, db.archivos, db.ordenes], async () => {
    await db.outbox.delete(op.uuid);
    await db.archivos.where("opUuid").equals(op.uuid).delete();
    await db.ordenes.delete(op.ordenId);
  });
}

async function subirLote(sede: string, ops: OperacionPendiente[]): Promise<void> {
  const porUuid = new Map(ops.map((o) => [o.uuid, o]));
  const operaciones = [];
  for (const op of ops) {
    const archivos = await db.archivos.where("opUuid").equals(op.uuid).toArray();
    const ids = new Map(archivos.map((a) => [a.uuid, a.archivoId]));
    const evidencias = op.evidencias
      .filter((e) => ids.get(e.archivoUuid))
      .map((e) => ({ archivo_id: ids.get(e.archivoUuid) as string, tipo: e.tipo }));
    operaciones.push({
      uuid: op.uuid,
      tipo: op.tipo,
      ordenId: op.ordenId,
      creadaEn: op.creadaEn,
      payload: { ...op.payload, evidencias },
    });
  }
  const { data, error, response } = await api.POST("/api/v1/campo/sincronizar", {
    headers: cabeceraSede(sede),
    body: { operaciones },
  });
  if (response.status === 401) throw new SesionVencida();
  if (!data) throw new Error(mensajeError(error, `El servidor falló (${response.status}).`));
  for (const resultado of data.resultados) {
    const op = porUuid.get(resultado.uuid);
    if (!op) continue;
    if (resultado.estado === "aplicada" || resultado.estado === "ya_aplicada") {
      await confirmar(op);
    } else {
      await aConflicto(op, resultado.estado, resultado.motivo ?? "No se pudo aplicar.");
    }
  }
}

async function subir(actual: Sesion): Promise<void> {
  const pendientes = await db.outbox
    .where("usuarioId")
    .equals(actual.usuarioId)
    .sortBy("creadaEn");
  const listas: OperacionPendiente[] = [];
  for (const op of pendientes) {
    try {
      const rechazo = await prepararArchivos(op);
      if (rechazo) {
        await aConflicto(op, "error", rechazo);
        continue;
      }
      listas.push(op);
    } catch (e) {
      await db.outbox.update(op.uuid, {
        intentos: op.intentos + 1,
        ultimoError: e instanceof Error ? e.message : String(e),
      });
      throw e;
    }
  }
  const porSede = new Map<string, OperacionPendiente[]>();
  for (const op of listas) porSede.set(op.sede, [...(porSede.get(op.sede) ?? []), op]);
  for (const [sede, ops] of porSede) {
    for (let i = 0; i < ops.length; i += MAX_LOTE) await subirLote(sede, ops.slice(i, i + MAX_LOTE));
  }
}

// --- Bajada -----------------------------------------------------------------------------------

function claveCursor(actual: Sesion): string {
  return `cursor:${actual.sede}:${actual.usuarioId}`;
}

const TEXTO_RETIRO: Record<string, string> = {
  anulada: "fue anulada en la oficina",
  reasignada: "fue reasignada a otra persona",
  cerrada: "fue cerrada desde la oficina",
};

async function aplicarPaquete(actual: Sesion, p: Paquete): Promise<void> {
  await db.transaction(
    "rw",
    [db.ordenes, db.luminarias, db.bodega, db.materiales, db.avisos, db.meta],
    async () => {
      const antes = new Set(await db.ordenes.toCollection().primaryKeys());
      await db.ordenes.clear();
      await db.ordenes.bulkPut(p.ordenes_asignadas);
      if (p.completo) await db.luminarias.clear();
      await db.luminarias.bulkPut(p.luminarias_zona);
      await db.bodega.clear();
      await db.bodega.bulkPut(p.luminarias_bodega);
      await db.materiales.clear();
      await db.materiales.bulkPut(p.materiales);
      for (const r of p.ordenes_anuladas_o_reasignadas) {
        if (!antes.has(r.id)) continue; // nunca estuvo en este teléfono, o ya se envió
        await db.avisos.add({
          texto: `La orden N.º ${r.numero} ${TEXTO_RETIRO[r.motivo] ?? r.motivo}.`,
          creadoEn: new Date().toISOString(),
        });
      }
      await db.meta.bulkPut([
        { clave: claveCursor(actual), valor: p.cursor },
        { clave: "catalogos", valor: p.catalogos },
        { clave: "mapaUrl", valor: p.mapa_base.url },
        { clave: "sedeNombre", valor: p.sede.nombre },
        { clave: "ultimaDescarga", valor: p.generado_en },
      ]);
    },
  );
}

async function guardarMapaBase(url: string): Promise<void> {
  if (typeof caches === "undefined") return;
  const cache = await caches.open(CACHE_MAPA);
  const guardado = await leerMeta<string>(`mapaGuardadoEn:${url}`);
  if ((await cache.match(url)) && guardado && Date.now() - Date.parse(guardado) < RENOVAR_MAPA_MS) {
    return;
  }
  const respuesta = await pedir(
    new Request(new URL(url, window.location.origin), { credentials: "same-origin" }),
  );
  if (!respuesta.ok) return;
  await cache.put(url, respuesta);
  await guardarMeta(`mapaGuardadoEn:${url}`, new Date().toISOString());
}

async function bajar(actual: Sesion): Promise<void> {
  const cursor = await leerMeta<string>(claveCursor(actual));
  const { data, response } = await api.GET("/api/v1/campo/paquete", {
    headers: cabeceraSede(actual.sede),
    params: { query: cursor ? { desde: cursor } : {} },
  });
  if (response.status === 401) throw new SesionVencida();
  if (response.status === 422 && cursor) {
    await db.meta.delete(claveCursor(actual)); // cursor de otra versión: descarga completa
    return bajar(actual);
  }
  if (!data) throw new Error(`No se pudo descargar el paquete (${response.status}).`);
  await aplicarPaquete(actual, data);
  // El mapa base es grande: se guarda aparte y su falla no detiene la sincronización.
  await guardarMapaBase(data.mapa_base.url).catch(() => undefined);
}

// --- Orquestación -----------------------------------------------------------------------------

let enCurso: Promise<void> | null = null;

/** Sube lo pendiente y baja lo nuevo. Si ya hay una sincronización en curso, espera esa. */
export function sincronizar(): Promise<void> {
  const actual = sesion;
  if (!actual) return Promise.resolve();
  enCurso ??= (async () => {
    cambiar({ enCurso: true });
    try {
      await subir(actual);
      await bajar(actual);
      cambiar({ ultimaSincronizacion: new Date().toISOString(), ultimoError: null });
      alTerminar.forEach((f) => f());
    } catch (e) {
      if (e instanceof SesionVencida) cambiar({ sesionVencida: true, ultimoError: e.message });
      else if (e instanceof SinConexion) cambiar({ ultimoError: "Sin señal: se enviará al volver." });
      else cambiar({ ultimoError: e instanceof Error ? e.message : String(e) });
    } finally {
      cambiar({ enCurso: false });
      enCurso = null;
    }
  })();
  return enCurso;
}

/** Dispara la sincronización en los momentos útiles. Devuelve la función para detenerlo. */
export function iniciarMotor(intervaloMs = 60_000): () => void {
  const alVolverSenal = () => void sincronizar();
  const alVolverApp = () => {
    if (document.visibilityState === "visible") void sincronizar();
  };
  window.addEventListener("online", alVolverSenal);
  document.addEventListener("visibilitychange", alVolverApp);
  const reloj = window.setInterval(() => {
    if (navigator.onLine) void sincronizar();
  }, intervaloMs);
  void sincronizar();
  return () => {
    window.removeEventListener("online", alVolverSenal);
    document.removeEventListener("visibilitychange", alVolverApp);
    window.clearInterval(reloj);
  };
}

// --- Conflictos -------------------------------------------------------------------------------

/** Devuelve un conflicto a la bandeja (p. ej., tras corregir existencias en la oficina). Los
 * archivos rechazados se descartan para que el resto del trabajo pueda entrar. */
export async function reintentarConflicto(uuid: string): Promise<void> {
  const conflicto = await db.conflictos.get(uuid);
  if (!conflicto) return;
  const rechazados = (await db.archivos.where("opUuid").equals(uuid).toArray()).filter(
    (a) => a.error,
  );
  const quitar = new Set(rechazados.map((a) => a.uuid));
  const { estado: _e, motivo: _m, recibidoEn: _r, ...op } = conflicto;
  await db.transaction("rw", [db.outbox, db.conflictos, db.archivos], async () => {
    await db.archivos.bulkDelete([...quitar]);
    await db.outbox.put({
      ...op,
      evidencias: op.evidencias.filter((e) => !quitar.has(e.archivoUuid)),
      intentos: 0,
      ultimoError: undefined,
    });
    await db.conflictos.delete(uuid);
  });
  void sincronizar();
}

export async function descartarConflicto(uuid: string): Promise<void> {
  await db.transaction("rw", db.conflictos, db.archivos, async () => {
    await db.conflictos.delete(uuid);
    await db.archivos.where("opUuid").equals(uuid).delete();
  });
}
