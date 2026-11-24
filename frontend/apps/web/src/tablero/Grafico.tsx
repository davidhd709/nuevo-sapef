// Envoltorio mínimo de ECharts: monta, actualiza y libera la instancia; redibuja al cambiar el
// tamaño del contenedor y respeta el tema claro/oscuro de Mantine.
import { useComputedColorScheme } from "@mantine/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export type OpcionGrafico = echarts.EChartsCoreOption;

interface Props {
  opcion: OpcionGrafico;
  alto?: number;
  /** Texto para lectores de pantalla: qué muestra el gráfico. */
  descripcion: string;
  onClicCategoria?: (nombre: string) => void;
}

export function Grafico({ opcion, alto = 260, descripcion, onClicCategoria }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const instancia = useRef<echarts.ECharts | null>(null);
  const esquema = useComputedColorScheme("light");
  const clic = useRef(onClicCategoria);
  clic.current = onClicCategoria;

  useEffect(() => {
    if (!ref.current) return undefined;
    const grafico = echarts.init(ref.current, esquema === "dark" ? "dark" : undefined);
    instancia.current = grafico;
    grafico.on("click", (p) => {
      if (clic.current && typeof p.name === "string") clic.current(p.name);
    });
    const observador = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => grafico.resize()) : null;
    observador?.observe(ref.current);
    return () => {
      observador?.disconnect();
      grafico.dispose();
      instancia.current = null;
    };
  }, [esquema]);

  useEffect(() => {
    instancia.current?.setOption(
      { backgroundColor: "transparent", animationDuration: 300, ...opcion },
      { notMerge: true },
    );
  }, [opcion, esquema]);

  return (
    <div
      ref={ref}
      role="img"
      aria-label={descripcion}
      style={{ width: "100%", height: alto, cursor: onClicCategoria ? "pointer" : undefined }}
    />
  );
}
