// Presenta cualquier resultado de análisis comercial: cifras sueltas como tarjetas, objetos
// planos como tablas de dos columnas y listas de objetos como tablas (con tope de filas).
import { Badge, Card, Group, ScrollArea, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";

type Valor = unknown;

const NUMERO = /^-?\d+(\.\d+)?$/;

export function formatear(valor: Valor): string {
  if (valor === null || valor === undefined || valor === "") return "—";
  if (typeof valor === "boolean") return valor ? "Sí" : "No";
  if (typeof valor === "number") return valor.toLocaleString("es-CO", { maximumFractionDigits: 4 });
  if (typeof valor === "string" && NUMERO.test(valor)) {
    const n = Number(valor);
    return n.toLocaleString("es-CO", { maximumFractionDigits: valor.includes(".") ? 2 : 0 });
  }
  if (Array.isArray(valor)) return valor.map((v) => formatear(v)).join(", ");
  if (typeof valor === "object") return JSON.stringify(valor);
  return String(valor);
}

function etiqueta(clave: string): string {
  const texto = clave.replace(/_/g, " ");
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

function esEscalar(v: Valor): boolean {
  return v === null || ["string", "number", "boolean"].includes(typeof v);
}

function esListaDeObjetos(v: Valor): v is Record<string, Valor>[] {
  return Array.isArray(v) && v.length > 0 && v.every((x) => x && typeof x === "object" && !Array.isArray(x));
}

export function TablaObjetos({ filas, tope = 300 }: { filas: Record<string, Valor>[]; tope?: number }) {
  const columnas = Object.keys(filas[0] ?? {}).filter((c) => filas.some((f) => esEscalar(f[c]) || Array.isArray(f[c])));
  return (
    <ScrollArea type="auto">
      <Table striped withTableBorder fz="xs" miw={600}>
        <Table.Thead>
          <Table.Tr>
            {columnas.map((c) => (
              <Table.Th key={c}>{etiqueta(c)}</Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {filas.slice(0, tope).map((fila, i) => (
            <Table.Tr key={i}>
              {columnas.map((c) => (
                <Table.Td key={c}>{formatear(fila[c])}</Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {filas.length > tope && (
        <Text size="xs" c="dimmed" mt={4}>
          Se muestran {tope} de {filas.length} filas; descargue el anexo para el listado completo.
        </Text>
      )}
    </ScrollArea>
  );
}

export function VistaResultado({ datos }: { datos: Record<string, Valor> }) {
  const escalares = Object.entries(datos).filter(([, v]) => esEscalar(v) && v !== null);
  const objetos = Object.entries(datos).filter(
    ([, v]) => v && typeof v === "object" && !Array.isArray(v) && Object.keys(v).length > 0,
  ) as [string, Record<string, Valor>][];
  const listas = Object.entries(datos).filter(([, v]) => esListaDeObjetos(v)) as [string, Record<string, Valor>[]][];
  const nota = typeof datos.nota === "string" ? datos.nota : null;

  return (
    <Stack gap="md">
      {nota && (
        <Text size="sm" c="dimmed">
          {nota}
        </Text>
      )}
      {escalares.length > 0 && (
        <SimpleGrid cols={{ base: 2, sm: 3, lg: 4 }} spacing="xs">
          {escalares
            .filter(([k]) => k !== "nota")
            .map(([clave, valor]) => (
              <Card key={clave} withBorder padding="xs">
                <Text size="xs" c="dimmed">
                  {etiqueta(clave)}
                </Text>
                <Text fw={600}>{formatear(valor)}</Text>
              </Card>
            ))}
        </SimpleGrid>
      )}
      {objetos.map(([clave, objeto]) => {
        const entradas = Object.entries(objeto);
        const anidadas = entradas.every(([, v]) => v && typeof v === "object" && !Array.isArray(v));
        return (
          <Stack key={clave} gap={4}>
            <Title order={5}>{etiqueta(clave)}</Title>
            {anidadas ? (
              <TablaObjetos
                filas={entradas.map(([k, v]) => ({ clave: k, ...(v as Record<string, Valor>) }))}
              />
            ) : (
              <Group gap="xs">
                {entradas.map(([k, v]) => (
                  <Badge key={k} variant="light" size="lg">
                    {etiqueta(k)}: {formatear(Array.isArray(v) ? v.length : v)}
                  </Badge>
                ))}
              </Group>
            )}
          </Stack>
        );
      })}
      {listas.map(([clave, filas]) => (
        <Stack key={clave} gap={4}>
          <Title order={5}>
            {etiqueta(clave)} ({filas.length})
          </Title>
          <TablaObjetos filas={filas} />
        </Stack>
      ))}
    </Stack>
  );
}
