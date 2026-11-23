import { Alert, Badge, Card, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { api, type Salud } from "@sapef/api";
import { useQuery } from "@tanstack/react-query";

async function consultarSalud(): Promise<Salud> {
  const { data, error, response } = await api.GET("/api/v1/salud");
  if (data) return data;
  // 503 también trae un cuerpo Salud ("degradado", declarado en el OpenAPI): se muestra.
  if (response.status === 503 && error && "estado" in error) return error;
  throw new Error(`La API respondió ${response.status}`);
}

export function EstadoSistema() {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["salud"],
    queryFn: consultarSalud,
  });

  return (
    <Stack maw={560}>
      <Title order={2}>Estado del sistema</Title>
      {isPending && <Loader aria-label="Consultando" />}
      {isError && (
        <Alert color="red" title="No se pudo consultar la API">
          {error.message}. Revise que los contenedores estén encendidos.
        </Alert>
      )}
      {data && (
        <Card withBorder>
          <Group justify="space-between">
            <Text fw={600}>API</Text>
            <Badge color={data.estado === "ok" ? "green" : "orange"}>{data.estado}</Badge>
          </Group>
          <Text size="sm" c="dimmed">
            Versión {data.version}
          </Text>
          <Group justify="space-between" mt="sm">
            <Text fw={600}>Base de datos</Text>
            <Badge color={data.base_de_datos === "ok" ? "green" : "red"}>{data.base_de_datos}</Badge>
          </Group>
          {data.postgres && (
            <Text size="sm" c="dimmed">
              PostgreSQL {data.postgres} · PostGIS {data.postgis}
            </Text>
          )}
        </Card>
      )}
    </Stack>
  );
}
