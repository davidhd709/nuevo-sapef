// Ejecución de una orden en campo (HU-062): los mismos datos que el cierre web, guardados primero
// en el teléfono (bandeja de salida con uuid) y enviados cuando haya señal.
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Checkbox,
  Divider,
  Group,
  Loader,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { Firma, type FirmaRef } from "../captura/Firma";
import { NotaVoz } from "../captura/NotaVoz";
import {
  comprimirFoto,
  enlaceGoogleMaps,
  extensionAudio,
  NOMBRE_COMPONENTE,
  NOMBRE_TIPO,
  PRIORIDAD,
  tamanoLegible,
  type Capturado,
} from "../comun/captura";
import { useConsulta, useUbicacion } from "../comun/ganchos";
import {
  db,
  leerMeta,
  nuevoUuid,
  type ArchivoLocal,
  type CatalogosCampo,
  type OperacionPendiente,
  type OrdenCampo,
  type TipoEvidencia,
} from "../datos/db";
import { sincronizar, type Sesion } from "../datos/sincronizacion";

const MAX_FOTOS = 5;

interface Evidencia extends Capturado {
  uuid: string;
  tipo: TipoEvidencia;
}

interface MaterialUso {
  material_id: number;
  cantidad: number;
}

export function PantallaOrden({
  ordenId,
  sesion,
  onVolver,
}: {
  ordenId: number;
  sesion: Sesion;
  onVolver: (mensaje?: string) => void;
}) {
  // null: cargando; undefined: la orden ya no está en el teléfono.
  const orden = useConsulta<OrdenCampo | null | undefined>(
    () => db.ordenes.get(ordenId),
    [ordenId],
    null,
  );
  const pendiente = useConsulta(
    () => db.outbox.where("ordenId").equals(ordenId).filter((p) => p.usuarioId === sesion.usuarioId && p.sede === sesion.sede).first(),
    [ordenId, sesion.usuarioId, sesion.sede],
    undefined,
  );
  const catalogos = useConsulta(
    () => leerMeta<CatalogosCampo>("catalogos"),
    [],
    undefined as CatalogosCampo | undefined,
  );
  const materiales = useConsulta(() => db.materiales.toArray(), [], []);
  const bodega = useConsulta(() => db.bodega.orderBy("codigo").toArray(), [], []);
  const { ubicacion, error: errorGps } = useUbicacion(true);

  // Mantenimiento
  const [sitio, setSitio] = useState("");
  const [quienRecibe, setQuienRecibe] = useState("");
  const [observacionTecnica, setObservacionTecnica] = useState("");
  const [componentes, setComponentes] = useState<Record<string, boolean>>({});
  const [requiereDesmonte, setRequiereDesmonte] = useState(false);
  const [causal, setCausal] = useState("");
  const [reemplazo, setReemplazo] = useState<string | null>(null);
  // Instalación (expansión, modernización, reubicación)
  const [tipoValor, setTipoValor] = useState<string | null>(null);
  const [barrio, setBarrio] = useState<string | null>(null);
  const [marca, setMarca] = useState<string | null>(null);
  const [poste, setPoste] = useState("");
  const [brazo, setBrazo] = useState<number | string>("");
  const [referencia, setReferencia] = useState("");
  const [novedades, setNovedades] = useState("");
  // Común
  const [destino, setDestino] = useState<string | null>(null);
  const [observaciones, setObservaciones] = useState("");
  const [usos, setUsos] = useState<MaterialUso[]>([]);
  const [materialSel, setMaterialSel] = useState<string | null>(null);
  const [cantidadSel, setCantidadSel] = useState<number | string>(1);
  const [evidencias, setEvidencias] = useState<Evidencia[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);

  // Las fotos se comprimen en segundo plano; al guardar se espera a que terminen.
  const evidenciasRef = useRef<Evidencia[]>([]);
  const procesando = useRef(new Set<Promise<void>>());
  const firmaTecnico = useRef<FirmaRef>(null);
  const firmaRecibe = useRef<FirmaRef>(null);
  const camara = useRef<HTMLInputElement>(null);
  const galeria = useRef<HTMLInputElement>(null);
  const audioArchivo = useRef<HTMLInputElement>(null);

  const esMantenimiento = orden?.tipo === "mantenimiento";
  const tieneDesmontada = Boolean(orden?.luminarias.some((l) => l.rol === "desmontada"));

  useEffect(() => {
    if (catalogos && Object.keys(componentes).length === 0) {
      setComponentes(Object.fromEntries(catalogos.componentes.map((c) => [c, true])));
    }
  }, [catalogos, componentes]);

  useEffect(() => {
    if (orden && barrio === null) {
      const b = orden.luminarias.find((l) => l.barrio_id)?.barrio_id;
      if (b) setBarrio(String(b));
    }
  }, [orden, barrio]);

  const opcionesTipo = useMemo(() => {
    const lista =
      orden?.tipo === "expansion" ? catalogos?.tipos_expansion : catalogos?.tipos_modernizacion;
    return (lista ?? []).map((v) => ({ value: String(v.id), label: v.nombre }));
  }, [orden?.tipo, catalogos]);

  const agregarEvidencia = (e: Evidencia) => {
    evidenciasRef.current = [...evidenciasRef.current, e];
    setEvidencias(evidenciasRef.current);
  };

  const quitarEvidencia = (uuid: string) => {
    evidenciasRef.current = evidenciasRef.current.filter((e) => e.uuid !== uuid);
    setEvidencias(evidenciasRef.current);
  };

  const enSegundoPlano = (tarea: Promise<void>) => {
    procesando.current.add(tarea);
    void tarea.finally(() => procesando.current.delete(tarea));
  };

  const alElegirFotos = (lista: FileList | null) => {
    const archivos = Array.from(lista ?? []);
    for (const archivo of archivos) {
      const fotos = evidenciasRef.current.filter((e) => e.tipo === "foto").length;
      if (fotos + procesando.current.size >= MAX_FOTOS) {
        setError(`Máximo ${MAX_FOTOS} fotos por trabajo.`);
        break;
      }
      enSegundoPlano(
        comprimirFoto(archivo).then((c) => agregarEvidencia({ ...c, uuid: nuevoUuid(), tipo: "foto" })),
      );
    }
  };

  const alElegirAudio = (lista: FileList | null) => {
    const archivo = lista?.[0];
    if (!archivo) return;
    agregarEvidencia({
      datos: archivo,
      mime: archivo.type || "audio/mp4",
      nombre: archivo.name || "nota.m4a",
      uuid: nuevoUuid(),
      tipo: "audio",
    });
  };

  const agregarMaterial = () => {
    const id = Number(materialSel);
    const cantidad = Number(cantidadSel);
    if (!id || !(cantidad > 0)) return;
    setUsos((actual) => [...actual.filter((u) => u.material_id !== id), { material_id: id, cantidad }]);
    setMaterialSel(null);
    setCantidadSel(1);
  };

  if (orden === null) return <Loader m="xl" />;
  if (!orden) {
    return (
      <Stack>
        <Alert color="gray">La orden ya no está en este teléfono (enviada, anulada o reasignada).</Alert>
        <Button variant="light" onClick={() => onVolver()}>
          Volver a mis órdenes
        </Button>
      </Stack>
    );
  }

  const guardar = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (guardando) return;
    if (esMantenimiento && requiereDesmonte && !causal.trim()) {
      setError("Indique la causal del desmonte.");
      return;
    }
    if (!esMantenimiento && orden.tipo !== "reubicacion" && !tipoValor) {
      setError(`Elija el tipo de ${NOMBRE_TIPO[orden.tipo]?.toLowerCase()}.`);
      return;
    }
    if (orden.tipo === "expansion" && !barrio) {
      setError("Elija el barrio de la expansión.");
      return;
    }
    if (!esMantenimiento && !tieneDesmontada && !ubicacion) {
      setError("Espere la ubicación GPS: la luminaria nueva necesita coordenadas.");
      return;
    }
    setGuardando(true);
    try {
      await Promise.all([...procesando.current]);
      const opUuid = nuevoUuid();
      const archivos: ArchivoLocal[] = evidenciasRef.current.map((ev) => ({
        uuid: ev.uuid,
        opUuid,
        tipo: ev.tipo,
        nombre: ev.nombre,
        mime: ev.mime,
        datos: ev.datos,
      }));
      for (const [firma, tipo, nombre] of [
        [firmaTecnico, "firma_tecnico", "firma_tecnico.png"],
        [firmaRecibe, "firma_quien_recibe", "firma_quien_recibe.png"],
      ] as const) {
        const png = await firma.current?.obtener();
        if (png) archivos.push({ uuid: nuevoUuid(), opUuid, tipo, nombre, mime: "image/png", datos: png });
      }
      const payload: Record<string, unknown> = {
        observaciones: observaciones.trim() || undefined,
        materiales: usos,
      };
      if (ubicacion) {
        payload.latitud = ubicacion.latitud;
        payload.longitud = ubicacion.longitud;
      }
      if (esMantenimiento) {
        Object.assign(payload, {
          sitio_arreglo: sitio.trim() || undefined,
          quien_recibe: quienRecibe.trim() || undefined,
          observacion_tecnica: observacionTecnica.trim() || undefined,
          componentes,
          requiere_desmonte: requiereDesmonte,
          causal_desmonte: requiereDesmonte ? causal.trim() : undefined,
          destino_desmontada: requiereDesmonte ? (destino ?? undefined) : undefined,
          luminaria_reemplazo_id: requiereDesmonte && reemplazo ? Number(reemplazo) : undefined,
        });
      } else {
        Object.assign(payload, {
          [orden.tipo === "expansion" ? "tipo_expansion_id" : "tipo_modernizacion_id"]: tipoValor
            ? Number(tipoValor)
            : undefined,
          barrio_id: barrio ? Number(barrio) : undefined,
          marca_id: marca ? Number(marca) : undefined,
          poste: poste.trim() || undefined,
          longitud_brazo: brazo === "" ? undefined : Number(brazo),
          referencia: referencia.trim() || undefined,
          novedades: novedades.trim() || undefined,
          comentario: observaciones.trim() || undefined,
          destino_desmontada: tieneDesmontada ? (destino ?? undefined) : undefined,
        });
      }
      const op: OperacionPendiente = {
        uuid: opUuid,
        tipo: orden.tipo,
        ordenId: orden.id,
        ordenNumero: orden.numero,
        creadaEn: new Date().toISOString(),
        payload: JSON.parse(JSON.stringify(payload)) as Record<string, unknown>,
        evidencias: archivos.map((a) => ({ archivoUuid: a.uuid, tipo: a.tipo })),
        sede: sesion.sede,
        usuarioId: sesion.usuarioId,
        intentos: 0,
      };
      await db.transaction("rw", db.outbox, db.archivos, async () => {
        await db.archivos.bulkAdd(archivos);
        await db.outbox.add(op);
      });
      void sincronizar();
      onVolver(
        navigator.onLine
          ? `Orden N.º ${orden.numero} guardada. Enviando…`
          : `Orden N.º ${orden.numero} guardada en el teléfono. Se enviará al volver la señal.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar el trabajo.");
      setGuardando(false);
    }
  };

  const prioridad = PRIORIDAD[orden.prioridad] ?? { texto: String(orden.prioridad), color: "gray" };
  const nombresMaterial = new Map(materiales.map((m) => [m.id, m]));

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="nowrap">
        <Button variant="subtle" size="compact-sm" onClick={() => onVolver()}>
          ← Mis órdenes
        </Button>
        <Badge color={prioridad.color}>{prioridad.texto}</Badge>
      </Group>

      <div>
        <Title order={3}>
          Orden N.º {orden.numero} · {NOMBRE_TIPO[orden.tipo] ?? orden.tipo}
        </Title>
        {orden.observaciones && (
          <Text size="sm" c="dimmed">
            {orden.observaciones}
          </Text>
        )}
      </div>

      <Stack gap="xs">
        {orden.luminarias.map((l) => (
          <Card key={`${l.luminaria_id}-${l.rol}`} withBorder padding="sm">
            <Group justify="space-between" wrap="nowrap">
              <div>
                <Text fw={600}>{l.codigo}</Text>
                <Text size="xs" c="dimmed">
                  {l.rol} · {l.barrio_nombre ?? "sin barrio"}
                  {l.poste ? ` · poste ${l.poste}` : ""} · estado {l.estado_codigo ?? "—"}
                </Text>
              </div>
              {l.latitud != null && l.longitud != null && (
                <Anchor size="xs" href={enlaceGoogleMaps(l.latitud, l.longitud)} target="_blank">
                  Google Maps
                </Anchor>
              )}
            </Group>
          </Card>
        ))}
      </Stack>

      {pendiente ? (
        <Alert color="blue" title="Ya registrada">
          Este trabajo está guardado en el teléfono y se enviará al haber señal.
        </Alert>
      ) : (
        <form onSubmit={(e) => void guardar(e)} noValidate>
          <Stack gap="md">
            <Divider label="Ejecución" labelPosition="left" />

            {esMantenimiento ? (
              <>
                <TextInput
                  name="sitio_arreglo"
                  label="Sitio del arreglo"
                  value={sitio}
                  onChange={(e) => setSitio(e.currentTarget.value)}
                />
                <TextInput
                  name="quien_recibe"
                  label="Quién recibe"
                  value={quienRecibe}
                  onChange={(e) => setQuienRecibe(e.currentTarget.value)}
                />
                <Textarea
                  name="observacion_tecnica"
                  label="Observación técnica"
                  autosize
                  minRows={2}
                  value={observacionTecnica}
                  onChange={(e) => setObservacionTecnica(e.currentTarget.value)}
                />
                <div>
                  <Text size="sm" fw={500} mb={4}>
                    Componentes en buen estado (desmarque lo que cambió o falló)
                  </Text>
                  <SimpleGrid cols={2} spacing="xs">
                    {(catalogos?.componentes ?? []).map((c) => (
                      <Checkbox
                        key={c}
                        name={`componente_${c}`}
                        label={NOMBRE_COMPONENTE[c] ?? c}
                        checked={componentes[c] ?? true}
                        onChange={(e) => {
                          const marcado = e.currentTarget.checked;
                          setComponentes((a) => ({ ...a, [c]: marcado }));
                        }}
                      />
                    ))}
                  </SimpleGrid>
                </div>
                <Switch
                  label="Requiere desmonte"
                  checked={requiereDesmonte}
                  onChange={(e) => setRequiereDesmonte(e.currentTarget.checked)}
                />
                {requiereDesmonte && (
                  <>
                    <TextInput
                      name="causal_desmonte"
                      label="Causal del desmonte"
                      required
                      value={causal}
                      onChange={(e) => setCausal(e.currentTarget.value)}
                    />
                    <Select
                      label="Destino de la luminaria desmontada"
                      data={(catalogos?.destinos_desmontada ?? []).map((d) => ({
                        value: d.codigo,
                        label: d.nombre,
                      }))}
                      value={destino}
                      onChange={setDestino}
                      placeholder="Desmontada (por defecto)"
                      clearable
                    />
                    <Select
                      label="Reemplazar por (luminaria de bodega)"
                      data={bodega.map((b) => ({ value: String(b.id), label: b.codigo }))}
                      value={reemplazo}
                      onChange={setReemplazo}
                      searchable
                      clearable
                      nothingFoundMessage="No hay luminarias en bodega buena"
                    />
                  </>
                )}
              </>
            ) : (
              <>
                {orden.tipo !== "reubicacion" && (
                  <Select
                    label={`Tipo de ${NOMBRE_TIPO[orden.tipo]?.toLowerCase()}`}
                    data={opcionesTipo}
                    value={tipoValor}
                    onChange={setTipoValor}
                    required
                  />
                )}
                <Select
                  label="Barrio"
                  data={(catalogos?.barrios ?? []).map((b) => ({
                    value: String(b.id),
                    label: `${b.nombre} (${b.zona_nombre})`,
                  }))}
                  value={barrio}
                  onChange={setBarrio}
                  searchable
                  required={orden.tipo === "expansion"}
                />
                <Select
                  label="Marca"
                  data={(catalogos?.marcas ?? []).map((m) => ({ value: String(m.id), label: m.nombre }))}
                  value={marca}
                  onChange={setMarca}
                  searchable
                  clearable
                />
                <Group grow>
                  <TextInput
                    name="poste"
                    label="Número de poste"
                    value={poste}
                    onChange={(e) => setPoste(e.currentTarget.value)}
                  />
                  <NumberInput
                    name="longitud_brazo"
                    label="Brazo (m)"
                    min={0}
                    decimalScale={2}
                    value={brazo}
                    onChange={setBrazo}
                  />
                </Group>
                {orden.tipo === "reubicacion" && (
                  <>
                    <TextInput
                      name="referencia"
                      label="Referencia"
                      value={referencia}
                      onChange={(e) => setReferencia(e.currentTarget.value)}
                    />
                    <Textarea
                      name="novedades"
                      label="Novedades"
                      autosize
                      value={novedades}
                      onChange={(e) => setNovedades(e.currentTarget.value)}
                    />
                  </>
                )}
                {tieneDesmontada && (
                  <Select
                    label="Destino de la luminaria desmontada"
                    data={(catalogos?.destinos_desmontada ?? []).map((d) => ({
                      value: d.codigo,
                      label: d.nombre,
                    }))}
                    value={destino}
                    onChange={setDestino}
                    placeholder="Desmontada (por defecto)"
                    clearable
                  />
                )}
              </>
            )}

            <Textarea
              name="observaciones"
              label="Observaciones"
              autosize
              minRows={2}
              value={observaciones}
              onChange={(e) => setObservaciones(e.currentTarget.value)}
            />

            <Divider label="Materiales" labelPosition="left" />
            <Group align="end" wrap="nowrap">
              <Select
                style={{ flex: 1 }}
                label="Material"
                data={materiales.map((m) => ({
                  value: String(m.id),
                  label: `${m.descripcion} (${m.codigo})`,
                }))}
                value={materialSel}
                onChange={setMaterialSel}
                searchable
                clearable
              />
              <NumberInput w={90} label="Cant." min={0.001} value={cantidadSel} onChange={setCantidadSel} />
              <Button variant="light" onClick={agregarMaterial} disabled={!materialSel}>
                Agregar
              </Button>
            </Group>
            {usos.map((u) => {
              const m = nombresMaterial.get(u.material_id);
              const pocas = m && Number(m.existencias) < u.cantidad;
              return (
                <Group key={u.material_id} justify="space-between" wrap="nowrap">
                  <Text size="sm">
                    {m?.descripcion ?? u.material_id}: {u.cantidad} {m?.unidad}
                    {pocas && (
                      <Text span size="xs" c="orange">
                        {" "}
                        (la bodega reporta {m?.existencias})
                      </Text>
                    )}
                  </Text>
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    aria-label="Quitar material"
                    onClick={() => setUsos((a) => a.filter((x) => x.material_id !== u.material_id))}
                  >
                    ×
                  </ActionIcon>
                </Group>
              );
            })}

            <Divider label="Evidencias" labelPosition="left" />
            <input
              ref={camara}
              type="file"
              accept="image/*"
              capture="environment"
              hidden
              onChange={(e) => {
                alElegirFotos(e.currentTarget.files);
                e.currentTarget.value = "";
              }}
            />
            <input
              ref={galeria}
              type="file"
              accept="image/*"
              multiple
              hidden
              onChange={(e) => {
                alElegirFotos(e.currentTarget.files);
                e.currentTarget.value = "";
              }}
            />
            <input
              ref={audioArchivo}
              type="file"
              accept="audio/*"
              hidden
              onChange={(e) => {
                alElegirAudio(e.currentTarget.files);
                e.currentTarget.value = "";
              }}
            />
            <Group gap="xs">
              <Button variant="light" onClick={() => camara.current?.click()}>
                Tomar foto
              </Button>
              <Button variant="default" onClick={() => galeria.current?.click()}>
                Galería
              </Button>
              <Button variant="default" onClick={() => audioArchivo.current?.click()}>
                Adjuntar audio
              </Button>
            </Group>
            <NotaVoz
              onGrabada={(datos, mime) =>
                agregarEvidencia({
                  datos,
                  mime,
                  nombre: `nota_voz.${extensionAudio(mime)}`,
                  uuid: nuevoUuid(),
                  tipo: "audio",
                })
              }
            />
            {evidencias.map((ev) => (
              <Group key={ev.uuid} justify="space-between" wrap="nowrap">
                <Text size="sm">
                  {ev.tipo === "audio" ? "Audio" : "Foto"} · {ev.nombre} ({tamanoLegible(ev.datos.size)})
                </Text>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  aria-label="Quitar evidencia"
                  onClick={() => quitarEvidencia(ev.uuid)}
                >
                  ×
                </ActionIcon>
              </Group>
            ))}
            <Firma ref={firmaTecnico} etiqueta="Firma del técnico" />
            <Firma ref={firmaRecibe} etiqueta="Firma de quien recibe" />

            <Text size="xs" c={ubicacion ? "teal" : "dimmed"}>
              {ubicacion
                ? `Ubicación GPS: ±${Math.round(ubicacion.precision)} m`
                : (errorGps ?? "Buscando señal GPS…")}
            </Text>

            {error && (
              <Alert color="red" variant="light">
                {error}
              </Alert>
            )}
            <Button type="submit" size="lg" fullWidth loading={guardando}>
              Guardar trabajo
            </Button>
          </Stack>
        </form>
      )}
    </Stack>
  );
}
