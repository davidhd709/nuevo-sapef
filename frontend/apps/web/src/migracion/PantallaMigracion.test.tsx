import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";

const perfil = (permisos: string[]) => ({
  id: 1,
  nombre_usuario: "admin",
  nombre_completo: "Administrador",
  identificacion: "1",
  correo: "a@sapef.test",
  activo: true,
  debe_cambiar_clave: false,
  acepto_condiciones_en: "2026-11-01T00:00:00Z",
  rol: { id: 1, codigo: "ADMIN", nombre: "Administrador" },
  permisos,
  sedes: [{ id: 1, codigo: "montelibano", nombre: "Montelíbano" }],
});

const ejecucion = {
  id: 7,
  ejecucion_id: 7,
  ejecucionId: 7,
  tipo: "luminarias",
  estado: "con_errores",
  archivos: ["LUMINARIAS_LIST_DESCARGA.csv"],
  conciliacion: { leidas: 11205, creadas: 11110, errores: 1, repetidas_en_archivo: 92 },
  errores: [{ fila: 40, detalle: "Estado desconocido: XX", codigo: "SN-1" }],
  advertencias: [{ fila: 12, detalle: "Código repetido en el archivo; se tomó la primera fila." }],
  creado_en: "2026-11-25T14:00:00Z",
  procesado_en: "2026-11-25T14:02:00Z",
};

function montar(permisos: string[]) {
  const peticiones: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (entrada: Request | string, init?: RequestInit) => {
      const peticion = typeof entrada === "string" ? new Request(new URL(entrada, "http://localhost"), init) : entrada;
      peticiones.push(peticion);
      const ruta = new URL(peticion.url).pathname;
      let cuerpo: unknown = [];
      if (ruta === "/api/v1/yo") cuerpo = perfil(permisos);
      if (ruta === "/api/v1/migracion/ejecuciones") cuerpo = [ejecucion];
      if (ruta === "/api/v1/migracion/luminarias") cuerpo = { ...ejecucion, id: 8, estado: "pendiente" };
      return new Response(JSON.stringify(cuerpo), {
        status: ruta === "/api/v1/migracion/luminarias" ? 202 : 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  window.history.replaceState(null, "", "/migracion");
  const consultas = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <MantineProvider>
      <QueryClientProvider client={consultas}>
        <App />
      </QueryClientProvider>
    </MantineProvider>,
  );
  return peticiones;
}

afterEach(() => vi.unstubAllGlobals());

describe("Migración desde SAPEF", () => {
  it("muestra solo los importadores permitidos y el informe de una ejecución", async () => {
    montar(["activos.luminaria.crear", "activos.luminaria.ver"]);

    expect(await screen.findByText("2. Luminarias")).toBeInTheDocument();
    expect(screen.queryByText("3. PQRS")).not.toBeInTheDocument();
    const fila = await screen.findByText("LUMINARIAS_LIST_DESCARGA.csv");
    expect(within(fila.closest("tr")!).getByText("Con errores")).toBeInTheDocument();

    fireEvent.click(fila);
    expect(await screen.findByText("Repetidas en archivo")).toBeInTheDocument();
    expect(screen.getByText("Estado desconocido: XX")).toBeInTheDocument();
    expect(screen.getByText(/Advertencias \(se importaron\)/)).toBeInTheDocument();
  });

  it("envía el archivo con la sede activa", async () => {
    const peticiones = montar(["activos.luminaria.crear"]);
    await screen.findByText("2. Luminarias");
    const entrada = document.querySelector('input[type="file"]') as HTMLInputElement;
    const archivo = new File(["codigo;estado\nSN-1;121\n"], "lums.csv", { type: "text/csv" });
    fireEvent.change(entrada, { target: { files: [archivo] } });
    fireEvent.click(screen.getByRole("button", { name: "Importar" }));

    expect(await screen.findByText(/Importación #8 en cola/)).toBeInTheDocument();
    const envio = peticiones.find((p) => new URL(p.url).pathname === "/api/v1/migracion/luminarias");
    expect(envio?.method).toBe("POST");
    expect(envio?.headers.get("X-Sede")).toBe("montelibano");
  });

  it("sin permisos de importación muestra 403", async () => {
    montar(["activos.luminaria.ver"]);
    expect(await screen.findByText("403 · Acceso denegado")).toBeInTheDocument();
  });
});
