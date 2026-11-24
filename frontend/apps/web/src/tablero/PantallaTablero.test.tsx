import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";

// jsdom no dibuja canvas: el gráfico se reemplaza por su descripción accesible.
vi.mock("./Grafico", () => ({
  Grafico: ({ descripcion }: { descripcion: string }) => <div role="img" aria-label={descripcion} />,
}));

const perfil = {
  id: 1,
  nombre_usuario: "gerente",
  nombre_completo: "Gerente",
  identificacion: "1",
  correo: "g@sapef.test",
  activo: true,
  debe_cambiar_clave: false,
  acepto_condiciones_en: "2026-11-01T00:00:00Z",
  rol: { id: 3, codigo: "GERENTE", nombre: "Gerente" },
  permisos: ["tablero.ver", "tablero.consolidado.ver"],
  sedes: [
    { id: 1, codigo: "montelibano", nombre: "Montelíbano" },
    { id: 2, codigo: "alcala", nombre: "Alcalá" },
  ],
};

const conteo = (etiqueta: string, cantidad: number, grupo: string | null = null) => ({ etiqueta, grupo, cantidad });

const resumen = {
  sede: "todas",
  sedes_incluidas: perfil.sedes,
  anio: 2026,
  calculado_en: "2026-11-24T08:00:00Z",
  activos: {
    total_luminarias: 12000,
    en_servicio: 11800,
    en_bodega: 200,
    instaladas_anio: 340,
    luminarias_instaladas_mes: Array.from({ length: 12 }, (_, i) => ({ mes: i + 1, cantidad: 10, acumulado: 10 * (i + 1) })),
    por_tecnologia: [conteo("LED", 9000), conteo("Sodio", 2800)],
    por_potencia: [conteo("70 W", 5000)],
    por_zona: [conteo("Urbana", 8000)],
    por_barrio: [conteo("El Centro", 900, "Montelíbano · Urbana")],
  },
  operacion: {
    luminarias_por_estado: [conteo("121 · Activo en operación", 11000)],
    pqrs_abiertas: 37,
    pqrs_semaforo: { verde: 20, amarillo: 10, rojo: 7, umbral_verde_dias: 3, umbral_amarillo_dias: 7 },
    pqrs_recibidas_mes: 50,
    pqrs_recibidas_mes_anterior: 40,
    variacion_pqrs_recibidas: 25,
    pqrs_atendidas_mes: 45,
    pqrs_atendidas_anio: 500,
    tiempo_promedio_atencion_horas: 60,
    pqrs_por_barrio: [conteo("El Centro", 12, "Montelíbano · Urbana")],
    mantenimientos_mes: 80,
    mantenimientos_mes_anterior: 100,
    variacion_mantenimientos: -20,
    ordenes_abiertas: 15,
    materiales_bajo_minimo: 2,
  },
  comercial: {
    estado: "con_datos",
    comercializadores: [
      {
        sede_codigo: "montelibano",
        sede_nombre: "Montelíbano",
        comercializador: "afinia",
        nombre: "Afinia",
        periodo: "202610",
        periodo_anterior: "202609",
        actual: { n_facturados: 21000, facturacion: 450000000, recaudo: 400000000, eficiencia: 0.89 },
        anterior: { n_facturados: 20900 },
        variacion: { n_facturados: 0.5 },
        participacion: [{ grupo: "Residencial 1", usuarios: 9000, facturacion: 100, recaudo: 90, consumo: 10 }],
        historico: [{ periodo: "202610", facturacion: 1, recaudo: 1, cartera: 1, n_facturados: 1 }],
      },
    ],
  },
  por_sede: [
    {
      sede: perfil.sedes[0],
      calculado_en: "2026-11-24T08:00:00Z",
      total_luminarias: 11000,
      en_servicio: 10800,
      instaladas_anio: 300,
      pqrs_abiertas: 30,
      pqrs_rojo: 6,
      mantenimientos_mes: 70,
    },
    {
      sede: perfil.sedes[1],
      calculado_en: "2026-11-24T08:00:00Z",
      total_luminarias: 1000,
      en_servicio: 1000,
      instaladas_anio: 40,
      pqrs_abiertas: 7,
      pqrs_rojo: 1,
      mantenimientos_mes: 10,
    },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe("Tablero gerencial", () => {
  it("abre el consolidado desde la URL y muestra operación, sedes y comercial", async () => {
    const peticiones: Request[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (entrada: Request) => {
        peticiones.push(entrada);
        const ruta = new URL(entrada.url).pathname;
        const cuerpo = ruta === "/api/v1/yo" ? perfil : ruta === "/api/v1/tablero/resumen" ? resumen : [];
        return new Response(JSON.stringify(cuerpo), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
    window.history.replaceState(null, "", "/tablero?sede=todas");
    const consultas = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MantineProvider>
        <QueryClientProvider client={consultas}>
          <App />
        </QueryClientProvider>
      </MantineProvider>,
    );

    expect(await screen.findByText("Por sede")).toBeInTheDocument();
    expect(screen.getByText("12.000")).toBeInTheDocument();
    expect(screen.getByText("7 en rojo")).toBeInTheDocument();
    expect(screen.getByText("Afinia · Montelíbano")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Luminarias instaladas por mes en 2026" })).toBeInTheDocument();
    expect(screen.getByText(/▼ 20 % vs. mes anterior/)).toBeInTheDocument();

    const pedido = peticiones.find((p) => new URL(p.url).pathname === "/api/v1/tablero/resumen");
    expect(new URL(pedido!.url).searchParams.get("sede")).toBe("todas");
    expect(pedido!.headers.get("X-Sede")).toBeNull();
  });
});
