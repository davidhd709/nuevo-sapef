import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  MultiSelect,
  PasswordInput,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { api } from "@sapef/api";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { useAuth } from "../auth/AuthContext";

export function PantallaSeguridad() {
  const { tienePermiso } = useAuth();
  const queryClient = useQueryClient();
  const [buscar, setBuscar] = useState("");
  const [modalUsuario, setModalUsuario] = useState(false);

  const [nombreUsuario, setNombreUsuario] = useState("");
  const [nombreCompleto, setNombreCompleto] = useState("");
  const [identificacion, setIdentificacion] = useState("");
  const [correo, setCorreo] = useState("");
  const [clave, setClave] = useState("");
  const [rolId, setRolId] = useState<string | null>(null);
  const [sedeIds, setSedeIds] = useState<string[]>([]);
  const [errorForm, setErrorForm] = useState<string | null>(null);

  const puedeVerUsuarios = tienePermiso("seguridad.usuario.ver");
  const puedeCrearUsuario = tienePermiso("seguridad.usuario.crear");
  const puedeVerRoles = tienePermiso("seguridad.rol.ver");
  const puedeVerAuditoria = tienePermiso("seguridad.auditoria.ver");

  const { data: usuariosData, isPending } = useQuery({
    queryKey: ["usuarios", buscar],
    enabled: puedeVerUsuarios,
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/usuarios", {
        params: { query: { page: 1, size: 50, buscar: buscar || undefined } },
      });
      return data;
    },
  });

  const { data: rolesData } = useQuery({
    queryKey: ["roles"],
    enabled: puedeVerRoles || puedeCrearUsuario,
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/roles", {
        params: { query: { page: 1, size: 50 } },
      });
      return data;
    },
  });

  const { data: sedesData } = useQuery({
    queryKey: ["sedes"],
    enabled: puedeVerUsuarios,
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/sedes");
      return data ?? [];
    },
  });

  const { data: auditoriaData } = useQuery({
    queryKey: ["auditoria"],
    enabled: puedeVerAuditoria,
    queryFn: async () => {
      const { data } = await api.GET("/api/v1/auditoria", {
        params: { query: { page: 1, size: 30, tipo: "cambios" } },
      });
      return data;
    },
  });

  const crearUsuarioMut = useMutation({
    mutationFn: async () => {
      if (!rolId || sedeIds.length === 0) {
        throw new Error("Debe seleccionar un rol y al menos una sede.");
      }
      const { data, error } = await api.POST("/api/v1/usuarios", {
        body: {
          nombre_usuario: nombreUsuario,
          nombre_completo: nombreCompleto,
          identificacion,
          correo,
          clave: clave || null,
          rol_id: Number(rolId),
          sede_ids: sedeIds.map(Number),
          debe_cambiar_clave: true,
          activo: true,
        },
      });
      if (!data) {
        const msg =
          error && typeof error === "object" && "detail" in error && typeof error.detail === "string"
            ? error.detail
            : "No se pudo crear el usuario.";
        throw new Error(msg);
      }
      return data;
    },
    onSuccess: () => {
      setModalUsuario(false);
      setNombreUsuario("");
      setNombreCompleto("");
      setIdentificacion("");
      setCorreo("");
      setClave("");
      setErrorForm(null);
      void queryClient.invalidateQueries({ queryKey: ["usuarios"] });
    },
    onError: (err) => {
      setErrorForm(err instanceof Error ? err.message : "Error al guardar usuario");
    },
  });

  if (!puedeVerUsuarios) {
    return (
      <Alert color="red" title="403 · Acceso denegado" data-testid="error-403">
        No tiene permiso suficiente (<code>seguridad.usuario.ver</code>) para administrar usuarios.
      </Alert>
    );
  }

  function manejarCrear(e: FormEvent) {
    e.preventDefault();
    setErrorForm(null);
    crearUsuarioMut.mutate();
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Seguridad y usuarios</Title>
        {puedeCrearUsuario && (
          <Button onClick={() => setModalUsuario(true)}>Nuevo usuario</Button>
        )}
      </Group>

      <Tabs defaultValue="usuarios">
        <Tabs.List>
          <Tabs.Tab value="usuarios">Usuarios</Tabs.Tab>
          {puedeVerRoles && <Tabs.Tab value="roles">Roles y permisos</Tabs.Tab>}
          {puedeVerAuditoria && <Tabs.Tab value="auditoria">Auditoría</Tabs.Tab>}
        </Tabs.List>

        <Tabs.Panel value="usuarios" pt="md">
          <Stack gap="sm">
            <TextInput
              placeholder="Buscar por usuario, nombre o identificación..."
              value={buscar}
              onChange={(e) => setBuscar(e.currentTarget.value)}
              maw={360}
            />
            <Card withBorder p={0}>
              <Table striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Usuario</Table.Th>
                    <Table.Th>Nombre</Table.Th>
                    <Table.Th>Rol</Table.Th>
                    <Table.Th>Sedes</Table.Th>
                    <Table.Th>Estado</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {isPending && (
                    <Table.Tr>
                      <Table.Td colSpan={5}>Cargando usuarios...</Table.Td>
                    </Table.Tr>
                  )}
                  {(usuariosData?.items ?? []).map((u) => (
                    <Table.Tr key={u.id}>
                      <Table.Td>{u.nombre_usuario}</Table.Td>
                      <Table.Td>{u.nombre_completo}</Table.Td>
                      <Table.Td>{u.rol.nombre}</Table.Td>
                      <Table.Td>{u.sedes.map((s) => s.nombre).join(", ")}</Table.Td>
                      <Table.Td>
                        <Badge color={u.activo ? "green" : "gray"}>
                          {u.activo ? "Activo" : "Inactivo"}
                        </Badge>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Card>
          </Stack>
        </Tabs.Panel>

        {puedeVerRoles && (
          <Tabs.Panel value="roles" pt="md">
            <Card withBorder p={0}>
              <Table striped>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Código</Table.Th>
                    <Table.Th>Nombre</Table.Th>
                    <Table.Th>Permisos</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {(rolesData?.items ?? []).map((r) => (
                    <Table.Tr key={r.id}>
                      <Table.Td>{r.codigo}</Table.Td>
                      <Table.Td>{r.nombre}</Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          {r.permisos.length} permisos asignados
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Card>
          </Tabs.Panel>
        )}

        {puedeVerAuditoria && (
          <Tabs.Panel value="auditoria" pt="md">
            <Card withBorder p={0}>
              <Table striped>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Instante</Table.Th>
                    <Table.Th>Acción</Table.Th>
                    <Table.Th>Entidad</Table.Th>
                    <Table.Th>ID</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {(auditoriaData?.items ?? []).map((a) => (
                    <Table.Tr key={a.id}>
                      <Table.Td>{new Date(a.instante).toLocaleString()}</Table.Td>
                      <Table.Td>{"accion" in a ? a.accion : a.recurso}</Table.Td>
                      <Table.Td>{"entidad" in a ? a.entidad : "consulta"}</Table.Td>
                      <Table.Td>{"entidad_id" in a ? a.entidad_id : "-"}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Card>
          </Tabs.Panel>
        )}
      </Tabs>

      <Modal
        opened={modalUsuario}
        onClose={() => setModalUsuario(false)}
        title="Crear usuario"
      >
        <form onSubmit={manejarCrear}>
          <Stack gap="sm">
            {errorForm && <Alert color="red">{errorForm}</Alert>}
            <TextInput
              label="Nombre de usuario"
              required
              value={nombreUsuario}
              onChange={(e) => setNombreUsuario(e.currentTarget.value)}
            />
            <TextInput
              label="Nombre completo"
              required
              value={nombreCompleto}
              onChange={(e) => setNombreCompleto(e.currentTarget.value)}
            />
            <TextInput
              label="Identificación"
              required
              value={identificacion}
              onChange={(e) => setIdentificacion(e.currentTarget.value)}
            />
            <TextInput
              label="Correo electrónico"
              type="email"
              required
              value={correo}
              onChange={(e) => setCorreo(e.currentTarget.value)}
            />
            <PasswordInput
              label="Contraseña inicial (opcional)"
              value={clave}
              onChange={(e) => setClave(e.currentTarget.value)}
            />
            <Select
              label="Rol"
              required
              data={(rolesData?.items ?? []).map((r) => ({
                value: String(r.id),
                label: r.nombre,
              }))}
              value={rolId}
              onChange={setRolId}
            />
            <MultiSelect
              label="Sedes"
              required
              data={(sedesData ?? []).map((s) => ({
                value: String(s.id),
                label: s.nombre,
              }))}
              value={sedeIds}
              onChange={setSedeIds}
            />
            <Button type="submit" loading={crearUsuarioMut.isPending}>
              Guardar usuario
            </Button>
          </Stack>
        </form>
      </Modal>
    </Stack>
  );
}
