// Armazón de la app de campo: sesión (también sin señal), pestañas y navegación a una orden.
import {
  Badge,
  Box,
  Button,
  Container,
  Group,
  Loader,
  NativeSelect,
  Stack,
  Tabs,
  Text,
} from "@mantine/core";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";

import { useConsulta, useEnLinea, useEstadoSincronizacion } from "./comun/ganchos";
import { api, mensajeError, SinConexion } from "./datos/api";
import { db, guardarMeta, leerMeta, limpiarDescargas, type PerfilActual } from "./datos/db";
import { fijarSesion, iniciarMotor, sincronizar, type Sesion } from "./datos/sincronizacion";
import { PantallaEnvios } from "./envios/PantallaEnvios";
import { PantallaBandeja } from "./ordenes/PantallaBandeja";
import { PantallaOrden } from "./ordenes/PantallaOrden";
import { GuiaInstalacion } from "./sesion/GuiaInstalacion";
import { PantallaCambiarClave, PantallaIngreso } from "./sesion/PantallaIngreso";

const PantallaMapa = lazy(() => import("./mapa/PantallaMapa"));

const PERMISO_CAMPO = "campo.app.usar";

type Fase =
  | { tipo: "cargando" }
  | { tipo: "ingreso"; aviso?: string }
  | { tipo: "cambiar_clave"; perfil: PerfilActual }
  | { tipo: "listo"; perfil: PerfilActual; sede: string };

function ordenDeUrl(url: string): number | null {
  const valor = new URL(url, window.location.origin).searchParams.get("orden");
  return valor && /^\d+$/.test(valor) ? Number(valor) : null;
}

function Cabecera({
  perfil,
  sede,
  onCambiarSede,
  onSalir,
}: {
  perfil: PerfilActual;
  sede: string;
  onCambiarSede: (codigo: string) => void;
  onSalir: () => void;
}) {
  const enLinea = useEnLinea();
  const sync = useEstadoSincronizacion();
  const pendientes = useConsulta(() => db.outbox.count(), [], 0);
  return (
    <Box
      px="md"
      py="xs"
      style={{
        borderBottom: "1px solid var(--mantine-color-default-border)",
        position: "sticky",
        top: 0,
        zIndex: 10,
        background: "var(--mantine-color-body)",
      }}
    >
      <Group justify="space-between" wrap="nowrap">
        <div>
          <Text fw={700} size="sm">
            SAPEF Campo
          </Text>
          <Text size="xs" c="dimmed">
            {perfil.nombre_completo}
          </Text>
        </div>
        <Group gap={6} wrap="nowrap">
          <Badge color={enLinea ? "teal" : "gray"} variant="dot">
            {enLinea ? (sync.enCurso ? "Enviando…" : "Con señal") : "Sin señal"}
          </Badge>
          {pendientes > 0 && (
            <Badge color="blue" title="Trabajos por enviar">
              {pendientes}
            </Badge>
          )}
        </Group>
      </Group>
      <Group justify="space-between" mt={4} wrap="nowrap">
        {perfil.sedes.length > 1 ? (
          <NativeSelect
            size="xs"
            aria-label="Sede"
            value={sede}
            data={perfil.sedes.map((s) => ({ value: s.codigo, label: s.nombre }))}
            onChange={(e) => onCambiarSede(e.currentTarget.value)}
          />
        ) : (
          <Text size="xs">{perfil.sedes.find((s) => s.codigo === sede)?.nombre ?? sede}</Text>
        )}
        {sync.sesionVencida ? (
          <Button size="compact-xs" color="orange" onClick={onSalir}>
            Sesión vencida: ingresar
          </Button>
        ) : (
          <Button size="compact-xs" variant="subtle" color="gray" onClick={onSalir}>
            Salir
          </Button>
        )}
      </Group>
    </Box>
  );
}

function Trabajo({
  perfil,
  sede,
  onCambiarSede,
  onSalir,
}: {
  perfil: PerfilActual;
  sede: string;
  onCambiarSede: (codigo: string) => void;
  onSalir: () => void;
}) {
  const [pestana, setPestana] = useState<string | null>("ordenes");
  const [ordenAbierta, setOrdenAbierta] = useState<number | null>(() =>
    ordenDeUrl(window.location.href),
  );
  const [mensaje, setMensaje] = useState<string | null>(null);
  const sesion: Sesion = { usuarioId: perfil.id, sede };

  useEffect(() => iniciarMotor(), [sede, perfil.id]);

  // Aviso push tocado con la app abierta: el Service Worker pide abrir la orden.
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const alMensaje = (e: MessageEvent) => {
      const datos = e.data as { type?: string; url?: string } | null;
      if (datos?.type === "ABRIR" && datos.url) {
        const id = ordenDeUrl(datos.url);
        if (id) setOrdenAbierta(id);
        void sincronizar();
      }
    };
    navigator.serviceWorker.addEventListener("message", alMensaje);
    return () => navigator.serviceWorker.removeEventListener("message", alMensaje);
  }, []);

  const abrir = (id: number | null) => {
    setOrdenAbierta(id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("orden", String(id));
    else url.searchParams.delete("orden");
    window.history.replaceState(null, "", url);
    window.scrollTo(0, 0);
  };

  return (
    <>
      <Cabecera perfil={perfil} sede={sede} onCambiarSede={onCambiarSede} onSalir={onSalir} />
      <Container size="sm" px="md" py="sm" pb={90}>
        {ordenAbierta ? (
          <PantallaOrden
            ordenId={ordenAbierta}
            sesion={sesion}
            onVolver={(m) => {
              setMensaje(m ?? null);
              setPestana("ordenes");
              abrir(null);
            }}
          />
        ) : (
          <Stack gap="sm">
            <GuiaInstalacion />
            <Tabs value={pestana} onChange={setPestana} keepMounted={false}>
              <Tabs.List grow>
                <Tabs.Tab value="ordenes">Órdenes</Tabs.Tab>
                <Tabs.Tab value="mapa">Mapa</Tabs.Tab>
                <Tabs.Tab value="envios">Envíos</Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="ordenes" pt="sm">
                <PantallaBandeja
                  onAbrir={(id) => abrir(id)}
                  mensaje={mensaje}
                  onCerrarMensaje={() => setMensaje(null)}
                />
              </Tabs.Panel>
              <Tabs.Panel value="mapa" pt="sm">
                <Suspense fallback={<Loader m="xl" />}>
                  <PantallaMapa />
                </Suspense>
              </Tabs.Panel>
              <Tabs.Panel value="envios" pt="sm">
                <PantallaEnvios />
              </Tabs.Panel>
            </Tabs>
          </Stack>
        )}
      </Container>
    </>
  );
}

export function App() {
  const [fase, setFase] = useState<Fase>({ tipo: "cargando" });

  const continuar = useCallback(async (perfil: PerfilActual) => {
    if (!perfil.permisos.includes(PERMISO_CAMPO)) {
      await api.POST("/api/v1/auth/salir").catch(() => undefined);
      setFase({ tipo: "ingreso", aviso: "Su usuario no tiene acceso a la app de campo." });
      return;
    }
    if (perfil.debe_cambiar_clave) {
      setFase({ tipo: "cambiar_clave", perfil });
      return;
    }
    const anterior = await leerMeta<PerfilActual>("perfil");
    if (anterior && anterior.id !== perfil.id) await limpiarDescargas();
    const guardada = await leerMeta<string>("sede");
    const sede =
      perfil.sedes.find((s) => s.codigo === guardada)?.codigo ?? perfil.sedes[0]?.codigo ?? null;
    if (!sede) {
      setFase({ tipo: "ingreso", aviso: "Su usuario no tiene sedes asignadas." });
      return;
    }
    await guardarMeta("perfil", perfil);
    await guardarMeta("sede", sede);
    // Pide al navegador que no borre la base local cuando falte espacio (clave en iPhone).
    void navigator.storage?.persist?.().catch(() => false);
    fijarSesion({ usuarioId: perfil.id, sede });
    setFase({ tipo: "listo", perfil, sede });
  }, []);

  useEffect(() => {
    void (async () => {
      const local = await leerMeta<PerfilActual>("perfil");
      try {
        const { data } = await api.GET("/api/v1/yo");
        if (data) await continuar(data);
        else setFase({ tipo: "ingreso" });
      } catch (e) {
        // Sin señal al abrir: se trabaja con lo guardado en el teléfono.
        if (e instanceof SinConexion && local) await continuar(local);
        else setFase({ tipo: "ingreso" });
      }
    })();
  }, [continuar]);

  const ingresar = async (usuario: string, clave: string) => {
    let respuesta;
    try {
      respuesta = await api.POST("/api/v1/auth/ingresar", {
        body: { usuario, clave, tipo_cliente: "pwa" },
      });
    } catch (e) {
      if (e instanceof SinConexion) throw new Error("Sin señal: no se puede ingresar ahora.");
      throw e;
    }
    if (!respuesta.data) throw new Error(mensajeError(respuesta.error, "Usuario o contraseña incorrectos."));
    await continuar(respuesta.data);
  };

  const salir = async () => {
    const pendientes = await db.outbox.count();
    if (
      pendientes > 0 &&
      !window.confirm(
        `Hay ${pendientes} trabajo(s) sin enviar. Quedarán guardados en el teléfono y se enviarán cuando vuelva a ingresar. ¿Salir?`,
      )
    ) {
      return;
    }
    await api.POST("/api/v1/auth/salir").catch(() => undefined);
    fijarSesion(null);
    setFase({ tipo: "ingreso" });
  };

  const cambiarSede = async (codigo: string) => {
    if (fase.tipo !== "listo") return;
    await guardarMeta("sede", codigo);
    await limpiarDescargas();
    await guardarMeta("perfil", fase.perfil);
    await guardarMeta("sede", codigo);
    fijarSesion({ usuarioId: fase.perfil.id, sede: codigo });
    setFase({ ...fase, sede: codigo });
  };

  if (fase.tipo === "cargando") return <Loader m="xl" />;
  if (fase.tipo === "ingreso") return <PantallaIngreso onIngresar={ingresar} aviso={fase.aviso} />;
  if (fase.tipo === "cambiar_clave") {
    return (
      <PantallaCambiarClave
        onSalir={() => void salir()}
        onCambiar={async (actual, nueva) => {
          const { error, response } = await api.POST("/api/v1/auth/cambiar-clave", {
            body: { clave_actual: actual, clave_nueva: nueva },
          });
          if (!response.ok) throw new Error(mensajeError(error, "No se pudo cambiar la contraseña."));
          const { data } = await api.GET("/api/v1/yo");
          if (data) await continuar(data);
          else setFase({ tipo: "ingreso", aviso: "Ingrese con su contraseña nueva." });
        }}
      />
    );
  }
  return (
    <Trabajo
      key={`${fase.perfil.id}-${fase.sede}`}
      perfil={fase.perfil}
      sede={fase.sede}
      onCambiarSede={(c) => void cambiarSede(c)}
      onSalir={() => void salir()}
    />
  );
}
