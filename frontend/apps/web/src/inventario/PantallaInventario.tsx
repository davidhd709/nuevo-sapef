import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Drawer,
  FileInput,
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
import { useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { exigir, fecha, mensajeError, subirArchivo } from "../comun/api";

type Material = components["schemas"]["MaterialSalida"];

const ESTADOS_BODEGA = ["124", "123", "125", "112", "126"];

export function PantallaInventario() {
  const { tienePermiso } = useAuth();
  const [mensaje, setMensaje] = useState<string | null>(null);
  if (!tienePermiso("inventario.material.ver") && !tienePermiso("inventario.bodega.ver")) {
    return (
      <Alert color="red" title="403 · Acceso denegado">
        No tiene permiso para consultar el inventario.
      </Alert>
    );
  }
  return (
    <Stack gap="md">
      <Title order={2}>Inventario</Title>
      {mensaje && (
        <Alert color="green" withCloseButton onClose={() => setMensaje(null)}>
          {mensaje}
        </Alert>
      )}
      <Tabs defaultValue={tienePermiso("inventario.material.ver") ? "materiales" : "bodega"}>
        <Tabs.List>
          {tienePermiso("inventario.material.ver") && <Tabs.Tab value="materiales">Materiales</Tabs.Tab>}
          {tienePermiso("inventario.bodega.ver") && <Tabs.Tab value="bodega">Bodega de luminarias</Tabs.Tab>}
        </Tabs.List>
        <Tabs.Panel value="materiales" pt="md">
          <Materiales onMensaje={setMensaje} />
        </Tabs.Panel>
        <Tabs.Panel value="bodega" pt="md">
          <Bodega onMensaje={setMensaje} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

// --- Materiales y kárdex (RF-051) --------------------------------------------------------------

function Materiales({ onMensaje }: { onMensaje: (m: string) => void }) {
  const { sedeActiva, tienePermiso } = useAuth();
  const queryClient = useQueryClient();
  const sede = { "X-Sede": sedeActiva ?? "" };
  const [page, setPage] = useState(1);
  const [buscar, setBuscar] = useState("");
  const [soloBajos, setSoloBajos] = useState(false);
  const [nuevo, setNuevo] = useState(false);
  const [elegido, setElegido] = useState<Material | null>(null);
  const [form, setForm] = useState({ categoria: "", codigo: "", descripcion: "", unidad: "UND" });
  const [existencias, setExistencias] = useState<number | string>(0);
  const [minimas, setMinimas] = useState<number | string>(0);

  const { data, isPending } = useQuery({
    queryKey: ["materiales", sedeActiva, page, buscar, soloBajos],
    enabled: Boolean(sedeActiva),
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/materiales", {
        headers: sede,
        params: { query: { page, size: 50, buscar: buscar || undefined, bajo_minimo: soloBajos || undefined } },
      });
      return exigir(data, error, "No se pudieron cargar los materiales.");
    },
  });

  const crear = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/v1/materiales", {
        headers: sede,
        body: {
          ...form,
          activo: true,
          existencias: Number(existencias) || 0,
          existencias_minimas: Number(minimas) || 0,
        },
      });
      return exigir(data, error, "No se pudo crear el material.");
    },
    onSuccess: (m) => {
      onMensaje(`Material ${m.codigo} creado.`);
      setNuevo(false);
      void queryClient.invalidateQueries({ queryKey: ["materiales"] });
    },
  });

  return (
    <Stack gap="sm">
      <Group>
        <TextInput placeholder="Código o descripción" value={buscar} onChange={(e) => setBuscar(e.currentTarget.value)} w={260} />
        <Checkbox label="Solo bajo el mínimo" checked={soloBajos} onChange={(e) => setSoloBajos(e.currentTarget.checked)} />
        {tienePermiso("inventario.material.editar") && <Button onClick={() => setNuevo(true)}>Nuevo material</Button>}
      </Group>
      {isPending ? (
        <Text c="dimmed">Cargando…</Text>
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Código</Table.Th>
              <Table.Th>Descripción</Table.Th>
              <Table.Th>Categoría</Table.Th>
              <Table.Th>Existencias</Table.Th>
              <Table.Th>Mínimo</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data?.items.map((m) => (
              <Table.Tr key={m.id} onClick={() => setElegido(m)} style={{ cursor: "pointer" }}>
                <Table.Td>{m.codigo}</Table.Td>
                <Table.Td>{m.descripcion}</Table.Td>
                <Table.Td>{m.categoria}</Table.Td>
                <Table.Td>
                  {Number(m.existencias)} {m.unidad}
                </Table.Td>
                <Table.Td>{Number(m.existencias_minimas)}</Table.Td>
                <Table.Td>{m.bajo_minimo && <Badge color="red">Bajo el mínimo</Badge>}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {data && data.total > data.size && (
        <Pagination value={page} onChange={setPage} total={Math.ceil(data.total / data.size)} />
      )}
      <Modal opened={nuevo} onClose={() => setNuevo(false)} title="Nuevo material">
        <Stack gap="sm">
          {(
            [
              ["categoria", "Categoría"],
              ["codigo", "Código"],
              ["descripcion", "Descripción"],
              ["unidad", "Unidad"],
            ] as const
          ).map(([campo, etiqueta]) => (
            <TextInput
              key={campo}
              label={etiqueta}
              value={form[campo]}
              onChange={(e) => setForm({ ...form, [campo]: e.currentTarget.value })}
            />
          ))}
          <Group grow>
            <NumberInput label="Existencias iniciales" min={0} value={existencias} onChange={setExistencias} />
            <NumberInput label="Existencias mínimas" min={0} value={minimas} onChange={setMinimas} />
          </Group>
          {crear.error && <Alert color="red">{mensajeError(crear.error, "Error.")}</Alert>}
          <Button loading={crear.isPending} onClick={() => crear.mutate()}>
            Crear
          </Button>
        </Stack>
      </Modal>
      <Kardex material={elegido} onCerrar={() => setElegido(null)} />
    </Stack>
  );
}

function Kardex({ material, onCerrar }: { material: Material | null; onCerrar: () => void }) {
  const { sedeActiva, tienePermiso } = useAuth();
  const queryClient = useQueryClient();
  const sede = { "X-Sede": sedeActiva ?? "" };
  const [tipo, setTipo] = useState<string>("entrada");
  const [cantidad, setCantidad] = useState<number | string>(1);
  const [descripcion, setDescripcion] = useState("");

  const { data: movimientos } = useQuery({
    queryKey: ["kardex", sedeActiva, material?.id],
    enabled: material !== null,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/materiales/{material_id}/movimientos", {
        headers: sede,
        params: { path: { material_id: material!.id } },
      });
      return exigir(data, error, "No se pudo cargar el kárdex.");
    },
  });

  const registrar = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/v1/materiales/{material_id}/movimientos", {
        headers: sede,
        params: { path: { material_id: material!.id } },
        body: {
          tipo: tipo as "entrada" | "salida" | "ajuste",
          cantidad: Number(cantidad),
          descripcion: descripcion || null,
          uuid_origen: crypto.randomUUID(),
        },
      });
      return exigir(data, error, "No se pudo registrar el movimiento.");
    },
    onSuccess: () => {
      setDescripcion("");
      void queryClient.invalidateQueries({ queryKey: ["kardex"] });
      void queryClient.invalidateQueries({ queryKey: ["materiales"] });
    },
  });

  const tipos = [
    ...(tienePermiso("inventario.movimiento.crear")
      ? [{ value: "entrada", label: "Entrada" }, { value: "salida", label: "Salida" }]
      : []),
    ...(tienePermiso("inventario.movimiento.ajustar") ? [{ value: "ajuste", label: "Ajuste (±)" }] : []),
  ];
  return (
    <Drawer opened={material !== null} onClose={onCerrar} position="right" size="lg" title={`Kárdex · ${material?.codigo ?? ""}`}>
      <Stack gap="sm">
        {tipos.length > 0 && (
          <Group align="end">
            <Select label="Tipo" data={tipos} value={tipo} onChange={(v) => setTipo(v ?? "entrada")} w={140} />
            <NumberInput label="Cantidad" value={cantidad} onChange={setCantidad} w={120} />
            <TextInput label="Descripción" value={descripcion} onChange={(e) => setDescripcion(e.currentTarget.value)} style={{ flex: 1 }} />
            <Button loading={registrar.isPending} onClick={() => registrar.mutate()}>
              Registrar
            </Button>
          </Group>
        )}
        {registrar.error && <Alert color="red">{mensajeError(registrar.error, "Error.")}</Alert>}
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Fecha</Table.Th>
              <Table.Th>Tipo</Table.Th>
              <Table.Th>Cantidad</Table.Th>
              <Table.Th>Saldo</Table.Th>
              <Table.Th>Origen</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {movimientos?.items.map((m) => (
              <Table.Tr key={m.id}>
                <Table.Td>{fecha(m.creado_en)}</Table.Td>
                <Table.Td>{m.tipo}</Table.Td>
                <Table.Td>{Number(m.delta)}</Table.Td>
                <Table.Td>{Number(m.existencias_resultantes)}</Table.Td>
                <Table.Td>{m.orden_id ? `Orden #${m.orden_id}` : m.origen}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>
    </Drawer>
  );
}

// --- Bodega de luminarias (RF-053) ---------------------------------------------------------------

function Bodega({ onMensaje }: { onMensaje: (m: string) => void }) {
  const { sedeActiva, tienePermiso } = useAuth();
  const queryClient = useQueryClient();
  const sede = { "X-Sede": sedeActiva ?? "" };
  const [page, setPage] = useState(1);
  const [estado, setEstado] = useState<string | null>(null);
  const [destinos, setDestinos] = useState<Record<number, string | null>>({});
  const [archivo, setArchivo] = useState<File | null>(null);

  const { data: estados = [] } = useQuery({
    queryKey: ["estados-luminaria"],
    queryFn: async () =>
      (await api.GET("/api/v1/estados", { params: { query: { proceso: "luminaria" } } })).data ?? [],
  });
  const deBodega = estados.filter((e) => ESTADOS_BODEGA.includes(e.codigo));
  const { data, isPending } = useQuery({
    queryKey: ["bodega", sedeActiva, page, estado],
    enabled: Boolean(sedeActiva),
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/bodega/luminarias", {
        headers: sede,
        params: { query: { page, size: 50, estado_id: estado ? Number(estado) : undefined } },
      });
      return exigir(data, error, "No se pudo cargar la bodega.");
    },
  });

  const cambiar = useMutation({
    mutationFn: async ({ id, estadoId }: { id: number; estadoId: number }) => {
      const { data, error } = await api.PATCH("/api/v1/bodega/luminarias/{luminaria_id}", {
        headers: sede,
        params: { path: { luminaria_id: id } },
        body: { estado_id: estadoId },
      });
      return exigir(data, error, "No se pudo cambiar el estado.");
    },
    onSuccess: (l) => {
      onMensaje(`Luminaria ${l.codigo}: ${l.estado_nombre}.`);
      void queryClient.invalidateQueries({ queryKey: ["bodega"] });
    },
  });
  const cargar = useMutation({
    mutationFn: async () => subirArchivo<{ cargueId: number }>("/api/v1/bodega/cargue", archivo!, sedeActiva ?? ""),
    onSuccess: (r) => onMensaje(`Cargue #${r.cargueId} recibido: se valida en segundo plano (todo o nada).`),
  });

  const editable = tienePermiso("inventario.bodega.editar");
  return (
    <Stack gap="sm">
      <Group align="end">
        <Select
          label="Estado"
          clearable
          data={deBodega.map((e) => ({ value: String(e.id), label: `${e.codigo} · ${e.nombre}` }))}
          value={estado}
          onChange={(v) => {
            setEstado(v);
            setPage(1);
          }}
          w={240}
        />
        {editable && (
          <>
            <FileInput placeholder="Cargue de bodega (.xlsx)" accept=".xlsx" value={archivo} onChange={setArchivo} w={240} />
            <Button variant="light" disabled={!archivo} loading={cargar.isPending} onClick={() => cargar.mutate()}>
              Cargar
            </Button>
          </>
        )}
      </Group>
      {(cambiar.error || cargar.error) && (
        <Alert color="red">{mensajeError(cambiar.error ?? cargar.error, "Error.")}</Alert>
      )}
      {isPending ? (
        <Text c="dimmed">Cargando…</Text>
      ) : (
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Código</Table.Th>
              <Table.Th>Estado</Table.Th>
              <Table.Th>Tecnología</Table.Th>
              <Table.Th>Potencia</Table.Th>
              {editable && <Table.Th>Cambiar a</Table.Th>}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data?.items.map((l) => (
              <Table.Tr key={l.id}>
                <Table.Td>{l.codigo}</Table.Td>
                <Table.Td>
                  <Badge variant="light">{l.estado_nombre}</Badge>
                </Table.Td>
                <Table.Td>{l.tecnologia_nombre ?? "—"}</Table.Td>
                <Table.Td>{l.potencia_nombre ?? "—"}</Table.Td>
                {editable && (
                  <Table.Td>
                    {l.estado_codigo !== "126" && (
                      <Group gap="xs">
                        <Select
                          size="xs"
                          data={deBodega
                            .filter((e) => e.codigo !== l.estado_codigo)
                            .map((e) => ({ value: String(e.id), label: `${e.codigo} · ${e.nombre}` }))}
                          value={destinos[l.id] ?? null}
                          onChange={(v) => setDestinos({ ...destinos, [l.id]: v })}
                          w={200}
                        />
                        <Button
                          size="xs"
                          disabled={!destinos[l.id]}
                          onClick={() => cambiar.mutate({ id: l.id, estadoId: Number(destinos[l.id]) })}
                        >
                          Aplicar
                        </Button>
                      </Group>
                    )}
                  </Table.Td>
                )}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {data && data.total > data.size && (
        <Pagination value={page} onChange={setPage} total={Math.ceil(data.total / data.size)} />
      )}
    </Stack>
  );
}
