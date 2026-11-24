// Nota de voz (RF-101) con MediaRecorder. iPhone graba en MP4/AAC y Android en WebM/Opus; el
// servidor acepta los dos. Máximo 2 minutos para no pasar el límite de evidencia.
import { Button, Group, Text } from "@mantine/core";
import { useEffect, useRef, useState } from "react";

const MAXIMO_MS = 120_000;

export function NotaVoz({ onGrabada }: { onGrabada: (datos: Blob, mime: string) => void }) {
  const [grabando, setGrabando] = useState(false);
  const [segundos, setSegundos] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const grabadora = useRef<MediaRecorder | null>(null);
  const reloj = useRef<number | null>(null);

  const detener = () => {
    if (grabadora.current?.state === "recording") grabadora.current.stop();
  };

  useEffect(() => () => detener(), []);

  const empezar = async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Este teléfono no permite grabar aquí; adjunte un audio.");
      return;
    }
    try {
      const flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
      const tipo = ["audio/mp4", "audio/webm;codecs=opus", "audio/webm"].find((t) =>
        MediaRecorder.isTypeSupported(t),
      );
      const r = new MediaRecorder(flujo, tipo ? { mimeType: tipo } : undefined);
      const partes: Blob[] = [];
      r.ondataavailable = (e) => {
        if (e.data.size > 0) partes.push(e.data);
      };
      r.onstop = () => {
        flujo.getTracks().forEach((t) => t.stop());
        if (reloj.current) window.clearInterval(reloj.current);
        setGrabando(false);
        const mime = (r.mimeType || tipo || "audio/webm").split(";")[0] ?? "audio/webm";
        if (partes.length > 0) onGrabada(new Blob(partes, { type: mime }), mime);
      };
      grabadora.current = r;
      r.start(1000);
      setSegundos(0);
      setGrabando(true);
      const inicio = Date.now();
      reloj.current = window.setInterval(() => {
        const ms = Date.now() - inicio;
        setSegundos(Math.floor(ms / 1000));
        if (ms >= MAXIMO_MS) detener();
      }, 500);
    } catch {
      setError("No se pudo usar el micrófono (revise el permiso).");
    }
  };

  return (
    <Group gap="xs">
      {grabando ? (
        <Button color="red" variant="light" onClick={detener}>
          Detener ({segundos} s)
        </Button>
      ) : (
        <Button variant="light" onClick={() => void empezar()}>
          Grabar nota de voz
        </Button>
      )}
      {error && (
        <Text size="xs" c="red">
          {error}
        </Text>
      )}
    </Group>
  );
}
