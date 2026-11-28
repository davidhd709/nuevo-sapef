// Migración desde SAPEF (RF-110 a RF-112): subir las exportaciones, seguir cada ejecución en el
// worker y revisar su informe de conciliación, errores por fila y advertencias.
import {
  Alert,
  Badge,
  Button,
  Card,
  Drawer,
  FileInput,
  Group,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { api, type components } from "@sapef/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { Codigo, EncabezadoPagina, EstadoVacio, EtiquetaEstado, MarcoTabla, SinPermiso } from "../comun/ui";
import { exigir, mensajeError } from "../comun/api";

type Ejecucion = components["schemas"]["EjecucionMigracionSalida"];

interface Importador {
  tipo: string;
  titulo: string;
  permiso: string;
  descripcion: string;
  // Campos del formulario: uno por archivo que recibe la ruta.
  campos: { campo: string; etiqueta: string }[];
}

// El orden es el del corte: primero la base, luego luminarias y después lo que depende de ellas.
export const IMPORTADORES: Importador[] = [
  {
    tipo: "base",
    titulo: "1. Zonas, barrios y usuarios",
    permiso: "seguridad.usuario.crear",
    descripcion:
      "Excel con hojas ZonasBarrios y Usuarios. Los usuarios entran sin contraseña: cada uno la define en su primer ingreso.",
    campos: [{ campo: "archivo", etiqueta: "Libro de base (.xlsx)" }],
  },
  {
    tipo: "luminarias",
    titulo: "2. Luminarias",
    permiso: "activos.luminaria.crear",
    descripcion:
      "Exportación LUMINARIAS_LIST_DESCARGA de SAPEF (.csv) o la plantilla en Excel. Crea los barrios que falten con su zona.",
    campos: [{ campo: "archivo", etiqueta: "Luminarias (.csv o .xlsx)" }],
  },
  {
    tipo: "pqrs",
    titulo: "3. PQRS",
    permiso: "atencion.pqrs.crear",
    descripcion:
      "Exportación LUMINARIAS_REPARAR (pendientes) o la plantilla de PQRS. Requiere las luminarias ya importadas.",
    campos: [{ campo: "archivo", etiqueta: "PQRS (.csv o .xlsx)" }],
  },
  {
    tipo: "ordenes",
    titulo: "4. Órdenes históricas",
    permiso: "trabajos.orden.cerrar",
    descripcion:
      "Las cuatro exportaciones de SAPEF. Entran como órdenes cerradas: no cambian luminarias ni kárdex.",
    campos: [
      { campo: "mantenimientos", etiqueta: "MANTENIMIENTOS_EXPORTAR" },
      { campo: "expansiones", etiqueta: "EXPANSIONES" },
      { campo: "modernizaciones", etiqueta: "MODERNIZACIONES" },
      { campo: "reubicaciones", etiqueta: "REUBICACIONES" },
    ],
  },
  {
    tipo: "inventario",
    titulo: "5. Inventario",
    permiso: "inventario.material.editar",
    descripcion:
      "Excel con hojas Materiales, Movimientos (kárdex) y Bodega. Concilia las existencias del archivo con el kárdex resultante.",
    campos: [{ campo: "archivo", etiqueta: "Inventario (.xlsx)" }],
  },
];

const COLOR_ESTADO: Record<string, string> = {
  pendiente: "gray",
  procesando: "blue",
  completado: "green",
  con_errores: "yellow",
  error: "red",
};

const TEXTO_ESTADO: Record<string, string> = {
  pendiente: "En cola",
  procesando: "Procesando",
  completado: "Completada",
  con_errores: "Con errores",
  error: "Falló",
};

export function etiquetaConciliacion(clave: string): string {
  const texto = clave.replace(/_/g, " ");
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

async function subirImportacion(
  tipo: string,
  archivos: Record<string, File>,
  sede: string,
): Promise<Ejecucion> {
  const datos = new FormData();
  for (const [campo, archivo] of Object.entries(archivos)) datos.append(campo, archivo);
  const respuesta = await fetch(`/api/v1/migracion/${tipo}`, {
    method: "POST",
    body: datos,
    credentials: "same-origin",
    headers: { "X-Sede": sede },
  });
  const cuerpo = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(mensajeError(cuerpo, "No se pudo enviar la importación."));
  return cuerpo as Ejecucion;
}

export function PantallaMigracion() {
  const { tienePermiso, sedeActiva, usuario } = useAuth();
  const permitidos = IMPORTADORES.filter((i) => tienePermiso(i.permiso));
  const [elegida, setElegida] = useState<Ejecucion | null>(null);
  const sede = sedeActiva ?? "";
  const nombreSede = usuario?.sedes.find((s) => s.codigo === sede)?.nombre ?? sede;

  const { data: ejecuciones = [] } = useQuery({
    queryKey: ["migracion", "ejecuciones", sede],
    enabled: permitidos.length > 0 && !!sede,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/migracion/ejecuciones", {
        params: { header: { "X-Sede": sede }, query: { limite: 50 } },
      });
      return exigir(data, error, "No se pudieron cargar las ejecuciones.");
    },
    // Mientras haya algo en cola o procesando, se consulta cada 3 s.
    refetchInterval: (consulta) =>
      (consulta.state.data ?? []).some((e) => e.estado === "pendiente" || e.estado === "procesando")
        ? 3000
        : false,
  });

  if (permitidos.length === 0) {
    return <SinPermiso mensaje="No tiene permiso para importar datos." />;
  }

  const actual = elegida ? (ejecuciones.find((e) => e.id === elegida.id) ?? elegida) : null;

  return (
    <Stack gap="md">
      <EncabezadoPagina
        seccion="Administración"
        titulo="Migración de datos"
        descripcion={
          <>
            Importación de las exportaciones de SAPEF para la sede <b>{nombreSede}</b>. Cada archivo se procesa en
            segundo plano y se puede repetir sin duplicar datos. Siga el orden numerado.
          </>
        }
      />
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {permitidos.map((imp) => (
          <TarjetaImportador key={imp.tipo} importador={imp} sede={sede} />
        ))}
      </SimpleGrid>

      <Title order={2} fz="md" mt="sm">
        Ejecuciones
      </Title>
      {ejecuciones.length === 0 ? (
        <EstadoVacio titulo="Aún no hay importaciones en esta sede" />
      ) : (
        <MarcoTabla>
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>#</Table.Th>
              <Table.Th>Tipo</Table.Th>
              <Table.Th>Archivos</Table.Th>
              <Table.Th>Estado</Table.Th>
              <Table.Th>Leídas</Table.Th>
              <Table.Th>Creadas</Table.Th>
              <Table.Th>Errores</Table.Th>
              <Table.Th>Recibida</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {ejecuciones.map((e) => (
              <Table.Tr key={e.id} onClick={() => setElegida(e)} style={{ cursor: "pointer" }}>
                <Table.Td>
                  <Codigo>{e.id}</Codigo>
                </Table.Td>
                <Table.Td>{e.tipo}</Table.Td>
                <Table.Td>{e.archivos.join(", ")}</Table.Td>
                <Table.Td>
                  <EtiquetaEstado color={COLOR_ESTADO[e.estado] ?? "gray"} nombre={TEXTO_ESTADO[e.estado] ?? e.estado} />
                </Table.Td>
                <Table.Td>{e.conciliacion.leidas ?? "—"}</Table.Td>
                <Table.Td>{e.conciliacion.creadas ?? "—"}</Table.Td>
                <Table.Td>{e.conciliacion.errores ?? "—"}</Table.Td>
                <Table.Td>{new Date(e.creado_en).toLocaleString("es-CO")}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        </MarcoTabla>
      )}

      <Drawer
        opened={actual !== null}
        onClose={() => setElegida(null)}
        position="right"
        size="xl"
        title={actual ? `Ejecución #${actual.id} · ${actual.tipo}` : ""}
      >
        {actual && <InformeEjecucion ejecucion={actual} />}
      </Drawer>
    </Stack>
  );
}

function TarjetaImportador({ importador, sede }: { importador: Importador; sede: string }) {
  const queryClient = useQueryClient();
  const [archivos, setArchivos] = useState<Record<string, File | null>>({});
  const [aviso, setAviso] = useState<{ color: string; texto: string } | null>(null);
  const elegidos = Object.fromEntries(
    Object.entries(archivos).filter((par): par is [string, File] => par[1] !== null),
  );

  const enviar = useMutation({
    mutationFn: () => subirImportacion(importador.tipo, elegidos, sede),
    onSuccess: (ej) => {
      setAviso({ color: "green", texto: `Importación #${ej.id} en cola. Su avance aparece abajo.` });
      setArchivos({});
      void queryClient.invalidateQueries({ queryKey: ["migracion", "ejecuciones", sede] });
    },
    onError: (e) => setAviso({ color: "red", texto: mensajeError(e, "No se pudo enviar.") }),
  });

  return (
    <Card withBorder>
      <Stack gap="xs">
        <Text fw={600}>{importador.titulo}</Text>
        <Text size="sm" c="dimmed">
          {importador.descripcion}
        </Text>
        {importador.campos.map(({ campo, etiqueta }) => (
          <FileInput
            key={campo}
            label={etiqueta}
            placeholder="Elegir archivo"
            accept=".csv,.xlsx,.txt"
            clearable
            value={archivos[campo] ?? null}
            onChange={(f) => setArchivos((a) => ({ ...a, [campo]: f }))}
          />
        ))}
        {aviso && (
          <Alert color={aviso.color} withCloseButton onClose={() => setAviso(null)}>
            {aviso.texto}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button
            onClick={() => enviar.mutate()}
            loading={enviar.isPending}
            disabled={Object.keys(elegidos).length === 0}
          >
            Importar
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}

function InformeEjecucion({ ejecucion }: { ejecucion: Ejecucion }) {
  const advertencias = ejecucion.advertencias ?? [];
  return (
    <Stack gap="md">
      <Group>
        <Badge color={COLOR_ESTADO[ejecucion.estado] ?? "gray"} size="lg">
          {TEXTO_ESTADO[ejecucion.estado] ?? ejecucion.estado}
        </Badge>
        {ejecucion.procesado_en && (
          <Text size="sm" c="dimmed">
            Terminó {new Date(ejecucion.procesado_en).toLocaleString("es-CO")}
          </Text>
        )}
      </Group>

      <Title order={4}>Conciliación</Title>
      <Table>
        <Table.Tbody>
          {Object.entries(ejecucion.conciliacion).map(([clave, valor]) => (
            <Table.Tr key={clave}>
              <Table.Td>{etiquetaConciliacion(clave)}</Table.Td>
              <Table.Td ta="right">{valor.toLocaleString("es-CO")}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>

      <ListaDetalles titulo="Errores (no se importaron)" filas={ejecucion.errores} color="red" />
      <ListaDetalles titulo="Advertencias (se importaron)" filas={advertencias} color="yellow" />
    </Stack>
  );
}

function ListaDetalles({
  titulo,
  filas,
  color,
}: {
  titulo: string;
  filas: Record<string, unknown>[];
  color: string;
}) {
  if (filas.length === 0) return null;
  return (
    <Stack gap={4}>
      <Title order={4} c={color}>
        {titulo} · {filas.length.toLocaleString("es-CO")}
      </Title>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Fila</Table.Th>
            <Table.Th>Referencia</Table.Th>
            <Table.Th>Detalle</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {filas.map((f, i) => {
            const { fila, detalle, ...resto } = f;
            const referencia = Object.values(resto)
              .filter((v) => v !== null && v !== undefined && v !== "")
              .join(" · ");
            return (
              <Table.Tr key={i}>
                <Table.Td>{fila === null || fila === undefined ? "—" : String(fila)}</Table.Td>
                <Table.Td>{referencia || "—"}</Table.Td>
                <Table.Td>{String(detalle ?? "")}</Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
