// Firma con el dedo sobre un lienzo (RF-101). Se guarda como PNG al registrar el trabajo.
import { Button, Group, Paper, Text } from "@mantine/core";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { lienzoAPng } from "../comun/captura";

export interface FirmaRef {
  /** PNG de la firma, o null si no se firmó. */
  obtener: () => Promise<Blob | null>;
}

export const Firma = forwardRef<FirmaRef, { etiqueta: string }>(function Firma({ etiqueta }, ref) {
  const lienzo = useRef<HTMLCanvasElement | null>(null);
  const dibujando = useRef(false);
  const [firmado, setFirmado] = useState(false);

  useImperativeHandle(ref, () => ({
    obtener: async () => (firmado && lienzo.current ? lienzoAPng(lienzo.current) : null),
  }));

  useEffect(() => {
    const c = lienzo.current;
    if (!c) return;
    const escala = window.devicePixelRatio || 1;
    c.width = c.clientWidth * escala;
    c.height = c.clientHeight * escala;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.scale(escala, escala);
    ctx.lineWidth = 2.2;
    ctx.lineCap = "round";
    ctx.strokeStyle = "#1a1b1e";
  }, []);

  const punto = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  const empezar = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const ctx = e.currentTarget.getContext("2d");
    if (!ctx) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    dibujando.current = true;
    const { x, y } = punto(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
  };

  const mover = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!dibujando.current) return;
    const ctx = e.currentTarget.getContext("2d");
    if (!ctx) return;
    const { x, y } = punto(e);
    ctx.lineTo(x, y);
    ctx.stroke();
    setFirmado(true);
  };

  const terminar = () => {
    dibujando.current = false;
  };

  const borrar = () => {
    const c = lienzo.current;
    c?.getContext("2d")?.clearRect(0, 0, c.width, c.height);
    setFirmado(false);
  };

  return (
    <div>
      <Group justify="space-between" mb={4}>
        <Text size="sm" fw={500}>
          {etiqueta}
        </Text>
        <Button size="compact-xs" variant="subtle" onClick={borrar} disabled={!firmado}>
          Borrar
        </Button>
      </Group>
      <Paper withBorder radius="sm" style={{ overflow: "hidden" }}>
        <canvas
          ref={lienzo}
          aria-label={etiqueta}
          style={{ width: "100%", height: 140, display: "block", touchAction: "none" }}
          onPointerDown={empezar}
          onPointerMove={mover}
          onPointerUp={terminar}
          onPointerLeave={terminar}
          onPointerCancel={terminar}
        />
      </Paper>
    </div>
  );
});
