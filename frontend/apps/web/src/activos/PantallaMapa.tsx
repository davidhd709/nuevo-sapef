import "maplibre-gl/dist/maplibre-gl.css";

import { Alert, Anchor, Badge, Button, Card, Group, Select, SimpleGrid, Stack, Text, TextInput, Title } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { api, type components } from "@sapef/api";
import { useQuery } from "@tanstack/react-query";
import maplibregl, { type StyleSpecification, type VectorTileSource } from "maplibre-gl";
import { PMTiles, Protocol } from "pmtiles";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { ICONO_LUMINARIA, ICONOS_MAPA, registrarIconosMapa } from "./iconosMapa";

type LuminariaSalida = components["schemas"]["LuminariaSalida"];

const CENTROS: Record<string, [number, number]> = {
  montelibano: [-75.42, 7.98],
  alcala: [-75.785, 4.675],
};
const VERSION_MAPA_BASE = "20261125-ampliado";
const ZOOM_INICIAL = 11.5;

interface FiltrosMapa {
  estado: string | null;
  tecnologia: string | null;
  potencia: string | null;
  marca: string | null;
  intervencion: string | null;
  zona: string | null;
  barrio: string | null;
  bodega: string | null;
  validado: string | null;
  transito: string | null;
}

const FILTROS_VACIOS: FiltrosMapa = {
  estado: null, tecnologia: null, potencia: null, marca: null, intervencion: null, zona: null,
  barrio: null, bodega: null, validado: null, transito: null,
};

function urlTeselas(sede: string, filtros: FiltrosMapa, texto: string): string {
  const params = new URLSearchParams({ sede });
  const campos: [string, string | null][] = [
    ["estado_id", filtros.estado], ["tecnologia_id", filtros.tecnologia],
    ["potencia_id", filtros.potencia], ["marca_id", filtros.marca],
    ["tipo_intervencion_id", filtros.intervencion],
    ["zona_id", filtros.zona], ["barrio_id", filtros.barrio],
    ["en_bodega", filtros.bodega], ["validado", filtros.validado],
    ["en_transito", filtros.transito],
  ];
  for (const [campo, valor] of campos) if (valor !== null) params.set(campo, valor);
  if (texto.trim()) params.set("texto", texto.trim());
  return `${window.location.origin}/api/v1/mapa/luminarias/{z}/{x}/{y}.mvt?${params}`;
}

let protocolo: Protocol | null = null;

function estiloMapa(sede: string, filtros: FiltrosMapa, texto: string): StyleSpecification {
  const baseUrl = new URL(`/api/v1/mapa/base/${sede}.pmtiles?v=${VERSION_MAPA_BASE}`, window.location.origin).href;
  const base = new PMTiles(baseUrl);
  if (!protocolo) {
    protocolo = new Protocol();
    maplibregl.addProtocol("pmtiles", protocolo.tile);
  }
  protocolo.add(base);

  // La sede también forma parte de la URL para separar las teselas guardadas por el navegador.
  const teselas = urlTeselas(sede, filtros, texto);
  // MapLibre sustituye estas llaves al solicitar cada tesela. URL() las escaparía como %7B/%7D.

  return {
    version: 8,
    glyphs: `${window.location.origin}/mapa/fonts/{fontstack}/{range}.pbf`,
    sources: {
      base: { type: "vector", url: `pmtiles://${baseUrl}` },
      luminarias: { type: "vector", tiles: [teselas], minzoom: 0, maxzoom: 18 },
    },
    layers: [
      { id: "fondo", type: "background", paint: { "background-color": "#eef4e9" } },
      { id: "tierra", type: "fill", source: "base", "source-layer": "earth", paint: { "fill-color": "#edf4e8" } },
      { id: "vegetacion", type: "fill", source: "base", "source-layer": "landcover", paint: { "fill-color": "#d7efda", "fill-opacity": 0.75 } },
      { id: "parques", type: "fill", source: "base", "source-layer": "landuse", filter: ["in", ["get", "kind"], ["literal", ["park", "recreation_ground", "grass", "forest"]]], paint: { "fill-color": "#c7e9ce", "fill-opacity": 0.8 } },
      { id: "agua", type: "fill", source: "base", "source-layer": "water", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": "#9bd9ee" } },
      { id: "rios", type: "line", source: "base", "source-layer": "water", filter: ["==", ["geometry-type"], "LineString"], paint: { "line-color": "#8ed0e9", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 1, 14, 3] } },
      { id: "edificios", type: "fill", source: "base", "source-layer": "buildings", paint: { "fill-color": "#e7e5df" } },
      { id: "vias", type: "line", source: "base", "source-layer": "roads", paint: { "line-color": "#ffffff", "line-width": 2 } },
      {
        id: "nombres-rios", type: "symbol", source: "base", "source-layer": "water",
        minzoom: 10, filter: ["all", ["has", "name"], ["==", ["geometry-type"], "LineString"]],
        layout: { "symbol-placement": "line", "symbol-spacing": 300, "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"], "text-size": 11 },
        paint: { "text-color": "#1971a5", "text-halo-color": "#ffffff", "text-halo-width": 1.5 },
      },
      {
        id: "nombres-calles",
        type: "symbol",
        source: "base",
        "source-layer": "roads",
        minzoom: 13,
        filter: ["has", "name"],
        layout: {
          "symbol-placement": "line",
          "symbol-spacing": 180,
          "text-field": ["get", "name"],
          "text-font": ["Noto Sans Regular"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 13, 10, 16, 13],
          "text-max-angle": 60,
        },
        paint: { "text-color": "#495057", "text-halo-color": "#ffffff", "text-halo-width": 1.5 },
      },
      {
        id: "nombres-lugares",
        type: "symbol",
        source: "base",
        "source-layer": "places",
        filter: ["has", "name"],
        layout: {
          "text-field": ["get", "name"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 14,
        },
        paint: { "text-color": "#343a40", "text-halo-color": "#ffffff", "text-halo-width": 2 },
      },
      {
        id: "puntos-interes",
        type: "circle",
        source: "base",
        "source-layer": "pois",
        minzoom: 11,
        filter: ["has", "name"],
        paint: {
          "circle-radius": 3,
          "circle-color": ["match", ["get", "kind"], "park", "#2b8a3e", "hospital", "#c92a2a", "#4263eb"],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1,
        },
      },
      {
        id: "nombres-puntos-interes",
        type: "symbol",
        source: "base",
        "source-layer": "pois",
        minzoom: 11,
        filter: ["has", "name"],
        layout: {
          "text-field": ["get", "name"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 11,
          "text-offset": [0, 1],
          "text-max-width": 12,
        },
        paint: { "text-color": "#343a40", "text-halo-color": "#ffffff", "text-halo-width": 1.5 },
      },
      {
        id: "luminarias-grupos",
        type: "circle",
        source: "luminarias",
        "source-layer": "luminarias",
        filter: ["==", ["get", "es_grupo"], true],
        paint: {
          "circle-radius": 15,
          "circle-color": "#364fc7",
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
        },
      },
      {
        id: "luminarias-iconos",
        type: "symbol",
        source: "luminarias",
        "source-layer": "luminarias",
        filter: ["==", ["get", "es_grupo"], false],
        layout: { "icon-image": ICONO_LUMINARIA, "icon-anchor": "bottom", "icon-allow-overlap": true },
      },
      {
        id: "cantidad-luminarias",
        type: "symbol",
        source: "luminarias",
        "source-layer": "luminarias",
        filter: ["==", ["get", "es_grupo"], true],
        layout: { "text-field": ["to-string", ["get", "total"]], "text-font": ["Noto Sans Regular"], "text-size": 11, "text-allow-overlap": true },
        paint: { "text-color": "#ffffff" },
      },
    ],
  };
}

export function PantallaMapa() {
  const { sedeActiva, tienePermiso } = useAuth();
  const contenedor = useRef<HTMLDivElement | null>(null);
  const mapa = useRef<maplibregl.Map | null>(null);
  const marcadorEdicion = useRef<maplibregl.Marker | null>(null);
  const [filtros, setFiltros] = useState<FiltrosMapa>(FILTROS_VACIOS);
  const [texto, setTexto] = useState("");
  const [textoBuscado] = useDebouncedValue(texto, 350);
  const [seleccionada, setSeleccionada] = useState<LuminariaSalida | null>(null);
  const [editandoUbicacion, setEditandoUbicacion] = useState(false);
  const [ubicacionNueva, setUbicacionNueva] = useState<[number, number] | null>(null);
  const [guardandoUbicacion, setGuardandoUbicacion] = useState(false);
  const [revisionTeselas, setRevisionTeselas] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const puedeVerMapa = tienePermiso("activos.mapa.ver");
  const puedeMover = tienePermiso("activos.luminaria.mover");

  const { data: estados = [] } = useQuery({
    queryKey: ["estados-luminaria"],
    enabled: puedeVerMapa,
    queryFn: async () =>
      (await api.GET("/api/v1/estados", { params: { query: { proceso: "luminaria" } } })).data ??
      [],
  });

  const { data: tecnologias = [] } = useQuery({
    queryKey: ["maestros", "LUMINARIA_TECNOLOGIA"], enabled: puedeVerMapa,
    queryFn: async () => (await api.GET("/api/v1/maestros/{clase}", { params: { path: { clase: "LUMINARIA_TECNOLOGIA" } } })).data ?? [],
  });
  const { data: potencias = [] } = useQuery({
    queryKey: ["maestros", "LUMINARIA_POTENCIA"], enabled: puedeVerMapa,
    queryFn: async () => (await api.GET("/api/v1/maestros/{clase}", { params: { path: { clase: "LUMINARIA_POTENCIA" } } })).data ?? [],
  });
  const { data: marcas = [] } = useQuery({
    queryKey: ["maestros", "LUMINARIA_MARCA"], enabled: puedeVerMapa,
    queryFn: async () => (await api.GET("/api/v1/maestros/{clase}", { params: { path: { clase: "LUMINARIA_MARCA" } } })).data ?? [],
  });
  const { data: intervenciones = [] } = useQuery({
    queryKey: ["maestros", "TIPO_INTERVENCION"], enabled: puedeVerMapa,
    queryFn: async () => (await api.GET("/api/v1/maestros/{clase}", { params: { path: { clase: "TIPO_INTERVENCION" } } })).data ?? [],
  });
  const { data: zonas = [] } = useQuery({
    queryKey: ["zonas", sedeActiva], enabled: puedeVerMapa && Boolean(sedeActiva),
    queryFn: async () => (await api.GET("/api/v1/zonas", { headers: { "X-Sede": sedeActiva! } })).data ?? [],
  });
  const { data: barrios = [] } = useQuery({
    queryKey: ["barrios", sedeActiva], enabled: puedeVerMapa && Boolean(sedeActiva),
    queryFn: async () => (await api.GET("/api/v1/barrios", { headers: { "X-Sede": sedeActiva! } })).data ?? [],
  });

  useEffect(() => {
    if (!puedeVerMapa || !sedeActiva || !contenedor.current) return;
    let cancelado = false;
    setError(null);
    setSeleccionada(null);
    setEditandoUbicacion(false);

    try {
      const m = new maplibregl.Map({
        container: contenedor.current,
        style: estiloMapa(sedeActiva, FILTROS_VACIOS, ""),
        center: CENTROS[sedeActiva] ?? CENTROS.montelibano,
        zoom: ZOOM_INICIAL,
        attributionControl: { compact: true, customAttribution: "© OpenStreetMap" },
        transformRequest: (url) =>
          url.includes("/api/v1/mapa/luminarias/")
            ? { url, headers: { "X-Sede": sedeActiva } }
            : { url },
      });
      mapa.current = m;
      m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      m.addControl(new maplibregl.GeolocateControl({
        positionOptions: { enableHighAccuracy: true },
        trackUserLocation: false,
      }), "top-right");
      m.on("load", () => registrarIconosMapa(m));
      m.on("click", "luminarias-grupos", (evento) => {
        m.easeTo({ center: evento.lngLat, zoom: Math.max(m.getZoom() + 2, 13) });
      });
      m.on("click", "luminarias-iconos", (evento) => {
        const punto = evento.features?.[0];
        if (!punto) return;
        const id = Number(punto.properties?.id);
        if (!Number.isFinite(id)) return;
        setEditandoUbicacion(false);
        void api.GET("/api/v1/luminarias/{luminaria_id}", {
          headers: { "X-Sede": sedeActiva },
          params: { path: { luminaria_id: id } },
        }).then(({ data }) => {
          if (!cancelado) setSeleccionada(data ?? null);
        });
      });
      for (const capa of ["luminarias-grupos", "luminarias-iconos"]) {
        m.on("mouseenter", capa, () => { m.getCanvas().style.cursor = "pointer"; });
        m.on("mouseleave", capa, () => { m.getCanvas().style.cursor = ""; });
      }
    } catch {
      setError("No se pudo abrir el mapa. Comprueba que WebGL esté activado en el navegador.");
    }

    return () => {
      cancelado = true;
      marcadorEdicion.current?.remove();
      marcadorEdicion.current = null;
      mapa.current?.remove();
      mapa.current = null;
    };
  }, [puedeVerMapa, sedeActiva]);

  useEffect(() => {
    marcadorEdicion.current?.remove();
    marcadorEdicion.current = null;
    if (!editandoUbicacion || !seleccionada || !mapa.current || seleccionada.latitud == null || seleccionada.longitud == null) return;
    const marcador = new maplibregl.Marker({ draggable: true, color: "#e03131" })
      .setLngLat([seleccionada.longitud, seleccionada.latitud])
      .addTo(mapa.current);
    marcador.on("dragend", () => {
      const { lat, lng } = marcador.getLngLat();
      setUbicacionNueva([lat, lng]);
    });
    marcadorEdicion.current = marcador;
    return () => {
      marcador.remove();
      if (marcadorEdicion.current === marcador) marcadorEdicion.current = null;
    };
  }, [editandoUbicacion, seleccionada]);

  async function guardarUbicacion() {
    if (!sedeActiva || !seleccionada || !ubicacionNueva || guardandoUbicacion) return;
    setGuardandoUbicacion(true);
    setError(null);
    try {
      const respuesta = await api.POST("/api/v1/luminarias/{luminaria_id}/ubicacion", {
        headers: { "X-Sede": sedeActiva },
        params: { path: { luminaria_id: seleccionada.id } },
        body: { latitud: ubicacionNueva[0], longitud: ubicacionNueva[1], origen: "mapa_web" },
      });
      if (respuesta.error || !respuesta.data) throw new Error("No se pudo guardar la ubicación.");
      setSeleccionada(respuesta.data);
      setEditandoUbicacion(false);
      setUbicacionNueva(null);
      setRevisionTeselas((actual) => actual + 1);
    } catch {
      setError("No se pudo guardar la ubicación. Revise el permiso y las coordenadas e inténtelo de nuevo.");
    } finally {
      setGuardandoUbicacion(false);
    }
  }

  useEffect(() => {
    const m = mapa.current;
    if (!m || !sedeActiva) return;
    const actualizar = () => {
      (m.getSource("luminarias") as VectorTileSource | undefined)?.setTiles([
        `${urlTeselas(sedeActiva, filtros, textoBuscado)}&revision=${revisionTeselas}`,
      ]);
    };
    if (m.isStyleLoaded()) actualizar();
    else m.on("load", actualizar);
    return () => { m.off("load", actualizar); };
  }, [filtros, textoBuscado, sedeActiva, revisionTeselas]);

  if (!puedeVerMapa) {
    return (
      <Alert color="red" title="403 · Acceso denegado" data-testid="error-403">
        No tiene permiso para visualizar el mapa de luminarias.
      </Alert>
    );
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Mapa de alumbrado · {sedeActiva}</Title>
        <Button variant="light" onClick={() => mapa.current?.flyTo({ center: CENTROS[sedeActiva ?? ""] ?? CENTROS.montelibano, zoom: ZOOM_INICIAL })}>
          Volver a la vista general
        </Button>
      </Group>
      <Card withBorder>
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="sm">
          <TextInput label="Buscar" placeholder="Código, poste, barrio o marca" value={texto} onChange={(e) => setTexto(e.currentTarget.value)} />
          <Select label="Estado" placeholder="Todos" clearable searchable data={estados.map((e) => ({ value: String(e.id), label: e.nombre }))} value={filtros.estado} onChange={(valor) => setFiltros((f) => ({ ...f, estado: valor }))} />
          <Select label="Tecnología" placeholder="Todas" clearable searchable data={tecnologias.map((e) => ({ value: String(e.id), label: e.nombre }))} value={filtros.tecnologia} onChange={(valor) => setFiltros((f) => ({ ...f, tecnologia: valor }))} />
          <Select label="Potencia" placeholder="Todas" clearable searchable data={potencias.map((e) => ({ value: String(e.id), label: e.nombre }))} value={filtros.potencia} onChange={(valor) => setFiltros((f) => ({ ...f, potencia: valor }))} />
          <Select label="Marca" placeholder="Todas" clearable searchable data={marcas.map((e) => ({ value: String(e.id), label: e.nombre }))} value={filtros.marca} onChange={(valor) => setFiltros((f) => ({ ...f, marca: valor }))} />
          <Select label="Tipo de intervención" placeholder="Todos" clearable searchable data={intervenciones.map((e) => ({ value: String(e.id), label: e.nombre }))} value={filtros.intervencion} onChange={(valor) => setFiltros((f) => ({ ...f, intervencion: valor }))} />
          <Select label="Zona" placeholder="Todas" clearable searchable data={zonas.map((e) => ({ value: String(e.id), label: e.nombre }))} value={filtros.zona} onChange={(valor) => setFiltros((f) => ({ ...f, zona: valor, barrio: null }))} />
          <Select label="Barrio" placeholder="Todos" clearable searchable data={barrios.filter((b) => !filtros.zona || b.zona_id === Number(filtros.zona)).map((e) => ({ value: String(e.id), label: e.nombre }))} value={filtros.barrio} onChange={(valor) => setFiltros((f) => ({ ...f, barrio: valor }))} />
          <Select label="En bodega" placeholder="Todos" clearable data={[{ value: "true", label: "Sí" }, { value: "false", label: "No" }]} value={filtros.bodega} onChange={(valor) => setFiltros((f) => ({ ...f, bodega: valor }))} />
          <Select label="Validado" placeholder="Todos" clearable data={[{ value: "true", label: "Sí" }, { value: "false", label: "No" }]} value={filtros.validado} onChange={(valor) => setFiltros((f) => ({ ...f, validado: valor }))} />
          <Select label="En tránsito" placeholder="Todos" clearable data={[{ value: "true", label: "Sí" }, { value: "false", label: "No" }]} value={filtros.transito} onChange={(valor) => setFiltros((f) => ({ ...f, transito: valor }))} />
        </SimpleGrid>
        <Group justify="flex-end" mt="sm">
          <Button variant="subtle" size="xs" onClick={() => { setFiltros(FILTROS_VACIOS); setTexto(""); }}>Limpiar filtros</Button>
        </Group>
      </Card>
      {error && <Alert color="red">{error}</Alert>}
      <Card withBorder p="xs">
        <div
          ref={contenedor}
          data-testid="mapa-contenedor"
          style={{ width: "100%", height: "65vh", minHeight: 440, borderRadius: 6, overflow: "hidden" }}
        />
        <Group gap="md" mt="xs">
          {ICONOS_MAPA.map((icono) => (
            <Group key={icono.id} gap={4} wrap="nowrap">
              <svg aria-hidden="true" width="17" height="19" viewBox="0 0 32 36">
                <path d="M7 3V33" stroke="#343a40" strokeWidth="2" />
                <path d="M8 4L28 8L8 17Z" fill={icono.color} stroke="#fff" strokeWidth="1.5" />
              </svg>
              <Text size="xs">{icono.nombre}</Text>
            </Group>
          ))}
          <Badge color="indigo">Grupos con cantidad</Badge>
          <Text size="xs" c="dimmed">Acércate o haz clic en un grupo para ver sus luminarias.</Text>
        </Group>
      </Card>
      {seleccionada && (
        <Card withBorder maw={360}>
          <Group justify="space-between">
            <Text fw={600}>{seleccionada.codigo}</Text>
            <Badge>{seleccionada.estado_nombre}</Badge>
          </Group>
          <Text size="sm">Barrio: {seleccionada.barrio_nombre ?? "-"} ({seleccionada.zona_nombre ?? "-"})</Text>
          <Text size="xs" c="dimmed">{seleccionada.latitud}, {seleccionada.longitud}</Text>
          {puedeMover && seleccionada.latitud != null && seleccionada.longitud != null && (
            editandoUbicacion ? (
              <Stack gap="xs" mt="sm">
                <Text size="sm">Arrastre el marcador rojo a la ubicación correcta.</Text>
                {ubicacionNueva && <Text size="xs">Nueva ubicación: {ubicacionNueva[0].toFixed(6)}, {ubicacionNueva[1].toFixed(6)}</Text>}
                <Group gap="xs">
                  <Button size="xs" disabled={!ubicacionNueva} loading={guardandoUbicacion} onClick={() => void guardarUbicacion()}>Guardar ubicación</Button>
                  <Button size="xs" variant="subtle" disabled={guardandoUbicacion} onClick={() => { setEditandoUbicacion(false); setUbicacionNueva(null); }}>Cancelar</Button>
                </Group>
              </Stack>
            ) : (
              <Button size="xs" variant="light" mt="xs" onClick={() => { setUbicacionNueva(null); setEditandoUbicacion(true); }}>Corregir ubicación</Button>
            )
          )}
          {seleccionada.google_maps_url && (
            <Anchor href={seleccionada.google_maps_url} target="_blank" rel="noreferrer" size="sm">
              Ver en Google Maps
            </Anchor>
          )}
        </Card>
      )}
    </Stack>
  );
}
