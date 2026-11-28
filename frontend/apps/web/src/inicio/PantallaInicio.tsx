// Inicio: lo que está pendiente hoy en la sede activa, con acceso directo a cada lista.
// Solo usa datos que ya existen (PQRS pendientes, órdenes por estado, luminarias); cada bloque se
// muestra si el usuario tiene el permiso correspondiente.
import { Anchor, Group, SimpleGrid, Stack, Table, Text, Title, UnstyledButton } from "@mantine/core";
import { api } from "@sapef/api";
import { useQuery } from "@tanstack/react-query";
import { IconArrowRight } from "@tabler/icons-react";
import type { ReactNode } from "react";

import { useAuth } from "../auth/AuthContext";
import { cifra, Codigo, EncabezadoPagina, MarcoTabla } from "../comun/ui";
import { EstadoSistema } from "../sistema/EstadoSistema";

const COLOR_SEMAFORO = {
  rojo: "var(--mantine-color-red-6)",
  amarillo: "var(--mantine-color-yellow-6)",
  verde: "var(--mantine-color-green-6)",
} as const;

function saludo(): string {
  const h = new Date().getHours();
  if (h < 12) return "Buenos días";
  if (h < 19) return "Buenas tardes";
  return "Buenas noches";
}

/** Indicador con cifra grande, desglose y enlace a la lista. */
function Indicador({
  titulo,
  valor,
  detalle,
  onClick,
  testId,
}: {
  titulo: string;
  valor: number | undefined;
  detalle?: ReactNode;
  onClick?: () => void;
  testId?: string;
}) {
  return (
    <UnstyledButton
      onClick={onClick}
      data-testid={testId}
      style={{
        border: "1px solid var(--sapef-borde)",
        borderRadius: "var(--mantine-radius-sm)",
        background: "var(--sapef-superficie)",
        padding: "16px 18px",
        display: "block",
      }}
    >
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Text size="sm" c="dimmed">
          {titulo}
        </Text>
        {onClick && <IconArrowRight size={16} color="var(--mantine-color-gray-5)" />}
      </Group>
      <Text fz={30} fw={500} lh={1.1} mt={8} className="sapef-cifra">
        {valor === undefined ? "—" : cifra(valor)}
      </Text>
      {detalle && (
        <Text size="xs" c="dimmed" mt={6} className="sapef-cifra">
          {detalle}
        </Text>
      )}
    </UnstyledButton>
  );
}

function Punto({ color }: { color: string }) {
  return <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: 7, background: color, marginRight: 6 }} />;
}

export function PantallaInicio({ navegar }: { navegar: (ruta: string) => void }) {
  const { usuario, sedeActiva, tienePermiso } = useAuth();
  const headers = sedeActiva ? { "X-Sede": sedeActiva } : undefined;
  const conSede = Boolean(sedeActiva);
  const vePqrs = tienePermiso("atencion.pqrs.ver");
  const veOrdenes = tienePermiso("trabajos.orden.ver");
  const veLuminarias = tienePermiso("activos.luminaria.ver");

  const useTotalPendientes = (semaforo?: "rojo" | "amarillo" | "verde") =>
    useQuery({
      queryKey: ["inicio-pendientes", sedeActiva, semaforo ?? "todos"],
      enabled: vePqrs && conSede,
      queryFn: async () =>
        (
          await api.GET("/api/v1/pqrs/pendientes", {
            headers,
            params: { query: { page: 1, size: semaforo === "rojo" ? 6 : 1, semaforo } },
          })
        ).data,
    });
  const pendientes = useTotalPendientes();
  const rojos = useTotalPendientes("rojo");
  const amarillos = useTotalPendientes("amarillo");

  const { data: estadosOrden = [] } = useQuery({
    queryKey: ["estados", "orden"],
    enabled: veOrdenes,
    queryFn: async () =>
      (await api.GET("/api/v1/estados", { params: { query: { proceso: "orden" } } })).data ?? [],
  });
  const idEstado = (codigo: string) => estadosOrden.find((e) => e.codigo === codigo)?.id;
  const useTotalOrdenes = (codigo: string) =>
    useQuery({
      queryKey: ["inicio-ordenes", sedeActiva, codigo],
      enabled: veOrdenes && conSede && idEstado(codigo) !== undefined,
      queryFn: async () =>
        (
          await api.GET("/api/v1/ordenes", {
            headers,
            params: { query: { page: 1, size: 1, estado_id: idEstado(codigo) } },
          })
        ).data?.total ?? 0,
    });
  const enElaboracion = useTotalOrdenes("201");
  const enProceso = useTotalOrdenes("202");
  const enEjecucion = useTotalOrdenes("205");
  const abiertas =
    enElaboracion.data !== undefined && enProceso.data !== undefined && enEjecucion.data !== undefined
      ? enElaboracion.data + enProceso.data + enEjecucion.data
      : undefined;

  const { data: luminarias } = useQuery({
    queryKey: ["inicio-luminarias", sedeActiva],
    enabled: veLuminarias && conSede,
    queryFn: async () =>
      (await api.GET("/api/v1/luminarias", { headers, params: { query: { page: 1, size: 1 } } })).data?.total,
  });

  const sede = usuario?.sedes.find((s) => s.codigo === sedeActiva);
  const fechaHoy = new Date().toLocaleDateString("es-CO", { weekday: "long", day: "numeric", month: "long" });
  const nombre = (usuario?.nombre_completo || usuario?.nombre_usuario || "").split(" ")[0];
  const urgentes = rojos.data?.items ?? [];

  return (
    <Stack gap="lg">
      <EncabezadoPagina
        seccion={`${fechaHoy.charAt(0).toUpperCase()}${fechaHoy.slice(1)} · ${sede?.nombre ?? "Sin sede"}`}
        titulo={`${saludo()}, ${nombre}`}
        descripcion="Lo pendiente en la sede activa. Cada cifra abre su lista."
      />

      {(vePqrs || veOrdenes || veLuminarias) && (
        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
          {vePqrs && (
            <Indicador
              testId="inicio-pqrs"
              titulo="Luminarias con PQRS abierta"
              valor={pendientes.data?.total}
              detalle={
                rojos.data && amarillos.data ? (
                  <>
                    <Punto color={COLOR_SEMAFORO.rojo} />
                    {cifra(rojos.data.total)} vencidas
                    <span style={{ margin: "0 8px" }}>·</span>
                    <Punto color={COLOR_SEMAFORO.amarillo} />
                    {cifra(amarillos.data.total)} por vencer
                  </>
                ) : undefined
              }
              onClick={() => navegar("/atencion/pendientes")}
            />
          )}
          {veOrdenes && (
            <Indicador
              testId="inicio-ordenes"
              titulo="Órdenes de trabajo abiertas"
              valor={abiertas}
              detalle={
                abiertas !== undefined
                  ? `${cifra(enElaboracion.data)} sin asignar · ${cifra(enProceso.data)} asignadas · ${cifra(enEjecucion.data)} en ejecución`
                  : undefined
              }
              onClick={() => navegar("/trabajos/ordenes")}
            />
          )}
          {veLuminarias && (
            <Indicador
              titulo="Luminarias registradas"
              valor={luminarias}
              detalle={sede ? `Sede ${sede.nombre}` : undefined}
              onClick={() => navegar("/activos/luminarias")}
            />
          )}
        </SimpleGrid>
      )}

      {vePqrs && (
        <div>
          <Group justify="space-between" mb="xs">
            <Title order={2} fz="md">
              Más urgentes
            </Title>
            <Anchor size="sm" component="button" onClick={() => navegar("/atencion/pendientes")}>
              Ver todas las pendientes
            </Anchor>
          </Group>
          {urgentes.length === 0 ? (
            <Text size="sm" c="dimmed">
              {rojos.isPending ? "Consultando…" : "No hay luminarias con PQRS vencida. Buen trabajo."}
            </Text>
          ) : (
            <MarcoTabla>
              <Table>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Luminaria</Table.Th>
                    <Table.Th>PQRS</Table.Th>
                    <Table.Th>Barrio</Table.Th>
                    <Table.Th>Prioridad</Table.Th>
                    <Table.Th ta="right">Días abierta</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {urgentes.map((p) => (
                    <Table.Tr key={`${p.pqrs_id}-${p.luminaria_id}`}>
                      <Table.Td>
                        <Codigo>{p.luminaria_codigo}</Codigo>
                      </Table.Td>
                      <Table.Td>
                        <Codigo>#{p.pqrs_numero}</Codigo>
                      </Table.Td>
                      <Table.Td>{p.barrio_nombre ?? "—"}</Table.Td>
                      <Table.Td>{p.prioridad_nombre}</Table.Td>
                      <Table.Td ta="right">
                        <Punto color={COLOR_SEMAFORO[p.semaforo]} />
                        {p.dias_abierta}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </MarcoTabla>
          )}
        </div>
      )}

      {tienePermiso("seguridad.usuario.ver") && <EstadoSistema compacto />}
    </Stack>
  );
}
