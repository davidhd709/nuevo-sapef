// Envíos (HU-063): pendientes, última sincronización, conflictos y avisos push.
import { Alert, Badge, Button, Card, Group, Stack, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";

import { fechaHora, NOMBRE_TIPO, tamanoLegible } from "../comun/captura";
import { useConsulta, useEnLinea, useEstadoSincronizacion } from "../comun/ganchos";
import { db } from "../datos/db";
import { activarPush, desactivarPush, estadoPush, type EstadoPush } from "../datos/push";
import { descartarConflicto, reintentarConflicto, sincronizar, type Sesion } from "../datos/sincronizacion";

const TEXTO_PUSH: Record<EstadoPush, string> = {
  no_soportado:
    "Este navegador no recibe avisos. En iPhone, instale la app en la pantalla de inicio (iOS 16.4+).",
  no_configurado: "Los avisos aún no están configurados en el servidor.",
  denegado: "Los avisos están bloqueados en los ajustes del teléfono.",
  activo: "Recibirá un aviso cuando le asignen una orden.",
  inactivo: "Active los avisos para enterarse de las órdenes nuevas.",
};

function AvisosPush() {
  const [estado, setEstado] = useState<EstadoPush | null>(null);
  const [ocupado, setOcupado] = useState(false);
  useEffect(() => {
    void estadoPush().then(setEstado);
  }, []);
  if (!estado) return null;
  const cambiar = async () => {
    setOcupado(true);
    try {
      if (estado === "activo") {
        await desactivarPush();
        setEstado("inactivo");
      } else {
        setEstado(await activarPush());
      }
    } catch {
      setEstado(await estadoPush());
    } finally {
      setOcupado(false);
    }
  };
  return (
    <Card withBorder padding="sm">
      <Group justify="space-between" wrap="nowrap">
        <Text size="sm">{TEXTO_PUSH[estado]}</Text>
        {(estado === "activo" || estado === "inactivo") && (
          <Button size="xs" variant="light" loading={ocupado} onClick={() => void cambiar()}>
            {estado === "activo" ? "Desactivar" : "Activar avisos"}
          </Button>
        )}
      </Group>
    </Card>
  );
}

export function PantallaEnvios({ sesion }: { sesion: Sesion }) {
  const enLinea = useEnLinea();
  const sync = useEstadoSincronizacion();
  const pendientes = useConsulta(
    () => db.outbox.where("usuarioId").equals(sesion.usuarioId).filter((p) => p.sede === sesion.sede).sortBy("creadaEn"),
    [sesion.usuarioId, sesion.sede],
    [],
  );
  const conflictos = useConsulta(
    () => db.conflictos.toArray().then((filas) => filas.filter((c) => c.usuarioId === sesion.usuarioId && c.sede === sesion.sede)),
    [sesion.usuarioId, sesion.sede],
    [],
  );
  const archivos = useConsulta(() => db.archivos.toArray(), [], []);
  const operacionesVisibles = new Set([...pendientes, ...conflictos].map((op) => op.uuid));
  const porSubir = archivos.filter((a) => operacionesVisibles.has(a.opUuid) && !a.archivoId);
  const bytes = porSubir.reduce((t, a) => t + a.datos.size, 0);

  return (
    <Stack gap="sm">
      <Title order={4}>Envíos</Title>
      <Card withBorder padding="sm">
        <Group justify="space-between">
          <Badge color={enLinea ? "teal" : "gray"}>{enLinea ? "Con señal" : "Sin señal"}</Badge>
          <Button size="xs" onClick={() => void sincronizar()} loading={sync.enCurso} disabled={!enLinea}>
            Sincronizar ahora
          </Button>
        </Group>
        <Text size="sm" mt="xs">
          Trabajos por enviar: <b>{pendientes.length}</b>
          {porSubir.length > 0 && ` · ${porSubir.length} archivo(s), ${tamanoLegible(bytes)}`}
        </Text>
        <Text size="xs" c="dimmed">
          Última sincronización: {fechaHora(sync.ultimaSincronizacion)}
        </Text>
        {sync.ultimoError && (
          <Text size="xs" c="orange">
            {sync.ultimoError}
          </Text>
        )}
      </Card>

      {pendientes.map((p) => (
        <Card key={p.uuid} withBorder padding="xs">
          <Text size="sm">
            N.º {p.ordenNumero} · {NOMBRE_TIPO[p.tipo] ?? p.tipo} · {fechaHora(p.creadaEn)}
          </Text>
          <Text size="xs" c="dimmed">
            {p.evidencias.length} evidencia(s) · intentos: {p.intentos}
          </Text>
        </Card>
      ))}

      {conflictos.length > 0 && (
        <>
          <Title order={5} mt="sm">
            Conflictos
          </Title>
          {conflictos.map((c) => (
            <Alert
              key={c.uuid}
              color={c.estado === "conflicto" ? "red" : "orange"}
              title={`Orden N.º ${c.ordenNumero} · ${c.estado === "conflicto" ? "Conflicto" : "Error"}`}
            >
              <Text size="sm">{c.motivo}</Text>
              <Text size="xs" c="dimmed">
                Registrado {fechaHora(c.creadaEn)} · respuesta {fechaHora(c.recibidoEn)}
              </Text>
              <Group gap="xs" mt="xs">
                {c.estado === "error" && (
                  <Button size="xs" variant="light" onClick={() => void reintentarConflicto(c.uuid)}>
                    Reintentar
                  </Button>
                )}
                <Button size="xs" variant="subtle" color="gray" onClick={() => void descartarConflicto(c.uuid)}>
                  Descartar
                </Button>
              </Group>
            </Alert>
          ))}
          <Text size="xs" c="dimmed">
            La oficina también ve estos conflictos. Si la orden fue anulada o reasignada, el trabajo
            no se aplicó; si fue un error de datos, puede volver a ejecutar la orden.
          </Text>
        </>
      )}

      <AvisosPush />
    </Stack>
  );
}
