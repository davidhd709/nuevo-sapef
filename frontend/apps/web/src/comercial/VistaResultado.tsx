// Presenta cualquier resultado de análisis comercial: cifras sueltas como tarjetas, objetos
// planos como tablas de dos columnas y listas de objetos como tablas (con tope de filas).
import { Group, ScrollArea, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";

import { MarcoTabla } from "../comun/ui";

type Valor = unknown;

// Decimales del backend: «123», «-4.5» y también notación científica («0E-10», «1.2E+3»).
const NUMERO = /^-?\d+(\.\d+)?([eE][-+]?\d+)?$/;
// Columnas que son identificadores: se muestran tal cual (sin separador de miles).
const IDENTIFICADORES = /^(nic|nis|nis_rad|cuenta|identificador|codigo|cliente|periodo|corte|anio|mes)$/i;

/** ¿La clave es una fracción que debe verse como porcentaje? (pct_*, eficiencia*) */
function esPorcentaje(clave?: string): boolean {
  return Boolean(clave && (/^pct_/i.test(clave) || /^eficiencia/i.test(clave)));
}

export function formatear(valor: Valor, clave?: string): string {
  if (valor === null || valor === undefined || valor === "") return "—";
  if (typeof valor === "boolean") return valor ? "Sí" : "No";
  if (clave && IDENTIFICADORES.test(clave)) return String(valor);
  let n: number | null = null;
  let decimales = 0;
  if (typeof valor === "number") {
    n = valor;
    decimales = Number.isInteger(valor) ? 0 : 2;
  } else if (typeof valor === "string" && NUMERO.test(valor)) {
    n = Number(valor);
    decimales = Number.isInteger(n) ? 0 : 2;
  }
  if (n !== null && Number.isFinite(n)) {
    if (Math.abs(n) < 1e-9) n = 0;
    if (esPorcentaje(clave)) {
      return (n * 100).toLocaleString("es-CO", { maximumFractionDigits: 1 }) + " %";
    }
    return n.toLocaleString("es-CO", { maximumFractionDigits: decimales });
  }
  if (Array.isArray(valor)) return valor.map((v) => formatear(v)).join(", ");
  if (typeof valor === "object") return JSON.stringify(valor);
  return String(valor);
}

export function etiqueta(clave: string): string {
  let texto = clave.replace(/_/g, " ").trim();
  texto = texto.replace(/^pct /i, "% ").replace(/^n /i, "Nº ").replace(/\bkwh\b/gi, "kWh");
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

function esEscalar(v: Valor): boolean {
  return v === null || ["string", "number", "boolean"].includes(typeof v);
}

function esListaDeObjetos(v: Valor): v is Record<string, Valor>[] {
  return Array.isArray(v) && v.length > 0 && v.every((x) => x && typeof x === "object" && !Array.isArray(x));
}

function esNumerica(filas: Record<string, Valor>[], columna: string): boolean {
  if (IDENTIFICADORES.test(columna)) return false;
  return filas.slice(0, 20).every((f) => {
    const v = f[columna];
    return v === null || v === undefined || typeof v === "number" || (typeof v === "string" && NUMERO.test(v));
  });
}

export function TablaObjetos({ filas, tope = 300 }: { filas: Record<string, Valor>[]; tope?: number }) {
  const columnas = Object.keys(filas[0] ?? {}).filter((c) => filas.some((f) => esEscalar(f[c]) || Array.isArray(f[c])));
  const numericas = new Set(columnas.filter((c) => esNumerica(filas, c)));
  return (
    <div>
      <MarcoTabla>
        <ScrollArea type="auto">
          <Table fz="xs" miw={600}>
            <Table.Thead>
              <Table.Tr>
                {columnas.map((c) => (
                  <Table.Th key={c} ta={numericas.has(c) ? "right" : undefined}>
                    {etiqueta(c)}
                  </Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {filas.slice(0, tope).map((fila, i) => (
                <Table.Tr key={i}>
                  {columnas.map((c) => (
                    <Table.Td
                      key={c}
                      ta={numericas.has(c) ? "right" : undefined}
                      className={IDENTIFICADORES.test(c) ? "sapef-mono" : undefined}
                    >
                      {formatear(fila[c], c)}
                    </Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </MarcoTabla>
      {filas.length > tope && (
        <Text size="xs" c="dimmed" mt={4}>
          Se muestran {tope} de {filas.length} filas; descargue el anexo para el listado completo.
        </Text>
      )}
    </div>
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
        <SimpleGrid
          cols={{ base: 2, sm: 3, lg: 4 }}
          spacing={0}
          verticalSpacing={0}
          style={{
            border: "1px solid var(--sapef-borde)",
            borderRadius: "var(--mantine-radius-sm)",
            background: "var(--sapef-superficie)",
            overflow: "hidden",
          }}
        >
          {escalares
            .filter(([k]) => k !== "nota")
            .map(([clave, valor]) => (
              <div
                key={clave}
                style={{
                  padding: "10px 14px",
                  borderRight: "1px solid var(--sapef-borde)",
                  borderBottom: "1px solid var(--sapef-borde)",
                  marginRight: -1,
                  marginBottom: -1,
                }}
              >
                <Text size="xs" c="dimmed" lineClamp={1} title={etiqueta(clave)}>
                  {etiqueta(clave)}
                </Text>
                <Text fz="lg" fw={500} className="sapef-cifra" mt={2}>
                  {formatear(valor, clave)}
                </Text>
              </div>
            ))}
        </SimpleGrid>
      )}
      {objetos.map(([clave, objeto]) => {
        const entradas = Object.entries(objeto);
        const anidadas = entradas.every(([, v]) => v && typeof v === "object" && !Array.isArray(v));
        return (
          <Stack key={clave} gap={6}>
            <Title order={3} fz="sm">
              {etiqueta(clave)}
            </Title>
            {anidadas ? (
              <TablaObjetos filas={entradas.map(([k, v]) => ({ clave: k, ...(v as Record<string, Valor>) }))} />
            ) : (
              <Group gap="lg">
                {entradas.map(([k, v]) => (
                  <div key={k}>
                    <Text size="xs" c="dimmed">
                      {etiqueta(k)}
                    </Text>
                    <Text fw={500} className="sapef-cifra">
                      {formatear(Array.isArray(v) ? v.length : v, k)}
                    </Text>
                  </div>
                ))}
              </Group>
            )}
          </Stack>
        );
      })}
      {listas.map(([clave, filas]) => (
        <Stack key={clave} gap={6}>
          <Title order={3} fz="sm">
            {etiqueta(clave)}{" "}
            <Text span c="dimmed" fw={400} fz="sm">
              ({filas.length})
            </Text>
          </Title>
          <TablaObjetos filas={filas} />
        </Stack>
      ))}
    </Stack>
  );
}
