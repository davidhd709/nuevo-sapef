// Hoja de vida de la luminaria (RF-024), equivalente a la «Matriz de luminaria» de SAPEF:
// compra (por el lote o la marcación), acción operativa, misión, fechas y responsable.
import { Alert, Button, Card, Group, Select, SimpleGrid, Stack, Text, TextInput } from "@mantine/core";
import { api, type components } from "@sapef/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { exigir } from "../comun/api";
import { fechaCorta, useMaestro } from "./maestros";

type LuminariaSalida = components["schemas"]["LuminariaSalida"];

function Dato({ etiqueta, valor }: { etiqueta: string; valor: string }) {
  return (
    <div>
      <Text size="xs" c="dimmed">
        {etiqueta}
      </Text>
      <Text size="sm">{valor}</Text>
    </div>
  );
}

export function HojaDeVida({
  luminaria,
  alGuardar,
}: {
  luminaria: LuminariaSalida;
  alGuardar: (actualizada: LuminariaSalida) => void;
}) {
  const { sedeActiva, tienePermiso } = useAuth();
  const queryClient = useQueryClient();
  const headersSede = sedeActiva ? { "X-Sede": sedeActiva } : undefined;
  const acciones = useMaestro("ACCION_OPERATIVA");
  const misiones = useMaestro("MISION_OBJETIVO");
  const puedeEditar = tienePermiso("activos.luminaria.editar");
  const [editando, setEditando] = useState(false);

  const [codigoExterno, setCodigoExterno] = useState("");
  const [accion, setAccion] = useState<string | null>(null);
  const [mision, setMision] = useState<string | null>(null);
  const [fechaMision, setFechaMision] = useState("");
  const [fechaBaja, setFechaBaja] = useState("");
  const [fechaDisposicion, setFechaDisposicion] = useState("");
  const [responsable, setResponsable] = useState("");

  useEffect(() => {
    setEditando(false);
    setCodigoExterno(luminaria.codigo_externo ?? "");
    setAccion(luminaria.accion_operativa_id != null ? String(luminaria.accion_operativa_id) : null);
    setMision(luminaria.mision_objetivo_id != null ? String(luminaria.mision_objetivo_id) : null);
    setFechaMision(luminaria.fecha_mision ?? "");
    setFechaBaja(luminaria.fecha_baja ?? "");
    setFechaDisposicion(luminaria.fecha_disposicion_final ?? "");
    setResponsable(luminaria.responsable ?? "");
  }, [luminaria]);

  const { data: lote } = useQuery({
    queryKey: ["lote", sedeActiva, luminaria.lote_id],
    enabled: luminaria.lote_id != null && Boolean(sedeActiva),
    queryFn: async () =>
      (
        await api.GET("/api/v1/lotes/{lote_id}", {
          headers: headersSede,
          params: { path: { lote_id: luminaria.lote_id! } },
        })
      ).data,
  });

  const guardarMut = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.PATCH("/api/v1/luminarias/{luminaria_id}", {
        headers: headersSede,
        params: { path: { luminaria_id: luminaria.id } },
        body: {
          codigo_externo: codigoExterno.trim() || null,
          accion_operativa_id: accion ? Number(accion) : null,
          mision_objetivo_id: mision ? Number(mision) : null,
          fecha_mision: fechaMision || null,
          fecha_baja: fechaBaja || null,
          fecha_disposicion_final: fechaDisposicion || null,
          responsable: responsable.trim() || null,
        },
      });
      return exigir(data, error, "No se pudo guardar la hoja de vida.");
    },
    onSuccess: (actualizada) => {
      alGuardar(actualizada);
      void queryClient.invalidateQueries({ queryKey: ["luminarias"] });
    },
  });

  return (
    <Card withBorder data-testid="hoja-de-vida">
      <Stack gap="sm">
        <Group justify="space-between">
          <Text fw={600} size="sm">
            Hoja de vida
          </Text>
          {puedeEditar && !editando && (
            <Button size="xs" variant="light" onClick={() => setEditando(true)}>
              Modificar
            </Button>
          )}
        </Group>

        <Text size="xs" fw={600} c="dimmed" tt="uppercase">
          Compra
        </Text>
        {lote ? (
          <SimpleGrid cols={2} spacing="xs">
            <Dato etiqueta="Orden de compra" valor={lote.orden_compra ?? "—"} />
            <Dato etiqueta="Fecha de la orden" valor={fechaCorta(lote.fecha_orden_compra)} />
            <Dato etiqueta="Entrada de almacén" valor={lote.entrada_almacen ?? "—"} />
            <Dato etiqueta="Fecha de entrada" valor={fechaCorta(lote.fecha_entrada_almacen)} />
            <Dato
              etiqueta="Lote de marcación"
              valor={`${lote.consecutivo_inicial} a ${lote.consecutivo_final} (${lote.cantidad})`}
            />
          </SimpleGrid>
        ) : (
          <Text size="sm" c="dimmed">
            {luminaria.lote_id != null ? "Cargando lote..." : "No llegó por un lote de marcación."}
          </Text>
        )}

        <Text size="xs" fw={600} c="dimmed" tt="uppercase">
          Operación
        </Text>
        {!editando ? (
          <SimpleGrid cols={2} spacing="xs">
            <Dato etiqueta="Código externo" valor={luminaria.codigo_externo ?? "—"} />
            <Dato etiqueta="Marca" valor={luminaria.marca_nombre ?? "—"} />
            <Dato etiqueta="Acción operativa" valor={acciones.nombre(luminaria.accion_operativa_id)} />
            <Dato etiqueta="Misión u objetivo" valor={misiones.nombre(luminaria.mision_objetivo_id)} />
            <Dato etiqueta="Fecha de misión" valor={fechaCorta(luminaria.fecha_mision)} />
            <Dato etiqueta="Fecha de instalación" valor={fechaCorta(luminaria.fecha_instalacion)} />
            <Dato etiqueta="Fecha de baja" valor={fechaCorta(luminaria.fecha_baja)} />
            <Dato etiqueta="Disposición final" valor={fechaCorta(luminaria.fecha_disposicion_final)} />
            <Dato etiqueta="Responsable" valor={luminaria.responsable ?? "—"} />
          </SimpleGrid>
        ) : (
          <Stack gap="xs">
            {guardarMut.error && <Alert color="red">{guardarMut.error.message}</Alert>}
            <TextInput label="Código externo" value={codigoExterno} onChange={(e) => setCodigoExterno(e.currentTarget.value)} />
            <Group grow>
              <Select label="Acción operativa" clearable data={acciones.opciones} value={accion} onChange={setAccion} />
              <Select label="Misión u objetivo" clearable data={misiones.opciones} value={mision} onChange={setMision} />
            </Group>
            <Group grow>
              <TextInput label="Fecha de misión" type="date" value={fechaMision} onChange={(e) => setFechaMision(e.currentTarget.value)} />
              <TextInput label="Fecha de baja" type="date" value={fechaBaja} onChange={(e) => setFechaBaja(e.currentTarget.value)} />
            </Group>
            <Group grow>
              <TextInput label="Disposición final" type="date" value={fechaDisposicion} onChange={(e) => setFechaDisposicion(e.currentTarget.value)} />
              <TextInput label="Responsable" value={responsable} onChange={(e) => setResponsable(e.currentTarget.value)} />
            </Group>
            <Group justify="flex-end" gap="xs">
              <Button size="xs" variant="default" onClick={() => setEditando(false)}>
                Cancelar
              </Button>
              <Button size="xs" loading={guardarMut.isPending} onClick={() => guardarMut.mutate()}>
                Guardar
              </Button>
            </Group>
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
