// Catálogos (maestros) que usan las pantallas de activos: opciones para listas y nombre por id.
import { api } from "@sapef/api";
import { useQuery } from "@tanstack/react-query";

export function useMaestro(clase: string, habilitado = true) {
  const { data: valores = [] } = useQuery({
    queryKey: ["maestros", clase],
    enabled: habilitado,
    queryFn: async () =>
      (await api.GET("/api/v1/maestros/{clase}", { params: { path: { clase } } })).data ?? [],
  });
  return {
    valores,
    opciones: valores.map((v) => ({ value: String(v.id), label: v.nombre })),
    nombre: (id: number | null | undefined) =>
      id == null ? "—" : (valores.find((v) => v.id === id)?.nombre ?? `#${id}`),
  };
}

/** Fecha sin hora (AAAA-MM-DD) en formato local, sin correrla por la zona horaria. */
export function fechaCorta(valor: string | null | undefined): string {
  if (!valor) return "—";
  const [a, m, d] = valor.slice(0, 10).split("-");
  return a && m && d ? `${d}/${m}/${a}` : valor;
}
