// Guía de instalación (HU-060). En iPhone la app debe ir a la pantalla de inicio: solo así iOS
// conserva los datos sin señal por más tiempo y permite los avisos push.
import { Alert, Button, Group, Text } from "@mantine/core";
import { useEffect, useState } from "react";

interface EventoInstalar extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

const CLAVE_OCULTA = "sapef_campo_guia_oculta";

function instalada(): boolean {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

function esIos(): boolean {
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

export function GuiaInstalacion() {
  const [evento, setEvento] = useState<EventoInstalar | null>(null);
  const [oculta, setOculta] = useState(() => {
    try {
      return instalada() || window.sessionStorage.getItem(CLAVE_OCULTA) === "1";
    } catch {
      return instalada();
    }
  });

  useEffect(() => {
    const guardar = (e: Event) => {
      e.preventDefault();
      setEvento(e as EventoInstalar);
    };
    window.addEventListener("beforeinstallprompt", guardar);
    return () => window.removeEventListener("beforeinstallprompt", guardar);
  }, []);

  if (oculta) return null;

  const ocultar = () => {
    setOculta(true);
    try {
      window.sessionStorage.setItem(CLAVE_OCULTA, "1");
    } catch {
      // sin almacenamiento de sesión: solo se oculta ahora
    }
  };

  return (
    <Alert color="blue" variant="light" title="Instale la app" withCloseButton onClose={ocultar}>
      {esIos() ? (
        <Text size="sm">
          En el iPhone, toque <b>Compartir</b> y luego <b>Agregar a inicio</b>. Es necesario para
          trabajar sin señal sin perder datos y para recibir avisos.
        </Text>
      ) : (
        <Group justify="space-between" wrap="nowrap">
          <Text size="sm">Instálela en la pantalla de inicio para usarla sin señal.</Text>
          {evento && (
            <Button
              size="xs"
              onClick={() => {
                void evento.prompt();
                void evento.userChoice.finally(() => setEvento(null));
              }}
            >
              Instalar
            </Button>
          )}
        </Group>
      )}
    </Alert>
  );
}
