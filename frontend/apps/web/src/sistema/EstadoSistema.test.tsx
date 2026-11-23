import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EstadoSistema } from "./EstadoSistema";

function montar() {
  const consultas = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MantineProvider>
      <QueryClientProvider client={consultas}>
        <EstadoSistema />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

function responder(estado: number, cuerpo: unknown) {
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
    responder(200, {
      estado: "ok",
      version: "0.1.0",
      base_de_datos: "ok",
      postgres: "17.5",
      postgis: "3.5.2",
    });
    montar();
    expect(await screen.findByText("PostgreSQL 17.5 · PostGIS 3.5.2")).toBeInTheDocument();
    expect(screen.getAllByText("ok")).toHaveLength(2);
  });

  it("muestra el estado degradado cuando la base no responde (503)", async () => {
    responder(503, { estado: "degradado", version: "0.1.0", base_de_datos: "no disponible" });
    montar();
    expect(await screen.findByText("no disponible")).toBeInTheDocument();
    expect(screen.getByText("degradado")).toBeInTheDocument();
  });
});
