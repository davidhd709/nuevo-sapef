import { Alert, Badge, Group, Loader, Stack, Text } from "@mantine/core";
import { api, type Salud } from "@sapef/api";
import { useQuery } from "@tanstack/react-query";

async function consultarSalud(): Promise<Salud> {
  const { data, error, response } = await api.GET("/api/v1/salud");
  if (data) return data;
  // 503 también trae un cuerpo Salud ("degradado", declarado en el OpenAPI): se muestra.
  if (response.status === 503 && error && "estado" in error) return error;
  throw new Error(`La API respondió ${response.status}`);
}

/** Estado técnico de la API y la base de datos (franja discreta para administradores). */
export function EstadoSistema({ compacto = false }: { compacto?: boolean }) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["salud"],
    queryFn: consultarSalud,
  });

  const color = (valor: string) => (valor === "ok" ? "green" : valor === "degradado" ? "orange" : "red");

  return (
    <Stack gap={6}>
      <Text fz={11} fw={600} tt="uppercase" c="dimmed" style={{ letterSpacing: "0.08em" }}>
        Estado del sistema
      </Text>
      {isPending && <Loader size="xs" color="gray" aria-label="Consultando" />}
      {isError && (
        <Alert color="red" title="No se pudo consultar la API">
          {error.message}. Revise que los contenedores estén encendidos.
        </Alert>
      )}
      {data && (
        <Group
          gap="lg"
          wrap="wrap"
          style={{
            border: "1px solid var(--sapef-borde)",
            borderRadius: "var(--mantine-radius-sm)",
            background: "var(--sapef-superficie)",
            padding: compacto ? "8px 14px" : "12px 16px",
          }}
        >
          <Group gap={6}>
            <Text size="sm">API</Text>
            <Badge variant="dot" color={color(data.estado)}>
              {data.estado}
            </Badge>
          </Group>
          <Group gap={6}>
            <Text size="sm">Base de datos</Text>
            <Badge variant="dot" color={color(data.base_de_datos)}>
              {data.base_de_datos}
            </Badge>
          </Group>
          <Text size="xs" c="dimmed" className="sapef-cifra">
            Versión {data.version}
          </Text>
          {data.postgres && (
            <Text size="xs" c="dimmed" className="sapef-cifra">
              PostgreSQL {data.postgres} · PostGIS {data.postgis}
            </Text>
          )}
        </Group>
      )}
    </Stack>
  );
}
