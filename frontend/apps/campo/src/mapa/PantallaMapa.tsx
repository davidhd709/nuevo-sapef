// Mapa sin señal (RF-104): mapa base PMTiles de la sede guardado en el teléfono y las luminarias
// de la base local. Se carga aparte (MapLibre pesa) solo cuando el técnico abre esta pestaña.
import "maplibre-gl/dist/maplibre-gl.css";

import { Alert, Anchor, Badge, Card, Group, Stack, Text } from "@mantine/core";
import maplibregl, { type GeoJSONSource, type StyleSpecification } from "maplibre-gl";
import { FileSource, PMTiles, Protocol } from "pmtiles";
import { useEffect, useRef, useState } from "react";

import { enlaceGoogleMaps } from "../comun/captura";
import { useConsulta } from "../comun/ganchos";
import { db, leerMeta, type LuminariaCampo } from "../datos/db";
import { CACHE_MAPA } from "../datos/sincronizacion";

const COLOR_ESTADO: [string, string][] = [
  ["121", "#2f9e44"], // en operación
  ["122", "#e03131"], // con PQRS
  ["124", "#1971c2"], // bodega buena
];

let protocolo: Protocol | null = null;

async function fuenteBase(): Promise<string | null> {
  const url = await leerMeta<string>("mapaUrl");
  if (!url || typeof caches === "undefined") return null;
  const respuesta = await (await caches.open(CACHE_MAPA)).match(url);
  if (!respuesta) return null;
  const archivo = new File([await respuesta.blob()], url.split("/").pop() ?? "base.pmtiles");
  if (!protocolo) {
    protocolo = new Protocol();
    maplibregl.addProtocol("pmtiles", protocolo.tile);
  }
  const pm = new PMTiles(new FileSource(archivo));
  protocolo.add(pm);
  return `pmtiles://${pm.source.getKey()}`;
}

function estilo(base: string | null): StyleSpecification {
  const capasBase: StyleSpecification["layers"] = base
    ? [
        // Esquema de capas de OpenStreetMap recortado con Protomaps (SPIKE-02).
        { id: "tierra", type: "fill", source: "base", "source-layer": "earth", paint: { "fill-color": "#f1f3f5" } },
        { id: "agua", type: "fill", source: "base", "source-layer": "water", paint: { "fill-color": "#a5d8ff" } },
        {
          id: "edificios",
          type: "fill",
          source: "base",
          "source-layer": "buildings",
          paint: { "fill-color": "#dee2e6" },
        },
        {
          id: "vias",
          type: "line",
          source: "base",
          "source-layer": "roads",
          paint: { "line-color": "#ffffff", "line-width": 2 },
        },
      ]
    : [];
  return {
    version: 8,
    sources: base ? { base: { type: "vector", url: base } } : {},
    layers: [{ id: "fondo", type: "background", paint: { "background-color": "#e9ecef" } }, ...capasBase],
  };
}

interface Punto {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: { id: number; estado: string; enOrden: boolean };
}

function aGeoJson(
  luminarias: LuminariaCampo[],
  enOrden: Set<number>,
): { type: "FeatureCollection"; features: Punto[] } {
  return {
    type: "FeatureCollection",
    features: luminarias
      .filter((l) => l.latitud != null && l.longitud != null)
      .map((l) => ({
        type: "Feature" as const,
        geometry: {
          type: "Point" as const,
          coordinates: [l.longitud as number, l.latitud as number] as [number, number],
        },
        properties: { id: l.id, estado: l.estado_codigo, enOrden: enOrden.has(l.id) },
      })),
  };
}

export default function PantallaMapa() {
  const contenedor = useRef<HTMLDivElement | null>(null);
  const mapa = useRef<maplibregl.Map | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sinBase, setSinBase] = useState(false);
  const [seleccion, setSeleccion] = useState<LuminariaCampo | null>(null);
  const [listo, setListo] = useState(false);
  const centrado = useRef(false);
  const luminarias = useConsulta(() => db.luminarias.toArray(), [], [] as LuminariaCampo[]);
  const ordenes = useConsulta(() => db.ordenes.toArray(), [], []);

  useEffect(() => {
    let cancelado = false;
    void (async () => {
      try {
        const base = await fuenteBase();
        if (cancelado || !contenedor.current) return;
        setSinBase(!base);
        const m = new maplibregl.Map({
          container: contenedor.current,
          style: estilo(base),
          center: [-75.42, 7.98],
          zoom: 14,
          attributionControl: { compact: true, customAttribution: "© OpenStreetMap" },
        });
        m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
        m.addControl(
          new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true }, trackUserLocation: true }),
          "top-right",
        );
        m.on("load", () => {
          m.addSource("luminarias", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
          m.addLayer({
            id: "luminarias",
            type: "circle",
            source: "luminarias",
            paint: {
              "circle-radius": ["case", ["get", "enOrden"], 9, 5],
              "circle-stroke-width": ["case", ["get", "enOrden"], 3, 1],
              "circle-stroke-color": "#212529",
              "circle-color": [
                "match",
                ["get", "estado"],
                ...COLOR_ESTADO.flat(),
                "#868e96",
              ] as unknown as maplibregl.ExpressionSpecification,
            },
          });
          m.on("click", "luminarias", (e) => {
            const id = e.features?.[0]?.properties?.id as number | undefined;
            if (id !== undefined) void db.luminarias.get(id).then((l) => setSeleccion(l ?? null));
          });
          setListo(true);
        });
        mapa.current = m;
      } catch {
        setError("Este teléfono no puede dibujar el mapa (WebGL no disponible).");
      }
    })();
    return () => {
      cancelado = true;
      mapa.current?.remove();
      mapa.current = null;
    };
  }, []);

  // Luminarias: se redibujan cuando cambia la base local.
  useEffect(() => {
    const m = mapa.current;
    if (!m || !listo) return;
    const enOrden = new Set(ordenes.flatMap((o) => o.luminarias.map((l) => l.luminaria_id)));
    const datos = aGeoJson(luminarias, enOrden);
    (m.getSource("luminarias") as GeoJSONSource | undefined)?.setData(datos);
    const primera = datos.features.find((f) => f.properties.enOrden) ?? datos.features[0];
    if (!centrado.current && primera) {
      m.jumpTo({ center: primera.geometry.coordinates });
      centrado.current = true;
    }
  }, [listo, luminarias, ordenes]);

  return (
    <Stack gap="xs">
      {error && <Alert color="red">{error}</Alert>}
      {sinBase && (
        <Alert color="yellow" variant="light">
          El mapa base de la sede aún no está en el teléfono; se descarga al sincronizar con señal.
        </Alert>
      )}
      <div ref={contenedor} style={{ height: "62vh", borderRadius: 8, overflow: "hidden" }} />
      <Group gap="xs">
        <Badge color="green">En operación</Badge>
        <Badge color="red">Con PQRS</Badge>
        <Badge color="blue">Bodega</Badge>
        <Badge color="dark" variant="outline">
          Borde grueso: en mis órdenes
        </Badge>
      </Group>
      {seleccion && (
        <Card withBorder padding="sm">
          <Text fw={700}>{seleccion.codigo}</Text>
          <Text size="sm">
            Estado {seleccion.estado_codigo} · {seleccion.tecnologia ?? "—"} {seleccion.potencia ?? ""}
            {seleccion.poste ? ` · poste ${seleccion.poste}` : ""}
          </Text>
          {seleccion.latitud != null && seleccion.longitud != null && (
            <Anchor size="sm" href={enlaceGoogleMaps(seleccion.latitud, seleccion.longitud)} target="_blank">
              Ver en Google Maps
            </Anchor>
          )}
        </Card>
      )}
    </Stack>
  );
}
