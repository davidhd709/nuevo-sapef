import { MantineProvider } from "@mantine/core";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it } from "vitest";

import { db, type OrdenCampo } from "../datos/db";
import { PantallaBandeja } from "./PantallaBandeja";

function orden(id: number, numero: number, prioridad: number): OrdenCampo {
  return {
    id,
    numero,
    tipo: "mantenimiento",
    estado_codigo: "202",
    estado_nombre: "En proceso",
    prioridad,
    pqrs_id: null,
    fecha_programada: null,
    asignada_en: null,
    observaciones: `Orden ${numero}`,
    modificado_en: "2026-11-24T09:00:00Z",
    luminarias: [
      {
        luminaria_id: id * 10,
        codigo: `L-${numero}`,
        rol: "intervenida",
        estado_codigo: "121",
        barrio_id: 1,
        barrio_nombre: "El Centro",
        poste: null,
        latitud: 7.98,
        longitud: -75.42,
      },
    ],
  };
}

beforeEach(async () => {
  await db.delete();
  await db.open();
});

it("lista por prioridad, aparta lo guardado sin enviar y muestra los conflictos", async () => {
  await db.ordenes.bulkAdd([orden(1, 1, 2), orden(2, 2, 0), orden(3, 3, 1)]);
  await db.outbox.add({
    uuid: "op",
    tipo: "mantenimiento",
    ordenId: 3,
    ordenNumero: 3,
    creadaEn: "2026-11-24T08:00:00Z",
    payload: {},
    evidencias: [],
    sede: "montelibano",
    usuarioId: 7,
    intentos: 0,
  });
  await db.conflictos.add({
    uuid: "c1",
    tipo: "mantenimiento",
    ordenId: 9,
    ordenNumero: 9,
    creadaEn: "2026-11-24T08:00:00Z",
    payload: {},
    evidencias: [],
    sede: "montelibano",
    usuarioId: 7,
    intentos: 1,
    estado: "conflicto",
    motivo: "La orden N.º 9 fue anulada en la oficina.",
    recibidoEn: "2026-11-24T09:00:00Z",
  });

  render(
    <MantineProvider>
      <PantallaBandeja onAbrir={() => undefined} mensaje={null} onCerrarMensaje={() => undefined} />
    </MantineProvider>,
  );

  await waitFor(() => expect(screen.getAllByTestId("orden-item")).toHaveLength(2));
  const ids = screen.getAllByTestId("orden-item").map((e) => e.getAttribute("data-orden-id"));
  expect(ids).toEqual(["2", "1"]);
  expect(screen.getByText(/Guardadas, por enviar \(1\)/)).toBeInTheDocument();
  expect(screen.getByText(/Conflicto en 1 trabajo/)).toBeInTheDocument();
  expect(screen.getByText(/fue anulada en la oficina/)).toBeInTheDocument();
});
