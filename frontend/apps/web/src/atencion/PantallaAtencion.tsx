import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Drawer,
  Group,
  Modal,
  Pagination,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { api, type components } from "@sapef/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { COLOR_SEMAFORO, PRIORIDADES, exigir, fecha, mensajeError } from "../comun/api";

type Pqrs = components["schemas"]["PqrsSalida"];
type Ciudadano = components["schemas"]["CiudadanoSalida"];
type Luminaria = components["schemas"]["LuminariaSalida"];

interface Props {
  ruta: string;
  navegar: (destino: string) => void;
}

export function PantallaAtencion({ ruta, navegar }: Props) {
  const { tienePermiso } = useAuth();
  const [mensaje, setMensaje] = useState<string | null>(null);
  const [nueva, setNueva] = useState(false);
  const pestana = ruta.startsWith("/atencion/pqrs") ? "pqrs" : "pendientes";

  if (!tienePermiso("atencion.pqrs.ver")) {
    return (
      <Alert color="red" title="403 · Acceso denegado">
        No tiene permiso para consultar PQRS.
      </Alert>
    );
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Atención · PQRS</Title>
        {tienePermiso("atencion.pqrs.crear") && (
          <Button onClick={() => setNueva(true)}>Registrar PQRS</Button>
        )}
      </Group>
      {mensaje && (
        <Alert color="green" withCloseButton onClose={() => setMensaje(null)}>
          {mensaje}
        </Alert>
      )}
      <Tabs value={pestana} onChange={(v) => navegar(`/atencion/${v ?? "pendientes"}`)}>
        <Tabs.List>
          <Tabs.Tab value="pendientes">Luminarias pendientes</Tabs.Tab>
          <Tabs.Tab value="pqrs">PQRS</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="pendientes" pt="md">
          <Pendientes onMensaje={setMensaje} />
        </Tabs.Panel>
        <Tabs.Panel value="pqrs" pt="md">
          <ListaPqrs onMensaje={setMensaje} />
        </Tabs.Panel>
      </Tabs>
      <NuevaPqrs
        abierta={nueva}
        onCerrar={() => setNueva(false)}
        onCreada={(p) => setMensaje(`PQRS ${p.numero} registrada.`)}
      />
    </Stack>
  );
}

// --- Luminarias pendientes con semáforo (RF-035) -----------------------------------------------

function Pendientes({ onMensaje }: { onMensaje: (m: string) => void }) {
  const { sedeActiva, tienePermiso } = useAuth();
  const [semaforo, setSemaforo] = useState("todos");
  const [page, setPage] = useState(1);
  const sede = { "X-Sede": sedeActiva ?? "" };
  const crearOrden = useCrearOrdenDesdePqrs(onMensaje);

  const { data, isPending, error } = useQuery({
    queryKey: ["pendientes", sedeActiva, semaforo, page],
    enabled: Boolean(sedeActiva),
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/pqrs/pendientes", {
        headers: sede,
        params: {
          query: {
            page,
            size: 50,
            semaforo: semaforo === "todos" ? undefined : (semaforo as "verde" | "amarillo" | "rojo"),
          },
        },
      });
      return exigir(data, error, "No se pudieron cargar las pendientes.");
    },
  });

  return (
    <Stack gap="sm">
      <SegmentedControl
        value={semaforo}
        onChange={(v) => {
          setSemaforo(v);
          setPage(1);
        }}
        data={[
          { value: "todos", label: "Todas" },
          { value: "verde", label: "Verde" },
          { value: "amarillo", label: "Amarillo" },
          { value: "rojo", label: "Rojo" },
        ]}
        w={360}
      />
      {error && <Alert color="red">{mensajeError(error, "Error al cargar.")}</Alert>}
      {isPending ? (
        <Text c="dimmed">Cargando…</Text>
      ) : !data || data.items.length === 0 ? (
        <Text c="dimmed">No hay luminarias pendientes.</Text>
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Luminaria</Table.Th>
              <Table.Th>PQRS</Table.Th>
              <Table.Th>Barrio</Table.Th>
              <Table.Th>Prioridad</Table.Th>
              <Table.Th>Solicitante</Table.Th>
              <Table.Th>Reporte</Table.Th>
              <Table.Th>Días</Table.Th>
              <Table.Th>Semáforo</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data.items.map((f) => (
              <Table.Tr key={`${f.pqrs_id}-${f.luminaria_id}`}>
                <Table.Td>{f.luminaria_codigo}</Table.Td>
                <Table.Td>{f.pqrs_numero}</Table.Td>
                <Table.Td>{f.barrio_nombre ?? "—"}</Table.Td>
                <Table.Td>{f.prioridad_nombre}</Table.Td>
                <Table.Td>{f.solicitante ?? "—"}</Table.Td>
                <Table.Td>{fecha(f.fecha_reporte)}</Table.Td>
                <Table.Td>{f.dias_abierta}</Table.Td>
                <Table.Td>
                  <Badge color={COLOR_SEMAFORO[f.semaforo]}>{f.semaforo}</Badge>
                </Table.Td>
                <Table.Td>
                  {tienePermiso("trabajos.orden.crear") && (
                    <Button
                      size="xs"
                      variant="light"
                      loading={crearOrden.isPending}
                      onClick={() =>
                        crearOrden.mutate({ pqrsId: f.pqrs_id, luminariaId: f.luminaria_id })
                      }
                    >
                      Crear orden
                    </Button>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {data && data.total > data.size && (
        <Pagination value={page} onChange={setPage} total={Math.ceil(data.total / data.size)} />
      )}
      {crearOrden.error && <Alert color="red">{mensajeError(crearOrden.error, "Error.")}</Alert>}
    </Stack>
  );
}

function useCrearOrdenDesdePqrs(onMensaje: (m: string) => void) {
  const { sedeActiva } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ pqrsId, luminariaId }: { pqrsId: number; luminariaId: number }) => {
      const { data, error } = await api.POST("/api/v1/ordenes", {
        headers: { "X-Sede": sedeActiva ?? "" },
        body: {
          tipo: "mantenimiento",
          pqrs_id: pqrsId,
          prioridad: 2,
          luminarias: [{ luminaria_id: luminariaId, rol: "intervenida" }],
        },
      });
      return exigir(data, error, "No se pudo crear la orden.");
    },
    onSuccess: (orden) => {
      onMensaje(`Orden ${orden.numero} creada. Asígnela en «Órdenes de trabajo».`);
      void queryClient.invalidateQueries({ queryKey: ["pqrs"] });
      void queryClient.invalidateQueries({ queryKey: ["pendientes"] });
    },
  });
}

// --- Lista y detalle de PQRS -------------------------------------------------------------------

function ListaPqrs({ onMensaje }: { onMensaje: (m: string) => void }) {
  const { sedeActiva } = useAuth();
  const [page, setPage] = useState(1);
  const [prioridad, setPrioridad] = useState<string | null>(null);
  const [seleccionada, setSeleccionada] = useState<number | null>(null);

  const { data, isPending } = useQuery({
    queryKey: ["pqrs", sedeActiva, page, prioridad],
    enabled: Boolean(sedeActiva),
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/pqrs", {
        headers: { "X-Sede": sedeActiva ?? "" },
        params: {
          query: { page, size: 20, prioridad: prioridad ? Number(prioridad) : undefined },
        },
      });
      return exigir(data, error, "No se pudieron cargar las PQRS.");
    },
  });

  return (
    <Stack gap="sm">
      <Group>
        <Select
          placeholder="Prioridad"
          clearable
          data={PRIORIDADES}
          value={prioridad}
          onChange={(v) => {
            setPrioridad(v);
            setPage(1);
          }}
          w={160}
        />
        <Text size="sm" c="dimmed">
          Último mes · {data?.total ?? 0} PQRS
        </Text>
      </Group>
      {isPending ? (
        <Text c="dimmed">Cargando…</Text>
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Número</Table.Th>
              <Table.Th>Fecha</Table.Th>
              <Table.Th>Canal</Table.Th>
              <Table.Th>Solicitante</Table.Th>
              <Table.Th>Luminarias</Table.Th>
              <Table.Th>Prioridad</Table.Th>
              <Table.Th>Estado</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data?.items.map((p) => (
              <Table.Tr key={p.id} onClick={() => setSeleccionada(p.id)} style={{ cursor: "pointer" }}>
                <Table.Td>{p.numero}</Table.Td>
                <Table.Td>{fecha(p.fecha_solicitud)}</Table.Td>
                <Table.Td>{p.canal_nombre}</Table.Td>
                <Table.Td>{p.ciudadano?.nombre_completo ?? "—"}</Table.Td>
                <Table.Td>{p.luminarias.map((l) => l.luminaria_codigo).join(", ")}</Table.Td>
                <Table.Td>{p.prioridad_nombre}</Table.Td>
                <Table.Td>
                  <Badge variant="light">{p.estado_nombre}</Badge>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {data && data.total > data.size && (
        <Pagination value={page} onChange={setPage} total={Math.ceil(data.total / data.size)} />
      )}
      <DetallePqrs id={seleccionada} onCerrar={() => setSeleccionada(null)} onMensaje={onMensaje} />
    </Stack>
  );
}

function DetallePqrs({
  id,
  onCerrar,
  onMensaje,
}: {
  id: number | null;
  onCerrar: () => void;
  onMensaje: (m: string) => void;
}) {
  const { sedeActiva, tienePermiso } = useAuth();
  const queryClient = useQueryClient();
  const [motivo, setMotivo] = useState("");
  const sede = { "X-Sede": sedeActiva ?? "" };
  const crearOrden = useCrearOrdenDesdePqrs(onMensaje);

  const { data: pqrs } = useQuery({
    queryKey: ["pqrs-detalle", sedeActiva, id],
    enabled: id !== null,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/pqrs/{pqrs_id}", {
        headers: sede,
        params: { path: { pqrs_id: id! } },
      });
      return exigir(data, error, "No se pudo cargar la PQRS.");
    },
  });

  const anular = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/v1/pqrs/{pqrs_id}/anular", {
        headers: sede,
        params: { path: { pqrs_id: id! } },
        body: { motivo },
      });
      return exigir(data, error, "No se pudo anular.");
    },
    onSuccess: (p) => {
      onMensaje(`PQRS ${p.numero} anulada.`);
      setMotivo("");
      void queryClient.invalidateQueries({ queryKey: ["pqrs"] });
      void queryClient.invalidateQueries({ queryKey: ["pqrs-detalle"] });
    },
  });

  const abierta = pqrs && !["303", "304"].includes(pqrs.estado_codigo);
  return (
    <Drawer opened={id !== null} onClose={onCerrar} position="right" size="lg" title="PQRS">
      {pqrs && (
        <Stack gap="sm">
          <Title order={3}>
            PQRS {pqrs.numero} · <Badge>{pqrs.estado_nombre}</Badge>
          </Title>
          <Text size="sm">
            {fecha(pqrs.fecha_solicitud)} · {pqrs.canal_nombre} · prioridad {pqrs.prioridad_nombre}
          </Text>
          {pqrs.ciudadano && (
            <Text size="sm">
              {pqrs.ciudadano.nombre_completo} · {pqrs.ciudadano.identificacion} ·{" "}
              {pqrs.ciudadano.celular ?? pqrs.ciudadano.telefono ?? "sin teléfono"}
              {pqrs.ciudadano.enmascarado && " (datos enmascarados)"}
            </Text>
          )}
          {pqrs.observacion_solicitante && <Text>{pqrs.observacion_solicitante}</Text>}
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Luminaria</Table.Th>
                <Table.Th>Reparada</Table.Th>
                <Table.Th>Observación técnica</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {pqrs.luminarias.map((l) => (
                <Table.Tr key={l.id}>
                  <Table.Td>{l.luminaria_codigo}</Table.Td>
                  <Table.Td>{l.reparada ? `Sí (${fecha(l.fecha_reparacion)})` : "No"}</Table.Td>
                  <Table.Td>{l.observacion_tecnico ?? "—"}</Table.Td>
                  <Table.Td>
                    {abierta && !l.reparada && !l.es_comodin && tienePermiso("trabajos.orden.crear") && (
                      <Button
                        size="xs"
                        variant="light"
                        onClick={() =>
                          crearOrden.mutate({ pqrsId: pqrs.id, luminariaId: l.luminaria_id })
                        }
                      >
                        Crear orden
                      </Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {abierta && tienePermiso("atencion.pqrs.anular") && (
            <Group align="end">
              <TextInput
                label="Motivo de anulación"
                value={motivo}
                onChange={(e) => setMotivo(e.currentTarget.value)}
                style={{ flex: 1 }}
              />
              <Button
                color="red"
                variant="light"
                disabled={motivo.trim().length < 3}
                loading={anular.isPending}
                onClick={() => anular.mutate()}
              >
                Anular
              </Button>
            </Group>
          )}
          {(anular.error || crearOrden.error) && (
            <Alert color="red">{mensajeError(anular.error ?? crearOrden.error, "Error.")}</Alert>
          )}
        </Stack>
      )}
    </Drawer>
  );
}

// --- Registrar una PQRS (HU-030) ---------------------------------------------------------------

function NuevaPqrs({
  abierta,
  onCerrar,
  onCreada,
}: {
  abierta: boolean;
  onCerrar: () => void;
  onCreada: (p: Pqrs) => void;
}) {
  const { sedeActiva } = useAuth();
  const queryClient = useQueryClient();
  const sede = { "X-Sede": sedeActiva ?? "" };
  const [canal, setCanal] = useState<string | null>(null);
  const [prioridad, setPrioridad] = useState<string>("2");
  const [observacion, setObservacion] = useState("");
  const [notificar, setNotificar] = useState(false);
  const [buscarCiudadano, setBuscarCiudadano] = useState("");
  const [ciudadano, setCiudadano] = useState<Ciudadano | null>(null);
  const [nuevoCiudadano, setNuevoCiudadano] = useState({ identificacion: "", nombre: "", celular: "", correo: "" });
  const [buscarLuminaria, setBuscarLuminaria] = useState("");
  const [luminarias, setLuminarias] = useState<Luminaria[]>([]);

  const { data: canales = [] } = useQuery({
    queryKey: ["maestros", "CANAL_PQRS"],
    queryFn: async () =>
      (await api.GET("/api/v1/maestros/{clase}", { params: { path: { clase: "CANAL_PQRS" } } }))
        .data ?? [],
  });
  const { data: ciudadanos } = useQuery({
    queryKey: ["ciudadanos", sedeActiva, buscarCiudadano],
    enabled: abierta && buscarCiudadano.trim().length >= 3,
    queryFn: async () =>
      (
        await api.GET("/api/v1/ciudadanos", {
          headers: sede,
          params: { query: { buscar: buscarCiudadano, size: 10 } },
        })
      ).data?.items ?? [],
  });
  const { data: encontradas } = useQuery({
    queryKey: ["luminarias-buscar", sedeActiva, buscarLuminaria],
    enabled: abierta && buscarLuminaria.trim().length >= 2,
    queryFn: async () =>
      (
        await api.GET("/api/v1/luminarias/buscar", {
          headers: sede,
          params: { query: { q: buscarLuminaria } },
        })
      ).data ?? [],
  });

  const registrarCiudadano = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/v1/ciudadanos", {
        headers: sede,
        body: {
          identificacion: nuevoCiudadano.identificacion,
          nombre_completo: nuevoCiudadano.nombre,
          celular: nuevoCiudadano.celular || null,
          correo: nuevoCiudadano.correo || null,
        },
      });
      return exigir(data, error, "No se pudo registrar el solicitante.");
    },
    onSuccess: (c) => setCiudadano(c),
  });

  const crear = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/v1/pqrs", {
        headers: sede,
        body: {
          canal_id: Number(canal),
          ciudadano_id: ciudadano?.id ?? null,
          prioridad: Number(prioridad),
          observacion_solicitante: observacion || null,
          notificar_cliente: notificar,
          luminarias: luminarias.map((l) => ({ luminaria_id: l.id })),
        },
      });
      return exigir(data, error, "No se pudo registrar la PQRS.");
    },
    onSuccess: (p) => {
      onCreada(p);
      setLuminarias([]);
      setCiudadano(null);
      setObservacion("");
      onCerrar();
      void queryClient.invalidateQueries({ queryKey: ["pqrs"] });
      void queryClient.invalidateQueries({ queryKey: ["pendientes"] });
    },
  });

  return (
    <Modal opened={abierta} onClose={onCerrar} title="Registrar PQRS" size="lg">
      <Stack gap="sm">
        <Group grow>
          <Select
            label="Canal"
            required
            data={canales.map((c) => ({ value: String(c.id), label: c.nombre }))}
            value={canal}
            onChange={setCanal}
          />
          <Select
            label="Prioridad"
            data={PRIORIDADES}
            value={prioridad}
            onChange={(v) => setPrioridad(v ?? "2")}
          />
        </Group>

        <Text fw={600} size="sm">
          Solicitante
        </Text>
        {ciudadano ? (
          <Group>
            <Badge size="lg" variant="light">
              {ciudadano.nombre_completo} · {ciudadano.identificacion}
            </Badge>
            <Button size="xs" variant="subtle" onClick={() => setCiudadano(null)}>
              Cambiar
            </Button>
          </Group>
        ) : (
          <>
            <TextInput
              placeholder="Buscar por nombre o identificación (sin tildes)"
              value={buscarCiudadano}
              onChange={(e) => setBuscarCiudadano(e.currentTarget.value)}
            />
            {ciudadanos?.map((c) => (
              <Button key={c.id} variant="default" size="xs" onClick={() => setCiudadano(c)}>
                {c.nombre_completo} · {c.identificacion}
              </Button>
            ))}
            <Group grow align="end">
              <TextInput
                label="Identificación"
                value={nuevoCiudadano.identificacion}
                onChange={(e) =>
                  setNuevoCiudadano({ ...nuevoCiudadano, identificacion: e.currentTarget.value })
                }
              />
              <TextInput
                label="Nombre"
                value={nuevoCiudadano.nombre}
                onChange={(e) => setNuevoCiudadano({ ...nuevoCiudadano, nombre: e.currentTarget.value })}
              />
            </Group>
            <Group grow align="end">
              <TextInput
                label="Celular"
                value={nuevoCiudadano.celular}
                onChange={(e) => setNuevoCiudadano({ ...nuevoCiudadano, celular: e.currentTarget.value })}
              />
              <TextInput
                label="Correo"
                value={nuevoCiudadano.correo}
                onChange={(e) => setNuevoCiudadano({ ...nuevoCiudadano, correo: e.currentTarget.value })}
              />
              <Button
                variant="light"
                loading={registrarCiudadano.isPending}
                disabled={!nuevoCiudadano.identificacion || !nuevoCiudadano.nombre}
                onClick={() => registrarCiudadano.mutate()}
              >
                Registrar solicitante
              </Button>
            </Group>
          </>
        )}

        <Text fw={600} size="sm">
          Luminarias reportadas
        </Text>
        <Group gap="xs">
          {luminarias.map((l) => (
            <Badge
              key={l.id}
              variant="outline"
              rightSection={
                <span
                  role="button"
                  aria-label={`Quitar ${l.codigo}`}
                  style={{ cursor: "pointer" }}
                  onClick={() => setLuminarias(luminarias.filter((x) => x.id !== l.id))}
                >
                  ×
                </span>
              }
            >
              {l.codigo}
            </Badge>
          ))}
        </Group>
        <TextInput
          placeholder="Código de la luminaria (o SIN-IDENTIFICAR)"
          value={buscarLuminaria}
          onChange={(e) => setBuscarLuminaria(e.currentTarget.value)}
        />
        <Group gap="xs">
          {encontradas
            ?.filter((l) => !luminarias.some((x) => x.id === l.id))
            .slice(0, 8)
            .map((l) => (
              <Button
                key={l.id}
                size="xs"
                variant="default"
                onClick={() => {
                  setLuminarias([...luminarias, l]);
                  setBuscarLuminaria("");
                }}
              >
                {l.codigo} · {l.estado_nombre}
              </Button>
            ))}
        </Group>

        <Textarea
          label="Observación del solicitante"
          value={observacion}
          onChange={(e) => setObservacion(e.currentTarget.value)}
        />
        <Checkbox
          label="Notificar al ciudadano por correo"
          checked={notificar}
          onChange={(e) => setNotificar(e.currentTarget.checked)}
        />
        {(crear.error || registrarCiudadano.error) && (
          <Alert color="red">{mensajeError(crear.error ?? registrarCiudadano.error, "Error.")}</Alert>
        )}
        <Group justify="flex-end">
          <Button
            loading={crear.isPending}
            disabled={!canal || luminarias.length === 0}
            onClick={() => crear.mutate()}
          >
            Registrar
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
