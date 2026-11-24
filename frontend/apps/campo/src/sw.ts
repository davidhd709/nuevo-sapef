/// <reference lib="webworker" />
// Service Worker de la app de campo (Workbox, estrategia injectManifest).
//
// - Precarga la app para abrirla sin señal.
// - Muestra los avisos Web Push de órdenes asignadas y abre la orden al tocarlos.
// - Regla de §6.10: una versión nueva solo se activa cuando la bandeja de salida está vacía; así
//   un cambio de formato nunca deja trabajo sin enviar.
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from "workbox-precaching";
import { NavigationRoute, registerRoute } from "workbox-routing";

declare const self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: (string | { url: string; revision: string | null })[];
};

const manifiesto = self.__WB_MANIFEST;
cleanupOutdatedCaches();
precacheAndRoute(manifiesto);

// Navegaciones sin señal: la app (index.html precargado). La API nunca pasa por aquí.
if (manifiesto.some((e) => (typeof e === "string" ? e : e.url).endsWith("index.html"))) {
  registerRoute(
    new NavigationRoute(createHandlerBoundToURL("index.html"), { denylist: [/^\/api\//] }),
  );
}

/** Operaciones en la bandeja de salida (IndexedDB «sapef-campo», almacén «outbox»). */
function contarPendientes(): Promise<number> {
  return new Promise((resolve) => {
    const abrir = indexedDB.open("sapef-campo");
    abrir.onerror = () => resolve(0);
    abrir.onupgradeneeded = () => {
      // La base aún no existe: no crearla aquí con otra versión.
      abrir.transaction?.abort();
      resolve(0);
    };
    abrir.onsuccess = () => {
      const base = abrir.result;
      if (!base.objectStoreNames.contains("outbox")) {
        base.close();
        resolve(0);
        return;
      }
      const conteo = base.transaction("outbox", "readonly").objectStore("outbox").count();
      conteo.onsuccess = () => {
        base.close();
        resolve(conteo.result);
      };
      conteo.onerror = () => {
        base.close();
        resolve(1); // ante la duda, no actualizar
      };
    };
  });
}

self.addEventListener("message", (evento) => {
  const datos = evento.data as { type?: string } | null;
  if (datos?.type !== "SKIP_WAITING") return;
  evento.waitUntil(
    contarPendientes().then((pendientes) => {
      if (pendientes === 0) return self.skipWaiting();
      return undefined;
    }),
  );
});

interface AvisoPush {
  titulo?: string;
  cuerpo?: string;
  url?: string;
  etiqueta?: string;
}

self.addEventListener("push", (evento) => {
  let aviso: AvisoPush = {};
  try {
    aviso = (evento.data?.json() as AvisoPush) ?? {};
  } catch {
    aviso = { cuerpo: evento.data?.text() };
  }
  evento.waitUntil(
    self.registration.showNotification(aviso.titulo ?? "SAPEF Campo", {
      body: aviso.cuerpo ?? "Tiene novedades en sus órdenes.",
      tag: aviso.etiqueta,
      icon: "/icono-192.png",
      badge: "/icono-192.png",
      data: { url: aviso.url ?? "/" },
    }),
  );
});

self.addEventListener("notificationclick", (evento) => {
  evento.notification.close();
  const destino = new URL(
    (evento.notification.data as { url?: string } | null)?.url ?? "/",
    self.location.origin,
  ).href;
  evento.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (ventanas) => {
      for (const ventana of ventanas) {
        if (new URL(ventana.url).origin !== self.location.origin) continue;
        await ventana.focus();
        ventana.postMessage({ type: "ABRIR", url: destino });
        return;
      }
      await self.clients.openWindow(destino);
    }),
  );
});
