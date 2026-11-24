// Base local de la app de campo (IndexedDB con Dexie). Todo lo que el técnico necesita para
// trabajar sin señal vive aquí, y lo que hace sin señal espera en la bandeja de salida (`outbox`)
// hasta que el servidor confirma cada operación por su uuid.
import type { components } from "@sapef/api";
import Dexie, { type Table } from "dexie";

export type Paquete = components["schemas"]["PaqueteCampo"];
export type OrdenCampo = components["schemas"]["OrdenCampo"];
export type LuminariaCampo = components["schemas"]["LuminariaCampo"];
export type MaterialCampo = components["schemas"]["MaterialCampo"];
export type CatalogosCampo = components["schemas"]["CatalogosCampo"];
export type PerfilActual = components["schemas"]["PerfilActual"];

export const NOMBRE_BASE = "sapef-campo";

export type TipoEvidencia =
  | "foto"
  | "firma_tecnico"
  | "firma_oficial"
  | "firma_quien_recibe"
  | "audio"
  | "adjunto";

/** Archivo capturado en el teléfono (foto comprimida, firma, audio). Se sube aparte, con
 * reintentos, usando su uuid como Idempotency-Key. */
export interface ArchivoLocal {
  uuid: string;
  opUuid: string;
  tipo: TipoEvidencia;
  nombre: string;
  mime: string;
  datos: Blob;
  /** Id del archivo en el servidor, cuando ya subió. */
  archivoId?: string;
  error?: string;
}

/** Operación en la bandeja de salida. Los campos `uuid`, `tipo`, `ordenId`, `creadaEn` y
 * `payload` son el contrato de POST /campo/sincronizar. */
export interface OperacionPendiente {
  uuid: string;
  tipo: string;
  ordenId: number;
  ordenNumero: number;
  creadaEn: string;
  payload: Record<string, unknown>;
  evidencias: { archivoUuid: string; tipo: TipoEvidencia }[];
  sede: string;
  usuarioId: number;
  intentos: number;
  ultimoError?: string;
}

export interface ConflictoLocal extends OperacionPendiente {
  estado: "conflicto" | "error";
  motivo: string;
  recibidoEn: string;
}

export interface AvisoLocal {
  id?: number;
  texto: string;
  creadoEn: string;
}

export interface Meta {
  clave: string;
  valor: unknown;
}

class BaseCampo extends Dexie {
  outbox!: Table<OperacionPendiente, string>;
  archivos!: Table<ArchivoLocal, string>;
  ordenes!: Table<OrdenCampo, number>;
  luminarias!: Table<LuminariaCampo, number>;
  bodega!: Table<LuminariaCampo, number>;
  materiales!: Table<MaterialCampo, number>;
  conflictos!: Table<ConflictoLocal, string>;
  avisos!: Table<AvisoLocal, number>;
  meta!: Table<Meta, string>;

  constructor() {
    super(NOMBRE_BASE);
    this.version(1).stores({
      outbox: "uuid, creadaEn, usuarioId, ordenId",
      archivos: "uuid, opUuid",
      ordenes: "id",
      luminarias: "id, codigo",
      bodega: "id, codigo",
      materiales: "id",
      conflictos: "uuid, ordenId",
      avisos: "++id",
      meta: "clave",
    });
  }
}

export const db = new BaseCampo();

export async function leerMeta<T>(clave: string): Promise<T | undefined> {
  return (await db.meta.get(clave))?.valor as T | undefined;
}

export async function guardarMeta(clave: string, valor: unknown): Promise<void> {
  await db.meta.put({ clave, valor });
}

/** Borra lo descargado (no la bandeja de salida ni los conflictos). */
export async function limpiarDescargas(): Promise<void> {
  await db.transaction(
    "rw",
    [db.ordenes, db.luminarias, db.bodega, db.materiales, db.avisos, db.meta],
    async () => {
      await Promise.all([
        db.ordenes.clear(),
        db.luminarias.clear(),
        db.bodega.clear(),
        db.materiales.clear(),
        db.avisos.clear(),
        db.meta.clear(),
      ]);
    },
  );
}

/** UUID v4 generado en el teléfono (idempotencia de operaciones y archivos). */
export function nuevoUuid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = ((b[6] ?? 0) & 0x0f) | 0x40;
  b[8] = ((b[8] ?? 0) & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
