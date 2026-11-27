import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Drawer,
  Group,
  Modal,
  NumberInput,
  Pagination,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { api, type components } from "@sapef/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { useAuth } from "../auth/AuthContext";
import { HojaDeVida } from "./HojaDeVida";
import { useMaestro } from "./maestros";
import { PanelLotes } from "./PanelLotes";

type LuminariaSalida = components["schemas"]["LuminariaSalida"];

export function PantallaLuminarias() {
  const { sedeActiva, tienePermiso } = useAuth();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [texto, setTexto] = useState("");
  const [estadoId, setEstadoId] = useState<string | null>(null);
  const [accionId, setAccionId] = useState<string | null>(null);
  const [misionId, setMisionId] = useState<string | null>(null);
  const [seleccionada, setSeleccionada] = useState<LuminariaSalida | null>(null);
  const [modalNueva, setModalNueva] = useState(false);
  const [mensaje, setMensaje] = useState<string | null>(null);

  const [codigoNuevo, setCodigoNuevo] = useState("");
  const [barrioNuevo, setBarrioNuevo] = useState<string | null>(null);
  const [estadoNuevo, setEstadoNuevo] = useState<string | null>(null);
  const [techNuevo, setTechNuevo] = useState<string | null>(null);
  const [potNuevo, setPotNuevo] = useState<string | null>(null);
  const [latNueva, setLatNueva] = useState<number | string>(7.98);
  const [lngNueva, setLngNueva] = useState<number | string>(-75.41);
  const [latFicha, setLatFicha] = useState<number | string>("");
  const [lngFicha, setLngFicha] = useState<number | string>("");

  const headersSede = sedeActiva ? { "X-Sede": sedeActiva } : undefined;
  const puedeVer = tienePermiso("activos.luminaria.ver");
  const acciones = useMaestro("ACCION_OPERATIVA", puedeVer);
  const misiones = useMaestro("MISION_OBJETIVO", puedeVer);

  const { data: estados = [] } = useQuery({
    queryKey: ["estados-luminaria"],
    enabled: puedeVer,
    queryFn: async () =>
      (await api.GET("/api/v1/estados", { params: { query: { proceso: "luminaria" } } })).data ??
      [],
  });

  const { data: barrios = [] } = useQuery({
    queryKey: ["barrios", sedeActiva],
    enabled: puedeVer && Boolean(sedeActiva),
    queryFn: async () =>
      (await api.GET("/api/v1/barrios", { headers: headersSede })).data ?? [],
  });

  const { data: tecnologias = [] } = useQuery({
    queryKey: ["maestros", "LUMINARIA_TECNOLOGIA"],
    enabled: puedeVer,
    queryFn: async () =>
      (
        await api.GET("/api/v1/maestros/{clase}", {
          params: { path: { clase: "LUMINARIA_TECNOLOGIA" } },
        })
      ).data ?? [],
  });

  const { data: potencias = [] } = useQuery({
    queryKey: ["maestros", "LUMINARIA_POTENCIA"],
    enabled: puedeVer,
    queryFn: async () =>
      (
        await api.GET("/api/v1/maestros/{clase}", {
          params: { path: { clase: "LUMINARIA_POTENCIA" } },
        })
      ).data ?? [],
  });

  const { data: lista, isPending } = useQuery({
    queryKey: ["luminarias", sedeActiva, page, texto, estadoId, accionId, misionId],
    enabled: puedeVer && Boolean(sedeActiva),
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/luminarias", {
        headers: headersSede,
        params: {
          query: {
            page,
            size: 20,
            texto: texto || undefined,
            estado_id: estadoId ? Number(estadoId) : undefined,
            accion_operativa_id: accionId ? Number(accionId) : undefined,
            mision_objetivo_id: misionId ? Number(misionId) : undefined,
          },
        },
      });
      return data;
    },
  });

  const { data: historial } = useQuery({
    queryKey: ["luminaria-historial", sedeActiva, seleccionada?.id],
    enabled: Boolean(seleccionada) && Boolean(sedeActiva),
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/luminarias/{luminaria_id}/historial", {
        headers: headersSede,
        params: { path: { luminaria_id: seleccionada!.id } },
      });
      return data;
    },
  });

  const crearMut = useMutation({
    mutationFn: async () => {
      if (!estadoNuevo) throw new Error("Seleccione un estado.");
      const { data, error } = await api.POST("/api/v1/luminarias", {
        headers: headersSede,
        body: {
          codigo: codigoNuevo,
          barrio_id: barrioNuevo ? Number(barrioNuevo) : null,
          estado_id: Number(estadoNuevo),
          tecnologia_id: techNuevo ? Number(techNuevo) : null,
          potencia_id: potNuevo ? Number(potNuevo) : null,
          latitud: typeof latNueva === "number" ? latNueva : null,
          longitud: typeof lngNueva === "number" ? lngNueva : null,
          es_rural: false,
          subnormal: false,
          tiene_medida: false,
          en_transito: false,
          validado: false,
        },
      });
      if (!data) {
        throw new Error(
          error && typeof error === "object" && "detail" in error && typeof error.detail === "string"
            ? error.detail
            : "No se pudo registrar la luminaria.",
        );
      }
      return data;
    },
    onSuccess: (creada) => {
      setModalNueva(false);
      setCodigoNuevo("");
      setMensaje(`Luminaria ${creada.codigo} registrada.`);
      void queryClient.invalidateQueries({ queryKey: ["luminarias"] });
    },
  });

  const exportarMut = useMutation({
    mutationFn: async () => {
      const { data } = await api.POST("/api/v1/luminarias/exportar", {
        headers: headersSede,
        body: { texto: texto || null },
      });
      return data;
    },
    onSuccess: (res) => {
      if (res) {
        setMensaje(`Exportación encolada en segundo plano (tarea #${res.tareaId}).`);
      }
    },
  });

  const moverMut = useMutation({
    mutationFn: async () => {
      if (!seleccionada || typeof latFicha !== "number" || typeof lngFicha !== "number") {
        throw new Error("Ingrese la latitud y la longitud verificadas.");
      }
      const { data, error } = await api.POST("/api/v1/luminarias/{luminaria_id}/ubicacion", {
        headers: headersSede,
        params: { path: { luminaria_id: seleccionada.id } },
        body: { latitud: latFicha, longitud: lngFicha, origen: "ficha_web" },
      });
      if (!data) {
        throw new Error(
          error && typeof error === "object" && "detail" in error && typeof error.detail === "string"
            ? error.detail
            : "No se pudo guardar la ubicación.",
        );
      }
      return data;
    },
    onSuccess: (actualizada) => {
      setSeleccionada(actualizada);
      setMensaje(`Ubicación de ${actualizada.codigo} actualizada y registrada en el historial.`);
      void queryClient.invalidateQueries({ queryKey: ["luminarias"] });
      void queryClient.invalidateQueries({ queryKey: ["luminaria-historial", sedeActiva, actualizada.id] });
    },
  });

  if (!puedeVer) {
    return (
      <Alert color="red" title="403 · Acceso denegado" data-testid="error-403">
        No tiene permiso para consultar luminarias.
      </Alert>
    );
  }

  function manejarCrear(e: FormEvent) {
    e.preventDefault();
    crearMut.mutate();
  }

  const totalPaginas = lista ? Math.max(1, Math.ceil(lista.total / lista.size)) : 1;

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Luminarias · {sedeActiva}</Title>
        <Group gap="xs">
          {tienePermiso("activos.luminaria.exportar") && (
            <Button variant="light" onClick={() => exportarMut.mutate()} loading={exportarMut.isPending}>
              Exportar Excel
            </Button>
          )}
          {tienePermiso("activos.luminaria.crear") && (
            <Button onClick={() => setModalNueva(true)}>Nueva luminaria</Button>
          )}
        </Group>
      </Group>

      {mensaje && (
        <Alert color="green" withCloseButton onClose={() => setMensaje(null)}>
          {mensaje}
        </Alert>
      )}

      <Tabs defaultValue="luminarias">
        <Tabs.List>
          <Tabs.Tab value="luminarias">Luminarias</Tabs.Tab>
          <Tabs.Tab value="lotes">Lotes de marcación</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="luminarias" pt="md">
      <Stack gap="md">
      <Group>
        <TextInput
          placeholder="Buscar código, poste, barrio o marca..."
          value={texto}
          onChange={(e) => {
            setTexto(e.currentTarget.value);
            setPage(1);
          }}
          w={320}
        />
        <Select
          placeholder="Filtrar por estado"
          clearable
          data={estados.map((e) => ({ value: String(e.id), label: `${e.codigo} · ${e.nombre}` }))}
          value={estadoId}
          onChange={(v) => {
            setEstadoId(v);
            setPage(1);
          }}
          w={240}
        />
        <Select
          placeholder="Acción operativa"
          clearable
          data={acciones.opciones}
          value={accionId}
          onChange={(v) => {
            setAccionId(v);
            setPage(1);
          }}
          w={220}
        />
        <Select
          placeholder="Misión u objetivo"
          clearable
          data={misiones.opciones}
          value={misionId}
          onChange={(v) => {
            setMisionId(v);
            setPage(1);
          }}
          w={260}
        />
      </Group>

      <Card withBorder p={0}>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Código</Table.Th>
              <Table.Th>Barrio</Table.Th>
              <Table.Th>Zona</Table.Th>
              <Table.Th>Estado</Table.Th>
              <Table.Th>Tecnología</Table.Th>
              <Table.Th>Potencia</Table.Th>
              <Table.Th>Acción operativa</Table.Th>
              <Table.Th>Ficha</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {isPending && (
              <Table.Tr>
                <Table.Td colSpan={8}>Cargando luminarias...</Table.Td>
              </Table.Tr>
            )}
            {(lista?.items ?? []).map((lum) => (
              <Table.Tr key={lum.id}>
                <Table.Td>{lum.codigo}</Table.Td>
                <Table.Td>{lum.barrio_nombre ?? "-"}</Table.Td>
                <Table.Td>{lum.zona_nombre ?? "-"}</Table.Td>
                <Table.Td>
                  <Badge variant="light">{lum.estado_nombre ?? lum.estado_id}</Badge>
                </Table.Td>
                <Table.Td>{lum.tecnologia_nombre ?? "-"}</Table.Td>
                <Table.Td>{lum.potencia_nombre ?? "-"}</Table.Td>
                <Table.Td>{acciones.nombre(lum.accion_operativa_id)}</Table.Td>
                <Table.Td>
                  <Button size="xs" variant="subtle" onClick={() => { setSeleccionada(lum); setLatFicha(lum.latitud ?? ""); setLngFicha(lum.longitud ?? ""); moverMut.reset(); }}>
                    Ver ficha
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>

      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          Total: {lista?.total ?? 0} luminarias
        </Text>
        <Pagination total={totalPaginas} value={page} onChange={setPage} />
      </Group>
      </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="lotes" pt="md">
          <PanelLotes />
        </Tabs.Panel>
      </Tabs>

      <Drawer
        opened={Boolean(seleccionada)}
        onClose={() => setSeleccionada(null)}
        title={`Ficha · ${seleccionada?.codigo ?? ""}`}
        position="right"
        size="lg"
      >
        {seleccionada && (
          <Stack gap="sm">
            <Text size="sm">
              <strong>Estado:</strong> {seleccionada.estado_nombre}
            </Text>
            <Text size="sm">
              <strong>Barrio / Zona:</strong> {seleccionada.barrio_nombre ?? "-"} /{" "}
              {seleccionada.zona_nombre ?? "-"}
            </Text>
            <Text size="sm">
              <strong>Ubicación actual:</strong> {seleccionada.latitud != null && seleccionada.longitud != null
                ? `${seleccionada.latitud}, ${seleccionada.longitud}` : "Sin coordenadas"}
            </Text>
            <HojaDeVida
              luminaria={seleccionada}
              alGuardar={(actualizada) => {
                setSeleccionada(actualizada);
                setMensaje(`Hoja de vida de ${actualizada.codigo} actualizada.`);
              }}
            />
            {tienePermiso("activos.luminaria.mover") && (
              <Card withBorder>
                <Stack gap="xs">
                  <Text fw={600} size="sm">Asignar ubicación verificada</Text>
                  <Text size="xs" c="dimmed">Compruebe las coordenadas antes de guardarlas. El cambio queda en la hoja de vida.</Text>
                  <Group grow>
                    <NumberInput label="Latitud" decimalScale={6} value={latFicha} onChange={setLatFicha} />
                    <NumberInput label="Longitud" decimalScale={6} value={lngFicha} onChange={setLngFicha} />
                  </Group>
                  {moverMut.error && <Alert color="red">{moverMut.error.message}</Alert>}
                  <Button size="xs" disabled={typeof latFicha !== "number" || typeof lngFicha !== "number" ||
                    (latFicha === seleccionada.latitud && lngFicha === seleccionada.longitud)}
                    loading={moverMut.isPending} onClick={() => moverMut.mutate()}>Guardar ubicación</Button>
                </Stack>
              </Card>
            )}
            {seleccionada.google_maps_url && (
              <Anchor href={seleccionada.google_maps_url} target="_blank" rel="noreferrer">
                Ver en Google Maps
              </Anchor>
            )}
            <Title order={5} mt="sm">
              Eventos registrados ({historial?.eventos.length ?? 0})
            </Title>
            {(historial?.eventos ?? []).map((ev) => (
              <Card key={ev.id} withBorder p="xs">
                <Group justify="space-between">
                  <Badge>{ev.tipo}</Badge>
                  <Text size="xs" c="dimmed">
                    {new Date(ev.fecha).toLocaleString()}
                  </Text>
                </Group>
              </Card>
            ))}
          </Stack>
        )}
      </Drawer>

      <Modal opened={modalNueva} onClose={() => setModalNueva(false)} title="Nueva luminaria">
        <form onSubmit={manejarCrear}>
          <Stack gap="sm">
            {crearMut.error && <Alert color="red">{crearMut.error.message}</Alert>}
            <TextInput
              label="Código"
              required
              value={codigoNuevo}
              onChange={(e) => setCodigoNuevo(e.currentTarget.value)}
            />
            <Select
              label="Estado"
              required
              data={estados.map((e) => ({ value: String(e.id), label: `${e.codigo} · ${e.nombre}` }))}
              value={estadoNuevo}
              onChange={setEstadoNuevo}
            />
            <Select
              label="Barrio"
              searchable
              data={barrios.map((b) => ({ value: String(b.id), label: `${b.nombre} (${b.zona_nombre})` }))}
              value={barrioNuevo}
              onChange={setBarrioNuevo}
            />
            <Select
              label="Tecnología"
              data={tecnologias.map((t) => ({ value: String(t.id), label: t.nombre }))}
              value={techNuevo}
              onChange={setTechNuevo}
            />
            <Select
              label="Potencia"
              data={potencias.map((p) => ({ value: String(p.id), label: p.nombre }))}
              value={potNuevo}
              onChange={setPotNuevo}
            />
            <Group grow>
              <NumberInput label="Latitud" decimalScale={6} value={latNueva} onChange={setLatNueva} />
              <NumberInput label="Longitud" decimalScale={6} value={lngNueva} onChange={setLngNueva} />
            </Group>
            <Button type="submit" loading={crearMut.isPending}>
              Guardar
            </Button>
          </Stack>
        </form>
      </Modal>
    </Stack>
  );
}
