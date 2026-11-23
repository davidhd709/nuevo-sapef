import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";

const perfil = {
  id: 1,
  nombre_usuario: "coordinadora",
  nombre_completo: "Coordinadora",
  identificacion: "1",
  correo: "c@sapef.test",
  activo: true,
  debe_cambiar_clave: false,
  acepto_condiciones_en: "2026-11-01T00:00:00Z",
  rol: { id: 2, codigo: "COORDINACION", nombre: "Coordinación" },
  permisos: ["atencion.pqrs.ver", "atencion.pqrs.crear", "trabajos.orden.crear"],
  sedes: [{ id: 1, codigo: "montelibano", nombre: "Montelíbano" }],
};

const pendientes = {
  total: 2,
  page: 1,
  size: 50,
  items: [
    {
      pqrs_id: 9, pqrs_numero: 41, luminaria_id: 5, luminaria_codigo: "L-100",
      barrio_nombre: "El Centro", estado_reportado_codigo: "121", prioridad: 0,
      prioridad_nombre: "Urgente", solicitante: "S•••• Á•••••", fecha_reporte: "2026-11-10",
      dias_abierta: 13, semaforo: "rojo", latitud: 7.98, longitud: -75.42,
    },
    {
      pqrs_id: 10, pqrs_numero: 42, luminaria_id: 6, luminaria_codigo: "L-200",
      barrio_nombre: "San Felipe", estado_reportado_codigo: "121", prioridad: 2,
      prioridad_nombre: "Media", solicitante: null, fecha_reporte: "2026-11-22",
      dias_abierta: 1, semaforo: "verde", latitud: null, longitud: null,
    },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe("Atención · luminarias pendientes", () => {
  it("muestra cada luminaria con su semáforo y pide los datos de la sede activa", async () => {
    const peticiones: Request[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (entrada: Request) => {
        peticiones.push(entrada);
        const ruta = new URL(entrada.url).pathname;
        const cuerpo =
          ruta === "/api/v1/yo" ? perfil : ruta === "/api/v1/pqrs/pendientes" ? pendientes : [];
        return new Response(JSON.stringify(cuerpo), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    window.history.replaceState(null, "", "/atencion/pendientes");
    const consultas = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MantineProvider>
        <QueryClientProvider client={consultas}>
          <App />
        </QueryClientProvider>
      </MantineProvider>,
    );

    const fila = (await screen.findByText("L-100")).closest("tr");
    expect(fila).not.toBeNull();
    expect(within(fila!).getByText("rojo")).toBeInTheDocument();
    expect(within(fila!).getByText("13")).toBeInTheDocument();
    expect(within(screen.getByText("L-200").closest("tr")!).getByText("verde")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Crear orden" })).toHaveLength(2);

    const consulta = peticiones.find((p) => p.url.includes("/api/v1/pqrs/pendientes"));
    expect(consulta?.headers.get("X-Sede")).toBe("montelibano");
  });
});
