// Plantillas de correo de la sede activa (RF-014): asunto, cuerpo HTML y si están activas.
// La vista previa se dibuja en un iframe aislado (sandbox sin scripts).
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Modal,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { api, type components } from "@sapef/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { exigir } from "../comun/api";

type Plantilla = components["schemas"]["PlantillaCorreoSalida"];

export function PanelPlantillas() {
  const { sedeActiva, tienePermiso } = useAuth();
  const queryClient = useQueryClient();
  const headersSede = sedeActiva ? { "X-Sede": sedeActiva } : undefined;
  const puedeEditar = tienePermiso("configuracion.plantilla.editar");

  const [seleccionada, setSeleccionada] = useState<Plantilla | null>(null);
  const [asunto, setAsunto] = useState("");
  const [cuerpo, setCuerpo] = useState("");
  const [activa, setActiva] = useState(true);
  const [mensaje, setMensaje] = useState<string | null>(null);

  const { data: plantillas = [], isPending } = useQuery({
    queryKey: ["plantillas-correo", sedeActiva],
    enabled: Boolean(sedeActiva),
    queryFn: async () =>
      (await api.GET("/api/v1/plantillas-correo", { headers: headersSede })).data ?? [],
  });

  function abrir(p: Plantilla) {
    setSeleccionada(p);
    setAsunto(p.asunto);
    setCuerpo(p.cuerpo_html);
    setActiva(p.activa);
    guardarMut.reset();
  }

  const guardarMut = useMutation({
    mutationFn: async () => {
      if (!seleccionada) throw new Error("Seleccione una plantilla.");
      const { data, error } = await api.PATCH("/api/v1/plantillas-correo/{plantilla_id}", {
        headers: headersSede,
        params: { path: { plantilla_id: seleccionada.id } },
        body: { asunto: asunto.trim(), cuerpo_html: cuerpo, activa },
      });
      return exigir(data, error, "No se pudo guardar la plantilla.");
    },
    onSuccess: (p) => {
      setSeleccionada(null);
      setMensaje(`Plantilla «${p.nombre}» guardada.`);
      void queryClient.invalidateQueries({ queryKey: ["plantillas-correo", sedeActiva] });
    },
  });

  return (
    <Stack gap="sm">
      {mensaje && (
        <Alert color="green" withCloseButton onClose={() => setMensaje(null)}>
          {mensaje}
        </Alert>
      )}
      <Card withBorder p={0}>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Nombre</Table.Th>
              <Table.Th>Asunto</Table.Th>
              <Table.Th>Estado</Table.Th>
              <Table.Th>Última modificación</Table.Th>
              <Table.Th>Acciones</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {isPending && (
              <Table.Tr>
                <Table.Td colSpan={5}>Cargando plantillas...</Table.Td>
              </Table.Tr>
            )}
            {!isPending && plantillas.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={5}>La sede no tiene plantillas de correo.</Table.Td>
              </Table.Tr>
            )}
            {plantillas.map((p) => (
              <Table.Tr key={p.id}>
                <Table.Td>{p.nombre}</Table.Td>
                <Table.Td>{p.asunto}</Table.Td>
                <Table.Td>
                  <Badge color={p.activa ? "green" : "gray"}>{p.activa ? "Activa" : "Inactiva"}</Badge>
                </Table.Td>
                <Table.Td>{new Date(p.modificado_en).toLocaleString("es-CO")}</Table.Td>
                <Table.Td>
                  <Button size="xs" variant="light" onClick={() => abrir(p)}>
                    {puedeEditar ? "Modificar" : "Ver"}
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>

      <Modal
        opened={Boolean(seleccionada)}
        onClose={() => setSeleccionada(null)}
        title={`Plantilla · ${seleccionada?.nombre ?? ""}`}
        size="xl"
      >
        {seleccionada && (
          <Stack gap="sm">
            {guardarMut.error && <Alert color="red">{guardarMut.error.message}</Alert>}
            {seleccionada.variables.length > 0 && (
              <Group gap={6}>
                <Text size="xs" c="dimmed">
                  Variables disponibles:
                </Text>
                {seleccionada.variables.map((v) => (
                  <Badge key={v} variant="outline" tt="none">
                    {`{{${v}}}`}
                  </Badge>
                ))}
              </Group>
            )}
            <TextInput
              label="Asunto del correo"
              required
              readOnly={!puedeEditar}
              value={asunto}
              onChange={(e) => setAsunto(e.currentTarget.value)}
            />
            <Textarea
              label="Cuerpo (HTML)"
              rows={10}
              readOnly={!puedeEditar}
              value={cuerpo}
              onChange={(e) => setCuerpo(e.currentTarget.value)}
              styles={{ input: { fontFamily: "monospace", fontSize: 12 } }}
            />
            <Text size="sm" fw={600}>
              Vista previa
            </Text>
            <iframe
              title="Vista previa de la plantilla"
              sandbox=""
              srcDoc={cuerpo}
              style={{ width: "100%", height: 240, border: "1px solid #ddd", borderRadius: 4, background: "#fff" }}
            />
            <Checkbox
              label="Plantilla activa"
              disabled={!puedeEditar}
              checked={activa}
              onChange={(e) => setActiva(e.currentTarget.checked)}
            />
            <Group justify="flex-end" gap="xs">
              <Button variant="default" onClick={() => setSeleccionada(null)}>
                {puedeEditar ? "Cancelar" : "Cerrar"}
              </Button>
              {puedeEditar && (
                <Button
                  loading={guardarMut.isPending}
                  disabled={!asunto.trim() || !cuerpo.trim()}
                  onClick={() => guardarMut.mutate()}
                >
                  Guardar
                </Button>
              )}
            </Group>
          </Stack>
        )}
      </Modal>
    </Stack>
  );
}
