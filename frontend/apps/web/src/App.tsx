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
import { useCallback, useEffect, useState } from "react";

import { PantallaLuminarias } from "./activos/PantallaLuminarias";
import { PantallaMapa } from "./activos/PantallaMapa";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { PantallaIngresar } from "./auth/PantallaIngresar";
import { PantallaConfiguracion } from "./configuracion/PantallaConfiguracion";
import { PantallaSeguridad } from "./seguridad/PantallaSeguridad";
import { EstadoSistema } from "./sistema/EstadoSistema";

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
