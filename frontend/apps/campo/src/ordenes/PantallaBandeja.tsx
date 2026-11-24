// Mis órdenes (HU-061): lo asignado al técnico, leído de la base local para que funcione sin
// señal. Las que ya se ejecutaron y esperan envío se muestran aparte.
import { Alert, Badge, Button, Card, Group, Stack, Text, UnstyledButton } from "@mantine/core";

import { fechaHora, NOMBRE_TIPO, PRIORIDAD } from "../comun/captura";
import { useConsulta } from "../comun/ganchos";
import { db, type OrdenCampo } from "../datos/db";

function TarjetaOrden({ orden, onAbrir }: { orden: OrdenCampo; onAbrir: () => void }) {
  const prioridad = PRIORIDAD[orden.prioridad] ?? { texto: String(orden.prioridad), color: "gray" };
  const principal = orden.luminarias[0];
  return (
    <UnstyledButton data-testid="orden-item" data-orden-id={orden.id} onClick={onAbrir}>
      <Card withBorder padding="sm" radius="md">
        <Group justify="space-between" wrap="nowrap" mb={4}>
          <Text fw={700}>
            N.º {orden.numero} · {NOMBRE_TIPO[orden.tipo] ?? orden.tipo}
          </Text>
          <Badge color={prioridad.color} variant="light">
            {prioridad.texto}
          </Badge>
        </Group>
        {principal && (
          <Text size="sm">
            {orden.luminarias.map((l) => l.codigo).join(", ")}
            {principal.barrio_nombre ? ` · ${principal.barrio_nombre}` : ""}
          </Text>
        )}
        {orden.observaciones && (
          <Text size="xs" c="dimmed" lineClamp={2}>
            {orden.observaciones}
          </Text>
        )}
        {orden.fecha_programada && (
          <Text size="xs" c="dimmed">
            Programada: {orden.fecha_programada}
          </Text>
        )}
      </Card>
    </UnstyledButton>
  );
}

export function PantallaBandeja({
  onAbrir,
  mensaje,
  onCerrarMensaje,
}: {
  onAbrir: (id: number) => void;
  mensaje: string | null;
  onCerrarMensaje: () => void;
}) {
  const ordenes = useConsulta(() => db.ordenes.toArray(), [], [] as OrdenCampo[]);
  const pendientes = useConsulta(() => db.outbox.toArray(), [], []);
  const conflictos = useConsulta(() => db.conflictos.toArray(), [], []);
  const avisos = useConsulta(() => db.avisos.toArray(), [], []);
  const ultimaDescarga = useConsulta(() => db.meta.get("ultimaDescarga"), [], undefined);

  const conTrabajoGuardado = new Set(pendientes.map((p) => p.ordenId));
  const porHacer = ordenes
    .filter((o) => !conTrabajoGuardado.has(o.id))
    .sort((a, b) => a.prioridad - b.prioridad || a.id - b.id);

  return (
    <Stack gap="sm">
      {mensaje && (
        <Alert color="teal" withCloseButton onClose={onCerrarMensaje}>
          {mensaje}
        </Alert>
      )}
      {conflictos.length > 0 && (
        <Alert color="red" title={`Conflicto en ${conflictos.length} trabajo(s)`} data-testid="conflictos">
          {conflictos.map((c) => (
            <Text key={c.uuid} size="sm">
              Orden N.º {c.ordenNumero}: {c.motivo}
            </Text>
          ))}
          <Text size="xs" mt={4}>
            Revíselos en «Envíos».
          </Text>
        </Alert>
      )}
      {avisos.map((a) => (
        <Alert
          key={a.id}
          color="yellow"
          withCloseButton
          onClose={() => a.id !== undefined && void db.avisos.delete(a.id)}
        >
          {a.texto}
        </Alert>
      ))}

      <Group justify="space-between">
        <Text fw={600}>Por ejecutar ({porHacer.length})</Text>
        <Text size="xs" c="dimmed">
          Actualizado: {fechaHora(ultimaDescarga?.valor as string | undefined)}
        </Text>
      </Group>
      {porHacer.length === 0 && (
        <Card withBorder padding="lg">
          <Text c="dimmed" ta="center">
            No tiene órdenes asignadas.
          </Text>
        </Card>
      )}
      {porHacer.map((o) => (
        <TarjetaOrden key={o.id} orden={o} onAbrir={() => onAbrir(o.id)} />
      ))}

      {pendientes.length > 0 && (
        <>
          <Text fw={600} mt="md">
            Guardadas, por enviar ({pendientes.length})
          </Text>
          {pendientes.map((p) => (
            <Card key={p.uuid} withBorder padding="sm" bg="var(--mantine-color-blue-light)">
              <Group justify="space-between" wrap="nowrap">
                <Text size="sm">
                  N.º {p.ordenNumero} · {NOMBRE_TIPO[p.tipo] ?? p.tipo}
                </Text>
                <Text size="xs" c="dimmed">
                  {fechaHora(p.creadaEn)}
                </Text>
              </Group>
              {p.ultimoError && (
                <Text size="xs" c="orange">
                  {p.ultimoError}
                </Text>
              )}
            </Card>
          ))}
        </>
      )}
      <Button variant="subtle" size="xs" onClick={() => void db.avisos.clear()} hidden={avisos.length === 0}>
        Ocultar avisos
      </Button>
    </Stack>
  );
}
