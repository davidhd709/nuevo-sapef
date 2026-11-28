import {
  ActionIcon,
  Alert,
  Anchor,
  Button,
  Card,
  Drawer,
  Group,
  Modal,
  NumberInput,
  Pagination,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Timeline,
} from "@mantine/core";
import {
  IconChevronRight,
  IconDownload,
  IconExternalLink,
  IconPlus,
  IconSearch,
  IconX,
} from "@tabler/icons-react";
import { api, type components } from "@sapef/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";

import { useAuth } from "../auth/AuthContext";
import {
  Cargando,
  capitalizar,
  cifra,
  Codigo,
  EncabezadoPagina,
  EstadoVacio,
  EtiquetaEstado,
  MarcoTabla,
  SinPermiso,
} from "../comun/ui";
import { HojaDeVida } from "./HojaDeVida";
import { useMaestro } from "./maestros";
import { PanelLotes } from "./PanelLotes";

type LuminariaSalida = components["schemas"]["LuminariaSalida"];

export function PantallaLuminarias() {
  const { usuario, sedeActiva, tienePermiso } = useAuth();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [texto, setTexto] = useState("");
  const [estadoId, setEstadoId] = useState<string | null>(null);
  const [accionId, setAccionId] = useState<string | null>(null);
  const [misionId, setMisionId] = useState<string | null>(null);
  const [barrioId, setBarrioId] = useState<string | null>(null);
  const [tecnologiaId, setTecnologiaId] = useState<string | null>(null);
  const [seleccionada, setSeleccionada] = useState<LuminariaSalida | null>(null);
  const [modalNueva, setModalNueva] = useState(false);
  const [mensaje, setMensaje] = useState<string | null>(null);

  const [codigoNuevo, setCodigoNuevo] = useState("");
  const [barrioNuevo, setBarrioNuevo] = useState<string | null>(null);
  const [estadoNuevo, setEstadoNuevo] = useState<string | null>(null);
  const [techNuevo, setTechNuevo] = useState<string | null>(null);
  const [potNuevo, setPotNuevo] = useState<string | null>(null);
  const [latNueva, setLatNueva] = useState<number | string>(7.98);
  const [lngNueva, setLngNueva] = useState<number | string>(-75.41);
  const [latFicha, setLatFicha] = useState<number | string>("");
  const [lngFicha, setLngFicha] = useState<number | string>("");

  const headersSede = sedeActiva ? { "X-Sede": sedeActiva } : undefined;
  const puedeVer = tienePermiso("activos.luminaria.ver");
  const acciones = useMaestro("ACCION_OPERATIVA", puedeVer);
  const misiones = useMaestro("MISION_OBJETIVO", puedeVer);

  const { data: estados = [] } = useQuery({
    queryKey: ["estados-luminaria"],
    enabled: puedeVer,
    queryFn: async () =>
      (await api.GET("/api/v1/estados", { params: { query: { proceso: "luminaria" } } })).data ??
      [],
  });

  const { data: barrios = [] } = useQuery({
    queryKey: ["barrios", sedeActiva],
    enabled: puedeVer && Boolean(sedeActiva),
    queryFn: async () =>
      (await api.GET("/api/v1/barrios", { headers: headersSede })).data ?? [],
  });

  const { data: tecnologias = [] } = useQuery({
    queryKey: ["maestros", "LUMINARIA_TECNOLOGIA"],
    enabled: puedeVer,
    queryFn: async () =>
      (
        await api.GET("/api/v1/maestros/{clase}", {
          params: { path: { clase: "LUMINARIA_TECNOLOGIA" } },
        })
      ).data ?? [],
  });

  const { data: potencias = [] } = useQuery({
    queryKey: ["maestros", "LUMINARIA_POTENCIA"],
    enabled: puedeVer,
    queryFn: async () =>
      (
        await api.GET("/api/v1/maestros/{clase}", {
          params: { path: { clase: "LUMINARIA_POTENCIA" } },
        })
      ).data ?? [],
  });

  const { data: lista, isPending } = useQuery({
    queryKey: ["luminarias", sedeActiva, page, texto, estadoId, accionId, misionId, barrioId, tecnologiaId],
    enabled: puedeVer && Boolean(sedeActiva),
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/luminarias", {
        headers: headersSede,
        params: {
          query: {
            page,
            size: 20,
            texto: texto || undefined,
            estado_id: estadoId ? Number(estadoId) : undefined,
            accion_operativa_id: accionId ? Number(accionId) : undefined,
            mision_objetivo_id: misionId ? Number(misionId) : undefined,
            barrio_id: barrioId ? Number(barrioId) : undefined,
            tecnologia_id: tecnologiaId ? Number(tecnologiaId) : undefined,
          },
        },
      });
      return data;
    },
  });

  const { data: historial } = useQuery({
    queryKey: ["luminaria-historial", sedeActiva, seleccionada?.id],
    enabled: Boolean(seleccionada) && Boolean(sedeActiva),
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/luminarias/{luminaria_id}/historial", {
        headers: headersSede,
        params: { path: { luminaria_id: seleccionada!.id } },
      });
      return data;
    },
  });

  const crearMut = useMutation({
    mutationFn: async () => {
      if (!estadoNuevo) throw new Error("Seleccione un estado.");
      const { data, error } = await api.POST("/api/v1/luminarias", {
        headers: headersSede,
        body: {
          codigo: codigoNuevo,
          barrio_id: barrioNuevo ? Number(barrioNuevo) : null,
          estado_id: Number(estadoNuevo),
          tecnologia_id: techNuevo ? Number(techNuevo) : null,
          potencia_id: potNuevo ? Number(potNuevo) : null,
          latitud: typeof latNueva === "number" ? latNueva : null,
          longitud: typeof lngNueva === "number" ? lngNueva : null,
          es_rural: false,
          subnormal: false,
          tiene_medida: false,
          en_transito: false,
          validado: false,
        },
      });
      if (!data) {
        throw new Error(
          error && typeof error === "object" && "detail" in error && typeof error.detail === "string"
            ? error.detail
            : "No se pudo registrar la luminaria.",
        );
      }
      return data;
    },
    onSuccess: (creada) => {
      setModalNueva(false);
      setCodigoNuevo("");
      setMensaje(`Luminaria ${creada.codigo} registrada.`);
      void queryClient.invalidateQueries({ queryKey: ["luminarias"] });
    },
  });

  const exportarMut = useMutation({
    mutationFn: async () => {
      const { data } = await api.POST("/api/v1/luminarias/exportar", {
        headers: headersSede,
        body: { texto: texto || null },
      });
      return data;
    },
    onSuccess: (res) => {
      if (res) {
        setMensaje(`Exportación encolada en segundo plano (tarea #${res.tareaId}).`);
      }
    },
  });

  const moverMut = useMutation({
    mutationFn: async () => {
      if (!seleccionada || typeof latFicha !== "number" || typeof lngFicha !== "number") {
        throw new Error("Ingrese la latitud y la longitud verificadas.");
      }
      const { data, error } = await api.POST("/api/v1/luminarias/{luminaria_id}/ubicacion", {
        headers: headersSede,
        params: { path: { luminaria_id: seleccionada.id } },
        body: { latitud: latFicha, longitud: lngFicha, origen: "ficha_web" },
      });
      if (!data) {
        throw new Error(
          error && typeof error === "object" && "detail" in error && typeof error.detail === "string"
            ? error.detail
            : "No se pudo guardar la ubicación.",
        );
      }
      return data;
    },
    onSuccess: (actualizada) => {
      setSeleccionada(actualizada);
      setMensaje(`Ubicación de ${actualizada.codigo} actualizada y registrada en el historial.`);
      void queryClient.invalidateQueries({ queryKey: ["luminarias"] });
      void queryClient.invalidateQueries({ queryKey: ["luminaria-historial", sedeActiva, actualizada.id] });
    },
  });

  if (!puedeVer) {
    return <SinPermiso mensaje="No tiene permiso para consultar luminarias." />;
  }

  function manejarCrear(e: FormEvent) {
    e.preventDefault();
    crearMut.mutate();
  }

  function abrirFicha(lum: LuminariaSalida) {
    setSeleccionada(lum);
    setLatFicha(lum.latitud ?? "");
    setLngFicha(lum.longitud ?? "");
    moverMut.reset();
  }

  const conFiltro =
    (fn: (v: string | null) => void) =>
    (v: string | null) => {
      fn(v);
      setPage(1);
    };
  const filtrosActivos = [texto, estadoId, accionId, misionId, barrioId, tecnologiaId].filter(Boolean).length;
  function limpiarFiltros() {
    setTexto("");
    setEstadoId(null);
    setAccionId(null);
    setMisionId(null);
    setBarrioId(null);
    setTecnologiaId(null);
    setPage(1);
  }

  const totalPaginas = lista ? Math.max(1, Math.ceil(lista.total / lista.size)) : 1;
  const nombreSede = usuario?.sedes.find((s) => s.codigo === sedeActiva)?.nombre ?? sedeActiva;
  const items = lista?.items ?? [];

  return (
    <div>
      <EncabezadoPagina
        seccion="Operación"
        titulo="Luminarias"
        descripcion={`Puntos de luz de ${nombreSede}: estado, ubicación y hoja de vida.`}
        acciones={
          <>
            {tienePermiso("activos.luminaria.exportar") && (
              <Button
                variant="default"
                leftSection={<IconDownload size={16} />}
                onClick={() => exportarMut.mutate()}
                loading={exportarMut.isPending}
              >
                Exportar
              </Button>
            )}
            {tienePermiso("activos.luminaria.crear") && (
              <Button leftSection={<IconPlus size={16} />} onClick={() => setModalNueva(true)}>
                Nueva luminaria
              </Button>
            )}
          </>
        }
      />

      {mensaje && (
        <Alert color="green" withCloseButton onClose={() => setMensaje(null)} mb="md">
          {mensaje}
        </Alert>
      )}

      <Tabs defaultValue="luminarias">
        <Tabs.List mb="md">
          <Tabs.Tab value="luminarias">Luminarias</Tabs.Tab>
          <Tabs.Tab value="lotes">Lotes de marcación</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="luminarias">
          <Stack gap="sm">
            <Group gap="xs" wrap="wrap">
              <TextInput
                placeholder="Código, poste, barrio o marca"
                aria-label="Buscar luminarias"
                leftSection={<IconSearch size={15} />}
                value={texto}
                onChange={(e) => {
                  setTexto(e.currentTarget.value);
                  setPage(1);
                }}
                w={220}
              />
              <Select
                placeholder="Estado"
                aria-label="Estado"
                clearable
                data={estados.map((e) => ({ value: String(e.id), label: capitalizar(e.nombre) }))}
                value={estadoId}
                onChange={conFiltro(setEstadoId)}
                w={165}
              />
              <Select
                placeholder="Barrio"
                aria-label="Barrio"
                clearable
                searchable
                data={barrios.map((b) => ({ value: String(b.id), label: b.nombre }))}
                value={barrioId}
                onChange={conFiltro(setBarrioId)}
                w={170}
              />
              <Select
                placeholder="Tecnología"
                aria-label="Tecnología"
                clearable
                data={tecnologias.map((t) => ({ value: String(t.id), label: t.nombre }))}
                value={tecnologiaId}
                onChange={conFiltro(setTecnologiaId)}
                w={130}
              />
              <Select
                placeholder="Acción operativa"
                aria-label="Acción operativa"
                clearable
                data={acciones.opciones.map((o) => ({ ...o, label: capitalizar(o.label) }))}
                value={accionId}
                onChange={conFiltro(setAccionId)}
                w={170}
              />
              <Select
                placeholder="Misión u objetivo"
                aria-label="Misión u objetivo"
                clearable
                data={misiones.opciones.map((o) => ({ ...o, label: capitalizar(o.label) }))}
                value={misionId}
                onChange={conFiltro(setMisionId)}
                w={185}
              />
              {filtrosActivos > 0 && (
                <Button variant="subtle" color="gray" leftSection={<IconX size={14} />} onClick={limpiarFiltros}>
                  Limpiar filtros ({filtrosActivos})
                </Button>
              )}
            </Group>

            {!isPending && items.length === 0 ? (
              <EstadoVacio
                titulo={filtrosActivos ? "Ninguna luminaria coincide con los filtros" : "Aún no hay luminarias en esta sede"}
                descripcion={
                  filtrosActivos
                    ? "Pruebe con otro código o quite alguno de los filtros."
                    : "Regístrelas una a una, por lotes de marcación o con la migración desde SAPEF."
                }
                accion={
                  filtrosActivos ? (
                    <Button variant="default" size="xs" onClick={limpiarFiltros}>
                      Limpiar filtros
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <MarcoTabla>
                <Table>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Código</Table.Th>
                      <Table.Th>Estado</Table.Th>
                      <Table.Th>Barrio</Table.Th>
                      <Table.Th>Zona</Table.Th>
                      <Table.Th>Tecnología</Table.Th>
                      <Table.Th ta="right">Potencia</Table.Th>
                      <Table.Th>Acción operativa</Table.Th>
                      <Table.Th w={36} />
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {isPending && (
                      <Table.Tr>
                        <Table.Td colSpan={8}>
                          <Cargando texto="Cargando luminarias…" />
                        </Table.Td>
                      </Table.Tr>
                    )}
                    {items.map((lum) => (
                      <Table.Tr key={lum.id} onClick={() => abrirFicha(lum)} style={{ cursor: "pointer" }}>
                        <Table.Td>
                          <Codigo>{lum.codigo}</Codigo>
                        </Table.Td>
                        <Table.Td>
                          <EtiquetaEstado codigo={lum.estado_codigo} nombre={lum.estado_nombre ?? String(lum.estado_id)} />
                        </Table.Td>
                        <Table.Td>{lum.barrio_nombre ?? "—"}</Table.Td>
                        <Table.Td c="dimmed">{lum.zona_nombre ?? "—"}</Table.Td>
                        <Table.Td>{lum.tecnologia_nombre ?? "—"}</Table.Td>
                        <Table.Td ta="right">{lum.potencia_nombre ?? "—"}</Table.Td>
                        <Table.Td c={lum.accion_operativa_id ? undefined : "dimmed"}>
                          {capitalizar(acciones.nombre(lum.accion_operativa_id))}
                        </Table.Td>
                        <Table.Td>
                          <ActionIcon
                            variant="subtle"
                            color="gray"
                            size="sm"
                            aria-label={`Ver ficha de ${lum.codigo}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              abrirFicha(lum);
                            }}
                          >
                            <IconChevronRight size={16} />
                          </ActionIcon>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </MarcoTabla>
            )}

            <Group justify="space-between">
              <Text size="sm" c="dimmed" className="sapef-cifra">
                {cifra(lista?.total ?? 0)} luminarias
              </Text>
              {totalPaginas > 1 && <Pagination total={totalPaginas} value={page} onChange={setPage} />}
            </Group>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="lotes">
          <PanelLotes />
        </Tabs.Panel>
      </Tabs>

      <Drawer
        opened={Boolean(seleccionada)}
        onClose={() => setSeleccionada(null)}
        position="right"
        size={520}
        title={
          seleccionada && (
            <Group gap="sm">
              <Text ff="monospace" fw={600} fz="lg">
                {seleccionada.codigo}
              </Text>
              <EtiquetaEstado codigo={seleccionada.estado_codigo} nombre={seleccionada.estado_nombre ?? ""} />
            </Group>
          )
        }
      >
        {seleccionada && (
          <Stack gap="md">
            <SimpleGrid cols={2} spacing="sm" verticalSpacing="sm">
              <Dato etiqueta="Barrio" valor={seleccionada.barrio_nombre ?? "—"} />
              <Dato etiqueta="Zona" valor={seleccionada.zona_nombre ?? "—"} />
              <Dato
                etiqueta="Tecnología y potencia"
                valor={[seleccionada.tecnologia_nombre, seleccionada.potencia_nombre].filter(Boolean).join(" · ") || "—"}
              />
              <Dato etiqueta="Poste" valor={seleccionada.poste ?? "—"} />
              <Dato
                etiqueta="Coordenadas"
                valor={
                  seleccionada.latitud != null && seleccionada.longitud != null ? (
                    <Group gap={6}>
                      <Codigo>
                        {seleccionada.latitud.toFixed(6)}, {seleccionada.longitud.toFixed(6)}
                      </Codigo>
                      {seleccionada.google_maps_url && (
                        <Anchor href={seleccionada.google_maps_url} target="_blank" rel="noreferrer" size="xs">
                          <Group gap={2} component="span">
                            Google Maps <IconExternalLink size={12} />
                          </Group>
                        </Anchor>
                      )}
                    </Group>
                  ) : (
                    "Sin coordenadas"
                  )
                }
              />
            </SimpleGrid>

            <HojaDeVida
              luminaria={seleccionada}
              alGuardar={(actualizada) => {
                setSeleccionada(actualizada);
                setMensaje(`Hoja de vida de ${actualizada.codigo} actualizada.`);
              }}
            />

            {tienePermiso("activos.luminaria.mover") && (
              <Card>
                <Stack gap="xs">
                  <Text fw={600} size="sm">
                    Corregir ubicación
                  </Text>
                  <Text size="xs" c="dimmed">
                    Use coordenadas verificadas en campo. El cambio queda registrado en el historial.
                  </Text>
                  <Group grow>
                    <NumberInput label="Latitud" decimalScale={6} value={latFicha} onChange={setLatFicha} />
                    <NumberInput label="Longitud" decimalScale={6} value={lngFicha} onChange={setLngFicha} />
                  </Group>
                  {moverMut.error && <Alert color="red">{moverMut.error.message}</Alert>}
                  <Group justify="flex-end">
                    <Button
                      size="xs"
                      variant="default"
                      disabled={
                        typeof latFicha !== "number" ||
                        typeof lngFicha !== "number" ||
                        (latFicha === seleccionada.latitud && lngFicha === seleccionada.longitud)
                      }
                      loading={moverMut.isPending}
                      onClick={() => moverMut.mutate()}
                    >
                      Guardar ubicación
                    </Button>
                  </Group>
                </Stack>
              </Card>
            )}

            <div>
              <Text fz={11} fw={600} tt="uppercase" c="dimmed" style={{ letterSpacing: "0.08em" }} mb="xs">
                Historial ({historial?.eventos.length ?? 0})
              </Text>
              {(historial?.eventos.length ?? 0) === 0 ? (
                <Text size="sm" c="dimmed">
                  Sin eventos registrados.
                </Text>
              ) : (
                <Timeline bulletSize={10} lineWidth={1} color="gray">
                  {(historial?.eventos ?? []).map((ev) => (
                    <Timeline.Item key={ev.id} title={<Text size="sm">{capitalizar(ev.tipo.replaceAll("_", " "))}</Text>}>
                      <Text size="xs" c="dimmed" className="sapef-cifra">
                        {new Date(ev.fecha).toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" })}
                      </Text>
                    </Timeline.Item>
                  ))}
                </Timeline>
              )}
            </div>
          </Stack>
        )}
      </Drawer>

      <Modal opened={modalNueva} onClose={() => setModalNueva(false)} title="Nueva luminaria">
        <form onSubmit={manejarCrear}>
          <Stack gap="sm">
            {crearMut.error && <Alert color="red">{crearMut.error.message}</Alert>}
            <TextInput
              label="Código"
              required
              value={codigoNuevo}
              onChange={(e) => setCodigoNuevo(e.currentTarget.value)}
            />
            <Select
              label="Estado"
              required
              data={estados.map((e) => ({ value: String(e.id), label: `${e.codigo} · ${e.nombre}` }))}
              value={estadoNuevo}
              onChange={setEstadoNuevo}
            />
            <Select
              label="Barrio"
              searchable
              data={barrios.map((b) => ({ value: String(b.id), label: `${b.nombre} (${b.zona_nombre})` }))}
              value={barrioNuevo}
              onChange={setBarrioNuevo}
            />
            <Select
              label="Tecnología"
              data={tecnologias.map((t) => ({ value: String(t.id), label: t.nombre }))}
              value={techNuevo}
              onChange={setTechNuevo}
            />
            <Select
              label="Potencia"
              data={potencias.map((p) => ({ value: String(p.id), label: p.nombre }))}
              value={potNuevo}
              onChange={setPotNuevo}
            />
            <Group grow>
              <NumberInput label="Latitud" decimalScale={6} value={latNueva} onChange={setLatNueva} />
              <NumberInput label="Longitud" decimalScale={6} value={lngNueva} onChange={setLngNueva} />
            </Group>
            <Button type="submit" loading={crearMut.isPending}>
              Guardar
            </Button>
          </Stack>
        </form>
      </Modal>
    </div>
  );
}

function Dato({ etiqueta, valor }: { etiqueta: string; valor: ReactNode }) {
  return (
    <div>
      <Text fz={11} c="dimmed" mb={2}>
        {etiqueta}
      </Text>
      <Text size="sm" component="div">
        {valor}
      </Text>
    </div>
  );
}
