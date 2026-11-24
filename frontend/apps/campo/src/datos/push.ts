// Avisos Web Push (RF-105). En Android funciona desde el navegador; en iPhone solo con la app
// instalada en la pantalla de inicio (iOS 16.4 o superior). Pedir el permiso exige un toque del
// usuario, por eso se activa con un botón y no al abrir.
import { api } from "./api";

export type EstadoPush = "no_soportado" | "no_configurado" | "denegado" | "activo" | "inactivo";

function base64UrlABytes(valor: string): Uint8Array<ArrayBuffer> {
  const relleno = "=".repeat((4 - (valor.length % 4)) % 4);
  const texto = atob((valor + relleno).replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(new ArrayBuffer(texto.length));
  for (let i = 0; i < texto.length; i++) bytes[i] = texto.charCodeAt(i);
  return bytes;
}

function soportado(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export async function estadoPush(): Promise<EstadoPush> {
  if (!soportado()) return "no_soportado";
  if (Notification.permission === "denied") return "denegado";
  const registro = await navigator.serviceWorker.getRegistration();
  const suscripcion = await registro?.pushManager.getSubscription();
  return suscripcion ? "activo" : "inactivo";
}

export async function activarPush(): Promise<EstadoPush> {
  if (!soportado()) return "no_soportado";
  const { data } = await api.GET("/api/v1/notificaciones/push/clave-publica");
  if (!data?.habilitado || !data.clave_publica) return "no_configurado";
  if ((await Notification.requestPermission()) !== "granted") return "denegado";
  const registro = await navigator.serviceWorker.ready;
  const suscripcion =
    (await registro.pushManager.getSubscription()) ??
    (await registro.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: base64UrlABytes(data.clave_publica),
    }));
  const json = suscripcion.toJSON();
  const { response } = await api.POST("/api/v1/notificaciones/push/suscripciones", {
    body: {
      endpoint: json.endpoint ?? suscripcion.endpoint,
      keys: { p256dh: json.keys?.p256dh ?? "", auth: json.keys?.auth ?? "" },
    },
  });
  return response.ok ? "activo" : "inactivo";
}

export async function desactivarPush(): Promise<void> {
  if (!soportado()) return;
  const registro = await navigator.serviceWorker.getRegistration();
  const suscripcion = await registro?.pushManager.getSubscription();
  if (!suscripcion) return;
  await api.DELETE("/api/v1/notificaciones/push/suscripciones", {
    body: { endpoint: suscripcion.endpoint },
  });
  await suscripcion.unsubscribe();
}
