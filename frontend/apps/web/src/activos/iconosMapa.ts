import type maplibregl from "maplibre-gl";

// Símbolos del mapa. El color dice la tecnología (tres tonos validados para daltonismo en todos los
// pares: azul, naranja y aguamarina) y la FORMA dice el estado, para que nada dependa solo del
// color: círculo = en operación, triángulo con «!» = PQR activa, cuadrado hueco = en bodega o
// desmontada, rombo = disposición final.
export type FormaSimbolo = "circulo" | "triangulo" | "cuadrado" | "rombo";

export const ICONOS_MAPA = [
  { id: "led", nombre: "LED", color: "#257de0", forma: "circulo" },
  { id: "sodio", nombre: "Sodio", color: "#f47230", forma: "circulo" },
  { id: "otras", nombre: "Otras tecnologías", color: "#00b894", forma: "circulo" },
  { id: "pqr", nombre: "PQRS activa", color: "#dc3c3d", forma: "triangulo" },
  { id: "bodega", nombre: "En bodega o desmontada", color: "#84847e", forma: "cuadrado" },
  { id: "final", nombre: "Disposición final", color: "#474743", forma: "rombo" },
] as const satisfies readonly { id: string; nombre: string; color: string; forma: FormaSimbolo }[];

export const ICONO_LUMINARIA = [
  "case",
  ["==", ["get", "estado_codigo"], "122"], "pqr",
  ["in", ["get", "estado_codigo"], ["literal", ["112", "123", "124", "125"]]], "bodega",
  ["==", ["get", "estado_codigo"], "126"], "final",
  ["in", ["get", "tecnologia_codigo"], ["literal", ["LED", "LED_SOLAR"]]], "led",
  ["==", ["get", "tecnologia_codigo"], "SODIO"], "sodio",
  "otras",
] as unknown as maplibregl.ExpressionSpecification;

/** Trazo SVG de cada forma en una caja de 24×24 (mapa y leyenda usan el mismo dibujo). */
export function trazoForma(forma: FormaSimbolo): string {
  switch (forma) {
    case "circulo":
      return "M12 5.5a6.5 6.5 0 1 0 0.001 0Z";
    case "triangulo":
      return "M12 3.5 L21 19.5 H3 Z";
    case "cuadrado":
      return "M6 6 H18 V18 H6 Z";
    case "rombo":
      return "M12 4 L20 12 L12 20 L4 12 Z";
  }
}

function imagenSimbolo(color: string, forma: FormaSimbolo): ImageData {
  const escala = 2;
  const lienzo = document.createElement("canvas");
  lienzo.width = 24 * escala;
  lienzo.height = 24 * escala;
  const ctx = lienzo.getContext("2d");
  if (!ctx) throw new Error("No se pudo dibujar el icono del mapa.");
  ctx.scale(escala, escala);
  const trazo = new Path2D(trazoForma(forma));
  ctx.lineJoin = "round";
  // Anillo claro alrededor: separa símbolos que se tocan y del fondo del mapa.
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 3;
  ctx.stroke(trazo);
  if (forma === "cuadrado") {
    ctx.fillStyle = "#ffffff";
    ctx.fill(trazo);
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.2;
    ctx.stroke(trazo);
  } else {
    ctx.fillStyle = color;
    ctx.fill(trazo);
  }
  if (forma === "triangulo") {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(11.1, 9, 1.8, 5.5);
    ctx.fillRect(11.1, 15.6, 1.8, 1.8);
  }
  return ctx.getImageData(0, 0, lienzo.width, lienzo.height);
}

export function registrarIconosMapa(mapa: maplibregl.Map): void {
  for (const icono of ICONOS_MAPA) {
    if (!mapa.hasImage(icono.id)) mapa.addImage(icono.id, imagenSimbolo(icono.color, icono.forma), { pixelRatio: 2 });
  }
}
