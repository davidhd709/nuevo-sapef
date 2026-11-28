// Tablero gerencial (EP-09, RF-090): se lee en ≤ 5 minutos, por sede o consolidado. Lee solo las
// tablas resumen del backend (respuesta < 2 s); el detalle sale al hacer clic en un gráfico.
import { api, type components } from "@sapef/api";
import {
  Alert,
  Button,
  Card,
  Group,
  Modal,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { exigir, mensajeError } from "../comun/api";
import { EncabezadoPagina, MarcoTabla } from "../comun/ui";
import { IconRefresh } from "@tabler/icons-react";
import { Grafico, type OpcionGrafico } from "./Grafico";

type Resumen = components["schemas"]["ResumenTableroSalida"];
type Conteo = components["schemas"]["ConteoTablero"];
type Comercializador = components["schemas"]["ComercializadorTablero"];

const MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];
const NUM = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 });
const PESOS = new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
const PCT = new Intl.NumberFormat("es-CO", { style: "percent", maximumFractionDigits: 1 });

function numero(v: unknown): string {
  return typeof v === "number" ? NUM.format(v) : "—";
}

function pesos(v: unknown): string {
  return typeof v === "number" ? PESOS.format(v) : "—";
}

function Variacion({ valor, inversa = false }: { valor: number | null | undefined; inversa?: boolean }) {
  if (valor === null || valor === undefined) return <Text size="xs" c="dimmed">sin comparación</Text>;
  const bueno = inversa ? valor <= 0 : valor >= 0;
  return (
    <Text size="xs" c={bueno ? "green.8" : "red.7"} className="sapef-cifra">
      {valor > 0 ? "▲" : valor < 0 ? "▼" : "="} {Math.abs(valor).toLocaleString("es-CO")} % vs. mes anterior
    </Text>
  );
}

function Indicador({ titulo, valor, pie }: { titulo: string; valor: string; pie?: React.ReactNode }) {
  return (
    <Card padding="md">
      <Text size="sm" c="dimmed">
        {titulo}
      </Text>
      <Text fz={26} fw={500} lh={1.15} mt={6} className="sapef-cifra">
        {valor}
      </Text>
      <div style={{ marginTop: 4 }}>{pie}</div>
    </Card>
  );
}

/** Tarjeta de una gráfica: título, nota opcional y contenido. */
function Panel({ titulo, nota, children }: { titulo: string; nota?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card padding="md">
      <Text fw={600} size="sm">
        {titulo}
      </Text>
      {nota && (
        <Text size="xs" c="dimmed" mt={2}>
          {nota}
        </Text>
      )}
      <div style={{ marginTop: 8 }}>{children}</div>
    </Card>
  );
}

/** Barras horizontales de una sola serie (magnitud por categoría), ordenadas de mayor a menor. */
function barrasHorizontales(filas: Conteo[], nombre: string): OpcionGrafico {
  const datos = [...filas].slice(0, 12).reverse();
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { left: 4, right: 36, top: 4, bottom: 4, containLabel: true },
    xAxis: { type: "value", splitNumber: 3 },
    yAxis: { type: "category", data: datos.map((f) => f.etiqueta) },
    series: [
      {
        name: nombre,
        type: "bar",
        data: datos.map((f) => f.cantidad),
        itemStyle: { borderRadius: [0, 4, 4, 0] },
        barCategoryGap: "35%",
        label: { show: true, position: "right", color: "#63635e", fontSize: 11 },
      },
    ],
  };
}

const COLOR_PLAZO = { verde: "#0aac23", amarillo: "#fbb315", rojo: "#dc3c3d" } as const;

/** PQRS abiertas por plazo: tres cifras con su estado (no necesita gráfico). */
function Semaforo({ s }: { s: Resumen["operacion"]["pqrs_semaforo"] }) {
  const filas = [
    { clave: "rojo" as const, nombre: "Vencidas", nota: `más de ${s.umbral_amarillo_dias ?? "?"} días`, valor: s.rojo },
    { clave: "amarillo" as const, nombre: "Por vencer", nota: `hasta ${s.umbral_amarillo_dias ?? "?"} días`, valor: s.amarillo },
    { clave: "verde" as const, nombre: "A tiempo", nota: `hasta ${s.umbral_verde_dias ?? "?"} días`, valor: s.verde },
  ];
  return (
    <Stack gap={10} py={4}>
      {filas.map((f) => (
        <Group key={f.clave} justify="space-between" wrap="nowrap">
          <Group gap={8} wrap="nowrap">
            <span style={{ width: 10, height: 10, borderRadius: 2, background: COLOR_PLAZO[f.clave], flex: "none" }} />
            <div>
              <Text size="sm">{f.nombre}</Text>
              <Text size="xs" c="dimmed">
                {f.nota}
              </Text>
            </div>
          </Group>
          <Text fz={22} fw={500} className="sapef-cifra">
            {numero(f.valor)}
          </Text>
        </Group>
      ))}
    </Stack>
  );
}

function SeccionComercializador({ c }: { c: Comercializador }) {
  const a = c.actual as Record<string, number | null>;
  const v = c.variacion;
  const historico = c.historico as { periodo: string; facturacion: number; recaudo: number; cartera: number }[];
  const participacion = c.participacion as { grupo: string; usuarios: number; facturacion: number; recaudo: number; consumo: number }[];
  const totalFact = participacion.reduce((s, p) => s + (p.facturacion || 0), 0);
  const filas: [string, string, number | null | undefined][] = [
    ["Usuarios facturados", numero(a.n_facturados), v.n_facturados],
    ["Facturado", pesos(a.facturacion), v.facturacion],
    ["Recaudo corriente", pesos(a.recaudo_corriente), v.recaudo_corriente],
    ["Recaudo de cartera", pesos(a.recaudo_cartera), v.recaudo_cartera],
    ["Recaudo total", pesos(a.recaudo), v.recaudo],
    ["Cartera", pesos(a.cartera), v.cartera],
    ["Usuarios en convenio", numero(a.n_usuarios_convenios), v.n_usuarios_convenios],
    ["Valor de convenios", pesos(a.valor_convenios_periodo), v.valor_convenios_periodo],
    ["Nuevos", numero(a.nuevos_usuarios), v.nuevos_usuarios],
    ["Dejaron de facturar", numero(a.usuarios_dejados_facturar), v.usuarios_dejados_facturar],
    ["Reintegrados", numero(a.usuarios_reintegrados), v.usuarios_reintegrados],
    ["Consumo (kWh)", numero(a.consumo), v.consumo],
  ];
  return (
    <Card padding="md">
      <Group justify="space-between" mb="sm">
        <Text fw={600}>
          {c.nombre}{" "}
          <Text span c="dimmed" fw={400}>
            · {c.sede_nombre}
          </Text>
        </Text>
        <Text size="sm" c="dimmed" className="sapef-cifra">
          Corte {c.periodo}
          {c.periodo_anterior ? ` frente a ${c.periodo_anterior}` : ""}
        </Text>
      </Group>
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <MarcoTabla>
        <Table fz="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Indicador</Table.Th>
              <Table.Th ta="right">Actual</Table.Th>
              <Table.Th ta="right">Variación</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {filas.map(([nombre, valor, variacion]) => (
              <Table.Tr key={nombre}>
                <Table.Td>{nombre}</Table.Td>
                <Table.Td ta="right">{valor}</Table.Td>
                <Table.Td ta="right" c={variacion == null ? "dimmed" : variacion >= 0 ? "green.8" : "red.7"}>
                  {variacion === null || variacion === undefined
                    ? "—"
                    : `${variacion > 0 ? "+" : ""}${variacion.toLocaleString("es-CO")} %`}
                </Table.Td>
              </Table.Tr>
            ))}
            <Table.Tr>
              <Table.Td>Eficiencia de recaudo</Table.Td>
              <Table.Td ta="right">{typeof a.eficiencia === "number" ? PCT.format(a.eficiencia) : "—"}</Table.Td>
              <Table.Td />
            </Table.Tr>
          </Table.Tbody>
        </Table>
        </MarcoTabla>
        <Stack gap="xs">
          <Grafico
            descripcion={`Histórico de facturación y recaudo de ${c.nombre}`}
            opcion={{
              tooltip: { trigger: "axis" },
              legend: { top: 0, left: 0 },
              grid: { left: 4, right: 8, top: 32, bottom: 4, containLabel: true },
              xAxis: { type: "category", data: historico.map((h) => h.periodo) },
              yAxis: { type: "value", splitNumber: 4 },
              series: [
                { name: "Facturado", type: "line", data: historico.map((h) => h.facturacion) },
                { name: "Recaudo", type: "line", data: historico.map((h) => h.recaudo) },
                {
                  name: "Cartera",
                  type: "bar",
                  data: historico.map((h) => h.cartera),
                  itemStyle: { borderRadius: [4, 4, 0, 0] },
                },
              ],
            }}
          />
          <MarcoTabla>
          <Table fz="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{c.comercializador === "afinia" ? "Tarifa" : "Segmento"}</Table.Th>
                <Table.Th ta="right">Usuarios</Table.Th>
                <Table.Th ta="right">Participación</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {participacion.slice(0, 8).map((p) => (
                <Table.Tr key={p.grupo}>
                  <Table.Td>{p.grupo}</Table.Td>
                  <Table.Td ta="right">{numero(p.usuarios)}</Table.Td>
                  <Table.Td ta="right">{totalFact ? PCT.format((p.facturacion || 0) / totalFact) : "—"}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          </MarcoTabla>
        </Stack>
      </SimpleGrid>
    </Card>
  );
}

function consolidadoEnUrl(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("sede") === "todas";
}

export function PantallaTablero() {
  const { sedeActiva, tienePermiso } = useAuth();
  const puedeConsolidado = tienePermiso("tablero.consolidado.ver");
  const [alcance, setAlcance] = useState<"sede" | "todas">(() =>
    puedeConsolidado && consolidadoEnUrl() ? "todas" : "sede",
  );
  const anioActual = new Date().getFullYear();
  const [anio, setAnio] = useState<string>(String(anioActual));
  const [detalle, setDetalle] = useState<{ titulo: string; filas: Conteo[] } | null>(null);
  const qc = useQueryClient();

  const cambiarAlcance = (valor: string) => {
    const nuevo = valor === "todas" ? "todas" : "sede";
    setAlcance(nuevo);
    const url = new URL(window.location.href);
    if (nuevo === "todas") url.searchParams.set("sede", "todas");
    else url.searchParams.delete("sede");
    window.history.replaceState(null, "", url.pathname + url.search);
  };

  const consulta = useQuery({
    queryKey: ["tablero", alcance, alcance === "todas" ? null : sedeActiva, anio],
    enabled: alcance === "todas" || !!sedeActiva,
    queryFn: async (): Promise<Resumen> => {
      const { data, error } = await api.GET("/api/v1/tablero/resumen", {
        headers: alcance === "todas" ? {} : { "X-Sede": sedeActiva ?? "" },
        params: { query: { sede: alcance === "todas" ? "todas" : undefined, anio: Number(anio) } },
      });
      return exigir(data, error, "No se pudo cargar el tablero.");
    },
  });

  const recalcular = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/v1/tablero/recalcular", {
        headers: alcance === "todas" ? {} : { "X-Sede": sedeActiva ?? "" },
        body: {},
      });
      return exigir(data, error, "No se pudo encolar el recálculo.");
    },
    onSuccess: () => {
      // El worker tarda unos segundos: se vuelve a consultar sin bloquear la pantalla.
      window.setTimeout(() => void qc.invalidateQueries({ queryKey: ["tablero"] }), 4000);
    },
  });

  const r = consulta.data;
  const opciones = useMemo(() => {
    if (!r) return null;
    const meses = r.activos.luminarias_instaladas_mes;
    return {
      // Un solo eje: las instaladas de cada mes. El acumulado va como cifra en el título.
      instaladas: {
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
        grid: { left: 4, right: 8, top: 12, bottom: 4, containLabel: true },
        xAxis: { type: "category", data: meses.map((m) => MESES[m.mes - 1]) },
        yAxis: { type: "value", splitNumber: 4, minInterval: 1 },
        series: [
          {
            name: "Instaladas en el mes",
            type: "bar",
            data: meses.map((m) => m.cantidad),
            itemStyle: { borderRadius: [4, 4, 0, 0] },
          },
        ],
      } satisfies OpcionGrafico,
      tecnologia: barrasHorizontales(r.activos.por_tecnologia, "Luminarias"),
      potencia: barrasHorizontales(r.activos.por_potencia, "Luminarias"),
      zona: barrasHorizontales(r.activos.por_zona, "Luminarias"),
      estado: barrasHorizontales(r.operacion.luminarias_por_estado, "Luminarias"),
      pqrsBarrio: barrasHorizontales(r.operacion.pqrs_por_barrio, "PQRS"),
    };
  }, [r]);

  const verBarriosDeZona = (zona: string) => {
    if (!r) return;
    const filas = r.activos.por_barrio.filter((b) => (b.grupo ?? "").endsWith(zona));
    setDetalle({ titulo: `Barrios de ${zona}`, filas });
  };

  const anios = Array.from({ length: 6 }, (_, i) => String(anioActual - i));

  return (
    <Stack>
      <EncabezadoPagina
        seccion="Gestión"
        titulo="Tablero gerencial"
        descripcion={
          r
            ? `${r.sede === "todas" ? "Consolidado de " + r.sedes_incluidas.map((s) => s.nombre).join(" y ") : r.sedes_incluidas[0]?.nombre ?? ""} · datos calculados el ${r.calculado_en ? new Date(r.calculado_en).toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" }) : "—"}`
            : "Cargando…"
        }
        acciones={
        <>
          {puedeConsolidado && (
            <SegmentedControl
              aria-label="Alcance del tablero"
              value={alcance}
              onChange={cambiarAlcance}
              data={[
                { value: "sede", label: "Sede activa" },
                { value: "todas", label: "Consolidado" },
              ]}
            />
          )}
          <Select aria-label="Año" data={anios} value={anio} onChange={(v) => v && setAnio(v)} w={100} allowDeselect={false} />
          <Button
            variant="default"
            leftSection={<IconRefresh size={16} />}
            loading={recalcular.isPending}
            onClick={() => recalcular.mutate()}
          >
            Recalcular
          </Button>
        </>
        }
      />

      {recalcular.isSuccess && <Alert color="blue">Recálculo encolado; el tablero se actualizará en unos segundos.</Alert>}
      {recalcular.isError && <Alert color="red">{mensajeError(recalcular.error, "No se pudo recalcular.")}</Alert>}
      {consulta.isError && <Alert color="red">{mensajeError(consulta.error, "No se pudo cargar el tablero.")}</Alert>}

      {r && opciones && (
        <>
          <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }}>
            <Indicador titulo="Luminarias" valor={numero(r.activos.total_luminarias)} pie={<Text size="xs" c="dimmed">{numero(r.activos.en_bodega)} en bodega</Text>} />
            <Indicador titulo={`Instaladas ${r.anio}`} valor={numero(r.activos.instaladas_anio)} />
            <Indicador
              titulo="PQRS abiertas"
              valor={numero(r.operacion.pqrs_abiertas)}
              pie={<Text size="xs" c={r.operacion.pqrs_semaforo.rojo ? "red.7" : "dimmed"}>{numero(r.operacion.pqrs_semaforo.rojo)} vencidas</Text>}
            />
            <Indicador
              titulo="PQRS recibidas (mes)"
              valor={numero(r.operacion.pqrs_recibidas_mes)}
              pie={<Variacion valor={r.operacion.variacion_pqrs_recibidas} inversa />}
            />
            <Indicador
              titulo="Mantenimientos (mes)"
              valor={numero(r.operacion.mantenimientos_mes)}
              pie={<Variacion valor={r.operacion.variacion_mantenimientos} />}
            />
            <Indicador
              titulo="Tiempo de atención"
              valor={r.operacion.tiempo_promedio_atencion_horas == null ? "—" : `${(r.operacion.tiempo_promedio_atencion_horas / 24).toLocaleString("es-CO", { maximumFractionDigits: 1 })} días`}
              pie={<Text size="xs" c="dimmed">promedio de PQRS atendidas en el año</Text>}
            />
          </SimpleGrid>

          {r.sede === "todas" && (
            <Panel titulo="Por sede">
              <MarcoTabla>
              <Table fz="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Sede</Table.Th>
                    <Table.Th ta="right">Luminarias</Table.Th>
                    <Table.Th ta="right">Instaladas {r.anio}</Table.Th>
                    <Table.Th ta="right">PQRS abiertas</Table.Th>
                    <Table.Th ta="right">Vencidas</Table.Th>
                    <Table.Th ta="right">Mantenimientos del mes</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {r.por_sede.map((p) => (
                    <Table.Tr key={p.sede.codigo}>
                      <Table.Td>{p.sede.nombre}</Table.Td>
                      <Table.Td ta="right">{numero(p.total_luminarias)}</Table.Td>
                      <Table.Td ta="right">{numero(p.instaladas_anio)}</Table.Td>
                      <Table.Td ta="right">{numero(p.pqrs_abiertas)}</Table.Td>
                      <Table.Td ta="right">{numero(p.pqrs_rojo)}</Table.Td>
                      <Table.Td ta="right">{numero(p.mantenimientos_mes)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
              </MarcoTabla>
            </Panel>
          )}

          <Panel
            titulo={`Luminarias instaladas en ${r.anio}, mes a mes`}
            nota={`${numero(r.activos.instaladas_anio)} en el año`}
          >
            <Grafico descripcion={`Luminarias instaladas por mes en ${r.anio}`} opcion={opciones.instaladas} alto={240} />
          </Panel>

          <SimpleGrid cols={{ base: 1, md: 3 }}>
            <Panel titulo="Por tecnología" nota="Clic para ver la tabla">
              <Grafico
                descripcion="Luminarias en servicio por tecnología"
                opcion={opciones.tecnologia}
                onClicCategoria={() => setDetalle({ titulo: "Luminarias por tecnología", filas: r.activos.por_tecnologia })}
              />
            </Panel>
            <Panel titulo="Por potencia" nota="Clic para ver la tabla">
              <Grafico
                descripcion="Luminarias en servicio por potencia"
                opcion={opciones.potencia}
                onClicCategoria={() => setDetalle({ titulo: "Luminarias por potencia", filas: r.activos.por_potencia })}
              />
            </Panel>
            <Panel titulo="Por zona" nota="Clic en una zona para ver sus barrios">
              <Grafico descripcion="Luminarias en servicio por zona" opcion={opciones.zona} onClicCategoria={verBarriosDeZona} />
            </Panel>
          </SimpleGrid>

          <SimpleGrid cols={{ base: 1, md: 3 }}>
            <Panel titulo="PQRS abiertas por plazo" nota="Umbrales de la sede">
              <Semaforo s={r.operacion.pqrs_semaforo} />
            </Panel>
            <Panel titulo="PQRS del año por barrio" nota="Clic para ver la tabla">
              <Grafico
                descripcion="PQRS del año por barrio"
                opcion={opciones.pqrsBarrio}
                onClicCategoria={() => setDetalle({ titulo: "PQRS del año por barrio", filas: r.operacion.pqrs_por_barrio })}
              />
            </Panel>
            <Panel titulo="Luminarias por estado" nota="Clic para ver la tabla">
              <Grafico
                descripcion="Luminarias por estado"
                opcion={opciones.estado}
                onClicCategoria={() => setDetalle({ titulo: "Luminarias por estado", filas: r.operacion.luminarias_por_estado })}
              />
              <Text size="xs" c="dimmed">
                {numero(r.operacion.ordenes_abiertas)} órdenes abiertas · {numero(r.operacion.materiales_bajo_minimo)} materiales bajo el mínimo
              </Text>
            </Panel>
          </SimpleGrid>

          <Title order={2} fz="md" mt="sm">
            Informe gerencial comercial
          </Title>
          {r.comercial.estado === "sin_cortes_cargados" && (
            <Alert color="gray">Todavía no hay cortes comerciales publicados para {r.sede === "todas" ? "estas sedes" : "esta sede"}.</Alert>
          )}
          {r.comercial.estado === "pendiente_de_calculo" && (
            <Alert color="blue">Los indicadores comerciales se están calculando; vuelva a consultar en unos minutos.</Alert>
          )}
          {r.comercial.comercializadores.map((c) => (
            <SeccionComercializador key={`${c.sede_codigo}-${c.comercializador}`} c={c} />
          ))}
        </>
      )}

      <Modal opened={detalle !== null} onClose={() => setDetalle(null)} title={detalle?.titulo} size="lg">
        <MarcoTabla>
        <Table fz="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Nombre</Table.Th>
              <Table.Th>Grupo</Table.Th>
              <Table.Th ta="right">Cantidad</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(detalle?.filas ?? []).map((f) => (
              <Table.Tr key={`${f.grupo}-${f.etiqueta}`}>
                <Table.Td>{f.etiqueta}</Table.Td>
                <Table.Td>{f.grupo ?? "—"}</Table.Td>
                <Table.Td ta="right">{numero(f.cantidad)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        </MarcoTabla>
      </Modal>
    </Stack>
  );
}
