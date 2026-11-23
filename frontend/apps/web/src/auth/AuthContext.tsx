import { api, type components } from "@sapef/api";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type PerfilActual = components["schemas"]["PerfilActual"];

const CLAVE_SEDE_STORAGE = "sapef_sede_activa";

interface AuthContextValue {
  usuario: PerfilActual | null;
  cargando: boolean;
  sedeActiva: string | null;
  cambiarSede: (codigo: string) => void;
  ingresar: (usuario: string, clave: string) => Promise<PerfilActual>;
  salir: () => Promise<void>;
  recargarPerfil: () => Promise<void>;
  tienePermiso: (permiso: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

async function cargarPerfil(): Promise<PerfilActual | null> {
  const { data, response } = await api.GET("/api/v1/yo");
  if (response.status === 401 || !data) {
    return null;
  }
  return data;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { data: usuario = null, isPending: cargando, refetch } = useQuery({
    queryKey: ["yo"],
    queryFn: cargarPerfil,
    retry: false,
  });

  const [sedeManual, setSedeManual] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      return window.localStorage.getItem(CLAVE_SEDE_STORAGE);
    } catch {
      return null;
    }
  });

  const sedeActiva = useMemo(() => {
    if (!usuario || usuario.sedes.length === 0) return null;
    if (sedeManual && usuario.sedes.some((s) => s.codigo === sedeManual)) {
      return sedeManual;
    }
    return usuario.sedes[0]?.codigo ?? null;
  }, [usuario, sedeManual]);

  useEffect(() => {
    if (sedeActiva && typeof window !== "undefined") {
      try {
        window.localStorage.setItem(CLAVE_SEDE_STORAGE, sedeActiva);
      } catch {
        // Sin acceso a localStorage en entornos restringidos
      }
    }
  }, [sedeActiva]);

  const cambiarSede = useCallback(
    (codigo: string) => {
      setSedeManual(codigo);
      if (typeof window !== "undefined") {
        try {
          window.localStorage.setItem(CLAVE_SEDE_STORAGE, codigo);
        } catch {
          // noop
        }
      }
      void queryClient.invalidateQueries();
    },
    [queryClient],
  );

  const ingresar = useCallback(
    async (nombreUsuario: string, clave: string): Promise<PerfilActual> => {
      const { data, error, response } = await api.POST("/api/v1/auth/ingresar", {
        body: { usuario: nombreUsuario, clave, tipo_cliente: "web" },
      });
      if (!data) {
        const msg =
          error && typeof error === "object" && "detail" in error && typeof error.detail === "string"
            ? error.detail
            : `No se pudo iniciar sesión (${response.status})`;
        throw new Error(msg);
      }
      queryClient.setQueryData(["yo"], data);
      if (data.sedes.length > 0 && (!sedeManual || !data.sedes.some((s) => s.codigo === sedeManual))) {
        const primera = data.sedes[0];
        if (primera) setSedeManual(primera.codigo);
      }
      return data;
    },
    [queryClient, sedeManual],
  );

  const salir = useCallback(async () => {
    await api.POST("/api/v1/auth/salir");
    queryClient.setQueryData(["yo"], null);
    queryClient.clear();
  }, [queryClient]);

  const recargarPerfil = useCallback(async () => {
    await refetch();
  }, [refetch]);

  const tienePermiso = useCallback(
    (permiso: string) => Boolean(usuario?.permisos.includes(permiso)),
    [usuario],
  );

  const valor = useMemo(
    () => ({
      usuario,
      cargando,
      sedeActiva,
      cambiarSede,
      ingresar,
      salir,
      recargarPerfil,
      tienePermiso,
    }),
    [usuario, cargando, sedeActiva, cambiarSede, ingresar, salir, recargarPerfil, tienePermiso],
  );

  return <AuthContext.Provider value={valor}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth debe usarse dentro de AuthProvider");
  return ctx;
}
