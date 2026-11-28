import "maplibre-gl/dist/maplibre-gl.css";

import { Alert, Anchor, Button, Group, Paper, ScrollArea, Select, Stack, Text, TextInput } from "@mantine/core";
import { IconFocusCentered, IconSearch } from "@tabler/icons-react";
import { useDebouncedValue } from "@mantine/hooks";
import { api, type components } from "@sapef/api";
import { useQuery } from "@tanstack/react-query";
import maplibregl, { type StyleSpecification, type VectorTileSource } from "maplibre-gl";
import { PMTiles, Protocol } from "pmtiles";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { capitalizar, EncabezadoPagina, EtiquetaEstado, SinPermiso } from "../comun/ui";
import { ICONO_LUMINARIA, ICONOS_MAPA, registrarIconosMapa, trazoForma } from "./iconosMapa";

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
      { id: "fondo", type: "background", paint: { "background-color": "#f2f1ec" } },
      { id: "tierra", type: "fill", source: "base", "source-layer": "earth", paint: { "fill-color": "#f2f1ec" } },
      { id: "vegetacion", type: "fill", source: "base", "source-layer": "landcover", paint: { "fill-color": "#e2e8da", "fill-opacity": 0.8 } },
      { id: "parques", type: "fill", source: "base", "source-layer": "landuse", filter: ["in", ["get", "kind"], ["literal", ["park", "recreation_ground", "grass", "forest"]]], paint: { "fill-color": "#d9e3d0", "fill-opacity": 0.9 } },
      { id: "agua", type: "fill", source: "base", "source-layer": "water", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": "#c4dce6" } },
      { id: "rios", type: "line", source: "base", "source-layer": "water", filter: ["==", ["geometry-type"], "LineString"], paint: { "line-color": "#b4d2df", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 1, 14, 3] } },
      { id: "edificios", type: "fill", source: "base", "source-layer": "buildings", paint: { "fill-color": "#e4e2db" } },
      { id: "vias", type: "line", source: "base", "source-layer": "roads", paint: { "line-color": "#ffffff", "line-width": 2 } },
      {
        id: "nombres-rios", type: "symbol", source: "base", "source-layer": "water",
        minzoom: 10, filter: ["all", ["has", "name"], ["==", ["geometry-type"], "LineString"]],
        layout: { "symbol-placement": "line", "symbol-spacing": 300, "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"], "text-size": 11 },
        paint: { "text-color": "#5b7d8c", "text-halo-color": "#ffffff", "text-halo-width": 1.5 },
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
          "circle-radius": ["step", ["get", "total"], 13, 100, 16, 1000, 20],
          "circle-color": "#2e2e2b",
          "circle-stroke-color": "#e8a33d",
          "circle-stroke-width": 2,
        },
      },
      {
        id: "luminarias-iconos",
        type: "symbol",
        source: "luminarias",
        "source-layer": "luminarias",
        filter: ["==", ["get", "es_grupo"], false],
        layout: { "icon-image": ICONO_LUMINARIA, "icon-anchor": "center", "icon-allow-overlap": true },
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
    return <SinPermiso mensaje="No tiene permiso para ver el mapa de luminarias." />;
  }

  const filtrosActivos =
    Object.values(filtros).filter(Boolean).length + (texto.trim() ? 1 : 0);
  const sel = (etiqueta: string, todos: string, datos: { value: string; label: string }[], clave: keyof FiltrosMapa, extra?: Partial<FiltrosMapa>) => (
    <Select
      label={etiqueta}
      placeholder={todos}
      clearable
      searchable={datos.length > 6}
      size="xs"
      data={datos}
      value={filtros[clave]}
      onChange={(valor) => setFiltros((f) => ({ ...f, [clave]: valor, ...extra }))}
    />
  );
  const siNo = [
    { value: "true", label: "Sí" },
    { value: "false", label: "No" },
  ];

  return (
    <div>
      <EncabezadoPagina
        seccion="Operación"
        titulo="Mapa de alumbrado"
        descripcion="Ubicación y estado de cada luminaria. Acérquese o haga clic en un grupo para ver sus puntos."
        acciones={
          <Button
            variant="default"
            leftSection={<IconFocusCentered size={16} />}
            onClick={() => mapa.current?.flyTo({ center: CENTROS[sedeActiva ?? ""] ?? CENTROS.montelibano, zoom: ZOOM_INICIAL })}
          >
            Vista general
          </Button>
        }
      />
      {error && (
        <Alert color="red" mb="sm">
          {error}
        </Alert>
      )}
      <div style={{ display: "flex", gap: 12, alignItems: "stretch", height: "calc(100vh - 210px)", minHeight: 480 }}>
        <ScrollArea
          w={250}
          style={{
            flex: "none",
            border: "1px solid var(--sapef-borde)",
            borderRadius: "var(--mantine-radius-sm)",
            background: "var(--sapef-superficie)",
          }}
          visibleFrom="md"
        >
          <Stack gap={10} p="sm">
            <Group justify="space-between">
              <Text fz={11} fw={600} tt="uppercase" c="dimmed" style={{ letterSpacing: "0.08em" }}>
                Filtros
              </Text>
              {filtrosActivos > 0 && (
                <Button
                  variant="subtle"
                  color="gray"
                  size="compact-xs"
                  onClick={() => {
                    setFiltros(FILTROS_VACIOS);
                    setTexto("");
                  }}
                >
                  Limpiar ({filtrosActivos})
                </Button>
              )}
            </Group>
            <TextInput
              label="Buscar"
              size="xs"
              placeholder="Código, poste, barrio o marca"
              leftSection={<IconSearch size={14} />}
              value={texto}
              onChange={(e) => setTexto(e.currentTarget.value)}
            />
            {sel("Estado", "Todos", estados.map((e) => ({ value: String(e.id), label: capitalizar(e.nombre) })), "estado")}
            {sel("Tecnología", "Todas", tecnologias.map((e) => ({ value: String(e.id), label: e.nombre })), "tecnologia")}
            {sel("Potencia", "Todas", potencias.map((e) => ({ value: String(e.id), label: e.nombre })), "potencia")}
            {sel("Marca", "Todas", marcas.map((e) => ({ value: String(e.id), label: e.nombre })), "marca")}
            {sel("Tipo de intervención", "Todos", intervenciones.map((e) => ({ value: String(e.id), label: capitalizar(e.nombre) })), "intervencion")}
            {sel("Zona", "Todas", zonas.map((e) => ({ value: String(e.id), label: e.nombre })), "zona", { barrio: null })}
            {sel(
              "Barrio",
              "Todos",
              barrios.filter((b) => !filtros.zona || b.zona_id === Number(filtros.zona)).map((e) => ({ value: String(e.id), label: e.nombre })),
              "barrio",
            )}
            {sel("En bodega", "Todos", siNo, "bodega")}
            {sel("Validado", "Todos", siNo, "validado")}
            {sel("En tránsito", "Todos", siNo, "transito")}
          </Stack>
        </ScrollArea>

        <div
          style={{
            position: "relative",
            flex: 1,
            border: "1px solid var(--sapef-borde)",
            borderRadius: "var(--mantine-radius-sm)",
            overflow: "hidden",
          }}
        >
          <div ref={contenedor} data-testid="mapa-contenedor" style={{ position: "absolute", inset: 0 }} />

          <Paper
            withBorder
            p="xs"
            style={{ position: "absolute", left: 10, bottom: 10, background: "var(--sapef-superficie)", maxWidth: 260 }}
          >
            <Stack gap={5}>
              {ICONOS_MAPA.map((icono) => (
                <Group key={icono.id} gap={7} wrap="nowrap">
                  <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24">
                    <path
                      d={trazoForma(icono.forma)}
                      fill={icono.forma === "cuadrado" ? "#ffffff" : icono.color}
                      stroke={icono.forma === "cuadrado" ? icono.color : "none"}
                      strokeWidth={2.4}
                    />
                  </svg>
                  <Text size="xs">{icono.nombre}</Text>
                </Group>
              ))}
              <Group gap={7} wrap="nowrap">
                <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="9" fill="#2e2e2b" stroke="#e8a33d" strokeWidth="2.5" />
                </svg>
                <Text size="xs">Grupo (cantidad)</Text>
              </Group>
            </Stack>
          </Paper>

          {seleccionada && (
            <Paper
              withBorder
              shadow="md"
              p="md"
              w={320}
              style={{ position: "absolute", right: 10, top: 10, background: "var(--sapef-superficie)" }}
            >
              <Group justify="space-between" wrap="nowrap" mb={6}>
                <Text ff="monospace" fw={600} fz="md">
                  {seleccionada.codigo}
                </Text>
                <EtiquetaEstado codigo={seleccionada.estado_codigo} nombre={seleccionada.estado_nombre ?? ""} />
              </Group>
              <Text size="sm">
                {seleccionada.barrio_nombre ?? "Sin barrio"}
                <Text span c="dimmed">
                  {" "}
                  · {seleccionada.zona_nombre ?? "sin zona"}
                </Text>
              </Text>
              <Text size="xs" c="dimmed" className="sapef-mono" mt={2}>
                {seleccionada.latitud?.toFixed(6)}, {seleccionada.longitud?.toFixed(6)}
              </Text>
              {puedeMover && seleccionada.latitud != null && seleccionada.longitud != null && (
                editandoUbicacion ? (
                  <Stack gap="xs" mt="sm">
                    <Text size="sm">Arrastre el marcador a la ubicación correcta.</Text>
                    {ubicacionNueva && (
                      <Text size="xs" className="sapef-mono">
                        {ubicacionNueva[0].toFixed(6)}, {ubicacionNueva[1].toFixed(6)}
                      </Text>
                    )}
                    <Group gap="xs">
                      <Button size="xs" disabled={!ubicacionNueva} loading={guardandoUbicacion} onClick={() => void guardarUbicacion()}>
                        Guardar ubicación
                      </Button>
                      <Button
                        size="xs"
                        variant="subtle"
                        color="gray"
                        disabled={guardandoUbicacion}
                        onClick={() => {
                          setEditandoUbicacion(false);
                          setUbicacionNueva(null);
                        }}
                      >
                        Cancelar
                      </Button>
                    </Group>
                  </Stack>
                ) : (
                  <Group gap="xs" mt="sm">
                    <Button
                      size="xs"
                      variant="default"
                      onClick={() => {
                        setUbicacionNueva(null);
                        setEditandoUbicacion(true);
                      }}
                    >
                      Corregir ubicación
                    </Button>
                    {seleccionada.google_maps_url && (
                      <Anchor href={seleccionada.google_maps_url} target="_blank" rel="noreferrer" size="xs">
                        Google Maps
                      </Anchor>
                    )}
                  </Group>
                )
              )}
              {!puedeMover && seleccionada.google_maps_url && (
                <Anchor href={seleccionada.google_maps_url} target="_blank" rel="noreferrer" size="xs" mt="xs" display="block">
                  Ver en Google Maps
                </Anchor>
              )}
            </Paper>
          )}
        </div>
      </div>
    </div>
  );
}
