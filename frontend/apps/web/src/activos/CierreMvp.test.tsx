// Lotes de marcación, hoja de vida y plantillas de correo (cierre del MVP de la web).
import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const maestros: Record<string, { id: number; codigo: string; nombre: string; activo: boolean }[]> = {
  LUMINARIA_TECNOLOGIA: [{ id: 11, codigo: "LED", nombre: "LED", activo: true }],
  LUMINARIA_POTENCIA: [{ id: 21, codigo: "60", nombre: "60 W", activo: true }],
  LUMINARIA_MARCA: [{ id: 31, codigo: "KUNIX", nombre: "KÜNIX", activo: true }],
  ACCION_OPERATIVA: [{ id: 41, codigo: "BB", nombre: "BODEGA BUENA", activo: true }],
  MISION_OBJETIVO: [{ id: 51, codigo: "MANT", nombre: "MANTENIMIENTO", activo: true }],
};

const lote = {
  id: 3,
  sede_id: 1,
  consecutivo_inicial: 7001,
  consecutivo_final: 7010,
  cantidad: 10,
  tecnologia_id: 11,
  potencia_id: 21,
  marca_id: 31,
  es_rural: false,
  orden_compra: "OC-77",
  fecha_orden_compra: "2026-11-02",
  entrada_almacen: "EA-9",
  fecha_entrada_almacen: "2026-11-05",
  creado_en: "2026-11-05T15:00:00Z",
};

const luminaria = {
  id: 9,
  sede_id: 1,
  codigo: "7001",
  codigo_externo: null,
  barrio_id: null,
  barrio_nombre: null,
  zona_id: null,
  zona_nombre: null,
  latitud: null,
  longitud: null,
  google_maps_url: null,
  estado_id: 124,
  estado_codigo: "124",
  estado_nombre: "Bodega buena",
  tecnologia_id: 11,
  tecnologia_codigo: "LED",
  tecnologia_nombre: "LED",
  potencia_id: 21,
  potencia_codigo: "60",
  potencia_nombre: "60 W",
  marca_id: 31,
  marca_codigo: "KUNIX",
  marca_nombre: "KÜNIX",
  tipo_intervencion_id: null,
  accion_operativa_id: 41,
  mision_objetivo_id: 51,
  lote_id: 3,
  luminaria_reemplazada_id: null,
  fecha_instalacion: null,
  fecha_mision: "2026-11-10",
  fecha_baja: null,
  fecha_disposicion_final: null,
  mac: null,
  poste: null,
  longitud_brazo: null,
  es_rural: false,
  subnormal: false,
  tiene_medida: false,
  en_transito: false,
  validado: false,
  es_comodin: false,
  responsable: "Coordinación",
  observaciones: null,
  creado_en: "2026-11-05T15:00:00Z",
  modificado_en: "2026-11-05T15:00:00Z",
};

const plantilla = {
  id: 5,
  sede_id: 1,
  codigo: "MAIL_PQRS",
  nombre: "Nueva PQRS",
  asunto: "Su solicitud {{numero}} fue registrada",
  cuerpo_html: "<p>Hola {{nombre}}</p>",
  variables: ["nombre", "numero"],
  activa: true,
  modificado_en: "2026-11-20T10:00:00Z",
};

function montar(ruta: string, permisos: string[]) {
  const peticiones: { metodo: string; ruta: string; query: string; cuerpo: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (entrada: Request | string, init?: RequestInit) => {
      const peticion =
        typeof entrada === "string" ? new Request(new URL(entrada, "http://localhost"), init) : entrada;
      const url = new URL(peticion.url);
      const cuerpoPeticion = peticion.method === "GET" ? "" : await peticion.clone().text();
      peticiones.push({ metodo: peticion.method, ruta: url.pathname, query: url.search, cuerpo: cuerpoPeticion });
      const p = url.pathname;
      let cuerpo: unknown = [];
      if (p === "/api/v1/yo") cuerpo = perfil(permisos);
      else if (p.startsWith("/api/v1/maestros/")) cuerpo = maestros[p.split("/").pop()!] ?? [];
      else if (p === "/api/v1/lotes") cuerpo = { items: [lote], total: 1, page: 1, size: 20 };
      else if (p === "/api/v1/lotes/3") cuerpo = lote;
      else if (p === "/api/v1/luminarias") cuerpo = { items: [luminaria], total: 1, page: 1, size: 20 };
      else if (p === "/api/v1/luminarias/9/historial")
        cuerpo = { luminaria, eventos: [], ubicaciones: [], pqrs: [], ordenes: [] };
      else if (p === "/api/v1/plantillas-correo") cuerpo = [plantilla];
      else if (p === "/api/v1/plantillas-correo/5") cuerpo = { ...plantilla, ...JSON.parse(cuerpoPeticion) };
      return new Response(JSON.stringify(cuerpo), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  window.history.replaceState(null, "", ruta);
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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Cierre del MVP de la web", () => {
  it("muestra el histórico de lotes con nombres de catálogo y consecutivos en su columna", async () => {
    montar("/activos", ["activos.luminaria.ver", "activos.lote.crear"]);
    fireEvent.click(await screen.findByRole("tab", { name: "Lotes de marcación" }));
    expect(await screen.findByText("OC-77 (02/11/2026)")).toBeInTheDocument();
    expect(screen.getByText("7001")).toBeInTheDocument();
    expect(screen.getByText("7010")).toBeInTheDocument();
    expect(screen.getAllByText("KÜNIX").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Nuevo lote" })).toBeInTheDocument();
  });

  it("muestra la hoja de vida con la compra del lote en la ficha y filtra por acción operativa", async () => {
    const peticiones = montar("/activos", ["activos.luminaria.ver", "activos.luminaria.editar"]);
    fireEvent.click(await screen.findByRole("button", { name: "Ver ficha" }));
    const hoja = await screen.findByTestId("hoja-de-vida");
    await waitFor(() => expect(hoja).toHaveTextContent("OC-77"));
    expect(hoja).toHaveTextContent("BODEGA BUENA");
    expect(hoja).toHaveTextContent("MANTENIMIENTO");
    expect(hoja).toHaveTextContent("10/11/2026");
    expect(screen.getByRole("button", { name: "Modificar" })).toBeInTheDocument();
    expect(peticiones.some((r) => r.ruta === "/api/v1/lotes/3")).toBe(true);
  });

  it("edita una plantilla de correo y envía asunto, cuerpo y estado", async () => {
    const peticiones = montar("/configuracion", ["configuracion.plantilla.editar"]);
    fireEvent.click(await screen.findByRole("tab", { name: "Plantillas de correo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Modificar" }));
    const asunto = await screen.findByLabelText(/Asunto del correo/);
    fireEvent.change(asunto, { target: { value: "Radicamos su PQRS {{numero}}" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() =>
      expect(peticiones.some((r) => r.metodo === "PATCH" && r.ruta === "/api/v1/plantillas-correo/5")).toBe(true),
    );
    const patch = peticiones.find((r) => r.metodo === "PATCH")!;
    expect(JSON.parse(patch.cuerpo)).toEqual({
      asunto: "Radicamos su PQRS {{numero}}",
      cuerpo_html: "<p>Hola {{nombre}}</p>",
      activa: true,
    });
    expect(await screen.findByText("Plantilla «Nueva PQRS» guardada.")).toBeInTheDocument();
  });
});
