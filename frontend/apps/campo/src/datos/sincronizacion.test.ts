import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { db, leerMeta, type OperacionPendiente } from "./db";
import { fijarSesion, leerEstado, reintentarConflicto, sincronizar } from "./sincronizacion";

const SESION = { usuarioId: 7, sede: "montelibano" };

function paquete(extra: Record<string, unknown> = {}) {
  return {
    cursor: "cursor-1",
    generado_en: "2026-11-24T10:00:00Z",
    completo: true,
    sede: { codigo: "montelibano", nombre: "Montelíbano" },
    usuario: { id: 7, nombre_completo: "Técnico" },
    ordenes_asignadas: [
      {
        id: 11,
        numero: 3,
        tipo: "mantenimiento",
        estado_codigo: "202",
        estado_nombre: "En proceso",
        prioridad: 1,
        pqrs_id: null,
        fecha_programada: null,
        asignada_en: null,
        observaciones: null,
        modificado_en: "2026-11-24T09:00:00Z",
        luminarias: [],
      },
    ],
    ordenes_anuladas_o_reasignadas: [],
    luminarias_zona: [
      {
        id: 1,
        codigo: "L-1",
        estado_codigo: "121",
        barrio_id: 1,
        poste: null,
        latitud: 7.98,
        longitud: -75.42,
        tecnologia: "LED",
        potencia: "70",
        marca: null,
      },
    ],
    luminarias_bodega: [],
    materiales: [],
    catalogos: {
      barrios: [],
      tipos_expansion: [],
      tipos_modernizacion: [],
      marcas: [],
      componentes: ["bombillo"],
      destinos_desmontada: [],
      tipos_evidencia: ["foto"],
    },
    mapa_base: { url: "/api/v1/mapa/base/montelibano.pmtiles" },
    ...extra,
  };
}

function operacion(uuid: string, ordenId = 10): OperacionPendiente {
  return {
    uuid,
    tipo: "mantenimiento",
    ordenId,
    ordenNumero: 2,
    creadaEn: "2026-11-24T08:00:00Z",
    payload: { sitio_arreglo: "Calle 1", materiales: [] },
    evidencias: [{ archivoUuid: `a-${uuid}`, tipo: "foto" }],
    sede: "montelibano",
    usuarioId: 7,
    intentos: 0,
  };
}

const json = (cuerpo: unknown, status = 200) =>
  new Response(JSON.stringify(cuerpo), { status, headers: { "Content-Type": "application/json" } });

interface Llamada {
  metodo: string;
  ruta: string;
  cabeceras: Headers;
  cuerpo: unknown;
}

function servidor(resultado: (uuid: string) => { estado: string; motivo?: string }) {
  const llamadas: Llamada[] = [];
  const fetchFalso = vi.fn(async (entrada: RequestInfo | URL, init?: RequestInit) => {
    const peticion = entrada instanceof Request ? entrada : new Request(String(entrada), init);
    const url = new URL(peticion.url);
    const tipo = peticion.headers.get("Content-Type") ?? "";
    const cuerpo = tipo.includes("json") ? await peticion.clone().json() : null;
    llamadas.push({ metodo: peticion.method, ruta: url.pathname + url.search, cabeceras: peticion.headers, cuerpo });
    if (url.pathname === "/api/v1/archivos") {
      return json({ id: `srv-${peticion.headers.get("Idempotency-Key")}` }, 201);
    }
    if (url.pathname === "/api/v1/campo/sincronizar") {
      const ops = (cuerpo as { operaciones: { uuid: string }[] }).operaciones;
      return json({
        resultados: ops.map((o) => ({ uuid: o.uuid, ...resultado(o.uuid) })),
        procesado_en: "2026-11-24T10:00:00Z",
      });
    }
    if (url.pathname === "/api/v1/campo/paquete") return json(paquete());
    return json({ detail: "no encontrado" }, 404);
  });
  vi.stubGlobal("fetch", fetchFalso);
  return llamadas;
}

beforeEach(async () => {
  await db.delete();
  await db.open();
  fijarSesion(SESION);
});

afterEach(() => {
  vi.unstubAllGlobals();
  fijarSesion(null);
});

describe("sincronización de campo", () => {
  it("sube archivos con su uuid, envía el lote y baja el paquete", async () => {
    await db.archivos.add({
      uuid: "a-op1",
      opUuid: "op1",
      tipo: "foto",
      nombre: "f.jpg",
      mime: "image/jpeg",
      datos: new Blob(["x"], { type: "image/jpeg" }),
    });
    await db.outbox.add(operacion("op1"));
    const llamadas = servidor(() => ({ estado: "aplicada" }));

    await sincronizar();

    const subida = llamadas.find((l) => l.ruta === "/api/v1/archivos");
    expect(subida?.cabeceras.get("Idempotency-Key")).toBe("a-op1");
    expect(subida?.cabeceras.get("X-Sede")).toBe("montelibano");
    const lote = llamadas.find((l) => l.ruta === "/api/v1/campo/sincronizar");
    expect(lote?.cuerpo).toEqual({
      operaciones: [
        {
          uuid: "op1",
          tipo: "mantenimiento",
          ordenId: 10,
          creadaEn: "2026-11-24T08:00:00Z",
          payload: {
            sitio_arreglo: "Calle 1",
            materiales: [],
            evidencias: [{ archivo_id: "srv-a-op1", tipo: "foto" }],
          },
        },
      ],
    });
    expect(await db.outbox.count()).toBe(0);
    expect(await db.archivos.count()).toBe(0);
    expect((await db.ordenes.toArray()).map((o) => o.id)).toEqual([11]);
    expect(await db.luminarias.count()).toBe(1);
    expect(await leerMeta("cursor:montelibano:7")).toBe("cursor-1");
    expect(leerEstado().ultimoError).toBeNull();

    // La segunda bajada pide solo cambios desde el cursor.
    await sincronizar();
    expect(llamadas.filter((l) => l.ruta.startsWith("/api/v1/campo/paquete")).at(-1)?.ruta).toBe(
      "/api/v1/campo/paquete?desde=cursor-1",
    );
  });

  it("un conflicto sale de la bandeja y queda visible; un error se puede reintentar", async () => {
    await db.outbox.bulkAdd([
      { ...operacion("op-ok"), evidencias: [] },
      { ...operacion("op-anulada", 12), evidencias: [] },
      { ...operacion("op-error", 13), evidencias: [] },
    ]);
    servidor((uuid) =>
      uuid === "op-anulada"
        ? { estado: "conflicto", motivo: "La orden N.º 2 fue anulada en la oficina." }
        : uuid === "op-error"
          ? { estado: "error", motivo: "Checklist incompleto." }
          : { estado: "ya_aplicada" },
    );

    await sincronizar();

    expect(await db.outbox.count()).toBe(0);
    const conflictos = await db.conflictos.toArray();
    expect(conflictos.map((c) => [c.uuid, c.estado])).toEqual([
      ["op-anulada", "conflicto"],
      ["op-error", "error"],
    ]);

    servidor(() => ({ estado: "aplicada" }));
    await reintentarConflicto("op-error");
    await sincronizar();
    expect(await db.conflictos.count()).toBe(1);
  });

  it("sin señal no pierde nada y lo informa", async () => {
    await db.outbox.add({ ...operacion("op-offline"), evidencias: [] });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    await sincronizar();

    expect(await db.outbox.count()).toBe(1);
    expect(leerEstado().ultimoError).toMatch(/Sin señal/);
  });
});
