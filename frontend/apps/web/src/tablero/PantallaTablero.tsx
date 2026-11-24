// Tablero gerencial (EP-09, RF-090): se lee en ≤ 5 minutos, por sede o consolidado. Lee solo las
// tablas resumen del backend (respuesta < 2 s); el detalle sale al hacer clic en un gráfico.
import { api, type components } from "@sapef/api";
import {
  Alert,
  Badge,
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
    <Text size="xs" c={bueno ? "teal" : "red"}>
      {valor > 0 ? "▲" : valor < 0 ? "▼" : "="} {Math.abs(valor).toLocaleString("es-CO")} % vs. mes anterior
    </Text>
  );
}

function Indicador({ titulo, valor, pie }: { titulo: string; valor: string; pie?: React.ReactNode }) {
  return (
    <Card withBorder padding="sm">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {titulo}
      </Text>
      <Text size="xl" fw={700}>
        {valor}
      </Text>
      {pie}
    </Card>
  );
}

function barrasHorizontales(filas: Conteo[], nombre: string): OpcionGrafico {
  const datos = [...filas].slice(0, 12).reverse();
  return {
    tooltip: { trigger: "axis" },
    grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "value" },
    yAxis: { type: "category", data: datos.map((f) => f.etiqueta) },
    series: [{ name: nombre, type: "bar", data: datos.map((f) => f.cantidad), label: { show: true, position: "right" } }],
  };
}

function dona(filas: { name: string; value: number; color?: string }[], nombre: string): OpcionGrafico {
  return {
    tooltip: { trigger: "item" },
    legend: { bottom: 0 },
    series: [
      {
        name: nombre,
        type: "pie",
        radius: ["45%", "70%"],
        label: { formatter: "{b}: {c}" },
        data: filas.map((f) => ({ name: f.name, value: f.value, itemStyle: f.color ? { color: f.color } : undefined })),
      },
    ],
  };
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
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Title order={4}>
          {c.nombre} · {c.sede_nombre}
        </Title>
        <Badge variant="light">
          Corte {c.periodo}
          {c.periodo_anterior ? ` vs. ${c.periodo_anterior}` : ""}
        </Badge>
      </Group>
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Table striped withTableBorder fz="sm">
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
                <Table.Td ta="right">
                  {variacion === null || variacion === undefined ? "—" : `${variacion.toLocaleString("es-CO")} %`}
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
        <Stack gap="xs">
          <Grafico
            descripcion={`Histórico de facturación y recaudo de ${c.nombre}`}
            opcion={{
              tooltip: { trigger: "axis" },
              legend: { top: 0 },
              grid: { left: 8, right: 8, top: 32, bottom: 8, containLabel: true },
              xAxis: { type: "category", data: historico.map((h) => h.periodo) },
              yAxis: { type: "value" },
              series: [
                { name: "Facturado", type: "line", data: historico.map((h) => h.facturacion) },
                { name: "Recaudo", type: "line", data: historico.map((h) => h.recaudo) },
                { name: "Cartera", type: "bar", data: historico.map((h) => h.cartera) },
              ],
            }}
          />
          <Table fz="xs" withTableBorder>
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
    const s = r.operacion.pqrs_semaforo;
    return {
      instaladas: {
        tooltip: { trigger: "axis" },
        legend: { top: 0 },
        grid: { left: 8, right: 8, top: 32, bottom: 8, containLabel: true },
        xAxis: { type: "category", data: meses.map((m) => MESES[m.mes - 1]) },
        yAxis: [{ type: "value", name: "Mes" }, { type: "value", name: "Acumulado" }],
        series: [
          { name: "Instaladas en el mes", type: "bar", data: meses.map((m) => m.cantidad) },
          { name: "Acumulado del año", type: "line", yAxisIndex: 1, data: meses.map((m) => m.acumulado) },
        ],
      } satisfies OpcionGrafico,
      tecnologia: dona(r.activos.por_tecnologia.map((f) => ({ name: f.etiqueta, value: f.cantidad })), "Tecnología"),
      potencia: barrasHorizontales(r.activos.por_potencia, "Luminarias"),
      zona: barrasHorizontales(r.activos.por_zona, "Luminarias"),
      estado: barrasHorizontales(r.operacion.luminarias_por_estado, "Luminarias"),
      semaforo: dona(
        [
          { name: `Verde (≤ ${s.umbral_verde_dias ?? "?"} d)`, value: s.verde, color: "#2f9e44" },
          { name: `Amarillo (≤ ${s.umbral_amarillo_dias ?? "?"} d)`, value: s.amarillo, color: "#f59f00" },
          { name: "Rojo", value: s.rojo, color: "#e03131" },
        ],
        "PQRS abiertas",
      ),
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
      <Group justify="space-between" wrap="wrap">
        <div>
          <Title order={2}>Tablero gerencial</Title>
          <Text size="sm" c="dimmed">
            {r
              ? `${r.sede === "todas" ? "Consolidado: " + r.sedes_incluidas.map((s) => s.nombre).join(", ") : r.sedes_incluidas[0]?.nombre ?? ""} · calculado ${r.calculado_en ? new Date(r.calculado_en).toLocaleString("es-CO") : "—"}`
              : "Cargando…"}
          </Text>
        </div>
        <Group>
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
          <Select aria-label="Año" data={anios} value={anio} onChange={(v) => v && setAnio(v)} w={100} />
          <Button variant="light" loading={recalcular.isPending} onClick={() => recalcular.mutate()}>
            Recalcular
          </Button>
        </Group>
      </Group>

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
              pie={<Text size="xs" c={r.operacion.pqrs_semaforo.rojo ? "red" : "dimmed"}>{numero(r.operacion.pqrs_semaforo.rojo)} en rojo</Text>}
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
            <Card withBorder>
              <Title order={4} mb="xs">Por sede</Title>
              <Table striped fz="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Sede</Table.Th>
                    <Table.Th ta="right">Luminarias</Table.Th>
                    <Table.Th ta="right">Instaladas {r.anio}</Table.Th>
                    <Table.Th ta="right">PQRS abiertas</Table.Th>
                    <Table.Th ta="right">En rojo</Table.Th>
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
            </Card>
          )}

          <Card withBorder>
            <Title order={4}>Luminarias instaladas en {r.anio}, mes a mes</Title>
            <Grafico descripcion={`Luminarias instaladas por mes en ${r.anio}`} opcion={opciones.instaladas} alto={280} />
          </Card>

          <SimpleGrid cols={{ base: 1, md: 3 }}>
            <Card withBorder>
              <Title order={5}>Por tecnología</Title>
              <Grafico
                descripcion="Luminarias en servicio por tecnología"
                opcion={opciones.tecnologia}
                onClicCategoria={() => setDetalle({ titulo: "Luminarias por tecnología", filas: r.activos.por_tecnologia })}
              />
            </Card>
            <Card withBorder>
              <Title order={5}>Por potencia</Title>
              <Grafico
                descripcion="Luminarias en servicio por potencia"
                opcion={opciones.potencia}
                onClicCategoria={() => setDetalle({ titulo: "Luminarias por potencia", filas: r.activos.por_potencia })}
              />
            </Card>
            <Card withBorder>
              <Title order={5}>Por zona</Title>
              <Text size="xs" c="dimmed">Clic en una zona para ver sus barrios</Text>
              <Grafico descripcion="Luminarias en servicio por zona" opcion={opciones.zona} onClicCategoria={verBarriosDeZona} />
            </Card>
          </SimpleGrid>

          <SimpleGrid cols={{ base: 1, md: 3 }}>
            <Card withBorder>
              <Title order={5}>PQRS abiertas por antigüedad</Title>
              <Grafico descripcion="Semáforo de PQRS abiertas" opcion={opciones.semaforo} />
            </Card>
            <Card withBorder>
              <Title order={5}>PQRS del año por barrio</Title>
              <Grafico
                descripcion="PQRS del año por barrio"
                opcion={opciones.pqrsBarrio}
                onClicCategoria={() => setDetalle({ titulo: "PQRS del año por barrio", filas: r.operacion.pqrs_por_barrio })}
              />
            </Card>
            <Card withBorder>
              <Title order={5}>Luminarias por estado</Title>
              <Grafico
                descripcion="Luminarias por estado"
                opcion={opciones.estado}
                onClicCategoria={() => setDetalle({ titulo: "Luminarias por estado", filas: r.operacion.luminarias_por_estado })}
              />
              <Text size="xs" c="dimmed">
                {numero(r.operacion.ordenes_abiertas)} órdenes abiertas · {numero(r.operacion.materiales_bajo_minimo)} materiales bajo el mínimo
              </Text>
            </Card>
          </SimpleGrid>

          <Title order={3}>Informe gerencial comercial</Title>
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
        <Table striped fz="sm">
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
      </Modal>
    </Stack>
  );
}
