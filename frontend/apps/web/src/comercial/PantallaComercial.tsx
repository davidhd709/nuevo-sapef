// Módulo comercial (EP-08): cargues por comercializador, análisis del catálogo común, control
// tarifario, entregables y bitácora de hallazgos. Todo con la sede activa (X-Sede).
import {
  Alert,
  Badge,
  Button,
  Card,
  FileInput,
  Group,
  NavLink,
  Pagination,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Textarea,
  Title,
  Tooltip,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { Codigo, EncabezadoPagina, EtiquetaEstado, MarcoTabla, SinPermiso } from "../comun/ui";
import { formatear, VistaResultado } from "./VistaResultado";
import { IconCalendarMonth } from "@tabler/icons-react";

type Objeto = Record<string, unknown>;

interface Cargue {
  id: number;
  periodo: string;
  estado: string;
  origen: string;
  completo: boolean;
  publicable: boolean;
  archivos: Objeto[];
  familias: Record<string, number>;
  advertencias: string[];
  errores: string[];
  creado_en: string;
}

interface Corte {
  periodo: string;
  cargue_id: number;
  completo: boolean;
  familias: Record<string, number>;
}

interface EntradaCatalogo {
  id: string;
  grupo: string;
  nombre: string;
  pregunta: string;
  ruta: string;
  por_periodo: boolean;
  estado: string;
  nota: string | null;
}

const OPERADORES = [
  { value: "afinia", label: "Afinia" },
  { value: "celsia", label: "Celsia" },
  { value: "vatia", label: "Vatia" },
];

const COLOR_ESTADO: Record<string, string> = {
  publicado: "green",
  con_errores: "red",
  no_publicable: "orange",
  validando: "blue",
  recibido: "blue",
  reemplazado: "gray",
  eliminado: "gray",
  CORRECTO: "green",
  POR_ENCIMA: "red",
  POR_DEBAJO: "orange",
  NO_VALIDABLE: "gray",
  REQUIERE_REVISION: "yellow",
};

const NOMBRE_ESTADO: Record<string, string> = {
  publicado: "Publicado",
  con_errores: "Con errores",
  no_publicable: "No publicable",
  validando: "Validando",
  recibido: "Recibido",
  reemplazado: "Reemplazado",
  eliminado: "Eliminado",
  CORRECTO: "Correcto",
  POR_ENCIMA: "Por encima",
  POR_DEBAJO: "Por debajo",
  NO_VALIDABLE: "No validable",
  REQUIERE_REVISION: "Requiere revisión",
};

function nombreEstado(estado: string): string {
  return NOMBRE_ESTADO[estado] ?? estado.replaceAll("_", " ");
}

async function pedir<T>(url: string, sede: string, init: RequestInit = {}): Promise<T> {
  const respuesta = await fetch(url, {
    ...init,
    credentials: "same-origin",
    headers: { "X-Sede": sede, ...(init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}), ...init.headers },
  });
  if (respuesta.status === 204) return undefined as T;
  const cuerpo = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) {
    const detalle = (cuerpo as { detail?: string }).detail;
    throw new Error(detalle || `Error ${respuesta.status}`);
  }
  return cuerpo as T;
}

async function descargar(url: string, sede: string, cuerpo: Objeto, nombre: string): Promise<void> {
  const respuesta = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-Sede": sede, "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo),
  });
  if (!respuesta.ok) {
    const error = await respuesta.json().catch(() => ({}));
    throw new Error((error as { detail?: string }).detail || `Error ${respuesta.status}`);
  }
  const blob = await respuesta.blob();
  const enlace = document.createElement("a");
  enlace.href = URL.createObjectURL(blob);
  const disposicion = respuesta.headers.get("Content-Disposition") ?? "";
  enlace.download = /filename="([^"]+)"/.exec(disposicion)?.[1] ?? nombre;
  enlace.click();
  URL.revokeObjectURL(enlace.href);
}

// --- Cargues ------------------------------------------------------------------------------------

function Cargues({ operador, sede }: { operador: string; sede: string }) {
  const { tienePermiso } = useAuth();
  const queryClient = useQueryClient();
  const [periodo, setPeriodo] = useState("");
  const [archivos, setArchivos] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);

  const { data: cargues = [] } = useQuery({
    queryKey: ["comercial-cargues", sede, operador],
    queryFn: () => pedir<Cargue[]>(`/api/v1/comercial/${operador}/cargues`, sede),
    refetchInterval: (q) =>
      (q.state.data ?? []).some((c) => c.estado === "recibido" || c.estado === "validando") ? 2000 : false,
  });

  const cargar = useMutation({
    mutationFn: async () => {
      const datos = new FormData();
      datos.append("periodo", periodo.trim());
      archivos.forEach((a) => datos.append("files", a));
      return pedir<Objeto>(`/api/v1/comercial/${operador}/cargues`, sede, {
        method: "POST",
        body: datos,
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
    },
    onSuccess: () => {
      setArchivos([]);
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["comercial-cargues"] });
      void queryClient.invalidateQueries({ queryKey: ["comercial-cortes"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const eliminar = useMutation({
    mutationFn: (id: number) =>
      pedir<void>(`/api/v1/comercial/${operador}/cargues/${id}`, sede, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["comercial-cargues"] });
      void queryClient.invalidateQueries({ queryKey: ["comercial-cortes"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Stack>
      {tienePermiso("comercial.cargue.crear") && (
        <Card withBorder>
          <Group align="end" wrap="wrap">
            <TextInput
              label="Periodo (AAAAMM)"
              placeholder="202607"
              value={periodo}
              onChange={(e) => setPeriodo(e.currentTarget.value)}
              w={150}
            />
            <FileInput
              label="Archivos del corte"
              placeholder="Planos .txt/.Z o libros Excel"
              multiple
              clearable
              value={archivos}
              onChange={setArchivos}
              w={360}
            />
            <Button
              onClick={() => cargar.mutate()}
              loading={cargar.isPending}
              disabled={!/^\d{6}$/.test(periodo.trim()) || archivos.length === 0}
            >
              Cargar
            </Button>
          </Group>
          <Text size="xs" c="dimmed" mt="xs">
            Se validan y publican en segundo plano: el corte solo se reemplaza si el cargue nuevo
            queda completo y válido.
          </Text>
        </Card>
      )}
      {error && (
        <Alert color="red" withCloseButton onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      <MarcoTabla>
      <ScrollArea type="auto">
        <Table fz="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Periodo</Table.Th>
              <Table.Th>Estado</Table.Th>
              <Table.Th>Familias</Table.Th>
              <Table.Th>Avisos y errores</Table.Th>
              <Table.Th>Recibido</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {cargues.map((c) => (
              <Table.Tr key={c.id}>
                <Table.Td>
                  <Codigo>{c.periodo}</Codigo>
                </Table.Td>
                <Table.Td>
                  <Group gap={6} wrap="nowrap">
                    <EtiquetaEstado color={COLOR_ESTADO[c.estado] ?? "gray"} nombre={nombreEstado(c.estado)} />
                    {c.origen === "opainn" && (
                      <Badge variant="outline" color="gray" size="xs">
                        OPainn
                      </Badge>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td>
                  {Object.entries(c.familias)
                    .map(([f, n]) => `${f}: ${n}`)
                    .join(" · ") || "—"}
                </Table.Td>
                <Table.Td maw={420}>
                  {c.errores.map((e) => (
                    <Text key={e} size="xs" c="red">
                      {e}
                    </Text>
                  ))}
                  {c.advertencias.map((a) => (
                    <Text key={a} size="xs" c="dimmed">
                      {a}
                    </Text>
                  ))}
                </Table.Td>
                <Table.Td>{new Date(c.creado_en).toLocaleString("es-CO")}</Table.Td>
                <Table.Td>
                  {tienePermiso("comercial.cargue.eliminar") &&
                    !["eliminado", "recibido", "validando"].includes(c.estado) && (
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        color="red"
                        onClick={() => {
                          if (window.confirm(`¿Eliminar el cargue de ${c.periodo}?`)) eliminar.mutate(c.id);
                        }}
                      >
                        Eliminar
                      </Button>
                    )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
      </MarcoTabla>
    </Stack>
  );
}

// --- Análisis -----------------------------------------------------------------------------------

function Analisis({ operador, sede, periodo }: { operador: string; sede: string; periodo: string | null }) {
  const [elegido, setElegido] = useState<string>("resumen-indicadores");
  const [identificador, setIdentificador] = useState("");
  const [indicador, setIndicador] = useState("facturacion");

  const { data: catalogo = [] } = useQuery({
    queryKey: ["comercial-catalogo", sede, operador],
    queryFn: () => pedir<EntradaCatalogo[]>(`/api/v1/comercial/${operador}/catalogo`, sede),
  });
  const actual = catalogo.find((c) => c.id === elegido);
  const url = useMemo(() => {
    if (!actual || actual.estado === "no_aplica") return null;
    if (actual.ruta.includes("{periodo}") && !periodo) return null;
    if (actual.ruta.includes("{identificador}") && !identificador.trim()) return null;
    let ruta = actual.ruta
      .replace("{periodo}", periodo ?? "")
      .replace("{identificador}", encodeURIComponent(identificador.trim()));
    if (actual.id === "detalle-indicador") ruta += `?indicador=${encodeURIComponent(indicador)}`;
    return ruta;
  }, [actual, periodo, identificador, indicador]);

  const resultado = useQuery({
    queryKey: ["comercial-analisis", sede, url],
    enabled: Boolean(url),
    queryFn: () => pedir<Objeto>(url as string, sede),
  });

  const grupos = useMemo(() => {
    const salida = new Map<string, EntradaCatalogo[]>();
    for (const c of catalogo) salida.set(c.grupo, [...(salida.get(c.grupo) ?? []), c]);
    return [...salida.entries()];
  }, [catalogo]);

  return (
    <Group align="start" wrap="nowrap" gap="md">
      <ScrollArea h="70vh" w={260} type="auto">
        {grupos.map(([grupo, lista]) => (
          <Stack key={grupo} gap={0} mb="xs">
            <Text fz={10} fw={600} c="dimmed" tt="uppercase" px="sm" pt="xs" pb={4} style={{ letterSpacing: "0.08em" }}>
              {grupo}
            </Text>
            {lista.map((c) => (
              <Tooltip key={c.id} label={c.nota ?? c.pregunta} multiline w={260} withArrow>
                <NavLink
                  label={c.nombre}
                  color="gray"
                  variant="light"
                  fz="sm"
                  py={6}
                  style={{ borderRadius: 4 }}
                  active={c.id === elegido}
                  disabled={c.estado === "no_aplica"}
                  rightSection={
                    c.estado !== "disponible" ? (
                      <Text fz={10} c="dimmed">
                        {c.estado.replace("_", " ")}
                      </Text>
                    ) : null
                  }
                  onClick={() => setElegido(c.id)}
                />
              </Tooltip>
            ))}
          </Stack>
        ))}
      </ScrollArea>
      <Stack style={{ flex: 1, minWidth: 0 }}>
        {actual && (
          <div>
            <Title order={2} fz="lg">
              {actual.nombre}
            </Title>
            <Text size="sm" c="dimmed">
              {actual.pregunta}
            </Text>
          </div>
        )}
        {actual?.id === "trazabilidad" && (
          <TextInput
            label="NIC, cuenta o cliente"
            value={identificador}
            onChange={(e) => setIdentificador(e.currentTarget.value)}
            w={240}
          />
        )}
        {actual?.id === "detalle-indicador" && (
          <TextInput
            label="Indicador (nombre de la columna)"
            value={indicador}
            onChange={(e) => setIndicador(e.currentTarget.value)}
            w={300}
          />
        )}
        {!periodo && actual?.por_periodo && <Alert color="gray">Elija un corte cargado.</Alert>}
        {resultado.isFetching && <Text c="dimmed">Calculando…</Text>}
        {resultado.error && <Alert color="red">{(resultado.error as Error).message}</Alert>}
        {resultado.data && <VistaResultado datos={resultado.data} />}
      </Stack>
    </Group>
  );
}

// --- Control tarifario --------------------------------------------------------------------------

function ControlTarifario({ operador, sede, periodo }: { operador: string; sede: string; periodo: string | null }) {
  const [grupo, setGrupo] = useState("todos");
  const [estado, setEstado] = useState<string | null>(null);
  const [pagina, setPagina] = useState(1);
  const { data, error, isFetching } = useQuery({
    queryKey: ["comercial-control", sede, operador, periodo, grupo, estado, pagina],
    enabled: Boolean(periodo),
    queryFn: () =>
      pedir<Objeto & { items: Objeto[]; total: number; totales: Objeto }>(
        `/api/v1/comercial/${operador}/analisis/control-tarifario/${periodo}?grupo_consumo=${grupo}` +
          `${estado ? `&estado=${estado}` : ""}&page=${pagina}&size=100`,
        sede,
      ),
  });
  if (operador === "vatia") {
    return <Alert color="gray">Sin control tarifario para Vatia (decisión del 7-nov-2026).</Alert>;
  }
  const totales = data?.totales as { por_estado?: Record<string, number>; valor_por_encima?: string; valor_por_debajo?: string } | undefined;
  return (
    <Stack>
      <Group>
        <SegmentedControl
          value={grupo}
          onChange={(v) => {
            setGrupo(v);
            setPagina(1);
          }}
          data={[
            { value: "todos", label: "Todos" },
            { value: "minima", label: operador === "afinia" ? "Hasta 173 kWh" : "Tarifa fija" },
            { value: "variable", label: operador === "afinia" ? "Mayor de 173 kWh" : "Porcentual" },
            { value: "especial", label: "Especiales" },
            { value: "revision", label: "Sin dato para validar" },
          ]}
        />
        <Select
          placeholder="Estado"
          clearable
          value={estado}
          onChange={(v) => {
            setEstado(v);
            setPagina(1);
          }}
          data={["CORRECTO", "POR_ENCIMA", "POR_DEBAJO", "NO_VALIDABLE", "REQUIERE_REVISION"]}
          w={220}
        />
      </Group>
      {!periodo && <Alert color="gray">Elija un corte cargado.</Alert>}
      {error && <Alert color="red">{(error as Error).message}</Alert>}
      {totales && (
        <SimpleGrid cols={{ base: 2, md: 4, lg: 7 }} spacing="xs">
          {Object.entries(totales.por_estado ?? {}).map(([k, v]) => (
            <Card key={k} padding="sm">
              <EtiquetaEstado color={COLOR_ESTADO[k]} nombre={nombreEstado(k)} />
              <Text fz="xl" fw={500} className="sapef-cifra" mt={4}>
                {formatear(v)}
              </Text>
            </Card>
          ))}
          <Card padding="sm">
            <Text size="sm" c="dimmed">
              Cobrado por encima
            </Text>
            <Text fz="xl" fw={500} className="sapef-cifra" mt={4}>
              $ {formatear(totales.valor_por_encima)}
            </Text>
          </Card>
          <Card padding="sm">
            <Text size="sm" c="dimmed">
              Cobrado por debajo
            </Text>
            <Text fz="xl" fw={500} className="sapef-cifra" mt={4}>
              $ {formatear(totales.valor_por_debajo)}
            </Text>
          </Card>
        </SimpleGrid>
      )}
      {isFetching && <Text c="dimmed">Calculando…</Text>}
      {data && (
        <>
          <MarcoTabla>
          <ScrollArea type="auto">
            <Table fz="xs" miw={900}>
              <Table.Thead>
                <Table.Tr>
                  {["Usuario", "Nombre", "Tarifa", "Regla", "Estado", "Motivo", "Facturado", "Esperado", "Diferencia", "Señal CI401", "Señal CI851"].map((c) => (
                    <Table.Th key={c} ta={["Facturado", "Esperado", "Diferencia"].includes(c) ? "right" : undefined}>
                      {c}
                    </Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.items.map((f, i) => (
                  <Table.Tr key={i}>
                    <Table.Td>
                      <Codigo>{formatear(f.identificador, "identificador")}</Codigo>
                    </Table.Td>
                    <Table.Td>{formatear(f.nombre)}</Table.Td>
                    <Table.Td>{formatear(f.tarifa)}</Table.Td>
                    <Table.Td>{formatear(f.regla_aplicada)}</Table.Td>
                    <Table.Td>
                      <EtiquetaEstado color={COLOR_ESTADO[String(f.estado)]} nombre={nombreEstado(String(f.estado))} />
                    </Table.Td>
                    <Table.Td>{formatear(f.motivo_revision)}</Table.Td>
                    <Table.Td ta="right">{formatear(f.facturado_real)}</Table.Td>
                    <Table.Td ta="right">{formatear(f.esperado)}</Table.Td>
                    <Table.Td ta="right">{formatear(f.diferencia)}</Table.Td>
                    <Table.Td>{formatear(f.senal_ci401)}</Table.Td>
                    <Table.Td>{formatear(f.senal_ci851)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
          </MarcoTabla>
          {data.total > 100 && (
            <Pagination value={pagina} onChange={setPagina} total={Math.ceil(data.total / 100)} />
          )}
        </>
      )}
    </Stack>
  );
}

// --- Entregables ---------------------------------------------------------------------------------

function Entregables({ operador, sede, periodo }: { operador: string; sede: string; periodo: string | null }) {
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const base = `/api/v1/comercial/${operador}`;
  const acciones: [string, string, Objeto][] = [
    ["Requerimiento al operador (Word)", `${base}/entregables/requerimiento`, { formato: "docx" }],
    ["Requerimiento al operador (PDF)", `${base}/entregables/requerimiento`, { formato: "pdf" }],
    ["Análisis del corte (HTML)", `${base}/entregables/analisis`, { formato: "html" }],
    ["Análisis del corte (PDF)", `${base}/entregables/analisis`, { formato: "pdf" }],
    ["Anexo nominal (Excel)", `${base}/entregables/anexo-nominal`, {}],
    ["Informe gerencial (PDF)", `${base}/entregables/informe-gerencial`, {}],
  ];
  if (operador === "celsia") acciones.push(["Cartera (ZIP)", `${base}/exportaciones/cartera`, {}]);
  if (!periodo) return <Alert color="gray">Elija un corte cargado.</Alert>;
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        Las cifras del oficio, el anexo y el informe salen del mismo cálculo que el tablero. Si el anexo
        supera el tope de filas configurado, la descarga se detiene en lugar de recortarse.
      </Text>
      <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
        {acciones.map(([nombre, url, extra]) => (
          <Button
            key={nombre}
            variant="light"
            loading={ocupado === nombre}
            onClick={async () => {
              setOcupado(nombre);
              setError(null);
              try {
                await descargar(url, sede, { periodo, ...extra }, nombre);
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setOcupado(null);
              }
            }}
          >
            {nombre}
          </Button>
        ))}
      </SimpleGrid>
      {error && <Alert color="red">{error}</Alert>}
    </Stack>
  );
}

// --- Hallazgos ------------------------------------------------------------------------------------

function Hallazgos({ operador, sede, periodo }: { operador: string; sede: string; periodo: string | null }) {
  const queryClient = useQueryClient();
  const [tipo, setTipo] = useState<string | null>("ANOMALIA");
  const [responsable, setResponsable] = useState("");
  const [decision, setDecision] = useState("");
  const [identificador, setIdentificador] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { data: lista = [] } = useQuery({
    queryKey: ["comercial-hallazgos", sede, operador],
    queryFn: () => pedir<Objeto[]>(`/api/v1/comercial/${operador}/hallazgos`, sede),
  });
  const refrescar = () => void queryClient.invalidateQueries({ queryKey: ["comercial-hallazgos"] });
  const crear = useMutation({
    mutationFn: () =>
      pedir<Objeto>(`/api/v1/comercial/${operador}/hallazgos`, sede, {
        method: "POST",
        body: JSON.stringify({
          tipo,
          responsable,
          decision,
          identificador: identificador || null,
          periodo: periodo ?? null,
        }),
      }),
    onSuccess: () => {
      setDecision("");
      setIdentificador("");
      refrescar();
    },
    onError: (e: Error) => setError(e.message),
  });
  const cambiar = useMutation({
    mutationFn: ({ id, estado }: { id: number; estado: string }) =>
      pedir<Objeto>(`/api/v1/comercial/${operador}/hallazgos/${id}`, sede, {
        method: "PATCH",
        body: JSON.stringify({ estado }),
      }),
    onSuccess: refrescar,
    onError: (e: Error) => setError(e.message),
  });
  return (
    <Stack>
      <Card withBorder>
        <Group align="end" wrap="wrap">
          <Select label="Tipo" data={["RUTA", "ANOMALIA", "MOVIMIENTO"]} value={tipo} onChange={setTipo} w={150} />
          <TextInput label="Responsable" value={responsable} onChange={(e) => setResponsable(e.currentTarget.value)} />
          <TextInput label="Usuario (NIC o cuenta)" value={identificador} onChange={(e) => setIdentificador(e.currentTarget.value)} />
          <Textarea label="Decisión" value={decision} onChange={(e) => setDecision(e.currentTarget.value)} w={320} autosize />
          <Button onClick={() => crear.mutate()} disabled={responsable.trim().length < 2 || decision.trim().length < 2} loading={crear.isPending}>
            Registrar
          </Button>
        </Group>
      </Card>
      {error && (
        <Alert color="red" withCloseButton onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      <Table striped withTableBorder fz="sm">
        <Table.Thead>
          <Table.Tr>
            {["Tipo", "Usuario", "Responsable", "Decisión", "Periodo", "Estado"].map((c) => (
              <Table.Th key={c}>{c}</Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {lista.map((h) => (
            <Table.Tr key={String(h.id)}>
              <Table.Td>{formatear(h.tipo)}</Table.Td>
              <Table.Td>{formatear(h.identificador)}</Table.Td>
              <Table.Td>{formatear(h.responsable)}</Table.Td>
              <Table.Td>{formatear(h.decision)}</Table.Td>
              <Table.Td>{formatear(h.periodo)}</Table.Td>
              <Table.Td>
                <Select
                  size="xs"
                  data={["ABIERTO", "EN_REVISION", "RESUELTO"]}
                  value={String(h.estado)}
                  onChange={(v) => v && cambiar.mutate({ id: Number(h.id), estado: v })}
                  w={150}
                />
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

// --- Pantalla ---------------------------------------------------------------------------------------

export function PantallaComercial() {
  const { sedeActiva, tienePermiso } = useAuth();
  const sede = sedeActiva ?? "";
  const puedeVer = tienePermiso("comercial.analisis.ver") || tienePermiso("comercial.cargue.crear");
  const nominal = tienePermiso("comercial.nominal.ver");

  // Los comercializadores que operan en la sede: los que responden su catálogo.
  const { data: disponibles = [], isPending } = useQuery({
    queryKey: ["comercial-operadores", sede],
    enabled: puedeVer && Boolean(sede),
    queryFn: async () => {
      const respuestas = await Promise.all(
        OPERADORES.map(async (o) => {
          const r = await fetch(`/api/v1/comercial/${o.value}/catalogo`, {
            credentials: "same-origin",
            headers: { "X-Sede": sede },
          });
          return r.ok ? o : null;
        }),
      );
      return respuestas.filter((o): o is (typeof OPERADORES)[number] => o !== null);
    },
  });
  const [elegido, setElegido] = useState<string | null>(null);
  const operador = elegido && disponibles.some((o) => o.value === elegido) ? elegido : (disponibles[0]?.value ?? null);
  const [periodoElegido, setPeriodoElegido] = useState<string | null>(null);

  const { data: cortes = [] } = useQuery({
    queryKey: ["comercial-cortes", sede, operador],
    enabled: Boolean(operador),
    queryFn: () => pedir<Corte[]>(`/api/v1/comercial/${operador}/cortes`, sede),
  });
  const periodo =
    periodoElegido && cortes.some((c) => c.periodo === periodoElegido)
      ? periodoElegido
      : (cortes[cortes.length - 1]?.periodo ?? null);

  if (!puedeVer) {
    return <SinPermiso mensaje="No tiene permiso para el módulo comercial." />;
  }

  return (
    <Stack gap="md">
      <EncabezadoPagina
        seccion="Comercial"
        titulo="Análisis comercial"
        descripcion="Impuesto de alumbrado facturado y recaudado por los comercializadores: cargues mensuales, indicadores, control tarifario y entregables."
        acciones={
          <>
            {disponibles.length > 1 ? (
              <SegmentedControl
                aria-label="Comercializador"
                data={disponibles}
                value={operador ?? undefined}
                onChange={setElegido}
                disabled={isPending}
              />
            ) : (
              <Select
                aria-label="Comercializador"
                data={disponibles}
                value={operador}
                onChange={setElegido}
                w={150}
                disabled={isPending}
              />
            )}
            <Select
              aria-label="Corte"
              leftSection={<IconCalendarMonth size={15} />}
              data={[...cortes].reverse().map((c) => ({ value: c.periodo, label: `${c.periodo}${c.completo ? "" : " (incompleto)"}` }))}
              value={periodo}
              onChange={setPeriodoElegido}
              w={200}
              placeholder="Sin cortes"
              allowDeselect={false}
            />
          </>
        }
      />
      {!isPending && disponibles.length === 0 && (
        <Alert color="gray">Ningún comercializador opera en esta sede.</Alert>
      )}
      {operador && (
        <Tabs defaultValue="analisis" keepMounted={false}>
          <Tabs.List mb="md">
            <Tabs.Tab value="analisis">Análisis</Tabs.Tab>
            {nominal && <Tabs.Tab value="control">Control tarifario</Tabs.Tab>}
            <Tabs.Tab value="cargues">Cargues</Tabs.Tab>
            {tienePermiso("comercial.entregable.generar") && <Tabs.Tab value="entregables">Entregables</Tabs.Tab>}
            {nominal && <Tabs.Tab value="hallazgos">Hallazgos</Tabs.Tab>}
          </Tabs.List>
          <Tabs.Panel value="analisis">
            <Analisis operador={operador} sede={sede} periodo={periodo} />
          </Tabs.Panel>
          <Tabs.Panel value="control">
            <ControlTarifario operador={operador} sede={sede} periodo={periodo} />
          </Tabs.Panel>
          <Tabs.Panel value="cargues">
            <Cargues operador={operador} sede={sede} />
          </Tabs.Panel>
          <Tabs.Panel value="entregables">
            <Entregables operador={operador} sede={sede} periodo={periodo} />
          </Tabs.Panel>
          <Tabs.Panel value="hallazgos">
            <Hallazgos operador={operador} sede={sede} periodo={periodo} />
          </Tabs.Panel>
        </Tabs>
      )}
    </Stack>
  );
}
