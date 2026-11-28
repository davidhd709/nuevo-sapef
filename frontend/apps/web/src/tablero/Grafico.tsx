// Envoltorio mínimo de ECharts: monta, actualiza y libera la instancia; redibuja al cambiar el
// tamaño del contenedor y aplica el tema de SAPEF (claro u oscuro según Mantine).
import { useComputedColorScheme } from "@mantine/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export type OpcionGrafico = echarts.EChartsCoreOption;

// Orden categorico validado (daltonismo y vision normal, pares adyacentes) con el script de la
// guia de visualizacion. Se asigna en orden fijo: la serie 1 siempre es azul.
export const SERIES = {
  claro: ["#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6a4ce2", "#ec4647"],
  oscuro: ["#338ced", "#e76624", "#00a888", "#d28e05", "#e24d8b", "#0aac23", "#9887ef", "#eb6263"],
};

function tema(oscuro: boolean) {
  const tinta = oscuro ? "#efefef" : "#1c1c1a";
  const secundaria = oscuro ? "#9c9c9c" : "#63635e";
  const rejilla = oscuro ? "#303030" : "#ebebe8";
  const eje = oscuro ? "#474747" : "#cfcfca";
  const fuente = "'IBM Plex Sans', system-ui, sans-serif";
  const ejeComun = {
    axisLine: { lineStyle: { color: eje } },
    axisTick: { show: false },
    axisLabel: { color: secundaria, fontSize: 11 },
    splitLine: { lineStyle: { color: rejilla } },
    nameTextStyle: { color: secundaria, fontSize: 11 },
  };
  return {
    color: oscuro ? SERIES.oscuro : SERIES.claro,
    backgroundColor: "transparent",
    textStyle: { fontFamily: fuente, color: tinta },
    categoryAxis: { ...ejeComun, splitLine: { show: false } },
    valueAxis: { ...ejeComun, axisLine: { show: false } },
    legend: { textStyle: { color: secundaria, fontSize: 12 }, itemWidth: 10, itemHeight: 10, icon: "roundRect" },
    tooltip: {
      backgroundColor: oscuro ? "#2a2926" : "#ffffff",
      borderColor: oscuro ? "#3a3935" : "#e3e3df",
      borderWidth: 1,
      padding: [6, 10],
      textStyle: { color: tinta, fontSize: 12, fontFamily: fuente },
      extraCssText: "box-shadow: 0 4px 12px rgba(0,0,0,0.08); border-radius: 4px;",
    },
    bar: { barMaxWidth: 28 },
    line: { symbol: "circle", symbolSize: 8, lineStyle: { width: 2 } },
  };
}

echarts.registerTheme("sapef", tema(false));
echarts.registerTheme("sapef-oscuro", tema(true));

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
    const grafico = echarts.init(ref.current, esquema === "dark" ? "sapef-oscuro" : "sapef");
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
    instancia.current?.setOption({ animationDuration: 300, ...opcion }, { notMerge: true });
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
