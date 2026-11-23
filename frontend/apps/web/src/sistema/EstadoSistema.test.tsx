import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { EstadoSistema } from "./EstadoSistema";

function montarEstado() {
  const consultas = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MantineProvider>
      <QueryClientProvider client={consultas}>
        <EstadoSistema />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

function responderJson(estado: number, cuerpo: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(cuerpo), {
        status: estado,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("EstadoSistema", () => {
  it("muestra la API y la base de datos en buen estado", async () => {
    responderJson(200, {
      estado: "ok",
      version: "0.1.0",
      base_de_datos: "ok",
      postgres: "17.5",
      postgis: "3.5.2",
    });
    montarEstado();
    expect(await screen.findByText("PostgreSQL 17.5 · PostGIS 3.5.2")).toBeInTheDocument();
    expect(screen.getAllByText("ok")).toHaveLength(2);
  });

  it("muestra el estado degradado cuando la base no responde (503)", async () => {
    responderJson(503, { estado: "degradado", version: "0.1.0", base_de_datos: "no disponible" });
    montarEstado();
    expect(await screen.findByText("no disponible")).toBeInTheDocument();
    expect(screen.getByText("degradado")).toBeInTheDocument();
  });

  it("redirige a /ingresar cuando no hay sesión activa", async () => {
    window.history.replaceState(null, "", "/mapa");
    responderJson(401, { type: "about:blank", title: "Unauthorized", status: 401 });
    const consultas = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MantineProvider>
        <QueryClientProvider client={consultas}>
          <App />
        </QueryClientProvider>
      </MantineProvider>,
    );
    expect(await screen.findByRole("button", { name: "Ingresar" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/ingresar");
  });
});
