// Cliente HTTP de la app de campo. La sesión va en cookies HttpOnly (mismo origen). El token de
// acceso dura minutos; si una llamada responde 401 se renueva una vez (la renovación de la PWA
// dura 30 días) y se repite la llamada.
import type { paths } from "@sapef/api";
import createClient from "openapi-fetch";

/** No hubo respuesta del servidor (sin señal, servidor caído, DNS). */
export class SinConexion extends Error {
  constructor() {
    super("Sin conexión con el servidor.");
    this.name = "SinConexion";
  }
}

/** La sesión venció y no se pudo renovar: hay que volver a ingresar. */
export class SesionVencida extends Error {
  constructor() {
    super("La sesión venció. Ingrese de nuevo para enviar el trabajo pendiente.");
    this.name = "SesionVencida";
  }
}

let renovando: Promise<boolean> | null = null;

async function renovar(): Promise<boolean> {
  renovando ??= fetch("/api/v1/auth/renovar", { method: "POST", credentials: "same-origin" })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      renovando = null;
    });
  return renovando;
}

async function enviar(peticion: Request): Promise<Response> {
  try {
    return await globalThis.fetch(peticion);
  } catch {
    throw new SinConexion();
  }
}

/** fetch con renovación automática de la sesión. */
export async function pedir(peticion: Request): Promise<Response> {
  const copia = peticion.clone();
  const respuesta = await enviar(peticion);
  if (respuesta.status !== 401 || peticion.url.includes("/api/v1/auth/")) return respuesta;
  if (!(await renovar())) return respuesta;
  return enviar(copia);
}

const origen = typeof window !== "undefined" ? window.location.origin : "http://localhost";

export const api = createClient<paths>({
  baseUrl: origen,
  credentials: "same-origin",
  fetch: (peticion) => pedir(peticion),
});

/** Texto legible de un problema RFC 9457. */
export function mensajeError(error: unknown, porDefecto: string): string {
  if (error && typeof error === "object") {
    const detalle = (error as { detail?: unknown }).detail;
    if (typeof detalle === "string" && detalle) return detalle;
  }
  if (error instanceof Error && error.message) return error.message;
  return porDefecto;
}

export function cabeceraSede(sede: string): { "X-Sede": string } {
  return { "X-Sede": sede };
}
