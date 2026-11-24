// Captura en el teléfono: fotos comprimidas antes de guardarlas (la red de campo es lenta y el
// límite de evidencia es de 10 MB), nombres de archivo y utilidades de formato.

const LADO_MAXIMO = 1600;
const CALIDAD = 0.8;

export interface Capturado {
  datos: Blob;
  mime: string;
  nombre: string;
}

function conExtension(nombre: string, extension: string): string {
  const base = nombre.replace(/\.[^.]+$/, "") || "foto";
  return `${base}.${extension}`;
}

function aBlob(lienzo: HTMLCanvasElement, mime: string, calidad?: number): Promise<Blob | null> {
  return new Promise((resolve) => {
    const reloj = window.setTimeout(() => resolve(null), 5000);
    lienzo.toBlob(
      (blob) => {
        window.clearTimeout(reloj);
        resolve(blob);
      },
      mime,
      calidad,
    );
  });
}

/** Reduce la foto a 1600 px de lado y la pasa a JPEG. Si algo falla, guarda la original. */
export async function comprimirFoto(archivo: File): Promise<Capturado> {
  const original: Capturado = {
    datos: archivo,
    mime: archivo.type || "image/jpeg",
    nombre: archivo.name || "foto.jpg",
  };
  try {
    const imagen = await createImageBitmap(archivo);
    const escala = Math.min(1, LADO_MAXIMO / Math.max(imagen.width, imagen.height));
    const lienzo = document.createElement("canvas");
    lienzo.width = Math.max(1, Math.round(imagen.width * escala));
    lienzo.height = Math.max(1, Math.round(imagen.height * escala));
    const contexto = lienzo.getContext("2d");
    if (!contexto) return original;
    contexto.drawImage(imagen, 0, 0, lienzo.width, lienzo.height);
    imagen.close();
    const comprimida = await aBlob(lienzo, "image/jpeg", CALIDAD);
    if (!comprimida || (comprimida.size >= archivo.size && archivo.type.startsWith("image/"))) {
      return original;
    }
    return { datos: comprimida, mime: "image/jpeg", nombre: conExtension(original.nombre, "jpg") };
  } catch {
    return original;
  }
}

export function lienzoAPng(lienzo: HTMLCanvasElement): Promise<Blob | null> {
  return aBlob(lienzo, "image/png");
}

export function extensionAudio(mime: string): string {
  if (mime.includes("mp4") || mime.includes("aac")) return "m4a";
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("mpeg")) return "mp3";
  return "webm";
}

export function tamanoLegible(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function fechaHora(valor: string | null | undefined): string {
  if (!valor) return "—";
  return new Date(valor).toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short" });
}

export function enlaceGoogleMaps(latitud: number, longitud: number): string {
  return `https://www.google.com/maps/search/?api=1&query=${latitud},${longitud}`;
}

export const NOMBRE_TIPO: Record<string, string> = {
  mantenimiento: "Mantenimiento",
  modernizacion: "Modernización",
  expansion: "Expansión",
  reubicacion: "Reubicación",
};

export const PRIORIDAD: Record<number, { texto: string; color: string }> = {
  0: { texto: "Urgente", color: "red" },
  1: { texto: "Alta", color: "orange" },
  2: { texto: "Media", color: "yellow" },
  3: { texto: "Baja", color: "gray" },
};

export const NOMBRE_COMPONENTE: Record<string, string> = {
  conexion_red: "Conexión a red",
  conexion_interna: "Conexión interna",
  base_fotocelda: "Base de fotocelda",
  fotocelda: "Fotocelda",
  bombillo: "Bombillo",
  socket: "Socket",
  arrancador: "Arrancador",
  condensador: "Condensador",
  balasta: "Balasta",
  tubo: "Tubo",
  collarin: "Collarín",
  conectores_perforacion: "Conectores de perforación",
};
