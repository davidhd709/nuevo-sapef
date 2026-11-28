// Marco de la web: menú lateral oscuro agrupado por área de trabajo, cabecera con la sede activa y
// el menú del usuario. Los grupos y opciones se muestran según los permisos del usuario (la
// autorización real la hace el servidor).
import {
  AppShell,
  Avatar,
  Burger,
  Group,
  Menu,
  ScrollArea,
  Select,
  Stack,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconBuildingWarehouse,
  IconBulb,
  IconChartHistogram,
  IconChevronDown,
  IconDatabaseImport,
  IconHome2,
  IconLogout,
  IconMap2,
  IconMapPin,
  IconMessageExclamation,
  IconReceipt2,
  IconSettings,
  IconShieldLock,
  IconTool,
  type Icon,
} from "@tabler/icons-react";
import type { ReactNode } from "react";

import { useAuth } from "./auth/AuthContext";
import { MarcaSapef } from "./comun/Marca";
import { IMPORTADORES } from "./migracion/PantallaMigracion";

type Opcion = { etiqueta: string; ruta: string; activaSi: string; icono: Icon; visible: boolean };
type Grupo = { titulo?: string; opciones: Opcion[] };

function iniciales(nombre: string): string {
  const partes = nombre.trim().split(/\s+/).filter(Boolean);
  return ((partes[0]?.[0] ?? "") + (partes[1]?.[0] ?? "")).toUpperCase() || "?";
}

export function Marco({
  ruta,
  navegar,
  alSalir,
  children,
}: {
  ruta: string;
  navegar: (destino: string) => void;
  alSalir: () => void;
  children: ReactNode;
}) {
  const { usuario, sedeActiva, cambiarSede, tienePermiso } = useAuth();
  const [abierto, { toggle, close }] = useDisclosure(false);
  if (!usuario) return null;

  const grupos: Grupo[] = [
    { opciones: [{ etiqueta: "Inicio", ruta: "/", activaSi: "=/", icono: IconHome2, visible: true }] },
    {
      titulo: "Operación",
      opciones: [
        { etiqueta: "Mapa", ruta: "/mapa", activaSi: "/mapa", icono: IconMap2, visible: tienePermiso("activos.mapa.ver") },
        {
          etiqueta: "Luminarias",
          ruta: "/activos/luminarias",
          activaSi: "/activos",
          icono: IconBulb,
          visible: tienePermiso("activos.luminaria.ver"),
        },
        {
          etiqueta: "Atención (PQRS)",
          ruta: "/atencion/pendientes",
          activaSi: "/atencion",
          icono: IconMessageExclamation,
          visible: tienePermiso("atencion.pqrs.ver"),
        },
        {
          etiqueta: "Órdenes de trabajo",
          ruta: "/trabajos/ordenes",
          activaSi: "/trabajos",
          icono: IconTool,
          visible: tienePermiso("trabajos.orden.ver") || tienePermiso("trabajos.orden.ver_propias"),
        },
      ],
    },
    {
      titulo: "Almacén",
      opciones: [
        {
          etiqueta: "Inventario",
          ruta: "/inventario",
          activaSi: "/inventario",
          icono: IconBuildingWarehouse,
          visible: tienePermiso("inventario.material.ver") || tienePermiso("inventario.bodega.ver"),
        },
      ],
    },
    {
      titulo: "Comercial",
      opciones: [
        {
          etiqueta: "Análisis comercial",
          ruta: "/comercial",
          activaSi: "/comercial",
          icono: IconReceipt2,
          visible: tienePermiso("comercial.analisis.ver") || tienePermiso("comercial.cargue.crear"),
        },
      ],
    },
    {
      titulo: "Gestión",
      opciones: [
        {
          etiqueta: "Tablero gerencial",
          ruta: "/tablero",
          activaSi: "/tablero",
          icono: IconChartHistogram,
          visible: tienePermiso("tablero.ver"),
        },
      ],
    },
    {
      titulo: "Administración",
      opciones: [
        { etiqueta: "Configuración", ruta: "/configuracion", activaSi: "/configuracion", icono: IconSettings, visible: true },
        {
          etiqueta: "Usuarios y roles",
          ruta: "/seguridad/usuarios",
          activaSi: "/seguridad",
          icono: IconShieldLock,
          visible: tienePermiso("seguridad.usuario.ver"),
        },
        {
          etiqueta: "Migración de datos",
          ruta: "/migracion",
          activaSi: "/migracion",
          icono: IconDatabaseImport,
          visible: IMPORTADORES.some((i) => tienePermiso(i.permiso)),
        },
      ],
    },
  ];

  const esActiva = (o: Opcion) => (o.activaSi.startsWith("=") ? ruta === o.activaSi.slice(1) : ruta.startsWith(o.activaSi));
  const sede = usuario.sedes.find((s) => s.codigo === sedeActiva);

  return (
    <AppShell
      layout="alt"
      header={{ height: 52 }}
      navbar={{ width: 236, breakpoint: "sm", collapsed: { mobile: !abierto } }}
      padding="lg"
      classNames={{ navbar: "sapef-lateral", header: "sapef-cabecera" }}
    >
      <AppShell.Header>
        <Group h="100%" px="lg" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={abierto} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Abrir el menú" />
            {usuario.sedes.length > 1 ? (
              <Select
                aria-label="Sede"
                data-testid="sede-selector"
                data={usuario.sedes.map((s) => ({ value: s.codigo, label: s.nombre }))}
                value={sedeActiva}
                onChange={(v) => v && cambiarSede(v)}
                leftSection={<IconMapPin size={15} stroke={1.6} />}
                allowDeselect={false}
                variant="filled"
                size="xs"
                w={190}
              />
            ) : (
              <Group gap={6} c="dimmed" data-testid="sede-selector">
                <IconMapPin size={15} stroke={1.6} />
                <Text size="sm">{sede?.nombre ?? "Sin sede"}</Text>
              </Group>
            )}
          </Group>

          <Menu position="bottom-end" width={220}>
            <Menu.Target>
              <UnstyledButton aria-label="Menú del usuario">
                <Group gap={8} wrap="nowrap">
                  <Avatar size={28} radius="sm" color="gray" variant="filled">
                    {iniciales(usuario.nombre_completo || usuario.nombre_usuario)}
                  </Avatar>
                  <div style={{ lineHeight: 1.15 }}>
                    <Text size="sm" fw={500} visibleFrom="xs">
                      {usuario.nombre_completo || usuario.nombre_usuario}
                    </Text>
                    <Text fz={11} c="dimmed" visibleFrom="xs">
                      {usuario.rol.nombre}
                    </Text>
                  </div>
                  <IconChevronDown size={14} stroke={1.6} />
                </Group>
              </UnstyledButton>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Label>{usuario.nombre_usuario}</Menu.Label>
              <Menu.Item leftSection={<IconLogout size={15} />} onClick={alSalir}>
                Cerrar sesión
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar>
        <Group h={52} px={16} style={{ borderBottom: "1px solid var(--sapef-lateral-borde)", flex: "none" }}>
          <MarcaSapef tinta="#f2f1ec" tamano={20} />
        </Group>
        <AppShell.Section grow component={ScrollArea} px={8} py={6}>
          <nav aria-label="Menú principal">
            {grupos.map((g, i) => {
              const visibles = g.opciones.filter((o) => o.visible);
              if (visibles.length === 0) return null;
              return (
                <div key={g.titulo ?? `g${i}`}>
                  {g.titulo && <div className="sapef-lateral-grupo">{g.titulo}</div>}
                  <Stack gap={1}>
                    {visibles.map((o) => {
                      const Icono = o.icono;
                      const activa = esActiva(o);
                      return (
                        <button
                          key={o.ruta}
                          type="button"
                          className="sapef-lateral-enlace"
                          data-activo={activa || undefined}
                          aria-current={activa ? "page" : undefined}
                          onClick={() => {
                            navegar(o.ruta);
                            close();
                          }}
                        >
                          <Icono size={17} stroke={1.6} />
                          {o.etiqueta}
                        </button>
                      );
                    })}
                  </Stack>
                </div>
              );
            })}
          </nav>
        </AppShell.Section>
        <AppShell.Section px={16} py={10} style={{ borderTop: "1px solid var(--sapef-lateral-borde)" }}>
          <Text fz={10} c="#7b7a74" style={{ letterSpacing: "0.04em" }}>
            {sede ? `Sede ${sede.nombre}` : "Sin sede asignada"}
          </Text>
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        <div style={{ maxWidth: 1480, margin: "0 auto" }}>{children}</div>
      </AppShell.Main>
    </AppShell>
  );
}
