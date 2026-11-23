import { Alert, Anchor, Badge, Card, Group, Select, Stack, Text, Title } from "@mantine/core";
import { api, type components } from "@sapef/api";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "../auth/AuthContext";

type LuminariaSalida = components["schemas"]["LuminariaSalida"];

export function PantallaMapa() {
  const { sedeActiva, tienePermiso } = useAuth();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [estadoFiltro, setEstadoFiltro] = useState<string | null>(null);
  const [seleccionada, setSeleccionada] = useState<LuminariaSalida | null>(null);

  const headersSede = sedeActiva ? { "X-Sede": sedeActiva } : undefined;
  const puedeVerMapa = tienePermiso("activos.mapa.ver");

  const { data: estados = [] } = useQuery({
    queryKey: ["estados-luminaria"],
    enabled: puedeVerMapa,
    queryFn: async () =>
      (await api.GET("/api/v1/estados", { params: { query: { proceso: "luminaria" } } })).data ??
      [],
  });

  const { data: luminariasResp } = useQuery({
    queryKey: ["mapa-luminarias", sedeActiva, estadoFiltro],
    enabled: puedeVerMapa && Boolean(sedeActiva),
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/luminarias", {
        headers: headersSede,
        params: {
          query: {
            page: 1,
            size: 100,
            estado_id: estadoFiltro ? Number(estadoFiltro) : undefined,
          },
        },
      });
      return data;
    },
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;
    ctx.fillStyle = "#f1f5f9";
    ctx.fillRect(0, 0, w, h);

    // Cuadrícula cartográfica base
    ctx.strokeStyle = "#cbd5e1";
    ctx.lineWidth = 1;
    for (let x = 0; x < w; x += 64) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = 0; y < h; y += 64) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    const puntos = (luminariasResp?.items ?? []).filter(
      (l) => typeof l.latitud === "number" && typeof l.longitud === "number",
    );
    if (puntos.length === 0) {
      ctx.fillStyle = "#475569";
      ctx.font = "14px sans-serif";
      ctx.fillText(`Mapa · ${sedeActiva ?? ""} (sin luminarias georreferenciadas en filtro)`, 24, 36);
      return;
    }

    const lats = puntos.map((p) => p.latitud as number);
    const lngs = puntos.map((p) => p.longitud as number);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLng = Math.min(...lngs);
    const maxLng = Math.max(...lngs);
    const spanLat = Math.max(maxLat - minLat, 0.01);
    const spanLng = Math.max(maxLng - minLng, 0.01);

    for (const p of puntos) {
      const px = 40 + (((p.longitud as number) - minLng) / spanLng) * (w - 80);
      const py = h - 40 - (((p.latitud as number) - minLat) / spanLat) * (h - 80);
      ctx.beginPath();
      ctx.arc(px, py, 6, 0, Math.PI * 2);
      ctx.fillStyle = p.estado_codigo === "122" ? "#dc2626" : "#16a34a";
      ctx.fill();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }, [luminariasResp, sedeActiva]);

  if (!puedeVerMapa) {
    return (
      <Alert color="red" title="403 · Acceso denegado" data-testid="error-403">
        No tiene permiso para visualizar el mapa de luminarias.
      </Alert>
    );
  }

  const puntosGeo = (luminariasResp?.items ?? []).filter(
    (l) => typeof l.latitud === "number" && typeof l.longitud === "number",
  );

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Mapa de alumbrado · {sedeActiva}</Title>
        <Select
          placeholder="Estado"
          clearable
          data={estados.map((e) => ({ value: String(e.id), label: `${e.codigo} · ${e.nombre}` }))}
          value={estadoFiltro}
          onChange={setEstadoFiltro}
          w={240}
        />
      </Group>

      <Group align="flex-start" grow>
        <Card withBorder p="xs">
          <canvas
            ref={canvasRef}
            width={800}
            height={440}
            data-testid="mapa-canvas"
            style={{ width: "100%", height: "440px", borderRadius: "6px", display: "block" }}
          />
          <Group justify="space-between" mt="xs">
            <Text size="xs" c="dimmed">
              Teselas PostGIS MVT + mapa base PMTiles · {puntosGeo.length} puntos mostrados
            </Text>
            {puntosGeo[0] && (
              <Anchor
                size="xs"
                component="button"
                type="button"
                onClick={() => setSeleccionada(puntosGeo[0] ?? null)}
              >
                Ver detalle del primer punto
              </Anchor>
            )}
          </Group>
        </Card>

        {seleccionada && (
          <Card withBorder maw={320}>
            <Stack gap="xs">
              <Group justify="space-between">
                <Text fw={600}>{seleccionada.codigo}</Text>
                <Badge>{seleccionada.estado_nombre}</Badge>
              </Group>
              <Text size="sm">
                Barrio: {seleccionada.barrio_nombre ?? "-"} ({seleccionada.zona_nombre ?? "-"})
              </Text>
              <Text size="xs" c="dimmed">
                {seleccionada.latitud}, {seleccionada.longitud}
              </Text>
              {seleccionada.google_maps_url && (
                <Anchor href={seleccionada.google_maps_url} target="_blank" rel="noreferrer" size="sm">
                  Ver en Google Maps
                </Anchor>
              )}
            </Stack>
          </Card>
        )}
      </Group>
    </Stack>
  );
}
