import {
  Alert,
  Anchor,
  Button,
  Checkbox,
  Drawer,
  FileInput,
  Group,
  Modal,
  NumberInput,
  Pagination,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { api, type components } from "@sapef/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuth } from "../auth/AuthContext";
import {
  Cargando,
  cifra,
  Codigo,
  EncabezadoPagina,
  EstadoVacio,
  EtiquetaEstado,
  MarcoTabla,
  SinPermiso,
} from "../comun/ui";
import { IconAlertTriangle, IconPlus } from "@tabler/icons-react";
import { PRIORIDADES, exigir, fecha, mensajeError, subirArchivo } from "../comun/api";

type Orden = components["schemas"]["OrdenSalida"];
type TipoOrden = Orden["tipo"] & ("mantenimiento" | "modernizacion" | "expansion" | "reubicacion");

const TIPOS = [
  { value: "mantenimiento", label: "Mantenimiento" },
  { value: "modernizacion", label: "Modernización" },
  { value: "expansion", label: "Expansión" },
  { value: "reubicacion", label: "Reubicación" },
];
function nombreTipo(tipo: string): string {
  return TIPOS.find((t) => t.value === tipo)?.label ?? tipo;
}

const ROL: Record<string, string> = { intervenida: "", instalada: "instalada", desmontada: "desmontada" };

/** Códigos de las luminarias de una orden; en cambios, indica cuál se instala y cuál se desmonta. */
function Luminarias({ items }: { items: { luminaria_codigo: string; rol: string }[] }) {
  return (
    <span>
      {items.map((l, i) => (
        <span key={`${l.luminaria_codigo}-${i}`}>
          {i > 0 && <span style={{ color: "var(--sapef-texto-suave)" }}> → </span>}
          <Codigo>{l.luminaria_codigo}</Codigo>
          {ROL[l.rol] ? (
            <Text span size="xs" c="dimmed">
              {" "}
              {ROL[l.rol]}
            </Text>
          ) : null}
        </span>
      ))}
    </span>
  );
}

const COMPONENTES: [string, string][] = [
  ["conexion_red", "Conexión a red"],
  ["conexion_interna", "Conexión interna"],
  ["base_fotocelda", "Base de fotocelda"],
  ["fotocelda", "Fotocelda"],
  ["bombillo", "Bombillo"],
  ["socket", "Socket"],
  ["arrancador", "Arrancador"],
  ["condensador", "Condensador"],
  ["balasta", "Balasta"],
  ["tubo", "Tubo"],
  ["collarin", "Collarín"],
  ["conectores_perforacion", "Conectores de perforación"],
];
const DESTINOS = [
  { value: "112", label: "112 · Desmontada" },
  { value: "124", label: "124 · Bodega buena" },
  { value: "123", label: "123 · Bodega de baja" },
  { value: "125", label: "125 · Bodega en garantía" },
];

export function PantallaOrdenes() {
  const { sedeActiva, tienePermiso } = useAuth();
  const [page, setPage] = useState(1);
  const [tipo, setTipo] = useState<string | null>(null);
  const [estadoId, setEstadoId] = useState<string | null>(null);
  const [seleccionada, setSeleccionada] = useState<number | null>(null);
  const [nueva, setNueva] = useState(false);
  const [mensaje, setMensaje] = useState<string | null>(null);
  const puedeVer = tienePermiso("trabajos.orden.ver") || tienePermiso("trabajos.orden.ver_propias");

  const { data, isPending } = useQuery({
    queryKey: ["ordenes", sedeActiva, page, tipo, estadoId],
    enabled: puedeVer && Boolean(sedeActiva),
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/ordenes", {
        headers: { "X-Sede": sedeActiva ?? "" },
        params: {
          query: {
            page,
            size: 20,
            tipo: (tipo as TipoOrden) ?? undefined,
            estado_id: estadoId ? Number(estadoId) : undefined,
          },
        },
      });
      return exigir(data, error, "No se pudieron cargar las órdenes.");
    },
  });

  const { data: estadosOrden = [] } = useQuery({
    queryKey: ["estados", "orden"],
    enabled: puedeVer,
    queryFn: async () =>
      (await api.GET("/api/v1/estados", { params: { query: { proceso: "orden" } } })).data ?? [],
  });

  if (!puedeVer) {
    return <SinPermiso mensaje="No tiene permiso para consultar órdenes de trabajo." />;
  }

  const lista = (
    <Stack gap="sm">
      <Group gap="xs">
        <Select
          placeholder="Tipo"
          aria-label="Tipo"
          clearable
          data={TIPOS}
          value={tipo}
          onChange={(v) => {
            setTipo(v);
            setPage(1);
          }}
          w={180}
        />
        <Select
          placeholder="Estado"
          aria-label="Estado"
          clearable
          data={estadosOrden.map((e) => ({ value: String(e.id), label: e.nombre }))}
          value={estadoId}
          onChange={(v) => {
            setEstadoId(v);
            setPage(1);
          }}
          w={180}
        />
      </Group>
      {isPending ? (
        <Cargando texto="Cargando órdenes…" />
      ) : !data || data.items.length === 0 ? (
        <EstadoVacio
          titulo={tipo || estadoId ? "Ninguna orden coincide con los filtros" : "Aún no hay órdenes en esta sede"}
          descripcion="Las órdenes se crean desde una PQRS pendiente o con «Nueva orden»."
        />
      ) : (
        <MarcoTabla>
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Número</Table.Th>
              <Table.Th>Tipo</Table.Th>
              <Table.Th>Luminarias</Table.Th>
              <Table.Th>Asignada a</Table.Th>
              <Table.Th>Creada</Table.Th>
              <Table.Th>Estado</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data?.items.map((o) => (
              <Table.Tr key={o.id} onClick={() => setSeleccionada(o.id)} style={{ cursor: "pointer" }}>
                <Table.Td>
                  <Codigo>#{o.numero}</Codigo>
                </Table.Td>
                <Table.Td>{nombreTipo(o.tipo)}</Table.Td>
                <Table.Td>
                  <Luminarias items={o.luminarias} />
                </Table.Td>
                <Table.Td c={o.tecnico_nombre || o.cuadrilla_nombre ? undefined : "dimmed"}>
                  {o.tecnico_nombre ?? o.cuadrilla_nombre ?? "Sin asignar"}
                </Table.Td>
                <Table.Td>{fecha(o.creado_en)}</Table.Td>
                <Table.Td>
                  <EtiquetaEstado codigo={o.estado_codigo} nombre={o.estado_nombre} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        </MarcoTabla>
      )}
      <Group justify="space-between">
        <Text size="sm" c="dimmed" className="sapef-cifra">
          {cifra(data?.total ?? 0)} órdenes
        </Text>
        {data && data.total > data.size && (
          <Pagination value={page} onChange={setPage} total={Math.ceil(data.total / data.size)} />
        )}
      </Group>
    </Stack>
  );

  return (
    <Stack gap="md">
      <EncabezadoPagina
        seccion="Operación"
        titulo="Órdenes de trabajo"
        descripcion="Mantenimientos, modernizaciones, expansiones y reubicaciones: asignación, ejecución en campo y cierre."
        acciones={
          tienePermiso("trabajos.orden.crear") && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setNueva(true)}>
              Nueva orden
            </Button>
          )
        }
      />
      {mensaje && (
        <Alert color="green" withCloseButton onClose={() => setMensaje(null)}>
          {mensaje}
        </Alert>
      )}
      {tienePermiso("trabajos.orden.ver") && <ConflictosCampo onAbrir={setSeleccionada} />}
      {tienePermiso("trabajos.cargue_masivo.crear") ? (
        <Tabs defaultValue="ordenes">
          <Tabs.List mb="md">
            <Tabs.Tab value="ordenes">Órdenes</Tabs.Tab>
            <Tabs.Tab value="cargue">Cargue masivo</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="ordenes">{lista}</Tabs.Panel>
          <Tabs.Panel value="cargue">
            <CargueMasivo onMensaje={setMensaje} />
          </Tabs.Panel>
        </Tabs>
      ) : (
        lista
      )}
      <NuevaOrden
        abierta={nueva}
        onCerrar={() => setNueva(false)}
        onCreada={(o) => setMensaje(`Orden ${o.numero} creada.`)}
      />
      <DetalleOrden id={seleccionada} onCerrar={() => setSeleccionada(null)} onMensaje={setMensaje} />
    </Stack>
  );
}

// --- Conflictos de la app de campo (§9.7) -------------------------------------------------------

/** Trabajos hechos en campo que no se aplicaron: la orden se anuló o reasignó mientras el técnico
 * estaba sin señal, o faltó material. El técnico también los ve en su teléfono. */
function ConflictosCampo({ onAbrir }: { onAbrir: (id: number) => void }) {
  const { sedeActiva } = useAuth();
  const { data } = useQuery({
    queryKey: ["campo-conflictos", sedeActiva],
    enabled: Boolean(sedeActiva),
    refetchInterval: 60_000,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/campo/operaciones", {
        headers: { "X-Sede": sedeActiva ?? "" },
        params: { query: { estado: "conflicto", size: 20 } },
      });
      return exigir(data, error, "No se pudieron cargar los conflictos de campo.");
    },
  });
  if (!data || data.total === 0) return null;
  return (
    <Alert
      color="orange"
      icon={<IconAlertTriangle size={18} />}
      title={`${data.total} trabajos de la app de campo no se aplicaron`}
    >
      <Text size="sm" mb="xs">
        La orden se anuló o reasignó mientras el técnico estaba sin señal, o faltó material. Revise cada caso.
      </Text>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Orden</Table.Th>
            <Table.Th>Técnico</Table.Th>
            <Table.Th>Motivo</Table.Th>
            <Table.Th>Registrado en campo</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {data.items.map((c) => (
            <Table.Tr key={c.uuid}>
              <Table.Td>
                {c.orden_id ? (
                  <Anchor component="button" onClick={() => onAbrir(c.orden_id as number)}>
                    {c.orden_numero ?? c.orden_id}
                  </Anchor>
                ) : (
                  "—"
                )}
              </Table.Td>
              <Table.Td>{c.usuario_nombre}</Table.Td>
              <Table.Td>{c.motivo}</Table.Td>
              <Table.Td>{fecha(c.creada_en)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Alert>
  );
}

// --- Nueva orden ---------------------------------------------------------------------------------

function NuevaOrden({
  abierta,
  onCerrar,
  onCreada,
}: {
  abierta: boolean;
  onCerrar: () => void;
  onCreada: (o: Orden) => void;
}) {
  const { sedeActiva } = useAuth();
  const queryClient = useQueryClient();
  const sede = { "X-Sede": sedeActiva ?? "" };
  const [tipo, setTipo] = useState<string>("mantenimiento");
  const [prioridad, setPrioridad] = useState("2");
  const [codigoPrincipal, setCodigoPrincipal] = useState("");
  const [codigoDesmontada, setCodigoDesmontada] = useState("");
  const [observaciones, setObservaciones] = useState("");
  const conPar = tipo === "modernizacion" || tipo === "reubicacion";

  async function idPorCodigo(codigo: string): Promise<number> {
    const { data } = await api.GET("/api/v1/luminarias/buscar", {
      headers: sede,
      params: { query: { q: codigo } },
    });
    const exacta = data?.find((l) => l.codigo.toLowerCase() === codigo.trim().toLowerCase());
    if (!exacta) throw new Error(`No existe la luminaria ${codigo} en la sede.`);
    return exacta.id;
  }

  const crear = useMutation({
    mutationFn: async () => {
      const principal = await idPorCodigo(codigoPrincipal);
      const rolPrincipal = tipo === "mantenimiento" ? "intervenida" : "instalada";
      const luminarias: { luminaria_id: number; rol: "intervenida" | "instalada" | "desmontada" }[] = [
        { luminaria_id: principal, rol: rolPrincipal },
      ];
      if (conPar) luminarias.push({ luminaria_id: await idPorCodigo(codigoDesmontada), rol: "desmontada" });
      const { data, error } = await api.POST("/api/v1/ordenes", {
        headers: sede,
        body: {
          tipo: tipo as TipoOrden,
          prioridad: Number(prioridad),
          observaciones: observaciones || null,
          luminarias,
        },
      });
      return exigir(data, error, "No se pudo crear la orden.");
    },
    onSuccess: (o) => {
      onCreada(o);
      setCodigoPrincipal("");
      setCodigoDesmontada("");
      onCerrar();
      void queryClient.invalidateQueries({ queryKey: ["ordenes"] });
    },
  });

  return (
    <Modal opened={abierta} onClose={onCerrar} title="Nueva orden de trabajo">
      <Stack gap="sm">
        <Select label="Tipo" data={TIPOS} value={tipo} onChange={(v) => setTipo(v ?? "mantenimiento")} />
        <Select label="Prioridad" data={PRIORIDADES} value={prioridad} onChange={(v) => setPrioridad(v ?? "2")} />
        <TextInput
          label={tipo === "mantenimiento" ? "Luminaria a intervenir" : "Luminaria a instalar (de bodega)"}
          value={codigoPrincipal}
          onChange={(e) => setCodigoPrincipal(e.currentTarget.value)}
        />
        {conPar && (
          <TextInput
            label="Luminaria a desmontar"
            value={codigoDesmontada}
            onChange={(e) => setCodigoDesmontada(e.currentTarget.value)}
          />
        )}
        <Textarea label="Observaciones" value={observaciones} onChange={(e) => setObservaciones(e.currentTarget.value)} />
        {crear.error && <Alert color="red">{mensajeError(crear.error, "Error.")}</Alert>}
        <Group justify="flex-end">
          <Button
            loading={crear.isPending}
            disabled={!codigoPrincipal || (conPar && !codigoDesmontada)}
            onClick={() => crear.mutate()}
          >
            Crear
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

// --- Detalle: asignar, cerrar, anular ----------------------------------------------------------

function DetalleOrden({
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
  const sede = { "X-Sede": sedeActiva ?? "" };
  const [tecnico, setTecnico] = useState<string | null>(null);
  const [cuadrilla, setCuadrilla] = useState<string | null>(null);
  const [motivo, setMotivo] = useState("");

  const { data: orden } = useQuery({
    queryKey: ["orden", sedeActiva, id],
    enabled: id !== null,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/ordenes/{orden_id}", {
        headers: sede,
        params: { path: { orden_id: id! } },
      });
      return exigir(data, error, "No se pudo cargar la orden.");
    },
  });
  const puedeAsignar = tienePermiso("trabajos.orden.asignar");
  const { data: tecnicos = [] } = useQuery({
    queryKey: ["tecnicos", sedeActiva],
    enabled: id !== null && puedeAsignar,
    queryFn: async () => (await api.GET("/api/v1/tecnicos", { headers: sede })).data ?? [],
  });
  const { data: cuadrillas = [] } = useQuery({
    queryKey: ["cuadrillas", sedeActiva],
    enabled: id !== null && puedeAsignar,
    queryFn: async () =>
      (await api.GET("/api/v1/cuadrillas", { headers: sede, params: { query: { activa: true } } }))
        .data ?? [],
  });

  const refrescar = () => {
    void queryClient.invalidateQueries({ queryKey: ["ordenes"] });
    void queryClient.invalidateQueries({ queryKey: ["orden"] });
  };
  const asignar = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/v1/ordenes/{orden_id}/asignar", {
        headers: sede,
        params: { path: { orden_id: id! } },
        body: {
          tecnico_id: tecnico ? Number(tecnico) : null,
          cuadrilla_id: cuadrilla ? Number(cuadrilla) : null,
        },
      });
      return exigir(data, error, "No se pudo asignar.");
    },
    onSuccess: (o) => {
      onMensaje(`Orden ${o.numero} asignada.`);
      refrescar();
    },
  });
  const anular = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/v1/ordenes/{orden_id}/anular", {
        headers: sede,
        params: { path: { orden_id: id! } },
        body: { motivo },
      });
      return exigir(data, error, "No se pudo anular.");
    },
    onSuccess: (o) => {
      onMensaje(`Orden ${o.numero} anulada.`);
      refrescar();
    },
  });

  const abierta = orden && ["201", "202", "205"].includes(orden.estado_codigo);
  const puedeCerrar = tienePermiso("trabajos.orden.cerrar") || tienePermiso("trabajos.orden.ejecutar");
  return (
    <Drawer
      opened={id !== null}
      onClose={onCerrar}
      position="right"
      size="xl"
      title={
        orden && (
          <Group gap="sm">
            <Text fw={600} fz="lg">
              {nombreTipo(orden.tipo)} <Codigo>#{orden.numero}</Codigo>
            </Text>
            <EtiquetaEstado codigo={orden.estado_codigo} nombre={orden.estado_nombre} />
          </Group>
        )
      }
    >
      {orden && (
        <Stack gap="sm">
          <Text size="sm">
            Luminarias: <Luminarias items={orden.luminarias} />
            {orden.pqrs_id && ` · desde la PQRS #${orden.pqrs_id}`}
          </Text>
          {orden.materiales.length > 0 && (
            <Text size="sm">
              Materiales: {orden.materiales.map((m) => `${m.material_codigo} × ${Number(m.cantidad)}`).join(", ")}
            </Text>
          )}
          {orden.evidencias.length > 0 && (
            <Group gap="xs">
              {orden.evidencias.map((e) => (
                <Anchor key={e.archivo_id} href={`/api/v1/archivos/${e.archivo_id}`} target="_blank">
                  {e.tipo}
                </Anchor>
              ))}
            </Group>
          )}

          {abierta && puedeAsignar && (
            <Group align="end">
              <Select
                label="Técnico"
                clearable
                data={tecnicos.map((t) => ({ value: String(t.id), label: t.nombre_completo }))}
                value={tecnico}
                onChange={setTecnico}
              />
              <Select
                label="Cuadrilla"
                clearable
                data={cuadrillas.map((c) => ({ value: String(c.id), label: c.nombre }))}
                value={cuadrilla}
                onChange={setCuadrilla}
              />
              <Button
                loading={asignar.isPending}
                disabled={!tecnico && !cuadrilla}
                onClick={() => asignar.mutate()}
              >
                Asignar
              </Button>
            </Group>
          )}
          {abierta && puedeCerrar && (
            <FormularioCierre orden={orden} onCerrada={(o) => { onMensaje(`Orden ${o.numero} cerrada.`); refrescar(); }} />
          )}
          {abierta && tienePermiso("trabajos.orden.anular") && (
            <Group align="end">
              <TextInput label="Motivo de anulación" value={motivo} onChange={(e) => setMotivo(e.currentTarget.value)} style={{ flex: 1 }} />
              <Button color="red" variant="outline" disabled={motivo.trim().length < 3} loading={anular.isPending} onClick={() => anular.mutate()}>
                Anular
              </Button>
            </Group>
          )}
          {(asignar.error || anular.error) && (
            <Alert color="red">{mensajeError(asignar.error ?? anular.error, "Error.")}</Alert>
          )}
        </Stack>
      )}
    </Drawer>
  );
}

function FormularioCierre({ orden, onCerrada }: { orden: Orden; onCerrada: (o: Orden) => void }) {
  const { sedeActiva } = useAuth();
  const sede = { "X-Sede": sedeActiva ?? "" };
  const esMantenimiento = orden.tipo === "mantenimiento";
  const [componentes, setComponentes] = useState<Record<string, boolean>>(
    Object.fromEntries(COMPONENTES.map(([c]) => [c, true])),
  );
  const [sitio, setSitio] = useState("");
  const [recibe, setRecibe] = useState("");
  const [observacion, setObservacion] = useState("");
  const [desmonte, setDesmonte] = useState(false);
  const [causal, setCausal] = useState("");
  const [reemplazo, setReemplazo] = useState("");
  const [destino, setDestino] = useState<string>("112");
  const [tipoValor, setTipoValor] = useState<string | null>(null);
  const [barrio, setBarrio] = useState<string | null>(null);
  const [poste, setPoste] = useState("");
  const [latitud, setLatitud] = useState<number | string>("");
  const [longitud, setLongitud] = useState<number | string>("");
  const [material, setMaterial] = useState<string | null>(null);
  const [cantidad, setCantidad] = useState<number | string>(1);
  const [materiales, setMateriales] = useState<{ material_id: number; cantidad: number; codigo: string }[]>([]);
  const [foto, setFoto] = useState<File | null>(null);

  const claseTipo = orden.tipo === "expansion" ? "TIPO_EXPANSION" : "TIPO_MODERNIZACION";
  const { data: tipos = [] } = useQuery({
    queryKey: ["maestros", claseTipo],
    enabled: !esMantenimiento,
    queryFn: async () =>
      (await api.GET("/api/v1/maestros/{clase}", { params: { path: { clase: claseTipo } } })).data ?? [],
  });
  const { data: barrios = [] } = useQuery({
    queryKey: ["barrios", sedeActiva],
    enabled: !esMantenimiento,
    queryFn: async () => (await api.GET("/api/v1/barrios", { headers: sede })).data ?? [],
  });
  const { data: catalogoMateriales } = useQuery({
    queryKey: ["materiales-activos", sedeActiva],
    queryFn: async () =>
      (await api.GET("/api/v1/materiales", { headers: sede, params: { query: { activo: true, size: 200 } } }))
        .data?.items ?? [],
  });

  const cerrar = useMutation({
    mutationFn: async () => {
      let reemplazoId: number | null = null;
      if (esMantenimiento && reemplazo.trim()) {
        const { data } = await api.GET("/api/v1/luminarias/buscar", { headers: sede, params: { query: { q: reemplazo } } });
        const exacta = data?.find((l) => l.codigo.toLowerCase() === reemplazo.trim().toLowerCase());
        if (!exacta) throw new Error(`No existe la luminaria ${reemplazo}.`);
        reemplazoId = exacta.id;
      }
      const evidencias = [];
      if (foto && sedeActiva) {
        const subida = await subirArchivo<{ id: string }>("/api/v1/archivos", foto, sedeActiva);
        evidencias.push({ archivo_id: subida.id, tipo: "foto" as const });
      }
      const coordenadas =
        typeof latitud === "number" && typeof longitud === "number" ? { latitud, longitud } : {};
      const { data, error } = await api.POST("/api/v1/ordenes/{orden_id}/cerrar", {
        headers: sede,
        params: { path: { orden_id: orden.id } },
        body: {
          ...coordenadas,
          materiales: materiales.map(({ material_id, cantidad }) => ({ material_id, cantidad })),
          evidencias,
          ...(esMantenimiento
            ? {
                componentes,
                sitio_arreglo: sitio || null,
                quien_recibe: recibe || null,
                observacion_tecnica: observacion || null,
                requiere_desmonte: desmonte,
                causal_desmonte: causal || null,
                luminaria_reemplazo_id: reemplazoId,
                destino_desmontada: desmonte ? destino : null,
              }
            : {
                requiere_desmonte: false,
                tipo_expansion_id: orden.tipo === "expansion" && tipoValor ? Number(tipoValor) : null,
                tipo_modernizacion_id: orden.tipo !== "expansion" && tipoValor ? Number(tipoValor) : null,
                barrio_id: barrio ? Number(barrio) : null,
                poste: poste || null,
                destino_desmontada: destino,
              }),
        },
      });
      return exigir(data, error, "No se pudo cerrar la orden.");
    },
    onSuccess: onCerrada,
  });

  return (
    <Stack gap="xs" p="sm" style={{ border: "1px solid var(--mantine-color-default-border)", borderRadius: 8 }}>
      <Text fw={600}>Cerrar orden</Text>
      {esMantenimiento ? (
        <>
          <Text size="sm">Checklist de componentes (marque los que quedaron bien)</Text>
          <SimpleGrid cols={3} spacing={4}>
            {COMPONENTES.map(([clave, etiqueta]) => (
              <Checkbox
                key={clave}
                label={etiqueta}
                checked={componentes[clave]}
                onChange={(e) => setComponentes({ ...componentes, [clave]: e.currentTarget.checked })}
              />
            ))}
          </SimpleGrid>
          <Group grow>
            <TextInput label="Sitio del arreglo" value={sitio} onChange={(e) => setSitio(e.currentTarget.value)} />
            <TextInput label="Quien recibe" value={recibe} onChange={(e) => setRecibe(e.currentTarget.value)} />
          </Group>
          <Textarea label="Observación técnica" value={observacion} onChange={(e) => setObservacion(e.currentTarget.value)} />
          <Checkbox label="Requiere desmonte" checked={desmonte} onChange={(e) => setDesmonte(e.currentTarget.checked)} />
          {desmonte && (
            <Group grow>
              <TextInput label="Causal del desmonte" value={causal} onChange={(e) => setCausal(e.currentTarget.value)} />
              <TextInput label="Reemplazar por (código, opcional)" value={reemplazo} onChange={(e) => setReemplazo(e.currentTarget.value)} />
              <Select label="Destino de la desmontada" data={DESTINOS} value={destino} onChange={(v) => setDestino(v ?? "112")} />
            </Group>
          )}
        </>
      ) : (
        <>
          <Group grow>
            <Select
              label="Tipo"
              data={tipos.map((t) => ({ value: String(t.id), label: t.nombre }))}
              value={tipoValor}
              onChange={setTipoValor}
            />
            <Select
              label="Barrio"
              searchable
              data={barrios.map((b) => ({ value: String(b.id), label: b.nombre }))}
              value={barrio}
              onChange={setBarrio}
            />
            <TextInput label="Poste" value={poste} onChange={(e) => setPoste(e.currentTarget.value)} />
          </Group>
          {orden.tipo !== "expansion" && (
            <Select label="Destino de la desmontada" data={DESTINOS} value={destino} onChange={(v) => setDestino(v ?? "112")} />
          )}
        </>
      )}
      <Group grow>
        <NumberInput label="Latitud" decimalScale={6} value={latitud} onChange={setLatitud} />
        <NumberInput label="Longitud" decimalScale={6} value={longitud} onChange={setLongitud} />
      </Group>
      <Group align="end">
        <Select
          label="Material usado"
          searchable
          data={(catalogoMateriales ?? []).map((m) => ({
            value: String(m.id),
            label: `${m.codigo} · ${m.descripcion} (${Number(m.existencias)})`,
          }))}
          value={material}
          onChange={setMaterial}
          style={{ flex: 1 }}
        />
        <NumberInput label="Cantidad" min={0.001} value={cantidad} onChange={setCantidad} w={110} />
        <Button
          variant="light"
          disabled={!material || typeof cantidad !== "number"}
          onClick={() => {
            const elegido = catalogoMateriales?.find((m) => String(m.id) === material);
            if (elegido && typeof cantidad === "number") {
              setMateriales([...materiales, { material_id: elegido.id, cantidad, codigo: elegido.codigo }]);
              setMaterial(null);
            }
          }}
        >
          Agregar
        </Button>
      </Group>
      {materiales.length > 0 && (
        <Text size="sm">{materiales.map((m) => `${m.codigo} × ${m.cantidad}`).join(", ")}</Text>
      )}
      <FileInput label="Foto de evidencia" accept="image/*" value={foto} onChange={setFoto} clearable />
      {cerrar.error && <Alert color="red">{mensajeError(cerrar.error, "Error.")}</Alert>}
      <Group justify="flex-end">
        <Button loading={cerrar.isPending} onClick={() => cerrar.mutate()}>
          Cerrar orden
        </Button>
      </Group>
    </Stack>
  );
}

// --- Cargue masivo (todo o nada) ----------------------------------------------------------------

function CargueMasivo({ onMensaje }: { onMensaje: (m: string) => void }) {
  const { sedeActiva } = useAuth();
  const [tipo, setTipo] = useState<string>("expansion");
  const [archivo, setArchivo] = useState<File | null>(null);
  const [cargueId, setCargueId] = useState<number | null>(null);

  const { data: resultado } = useQuery({
    queryKey: ["cargue-masivo", sedeActiva, cargueId],
    enabled: cargueId !== null,
    refetchInterval: (q) => (q.state.data?.estado === "pendiente" ? 2000 : false),
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/ordenes/cargue-masivo/{cargue_id}", {
        headers: { "X-Sede": sedeActiva ?? "" },
        params: { path: { cargue_id: cargueId! } },
      });
      return exigir(data, error, "No se pudo consultar el cargue.");
    },
  });

  const subir = useMutation({
    mutationFn: async () =>
      subirArchivo<{ cargueId: number }>(`/api/v1/ordenes/cargue-masivo/${tipo}`, archivo!, sedeActiva ?? ""),
    onSuccess: (r) => {
      setCargueId(r.cargueId);
      onMensaje("Cargue recibido: se valida en segundo plano.");
    },
  });

  return (
    <Stack gap="sm" maw={900}>
      <Text size="sm" c="dimmed">
        Para registrar de una vez expansiones, modernizaciones o reubicaciones ya ejecutadas. Descargue la
        plantilla del tipo, llénela y cárguela. Si una fila tiene errores no se carga ninguna.
      </Text>
      <Group align="end">
        <Select
          label="Tipo"
          data={TIPOS.filter((t) => t.value !== "mantenimiento")}
          value={tipo}
          onChange={(v) => setTipo(v ?? "expansion")}
          w={180}
        />
        <Anchor href={`/api/v1/ordenes/plantillas/${tipo}`} onClick={(e) => {
          e.preventDefault();
          void fetch(`/api/v1/ordenes/plantillas/${tipo}`, { headers: { "X-Sede": sedeActiva ?? "" }, credentials: "same-origin" })
            .then((r) => r.blob())
            .then((b) => {
              const enlace = document.createElement("a");
              enlace.href = URL.createObjectURL(b);
              enlace.download = `plantilla_${tipo}.xlsx`;
              enlace.click();
            });
        }}>
          Descargar plantilla
        </Anchor>
        <FileInput placeholder="Archivo .xlsx" accept=".xlsx" value={archivo} onChange={setArchivo} w={260} />
        <Button disabled={!archivo} loading={subir.isPending} onClick={() => subir.mutate()}>
          Cargar
        </Button>
      </Group>
      {subir.error && <Alert color="red">{mensajeError(subir.error, "Error.")}</Alert>}
      {resultado && (
        <Alert color={resultado.estado === "completado" ? "green" : resultado.estado === "pendiente" ? "blue" : "red"}>
          {resultado.estado === "completado" && `${resultado.ordenes_creadas} órdenes creadas.`}
          {resultado.estado === "pendiente" && "Validando…"}
          {resultado.estado === "con_errores" && (
            <>
              No se cargó nada. Errores:
              {resultado.errores.map((e, i) => (
                <div key={i}>
                  Fila {String(e.fila ?? "—")}: {String(e.error ?? (e.errores as string[] | undefined)?.join("; "))}
                </div>
              ))}
            </>
          )}
        </Alert>
      )}
    </Stack>
  );
}
