// Utilidades compartidas por las pantallas: mensajes de error RFC 9457 y subida de archivos.

/** Texto legible de un error de la API (campo `detail` del problema RFC 9457). */
export function mensajeError(error: unknown, porDefecto: string): string {
  if (error && typeof error === "object") {
    const detalle = (error as { detail?: unknown }).detail;
    if (typeof detalle === "string" && detalle) return detalle;
    const errores = (error as { errors?: { campo: string; mensaje: string }[] }).errors;
    if (Array.isArray(errores) && errores.length > 0) {
      return errores.map((e) => `${e.campo}: ${e.mensaje}`).join(" · ");
    }
  }
  if (error instanceof Error && error.message) return error.message;
  return porDefecto;
}

/** Lanza un Error con el mensaje de la API si la respuesta no trajo datos. */
export function exigir<T>(data: T | undefined, error: unknown, porDefecto: string): T {
  if (data === undefined || data === null) throw new Error(mensajeError(error, porDefecto));
  return data;
}

/** Sube un archivo (multipart) a una ruta de la API con la sede activa. */
export async function subirArchivo<T>(
  ruta: string,
  archivo: File,
  sede: string,
  extra: Record<string, string> = {},
): Promise<T> {
  const datos = new FormData();
  datos.append("archivo", archivo);
  for (const [clave, valor] of Object.entries(extra)) datos.append(clave, valor);
  const respuesta = await fetch(ruta, {
    method: "POST",
    body: datos,
    credentials: "same-origin",
    headers: { "X-Sede": sede, "Idempotency-Key": crypto.randomUUID() },
  });
  const cuerpo = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(mensajeError(cuerpo, "No se pudo subir el archivo."));
  return cuerpo as T;
}

export const PRIORIDADES = [
  { value: "0", label: "Urgente" },
  { value: "1", label: "Alta" },
  { value: "2", label: "Media" },
  { value: "3", label: "Baja" },
];

export const COLOR_SEMAFORO: Record<string, string> = {
  verde: "green",
  amarillo: "yellow",
  rojo: "red",
};

export function fecha(valor: string | null | undefined): string {
  if (!valor) return "—";
  return new Date(valor).toLocaleDateString("es-CO");
}
