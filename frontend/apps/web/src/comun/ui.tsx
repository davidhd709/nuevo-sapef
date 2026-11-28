// Piezas comunes de las pantallas: encabezado, estados (vacío, error, sin permiso), marco de
// tabla, códigos y etiqueta de estado. Una sola forma de hacer cada cosa en toda la web.
import { Alert, Badge, Button, Group, Loader, Stack, Text, Title, type BadgeProps } from "@mantine/core";
import { IconAlertTriangle, IconLock, IconRefresh } from "@tabler/icons-react";
import type { ReactNode } from "react";

/** Encabezado de pantalla: sección (opcional), título, descripción corta y acciones a la derecha. */
export function EncabezadoPagina({
  seccion,
  titulo,
  descripcion,
  acciones,
}: {
  seccion?: string;
  titulo: ReactNode;
  descripcion?: ReactNode;
  acciones?: ReactNode;
}) {
  return (
    <Group justify="space-between" align="flex-end" wrap="wrap" gap="sm" mb="md">
      <div>
        {seccion && (
          <Text fz={11} fw={600} tt="uppercase" c="dimmed" style={{ letterSpacing: "0.08em" }} mb={4}>
            {seccion}
          </Text>
        )}
        <Title order={1}>{titulo}</Title>
        {descripcion && (
          <Text size="sm" c="dimmed" mt={4} maw={720}>
            {descripcion}
          </Text>
        )}
      </div>
      {acciones && (
        <Group gap="xs" wrap="wrap">
          {acciones}
        </Group>
      )}
    </Group>
  );
}

/** Sin registros, o sin resultados para los filtros. */
export function EstadoVacio({
  titulo,
  descripcion,
  accion,
}: {
  titulo: string;
  descripcion?: ReactNode;
  accion?: ReactNode;
}) {
  return (
    <div className="sapef-estado">
      <Text fw={600} size="sm">
        {titulo}
      </Text>
      {descripcion && (
        <Text size="sm" c="dimmed" mt={4}>
          {descripcion}
        </Text>
      )}
      {accion && <Group justify="center" mt="sm">{accion}</Group>}
    </div>
  );
}

/** Error al cargar datos, con reintento. */
export function EstadoError({ mensaje, reintentar }: { mensaje: string; reintentar?: () => void }) {
  return (
    <Alert color="red" icon={<IconAlertTriangle size={18} />} title="No se pudo cargar la información">
      <Stack gap="xs">
        <Text size="sm">{mensaje}</Text>
        {reintentar && (
          <Group>
            <Button size="xs" variant="default" leftSection={<IconRefresh size={14} />} onClick={reintentar}>
              Reintentar
            </Button>
          </Group>
        )}
      </Stack>
    </Alert>
  );
}

/** Pantalla o sección a la que el usuario no tiene acceso. */
export function SinPermiso({ mensaje }: { mensaje: string }) {
  return (
    <Alert color="gray" icon={<IconLock size={18} />} title="Sin acceso" data-testid="error-403">
      {mensaje}
    </Alert>
  );
}

export function Cargando({ texto = "Cargando…" }: { texto?: string }) {
  return (
    <Group gap="xs" c="dimmed" py="md">
      <Loader size="xs" color="gray" />
      <Text size="sm">{texto}</Text>
    </Group>
  );
}

/** Contenedor con borde para tablas (con desplazamiento horizontal en pantallas pequeñas). */
export function MarcoTabla({ children }: { children: ReactNode }) {
  return <div className="sapef-marco-tabla">{children}</div>;
}

/** Códigos (luminaria, NIC, consecutivos) en monoespaciada. */
export function Codigo({ children }: { children: ReactNode }) {
  return <span className="sapef-mono">{children}</span>;
}

// Color por estado (códigos de SAPEF, §10.2). El texto siempre acompaña al color.
const COLOR_ESTADO: Record<string, string> = {
  // Luminaria
  "121": "green", // activo en operación
  "122": "orange", // activo PQR (reportada)
  "124": "blue", // bodega buena
  "123": "gray", // bodega de baja
  "125": "cyan", // bodega en garantía
  "112": "gray", // desmontada
  "126": "dark", // disposición final
  "127": "gray", // otros
  "110": "gray", // sin identificar (comodín)
  // PQRS
  "301": "gray",
  "302": "blue",
  "305": "orange",
  "303": "green",
  "304": "red",
  // Orden de trabajo
  "201": "gray",
  "202": "blue",
  "205": "orange",
  "203": "green",
  "204": "red",
};
const COLOR_ESTADO_LUMINARIA = COLOR_ESTADO;

/** Estado de una luminaria: punto de color + nombre en minúscula inicial. */
export function EtiquetaEstado({
  codigo,
  nombre,
  color,
  ...props
}: { codigo?: string | null; nombre: ReactNode; color?: string } & Omit<BadgeProps, "children" | "color">) {
  const c = color ?? (codigo ? COLOR_ESTADO_LUMINARIA[codigo] : undefined) ?? "gray";
  return (
    <Badge variant="dot" color={c} radius="sm" fw={400} {...props}>
      {typeof nombre === "string" ? capitalizar(nombre) : nombre}
    </Badge>
  );
}

/** «ACTIVO EN OPERACIÓN» → «Activo en operación». Los catálogos de SAPEF vienen en mayúsculas. */
export function capitalizar(texto: string): string {
  const t = texto.trim();
  if (!t || t !== t.toUpperCase()) return t;
  const minus = t.toLocaleLowerCase("es-CO");
  return minus.charAt(0).toLocaleUpperCase("es-CO") + minus.slice(1);
}

/** Número con separador de miles colombiano. */
export function cifra(valor: number | null | undefined, decimales = 0): string {
  if (valor == null || Number.isNaN(valor)) return "—";
  return valor.toLocaleString("es-CO", { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
}
