import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
} from "@mantine/core";
import { api } from "@sapef/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuth } from "../auth/AuthContext";

export function PantallaConfiguracion() {
  const { sedeActiva, tienePermiso } = useAuth();
  const queryClient = useQueryClient();
  const [claseSel, setClaseSel] = useState<string>("LUMINARIA_MARCA");
  const [mensaje, setMensaje] = useState<string | null>(null);

  const headersSede = sedeActiva ? { "X-Sede": sedeActiva } : undefined;

  const { data: sedes = [] } = useQuery({
    queryKey: ["sedes"],
    queryFn: async () => (await api.GET("/api/v1/sedes")).data ?? [],
  });

  const { data: clases = [] } = useQuery({
    queryKey: ["maestros-clases"],
    queryFn: async () => (await api.GET("/api/v1/maestros/clases")).data ?? [],
  });

  const { data: valores = [] } = useQuery({
    queryKey: ["maestros-valores", claseSel],
    queryFn: async () =>
      (
        await api.GET("/api/v1/maestros/{clase}", {
          params: { path: { clase: claseSel } },
        })
      ).data ?? [],
  });

  const { data: zonas = [] } = useQuery({
    queryKey: ["zonas", sedeActiva],
    enabled: Boolean(sedeActiva),
    queryFn: async () =>
      (await api.GET("/api/v1/zonas", { headers: headersSede })).data ?? [],
  });

  const { data: barrios = [] } = useQuery({
    queryKey: ["barrios", sedeActiva],
    enabled: Boolean(sedeActiva),
    queryFn: async () =>
      (await api.GET("/api/v1/barrios", { headers: headersSede })).data ?? [],
  });

  const { data: estados = [] } = useQuery({
    queryKey: ["estados"],
    queryFn: async () => (await api.GET("/api/v1/estados")).data ?? [],
  });

  const { data: parametros = [] } = useQuery({
    queryKey: ["parametros", sedeActiva],
    enabled: Boolean(sedeActiva),
    queryFn: async () =>
      (await api.GET("/api/v1/parametros", { headers: headersSede })).data ?? [],
  });

  const { data: acuerdos = [] } = useQuery({
    queryKey: ["acuerdos", sedeActiva],
    enabled: Boolean(sedeActiva) && tienePermiso("configuracion.acuerdo.ver"),
    queryFn: async () =>
      (await api.GET("/api/v1/acuerdos", { headers: headersSede })).data ?? [],
  });

  const copiarAcuerdoMut = useMutation({
    mutationFn: async ({ id, anioDestino }: { id: number; anioDestino: number }) => {
      const { data, error } = await api.POST("/api/v1/acuerdos/{acuerdo_id}/copiar", {
        params: { path: { acuerdo_id: id } },
        headers: headersSede,
        body: { anio_destino: anioDestino },
      });
      if (!data) {
        throw new Error(
          error && typeof error === "object" && "detail" in error && typeof error.detail === "string"
            ? error.detail
            : "No se pudo copiar la vigencia.",
        );
      }
      return data;
    },
    onSuccess: (nuevo) => {
      setMensaje(`Borrador creado para el año ${nuevo.anio}.`);
      void queryClient.invalidateQueries({ queryKey: ["acuerdos", sedeActiva] });
    },
  });

  return (
    <Stack gap="md">
      <Title order={2}>Configuración del sistema</Title>
      {mensaje && (
        <Alert color="green" onClose={() => setMensaje(null)} withCloseButton>
          {mensaje}
        </Alert>
      )}

      <Tabs defaultValue="sedes">
        <Tabs.List>
          <Tabs.Tab value="sedes">Sedes</Tabs.Tab>
          <Tabs.Tab value="maestros">Maestros</Tabs.Tab>
          <Tabs.Tab value="zonas">Zonas y barrios ({sedeActiva ?? "-"})</Tabs.Tab>
          <Tabs.Tab value="estados">Estados</Tabs.Tab>
          <Tabs.Tab value="parametros">Parámetros</Tabs.Tab>
          {tienePermiso("configuracion.acuerdo.ver") && (
            <Tabs.Tab value="acuerdos">Acuerdos tarifarios</Tabs.Tab>
          )}
        </Tabs.List>

        <Tabs.Panel value="sedes" pt="md">
          <Card withBorder p={0}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Código</Table.Th>
                  <Table.Th>Nombre</Table.Th>
                  <Table.Th>Municipio</Table.Th>
                  <Table.Th>Departamento</Table.Th>
                  <Table.Th>Estado</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {sedes.map((s) => (
                  <Table.Tr key={s.id}>
                    <Table.Td>{s.codigo}</Table.Td>
                    <Table.Td>{s.nombre}</Table.Td>
                    <Table.Td>{s.municipio}</Table.Td>
                    <Table.Td>{s.departamento}</Table.Td>
                    <Table.Td>
                      <Badge color={s.activa ? "green" : "gray"}>
                        {s.activa ? "Activa" : "Inactiva"}
                      </Badge>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Card>
        </Tabs.Panel>

        <Tabs.Panel value="maestros" pt="md">
          <Stack gap="sm">
            <Select
              label="Clase de maestro"
              maw={360}
              data={clases.map((c) => ({ value: c.codigo, label: `${c.nombre} (${c.total_valores})` }))}
              value={claseSel}
              onChange={(v) => v && setClaseSel(v)}
            />
            <Card withBorder p={0}>
              <Table striped>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Código</Table.Th>
                    <Table.Th>Nombre</Table.Th>
                    <Table.Th>Estado</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {valores.map((v) => (
                    <Table.Tr key={v.id}>
                      <Table.Td>{v.codigo}</Table.Td>
                      <Table.Td>{v.nombre}</Table.Td>
                      <Table.Td>
                        <Badge color={v.activo ? "green" : "gray"}>
                          {v.activo ? "Activo" : "Inactivo"}
                        </Badge>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Card>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="zonas" pt="md">
          <Stack gap="sm">
            <Text size="sm" c="dimmed">
              {zonas.length} zonas y {barrios.length} barrios registrados en la sede activa.
            </Text>
            <Card withBorder p={0}>
              <Table striped>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Zona</Table.Th>
                    <Table.Th>Barrio</Table.Th>
                    <Table.Th>Estado</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {barrios.slice(0, 50).map((b) => (
                    <Table.Tr key={b.id}>
                      <Table.Td>{b.zona_nombre}</Table.Td>
                      <Table.Td>{b.nombre}</Table.Td>
                      <Table.Td>
                        <Badge color={b.activo ? "green" : "gray"}>
                          {b.activo ? "Activo" : "Inactivo"}
                        </Badge>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Card>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="estados" pt="md">
          <Card withBorder p={0}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Proceso</Table.Th>
                  <Table.Th>Código</Table.Th>
                  <Table.Th>Nombre</Table.Th>
                  <Table.Th>Vigente</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {estados.map((e) => (
                  <Table.Tr key={e.id}>
                    <Table.Td>{e.proceso}</Table.Td>
                    <Table.Td>{e.codigo}</Table.Td>
                    <Table.Td>{e.nombre}</Table.Td>
                    <Table.Td>{e.vigente ? "Sí" : "Histórico"}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Card>
        </Tabs.Panel>

        <Tabs.Panel value="parametros" pt="md">
          <Card withBorder p={0}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Alcance</Table.Th>
                  <Table.Th>Código</Table.Th>
                  <Table.Th>Nombre</Table.Th>
                  <Table.Th>Valor</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {parametros.map((p) => (
                  <Table.Tr key={p.id}>
                    <Table.Td>{p.alcance}</Table.Td>
                    <Table.Td>{p.codigo}</Table.Td>
                    <Table.Td>{p.nombre}</Table.Td>
                    <Table.Td>
                      <code>{JSON.stringify(p.valor)}</code>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Card>
        </Tabs.Panel>

        {tienePermiso("configuracion.acuerdo.ver") && (
          <Tabs.Panel value="acuerdos" pt="md">
            <Card withBorder p={0}>
              <Table striped>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Año</Table.Th>
                    <Table.Th>Comercializador</Table.Th>
                    <Table.Th>Estado</Table.Th>
                    <Table.Th>UVT</Table.Th>
                    <Table.Th>Tolerancia</Table.Th>
                    <Table.Th>Acciones</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {acuerdos.map((a) => (
                    <Table.Tr key={a.id}>
                      <Table.Td>{a.anio}</Table.Td>
                      <Table.Td>{a.comercializador_nombre}</Table.Td>
                      <Table.Td>
                        <Badge color={a.estado === "aprobado" ? "green" : "yellow"}>
                          {a.estado}
                        </Badge>
                      </Table.Td>
                      <Table.Td>{a.uvt ?? "-"}</Table.Td>
                      <Table.Td>{a.tolerancia ?? "-"}</Table.Td>
                      <Table.Td>
                        {tienePermiso("configuracion.acuerdo.editar") && (
                          <Group gap="xs">
                            <Button
                              size="xs"
                              variant="light"
                              onClick={() =>
                                copiarAcuerdoMut.mutate({ id: a.id, anioDestino: a.anio + 1 })
                              }
                            >
                              Copiar a {a.anio + 1}
                            </Button>
                          </Group>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Card>
          </Tabs.Panel>
        )}
      </Tabs>
    </Stack>
  );
}
