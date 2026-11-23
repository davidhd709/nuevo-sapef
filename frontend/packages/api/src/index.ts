// Cliente tipado de la API de SAPEF. Los tipos salen de esquema.ts, generado desde el OpenAPI
// del backend (pnpm api). Un cambio en la API que rompa el frontend falla al compilar.
import createClient from "openapi-fetch";

import type { components, paths } from "./esquema";

export type { components, paths };
export type Salud = components["schemas"]["Salud"];

/** Error en formato RFC 9457 que devuelve la API. */
export interface Problema {
  type: string;
  title: string;
  status: number;
  detail?: string;
  errors?: { campo: string; mensaje: string }[];
  requestId?: string;
}

// La API está en el mismo dominio que la web. Se usa el origen de la página como base porque
// `Request` exige URLs absolutas fuera del navegador (pruebas, Node).
const origenPagina = typeof window !== "undefined" ? window.location.origin : "";

export function crearCliente(baseUrl = origenPagina) {
  return createClient<paths>({
    baseUrl,
    // Las cookies de sesión (HttpOnly) viajan solas: mismo dominio.
    credentials: "same-origin",
    // fetch se resuelve en cada llamada (no al crear el cliente): permite sustituirlo en pruebas.
    fetch: (peticion) => globalThis.fetch(peticion),
  });
}

export const api = crearCliente();
