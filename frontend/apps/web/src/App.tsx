import { Loader, Stack } from "@mantine/core";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";

import { PantallaLuminarias } from "./activos/PantallaLuminarias";
import { PantallaAtencion } from "./atencion/PantallaAtencion";
import { PantallaComercial } from "./comercial/PantallaComercial";
import { PantallaMapa } from "./activos/PantallaMapa";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { PantallaCambiarClave } from "./auth/PantallaCambiarClave";
import { PantallaIngresar } from "./auth/PantallaIngresar";
import { PantallaConfiguracion } from "./configuracion/PantallaConfiguracion";
import { PantallaInventario } from "./inventario/PantallaInventario";
import { PantallaMigracion } from "./migracion/PantallaMigracion";
import { Marco } from "./Marco";
import { PantallaSeguridad } from "./seguridad/PantallaSeguridad";
import { PantallaInicio } from "./inicio/PantallaInicio";
import { PantallaOrdenes } from "./trabajos/PantallaOrdenes";

// ECharts pesa: el tablero se carga aparte, solo cuando se abre.
const PantallaTablero = lazy(() =>
  import("./tablero/PantallaTablero").then((m) => ({ default: m.PantallaTablero })),
);

function ContenidoApp() {
  const { usuario, cargando, salir } = useAuth();
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

  if (usuario.debe_cambiar_clave) {
    return <PantallaCambiarClave />;
  }

  let contenido = <PantallaInicio navegar={navegar} />;
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
  } else if (ruta.startsWith("/migracion")) {
    contenido = <PantallaMigracion />;
  }

  return (
    <Marco
      ruta={ruta}
      navegar={navegar}
      alSalir={async () => {
        await salir();
        navegar("/ingresar");
      }}
    >
      {contenido}
    </Marco>
  );
}

export function App() {
  return (
    <AuthProvider>
      <ContenidoApp />
    </AuthProvider>
  );
}
