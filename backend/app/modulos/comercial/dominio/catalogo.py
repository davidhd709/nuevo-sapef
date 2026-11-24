"""Catálogo común de análisis (§11.11). Se muestra igual para todos los comercializadores; cada
uno declara el estado de cada análisis y, si no está disponible del todo, la nota que explica por
qué. Agregar un comercializador obliga a declarar los 29."""

from dataclasses import dataclass

from app.modulos.comercial.dominio.modelo import Capacidad


@dataclass(frozen=True)
class Analisis:
    id: str
    grupo: str
    nombre: str
    pregunta: str
    ruta: str  # relativa a /comercial/{comercializador}/analisis
    por_periodo: bool = True


CATALOGO: tuple[Analisis, ...] = (
    Analisis(
        "resumen-indicadores",
        "Resumen",
        "Indicadores del corte",
        "¿Cuánto se facturó, recaudó y queda en cartera, y cómo cambió frente al comparable?",
        "indicadores/{periodo}",
    ),
    Analisis(
        "resumen-flujos",
        "Resumen",
        "Facturación y recaudo por periodo",
        "¿Cómo evolucionan mes a mes?",
        "serie",
        False,
    ),
    Analisis(
        "resumen-eficiencia",
        "Resumen",
        "Eficiencia de recaudo",
        "¿Qué parte de lo facturado se recauda?",
        "eficiencia/{periodo}",
    ),
    Analisis(
        "detalle-indicador",
        "Resumen",
        "Detalle del indicador",
        "¿Qué usuarios hay detrás de cada cifra?",
        "detalle/{periodo}",
    ),
    Analisis(
        "facturacion",
        "Flujos",
        "Facturación",
        "¿Cuántos usuarios y facturas, qué valor y consumo?",
        "facturacion/{periodo}",
    ),
    Analisis(
        "recaudo",
        "Flujos",
        "Recaudo",
        "¿Cuánto se recaudó; corriente y de cartera?",
        "recaudo/{periodo}",
    ),
    Analisis(
        "cartera",
        "Flujos",
        "Cartera",
        "¿Cartera del corte y usuarios con saldo?",
        "cartera/{periodo}",
    ),
    Analisis(
        "cartera-edades",
        "Flujos",
        "Cartera por edades",
        "¿Qué antigüedad tiene la cartera?",
        "cartera-edades/{periodo}",
    ),
    Analisis(
        "concentracion-cartera",
        "Flujos",
        "Concentración de cartera",
        "¿Qué usuarios concentran la cartera?",
        "concentracion/{periodo}",
    ),
    Analisis(
        "movimiento-usuarios",
        "Usuarios",
        "Movimiento de usuarios",
        "¿Nuevos, reintegrados, dejados?",
        "movimientos/{periodo}",
    ),
    Analisis(
        "usuarios-ausentes",
        "Usuarios",
        "Usuarios ausentes",
        "¿Quiénes llevan periodos esperados sin facturarse?",
        "ausencias/{periodo}",
    ),
    Analisis(
        "disminuciones",
        "Usuarios",
        "Disminuciones por usuario",
        "¿Qué usuarios explican las caídas?",
        "disminuciones/{periodo}",
    ),
    Analisis(
        "usuarios-periodicidad",
        "Usuarios",
        "Usuarios por periodicidad",
        "¿Cuántos mensuales y bimestrales?",
        "periodicidad/{periodo}",
    ),
    Analisis(
        "control-tarifario",
        "Hallazgos",
        "Control tarifario AP",
        "¿Lo facturado corresponde a la tarifa vigente?",
        "control-tarifario/{periodo}",
    ),
    Analisis(
        "facturas-revision",
        "Hallazgos",
        "Facturas en revisión",
        "¿Qué facturas tienen irregularidades?",
        "facturas-revision/{periodo}",
    ),
    Analisis(
        "consolidado-anual",
        "Históricos",
        "Consolidado anual",
        "¿Cómo va el año y con qué cobertura de meses?",
        "consolidado-anual",
        False,
    ),
    Analisis(
        "historico-facturacion",
        "Históricos",
        "Histórico de facturación",
        "Variación frente al periodo anterior o al promedio",
        "historico-facturacion",
        False,
    ),
    Analisis(
        "historico-cartera",
        "Históricos",
        "Histórico de cartera",
        "Evolución del saldo corte a corte",
        "historico-cartera",
        False,
    ),
    Analisis(
        "historico-comerciales",
        "Históricos",
        "Histórico de comerciales",
        "Comportamiento de los usuarios comerciales",
        "historico-comerciales",
        False,
    ),
    Analisis(
        "comportamiento-pago",
        "Gestión",
        "Comportamiento de pago",
        "¿Quiénes pagan siempre, a veces o nunca?",
        "comportamiento-pago",
        False,
    ),
    Analisis(
        "maduracion-recaudo",
        "Gestión",
        "Maduración del recaudo",
        "¿Cuánto de lo facturado se recauda en los meses siguientes?",
        "maduracion/{periodo}",
    ),
    Analisis(
        "convenios",
        "Gestión",
        "Convenios",
        "¿Usuarios con convenio o financiación y por qué valor?",
        "convenios/{periodo}",
    ),
    Analisis(
        "convenios-ajustes",
        "Gestión",
        "Convenios y ajustes",
        "Cohortes de convenios y ajustes negativos",
        "convenios-ajustes",
        False,
    ),
    Analisis(
        "rutas-campo",
        "Gestión",
        "Rutas y controles de campo",
        "Rutas de cobro y hallazgos de campo por barrio",
        "rutas-campo/{periodo}",
    ),
    Analisis(
        "segmentacion",
        "Herramientas",
        "Segmentación",
        "Reparto por segmento o estrato",
        "segmentacion/{periodo}",
    ),
    Analisis(
        "comparativo-segmentos",
        "Herramientas",
        "Comparativo segmento/estrato",
        "Cambio de cada segmento entre periodos",
        "comparativo-segmentos/{periodo}",
    ),
    Analisis("barrios", "Herramientas", "Barrios", "Reparto por barrio", "barrios/{periodo}"),
    Analisis(
        "tabla-dinamica",
        "Herramientas",
        "Tabla dinámica",
        "Consolidado completo de indicadores del corte",
        "tabla-dinamica/{periodo}",
    ),
    Analisis(
        "trazabilidad",
        "Herramientas",
        "Trazabilidad por usuario",
        "Historia completa de un usuario",
        "trazabilidad/{identificador}",
        False,
    ),
)

_D = Capacidad("disponible")


def _no(nota: str) -> Capacidad:
    return Capacidad("no_aplica", nota)


def _parcial(nota: str) -> Capacidad:
    return Capacidad("parcial", nota)


CAPACIDADES: dict[str, dict[str, Capacidad]] = {
    "afinia": {
        "cartera-edades": _no(
            "Afinia no entrega la edad de la cartera; use «Maduración del recaudo»."
        ),
        "usuarios-periodicidad": _no("En Afinia todos los usuarios son mensuales."),
    },
    "celsia": {
        "resumen-indicadores": Capacidad(
            "disponible",
            "La comparación usa el periodo esperado de cada usuario (ciclos mensual y bimestral).",
        ),
        "movimiento-usuarios": Capacidad(
            "disponible", "Por periodo esperado: un bimestral fuera de su mes no se cuenta."
        ),
        "convenios": _parcial("Celsia solo informa los conceptos de financiación."),
        "convenios-ajustes": _no("Análisis exclusivo de Afinia (operaciones OC135/CI306)."),
        "rutas-campo": _no("Análisis exclusivo de Afinia."),
        "barrios": _parcial("Celsia trae el barrio solo en la facturación."),
        "historico-comerciales": Capacidad(
            "disponible", "Celsia no distingue niveles comerciales."
        ),
    },
    "vatia": {
        "resumen-indicadores": Capacidad(
            "disponible",
            "Con notas crédito un corte puede quedar negativo; entonces la "
            "eficiencia no se interpreta (null).",
        ),
        "usuarios-periodicidad": _no("En Vatia todos los usuarios son mensuales."),
        "control-tarifario": _no("Sin control tarifario para Vatia (decisión del 7-nov-2026)."),
        "facturas-revision": _no("Vatia entrega una línea por factura; no hay líneas que revisar."),
        "maduracion-recaudo": _no("El archivo de Vatia no permite seguir cada factura."),
        "convenios": _no("Vatia no reporta convenios."),
        "convenios-ajustes": _no("Análisis exclusivo de Afinia."),
        "rutas-campo": _no("Análisis exclusivo de Afinia."),
        "barrios": _no("El archivo de Vatia no trae barrio."),
        "historico-facturacion": Capacidad("disponible", "Por submercado."),
        "historico-cartera": Capacidad("disponible", "Por submercado."),
        "historico-comerciales": Capacidad("disponible", "Por submercado."),
    },
}


def capacidad(comercializador: str, analisis_id: str) -> Capacidad:
    return CAPACIDADES.get(comercializador, {}).get(analisis_id, _D)


def catalogo(comercializador: str) -> list[dict[str, object]]:
    return [
        {
            "id": a.id,
            "grupo": a.grupo,
            "nombre": a.nombre,
            "pregunta": a.pregunta,
            "ruta": f"/api/v1/comercial/{comercializador}/analisis/{a.ruta}",
            "por_periodo": a.por_periodo,
            "estado": capacidad(comercializador, a.id).estado,
            "nota": capacidad(comercializador, a.id).nota,
        }
        for a in CATALOGO
    ]


def exigir_disponible(comercializador: str, analisis_id: str) -> Capacidad:
    from app.modulos.comercial.dominio.comun import ErrorDominioComercial

    cap = capacidad(comercializador, analisis_id)
    if cap.estado == "no_aplica":
        raise ErrorDominioComercial(
            422, cap.nota or "El análisis no aplica a este comercializador."
        )
    return cap
