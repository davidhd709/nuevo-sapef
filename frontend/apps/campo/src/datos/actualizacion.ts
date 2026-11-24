// Registro del Service Worker y actualización segura: la versión nueva se aplica solo con la
// bandeja de salida vacía (el SW hace la misma comprobación por su lado).
import { registerSW } from "virtual:pwa-register";

import { db } from "./db";
import { despuesDeSincronizar } from "./sincronizacion";

let hayVersionNueva = false;
let aplicar: ((recargar?: boolean) => Promise<void>) | null = null;

export async function intentarActualizar(): Promise<boolean> {
  if (!hayVersionNueva || !aplicar) return false;
  if ((await db.outbox.count()) > 0) return false;
  await aplicar(true);
  return true;
}

export function registrarServiceWorker(): void {
  if (!("serviceWorker" in navigator)) return;
  aplicar = registerSW({
    immediate: true,
    onNeedRefresh() {
      hayVersionNueva = true;
      void intentarActualizar();
    },
  });
  despuesDeSincronizar(() => void intentarActualizar());
}
