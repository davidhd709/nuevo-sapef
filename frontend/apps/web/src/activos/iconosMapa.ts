import type maplibregl from "maplibre-gl";

export const ICONOS_MAPA = [
  { id: "pqr", nombre: "PQR activa", color: "#e03131" },
  { id: "led-baja", nombre: "LED ≤ 60 W", color: "#20a65a" },
  { id: "led-media", nombre: "LED 61–120 W", color: "#74b816" },
  { id: "led-alta", nombre: "LED ≥ 121 W", color: "#a9e34b" },
  { id: "sodio-baja", nombre: "Sodio ≤ 70 W", color: "#c92a2a" },
  { id: "sodio-media", nombre: "Sodio 71–150 W", color: "#e67700" },
  { id: "sodio-alta", nombre: "Sodio ≥ 151 W", color: "#d6336c" },
  { id: "halogenuros", nombre: "Halogenuros metálicos", color: "#1971c2" },
  { id: "ahorradora", nombre: "Ahorradora", color: "#5c7cfa" },
  { id: "mixta", nombre: "Mixta", color: "#495057" },
  { id: "bodega", nombre: "Bodega o desmontada", color: "#868e96" },
  { id: "final", nombre: "Disposición final", color: "#e8590c" },
  { id: "otros", nombre: "Otros", color: "#7048e8" },
] as const;

export const ICONO_LUMINARIA = [
  "case",
  ["==", ["get", "estado_codigo"], "122"], "pqr",
  ["in", ["get", "estado_codigo"], ["literal", ["112", "123", "124", "125"]]], "bodega",
  ["==", ["get", "estado_codigo"], "126"], "final",
  ["in", ["get", "tecnologia_codigo"], ["literal", ["LED", "LED_SOLAR"]]],
  ["step", ["to-number", ["get", "potencia_codigo"], 0], "led-baja", 61, "led-media", 121, "led-alta"],
  ["==", ["get", "tecnologia_codigo"], "SODIO"],
  ["step", ["to-number", ["get", "potencia_codigo"], 0], "sodio-baja", 71, "sodio-media", 151, "sodio-alta"],
  ["match", ["get", "tecnologia_codigo"], "METAL_HALIDE", "halogenuros", "AHORRADORA", "ahorradora", "MIXTA", "mixta", "otros"],
] as unknown as maplibregl.ExpressionSpecification;

function imagenBandera(color: string): ImageData {
  const lienzo = document.createElement("canvas");
  lienzo.width = 32;
  lienzo.height = 36;
  const ctx = lienzo.getContext("2d");
  if (!ctx) throw new Error("No se pudo dibujar el icono del mapa.");
  ctx.lineCap = "round";
  ctx.strokeStyle = "#343a40";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(7, 3);
  ctx.lineTo(7, 33);
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(8, 4);
  ctx.lineTo(28, 8);
  ctx.lineTo(8, 17);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  return ctx.getImageData(0, 0, lienzo.width, lienzo.height);
}

export function registrarIconosMapa(mapa: maplibregl.Map): void {
  for (const icono of ICONOS_MAPA) {
    if (!mapa.hasImage(icono.id)) mapa.addImage(icono.id, imagenBandera(icono.color), { pixelRatio: 2 });
  }
}
