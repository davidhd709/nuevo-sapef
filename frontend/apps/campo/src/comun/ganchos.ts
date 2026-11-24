// Ganchos de React para la base local, la señal y el GPS.
import { liveQuery } from "dexie";
import { useEffect, useState, useSyncExternalStore } from "react";

import { leerEstado, suscribirEstado, type EstadoSincronizacion } from "../datos/sincronizacion";

/** Consulta a Dexie que se vuelve a ejecutar sola cuando cambian los datos. */
export function useConsulta<T>(consulta: () => Promise<T>, deps: unknown[], inicial: T): T {
  const [valor, setValor] = useState<T>(inicial);
  useEffect(() => {
    const sub = liveQuery(consulta).subscribe({ next: setValor, error: () => undefined });
    return () => sub.unsubscribe();
  }, deps);
  return valor;
}

export function useEnLinea(): boolean {
  return useSyncExternalStore(
    (avisar) => {
      window.addEventListener("online", avisar);
      window.addEventListener("offline", avisar);
      return () => {
        window.removeEventListener("online", avisar);
        window.removeEventListener("offline", avisar);
      };
    },
    () => navigator.onLine,
  );
}

export function useEstadoSincronizacion(): EstadoSincronizacion {
  return useSyncExternalStore(suscribirEstado, leerEstado);
}

export interface Ubicacion {
  latitud: number;
  longitud: number;
  precision: number;
}

/** Posición GPS mientras el formulario está abierto (RF-101). No bloquea: si no hay permiso
 * o no hay fijación, el trabajo se guarda sin coordenadas cuando el tipo lo permite. */
export function useUbicacion(activa: boolean): { ubicacion: Ubicacion | null; error: string | null } {
  const [ubicacion, setUbicacion] = useState<Ubicacion | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!activa) return;
    if (!("geolocation" in navigator)) {
      setError("Este teléfono no tiene GPS disponible.");
      return;
    }
    const id = navigator.geolocation.watchPosition(
      (p) => {
        setUbicacion({
          latitud: p.coords.latitude,
          longitud: p.coords.longitude,
          precision: p.coords.accuracy,
        });
        setError(null);
      },
      (e) =>
        setError(
          e.code === e.PERMISSION_DENIED
            ? "Sin permiso de ubicación."
            : "Buscando señal GPS…",
        ),
      { enableHighAccuracy: true, maximumAge: 30_000, timeout: 20_000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [activa]);
  return { ubicacion, error };
}
