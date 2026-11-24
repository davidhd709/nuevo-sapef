import {
  AppShell,
  Badge,
  Button,
  Group,
  Loader,
  NavLink,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";

import { PantallaLuminarias } from "./activos/PantallaLuminarias";
import { PantallaAtencion } from "./atencion/PantallaAtencion";
import { PantallaComercial } from "./comercial/PantallaComercial";
import { PantallaMapa } from "./activos/PantallaMapa";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { PantallaIngresar } from "./auth/PantallaIngresar";
import { PantallaConfiguracion } from "./configuracion/PantallaConfiguracion";
import { PantallaInventario } from "./inventario/PantallaInventario";
import { PantallaSeguridad } from "./seguridad/PantallaSeguridad";
import { EstadoSistema } from "./sistema/EstadoSistema";
import { PantallaOrdenes } from "./trabajos/PantallaOrdenes";

// ECharts pesa: el tablero se carga aparte, solo cuando se abre.
const PantallaTablero = lazy(() =>
  import("./tablero/PantallaTablero").then((m) => ({ default: m.PantallaTablero })),
);

function ContenidoApp() {
  const { usuario, cargando, sedeActiva, cambiarSede, salir, tienePermiso } = useAuth();
  const [ruta, setRuta] = useState<string>(() =>
    typeof window !== "undefined" ? window.location.pathname : "/",
  );

  const navegar = useCallback((destino: string) => {
    if (typeof window !== "undefined" && window.location.pathname !== destino) {
      window.history.pushState(null, "", destino);
    }
    setRuta(destino);
  }, []);

  useEffect(() => {
    const alCambiarHistorial = () => setRuta(window.location.pathname);
    window.addEventListener("popstate", alCambiarHistorial);
    return () => window.removeEventListener("popstate", alCambiarHistorial);
  }, []);

  useEffect(() => {
    if (!cargando && !usuario && ruta !== "/ingresar") {
      if (typeof window !== "undefined") {
        window.history.replaceState(null, "", "/ingresar");
      }
      setRuta("/ingresar");
    }
  }, [cargando, usuario, ruta]);

  if (cargando) {
    return (
      <Stack align="center" justify="center" mih="100vh">
        <Loader aria-label="Cargando sesión" />
      </Stack>
    );
  }

  if (!usuario || ruta === "/ingresar") {
    return (
      <PantallaIngresar
        onExito={() => {
          navegar("/");
        }}
      />
    );
  }

  let contenido = <EstadoSistema />;
  if (ruta.startsWith("/mapa")) {
    contenido = <PantallaMapa />;
  } else if (ruta.startsWith("/activos")) {
    contenido = <PantallaLuminarias />;
  } else if (ruta.startsWith("/atencion")) {
    contenido = <PantallaAtencion ruta={ruta} navegar={navegar} />;
  } else if (ruta.startsWith("/trabajos")) {
    contenido = <PantallaOrdenes />;
  } else if (ruta.startsWith("/inventario")) {
    contenido = <PantallaInventario />;
  } else if (ruta.startsWith("/comercial")) {
    contenido = <PantallaComercial />;
  } else if (ruta.startsWith("/tablero")) {
    contenido = (
      <Suspense fallback={<Loader aria-label="Cargando tablero" />}>
        <PantallaTablero />
      </Suspense>
    );
  } else if (ruta.startsWith("/seguridad")) {
    contenido = <PantallaSeguridad />;
  } else if (ruta.startsWith("/configuracion")) {
    contenido = <PantallaConfiguracion />;
  }

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 220, breakpoint: "sm" }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <Title order={3}>SAPEF</Title>
            <Text c="dimmed" size="sm">
              Alumbrado público
            </Text>
          </Group>
          <Group gap="sm">
            <Select
              aria-label="Sede"
              data-testid="sede-selector"
              data={usuario.sedes.map((s) => ({ value: s.codigo, label: s.nombre }))}
              value={sedeActiva}
              onChange={(v) => v && cambiarSede(v)}
              w={180}
            />
            <Badge variant="light">{usuario.nombre_usuario}</Badge>
            <Button
              size="xs"
              variant="subtle"
              color="gray"
              onClick={async () => {
                await salir();
                navegar("/ingresar");
              }}
            >
              Salir
            </Button>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        <Stack gap={4}>
          <NavLink
            label="Inicio"
            active={ruta === "/"}
            onClick={() => navegar("/")}
          />
          {tienePermiso("tablero.ver") && (
            <NavLink
              label="Tablero"
              active={ruta.startsWith("/tablero")}
              onClick={() => navegar("/tablero")}
            />
          )}
          {tienePermiso("activos.mapa.ver") && (
            <NavLink
              label="Mapa"
              active={ruta.startsWith("/mapa")}
              onClick={() => navegar("/mapa")}
            />
          )}
          {tienePermiso("activos.luminaria.ver") && (
            <NavLink
              label="Luminarias"
              active={ruta.startsWith("/activos")}
              onClick={() => navegar("/activos/luminarias")}
            />
          )}
          {tienePermiso("atencion.pqrs.ver") && (
            <NavLink
              label="Atención (PQRS)"
              active={ruta.startsWith("/atencion")}
              onClick={() => navegar("/atencion/pendientes")}
            />
          )}
          {(tienePermiso("trabajos.orden.ver") || tienePermiso("trabajos.orden.ver_propias")) && (
            <NavLink
              label="Órdenes de trabajo"
              active={ruta.startsWith("/trabajos")}
              onClick={() => navegar("/trabajos/ordenes")}
            />
          )}
          {(tienePermiso("inventario.material.ver") || tienePermiso("inventario.bodega.ver")) && (
            <NavLink
              label="Inventario"
              active={ruta.startsWith("/inventario")}
              onClick={() => navegar("/inventario")}
            />
          )}
          {(tienePermiso("comercial.analisis.ver") || tienePermiso("comercial.cargue.crear")) && (
            <NavLink
              label="Comercial"
              active={ruta.startsWith("/comercial")}
              onClick={() => navegar("/comercial")}
            />
          )}
          <NavLink
            label="Configuración"
            active={ruta.startsWith("/configuracion")}
            onClick={() => navegar("/configuracion")}
          />
          {tienePermiso("seguridad.usuario.ver") && (
            <NavLink
              label="Seguridad"
              active={ruta.startsWith("/seguridad")}
              onClick={() => navegar("/seguridad/usuarios")}
            />
          )}
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main>{contenido}</AppShell.Main>
    </AppShell>
  );
}

export function App() {
  return (
    <AuthProvider>
      <ContenidoApp />
    </AuthProvider>
  );
}
