// Lotes de marcación (RF-022): registra un rango de consecutivos que entra a bodega (estado 124)
// y muestra el histórico de lotes de la sede. Equivale a «Marcación luminaria» e «Histórico de
// consecutivos» de SAPEF, con las columnas de consecutivo inicial y final en su sitio.
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Group,
  Modal,
  NumberInput,
  Pagination,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { api } from "@sapef/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { useAuth } from "../auth/AuthContext";
import { exigir } from "../comun/api";
import { fechaCorta, useMaestro } from "./maestros";

export function PanelLotes() {
  const { sedeActiva, tienePermiso } = useAuth();
  const queryClient = useQueryClient();
  const headersSede = sedeActiva ? { "X-Sede": sedeActiva } : undefined;
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState(false);
  const [mensaje, setMensaje] = useState<string | null>(null);

  const [tecnologia, setTecnologia] = useState<string | null>(null);
  const [potencia, setPotencia] = useState<string | null>(null);
  const [marca, setMarca] = useState<string | null>(null);
  const [inicial, setInicial] = useState<number | string>("");
  const [cantidad, setCantidad] = useState<number | string>("");
  const [esRural, setEsRural] = useState(false);
  const [ordenCompra, setOrdenCompra] = useState("");
  const [fechaOrden, setFechaOrden] = useState("");
  const [entradaAlmacen, setEntradaAlmacen] = useState("");
  const [fechaEntrada, setFechaEntrada] = useState("");

  const tecnologias = useMaestro("LUMINARIA_TECNOLOGIA");
  const potencias = useMaestro("LUMINARIA_POTENCIA");
  const marcas = useMaestro("LUMINARIA_MARCA");

  const { data: lista, isPending } = useQuery({
    queryKey: ["lotes", sedeActiva, page],
    enabled: Boolean(sedeActiva),
    queryFn: async () =>
      (
        await api.GET("/api/v1/lotes", {
          headers: headersSede,
          params: { query: { page, size: 20 } },
        })
      ).data,
  });

  const final =
    typeof inicial === "number" && typeof cantidad === "number" && cantidad >= 1
      ? inicial + cantidad - 1
      : null;

  const crearMut = useMutation({
    mutationFn: async () => {
      if (!tecnologia || !potencia || typeof inicial !== "number" || final === null) {
        throw new Error("Complete tecnología, potencia, consecutivo inicial y cantidad.");
      }
      const { data, error } = await api.POST("/api/v1/lotes", {
        headers: headersSede,
        body: {
          consecutivo_inicial: inicial,
          consecutivo_final: final,
          cantidad: cantidad as number,
          tecnologia_id: Number(tecnologia),
          potencia_id: Number(potencia),
          marca_id: marca ? Number(marca) : null,
          es_rural: esRural,
          orden_compra: ordenCompra.trim() || null,
          fecha_orden_compra: fechaOrden || null,
          entrada_almacen: entradaAlmacen.trim() || null,
          fecha_entrada_almacen: fechaEntrada || null,
        },
      });
      return exigir(data, error, "No se pudo registrar el lote.");
    },
    onSuccess: (lote) => {
      setModal(false);
      setInicial("");
      setCantidad("");
      setOrdenCompra("");
      setFechaOrden("");
      setEntradaAlmacen("");
      setFechaEntrada("");
      setMensaje(
        `Lote registrado: ${lote.cantidad} luminarias (${lote.consecutivo_inicial} a ${lote.consecutivo_final}) en Bodega buena.`,
      );
      setPage(1);
      void queryClient.invalidateQueries({ queryKey: ["lotes"] });
      void queryClient.invalidateQueries({ queryKey: ["luminarias"] });
    },
  });

  function manejarCrear(e: FormEvent) {
    e.preventDefault();
    crearMut.mutate();
  }

  const totalPaginas = lista ? Math.max(1, Math.ceil(lista.total / lista.size)) : 1;

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          Cada lote crea sus luminarias en Bodega buena con los consecutivos del rango.
        </Text>
        {tienePermiso("activos.lote.crear") && (
          <Button onClick={() => setModal(true)}>Nuevo lote</Button>
        )}
      </Group>

      {mensaje && (
        <Alert color="green" withCloseButton onClose={() => setMensaje(null)}>
          {mensaje}
        </Alert>
      )}

      <Card withBorder p={0}>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Tecnología</Table.Th>
              <Table.Th>Potencia</Table.Th>
              <Table.Th>Marca</Table.Th>
              <Table.Th>Consecutivo inicial</Table.Th>
              <Table.Th>Consecutivo final</Table.Th>
              <Table.Th>Cantidad</Table.Th>
              <Table.Th>Zona</Table.Th>
              <Table.Th>Orden de compra</Table.Th>
              <Table.Th>Entrada de almacén</Table.Th>
              <Table.Th>Creación</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {isPending && (
              <Table.Tr>
                <Table.Td colSpan={10}>Cargando lotes...</Table.Td>
              </Table.Tr>
            )}
            {!isPending && (lista?.items.length ?? 0) === 0 && (
              <Table.Tr>
                <Table.Td colSpan={10}>No hay lotes registrados en la sede.</Table.Td>
              </Table.Tr>
            )}
            {(lista?.items ?? []).map((lote) => (
              <Table.Tr key={lote.id}>
                <Table.Td>{tecnologias.nombre(lote.tecnologia_id)}</Table.Td>
                <Table.Td>{potencias.nombre(lote.potencia_id)}</Table.Td>
                <Table.Td>{marcas.nombre(lote.marca_id)}</Table.Td>
                <Table.Td>{lote.consecutivo_inicial}</Table.Td>
                <Table.Td>{lote.consecutivo_final}</Table.Td>
                <Table.Td>{lote.cantidad}</Table.Td>
                <Table.Td>{lote.es_rural ? "Rural" : "Urbana"}</Table.Td>
                <Table.Td>
                  {lote.orden_compra ?? "—"}
                  {lote.fecha_orden_compra ? ` (${fechaCorta(lote.fecha_orden_compra)})` : ""}
                </Table.Td>
                <Table.Td>
                  {lote.entrada_almacen ?? "—"}
                  {lote.fecha_entrada_almacen ? ` (${fechaCorta(lote.fecha_entrada_almacen)})` : ""}
                </Table.Td>
                <Table.Td>{new Date(lote.creado_en).toLocaleDateString("es-CO")}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>

      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          Total: {lista?.total ?? 0} lotes
        </Text>
        <Pagination total={totalPaginas} value={page} onChange={setPage} />
      </Group>

      <Modal opened={modal} onClose={() => setModal(false)} title="Nuevo lote de marcación" size="lg">
        <form onSubmit={manejarCrear}>
          <Stack gap="sm">
            {crearMut.error && <Alert color="red">{crearMut.error.message}</Alert>}
            <Group grow>
              <Select label="Tecnología" required data={tecnologias.opciones} value={tecnologia} onChange={setTecnologia} />
              <Select label="Potencia" required searchable data={potencias.opciones} value={potencia} onChange={setPotencia} />
            </Group>
            <Select label="Marca" searchable clearable data={marcas.opciones} value={marca} onChange={setMarca} />
            <Group grow align="flex-end">
              <NumberInput label="Consecutivo inicial" required min={1} allowDecimal={false} value={inicial} onChange={setInicial} />
              <NumberInput label="Cantidad" required min={1} max={5000} allowDecimal={false} value={cantidad} onChange={setCantidad} />
              <TextInput label="Consecutivo final" readOnly value={final ?? ""} />
            </Group>
            <Checkbox label="Luminarias para zona rural" checked={esRural} onChange={(e) => setEsRural(e.currentTarget.checked)} />
            <Group grow>
              <TextInput label="Orden de compra" value={ordenCompra} onChange={(e) => setOrdenCompra(e.currentTarget.value)} />
              <TextInput label="Fecha de la orden" type="date" value={fechaOrden} onChange={(e) => setFechaOrden(e.currentTarget.value)} />
            </Group>
            <Group grow>
              <TextInput label="Entrada de almacén" value={entradaAlmacen} onChange={(e) => setEntradaAlmacen(e.currentTarget.value)} />
              <TextInput label="Fecha de entrada" type="date" value={fechaEntrada} onChange={(e) => setFechaEntrada(e.currentTarget.value)} />
            </Group>
            <Button type="submit" loading={crearMut.isPending}>
              Registrar lote
            </Button>
          </Stack>
        </form>
      </Modal>
    </Stack>
  );
}
