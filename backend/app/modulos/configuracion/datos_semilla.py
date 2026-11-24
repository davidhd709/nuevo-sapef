"""Datos semilla de configuración (catálogos reales de SAPEF Montelíbano y OPainn, §13).

Solo catálogos sin datos personales. La semilla es idempotente: crea lo que falte por su
llave natural y **no modifica** lo que ya existe (lo puede haber editado el administrador).

Pendientes conocidos:
- Zonas y barrios de Alcalá: saldrán de la exportación de su SAPEF (SPIKE-03).
- Excepciones tarifarias (contribuyentes especiales): los NIC vienen del catálogo privado
  de OPainn o de la exportación de SAPEF; no van en el repositorio.
- «Entra al cálculo» de conceptos y operaciones: solo CI400 marcado; confirmar contra SAPEF.
"""

from decimal import Decimal

SEDES: tuple[dict[str, str], ...] = (
    {
        "codigo": "montelibano",
        "nombre": "Montelíbano",
        "municipio": "Montelíbano",
        "departamento": "Córdoba",
    },
    {
        "codigo": "alcala",
        "nombre": "Alcalá",
        "municipio": "Alcalá",
        "departamento": "Valle del Cauca",
    },
)

# codigo -> (nombre, identificador del usuario en sus archivos, regla tarifaria, periodicidad)
COMERCIALIZADORES: dict[str, tuple[str, str, str | None, str]] = {
    "afinia": ("Afinia", "nic", "afinia_ci400", "mensual"),
    "celsia": ("Celsia", "cuenta", "celsia_impuesto", "bimestral"),
    # Vatia: sin control tarifario (decisión del 7-nov-2026).
    "vatia": ("Vatia", "cliente", None, "mensual"),
}

SEDE_COMERCIALIZADORES: dict[str, tuple[str, ...]] = {
    "montelibano": ("afinia",),
    "alcala": ("celsia", "vatia"),
}

# --- Maestros (RF-010) ---------------------------------------------------------------

_POTENCIAS_W = (
    0, 4, 5, 6, 8, 9, 10, 12, 15, 16, 25, 30, 35, 40, 45, 50, 55, 60, 65, 66, 70, 71, 75,
    80, 83, 90, 100, 114, 120, 150, 160, 180, 200, 240, 250, 300, 400, 500, 1000,
)

# clase -> (nombre de la clase, valores (codigo, nombre))
MAESTROS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "LUMINARIA_TECNOLOGIA": (
        "Tecnologías de luminaria",
        (
            ("LED", "LED"),
            ("LED_SOLAR", "LED solar"),
            ("SODIO", "Sodio"),
            ("METAL_HALIDE", "Metal halide"),
            ("INDUCCION", "Inducción"),
            ("MIXTA", "Mixta"),
            ("AHORRADORA", "Ahorradora"),
        ),
    ),
    "LUMINARIA_MARCA": (
        "Marcas de luminaria",
        (
            ("AEL", "AEL"),
            ("ANDILUM", "Andilum"),
            ("ASSIC", "Assic"),
            ("CELSA", "Celsa"),
            ("ECOLITE", "Ecolite"),
            ("ELECTROCONTROL", "Electrocontrol"),
            ("ENERLUZ", "Enerluz"),
            ("KARLUZ", "Karluz"),
            ("KUNIX", "Künix"),
            ("LEDVANCE", "Ledvance"),
            ("MERCURY", "Mercury"),
            ("PHILIPS", "Philips"),
            ("PROCONTROL", "Procontrol"),
            ("SCHREDER", "Schréder"),
            ("SYLVANIA", "Sylvania"),
            ("SINOZOC", "Sinozoc"),
            ("OTRA", "Otra"),
            ("TEMPORAL", "Temporal"),
        ),
    ),
    "LUMINARIA_POTENCIA": (
        "Potencias de luminaria (W)",
        tuple((str(w), f"{w} W") for w in _POTENCIAS_W),
    ),
    "TIPO_INTERVENCION": (
        "Tipos de intervención",
        (
            ("BODEGA", "Bodega"),
            ("CHATARRIZADA", "Chatarrizada"),
            ("EXPANSION", "Expansión"),
            ("EXPANSION_COMPLEMENTARIA", "Expansión complementaria"),
            ("EXPANSION_PRIORITARIA", "Expansión prioritaria"),
            ("EXPANSION_VEGETATIVA", "Expansión vegetativa"),
            ("MODERNIZACION", "Modernización"),
            ("MODERNIZACION_COMPLEMENTARIA", "Modernización complementaria"),
            ("MODERNIZACION_PRIORITARIA", "Modernización prioritaria"),
            ("RECIBO_INICIAL", "Recibo inicial"),
            ("REUBICADA", "Reubicada"),
        ),
    ),
    "TIPO_EXPANSION": (
        "Tipos de expansión",
        (
            ("COMPLEMENTARIA", "Complementaria"),
            ("PRIORITARIA", "Prioritaria"),
            ("VEGETATIVA", "Vegetativa"),
        ),
    ),
    "TIPO_MODERNIZACION": (
        "Tipos de modernización",
        (("COMPLEMENTARIA", "Complementaria"), ("PRIORITARIA", "Prioritaria")),
    ),
    "ACCION_OPERATIVA": (
        "Acción operativa",
        (
            ("ACTIVO_PQR", "Activo PQR"),
            ("BODEGA_BUENA", "Bodega buena"),
            ("BODEGA_DF", "Bodega disposición final"),
            ("REUBICADA", "Reubicada"),
            ("STAND_BY_GARANTIA", "Stand by garantía"),
            ("GARANTIA_PROVEEDOR", "Garantía proveedor"),
            ("POR_DIAGNOSTICAR", "Por diagnosticar"),
        ),
    ),
    "MISION_OBJETIVO": (
        "Misión u objetivo",
        (
            ("EXPANSION_COMPLEMENTARIA", "Expansión complementaria"),
            ("EXPANSION_PRIORITARIA", "Expansión prioritaria"),
            ("EXPANSION_VEGETATIVA", "Expansión vegetativa"),
            ("MODERNIZACION_COMPLEMENTARIA", "Modernización complementaria"),
            ("MODERNIZACION_PRIORITARIA", "Modernización prioritaria"),
            ("MANTENIMIENTO", "Mantenimiento"),
        ),
    ),
    "COMPONENTE_MANTENIMIENTO": (
        "Componentes del mantenimiento",
        (
            ("CONEXION_RED", "Conexión a red"),
            ("CONEXION_INTERNA", "Conexión interna"),
            ("BASE_FOTOCELDA", "Base de fotocelda"),
            ("FOTOCELDA", "Fotocelda"),
            ("BOMBILLO", "Bombillo"),
            ("SOCKET", "Socket"),
            ("ARRANCADOR", "Arrancador"),
            ("CONDENSADOR", "Condensador"),
            ("BALASTA", "Balasta"),
            ("TUBO", "Tubo"),
            ("COLLARIN", "Collarín"),
            ("CONECTORES_PERFORACION", "Conectores de perforación"),
        ),
    ),
    # El orden es la prioridad numérica (0 = urgente) que usa la PQRS.
    "PRIORIDAD_PQRS": (
        "Prioridades de PQRS",
        (("URGENTE", "Urgente"), ("ALTA", "Alta"), ("MEDIA", "Media"), ("BAJA", "Baja")),
    ),
    "CANAL_PQRS": (
        "Canales de PQRS",
        (
            ("WHATSAPP", "WhatsApp"),
            ("PRESENCIAL", "Presencial"),
            ("TELEFONO", "Teléfono"),
            ("CORREO", "Correo"),
        ),
    ),
    "TIPO_MOVIMIENTO_MATERIAL": (
        "Tipos de movimiento de material",
        (
            ("ENTRADA_ALMACEN", "Entrada almacén"),
            ("SALIDA_ALMACEN", "Salida almacén"),
            ("AJUSTE", "Ajuste"),
        ),
    ),
    "TIPO_ACTIVO": (
        "Tipos de activo",
        (
            ("POSTES", "Postes"),
            ("TRANSFORMADORES", "Transformadores"),
            ("PERSONAL", "Personal"),
            ("HERRAMIENTA", "Herramienta"),
            ("REDES", "Redes"),
            ("CAJAS", "Cajas"),
            ("PANELES_SOLARES", "Paneles solares"),
            ("BRAZOS", "Brazos"),
            ("OTROS", "Otros"),
        ),
    ),
    "TIPO_EVENTO": (
        "Tipos de evento del calendario",
        (
            ("HORA_EXTRA", "Hora extra"),
            ("PQRS", "PQRS"),
            ("TAREA", "Tarea"),
            ("REUNION", "Reunión"),
            ("LLAMADA", "Llamada"),
        ),
    ),
    "CONDICION_ATMOSFERICA": (
        "Condiciones atmosféricas",
        (
            ("DESPEJADO", "Despejado"),
            ("NUBLADO", "Nublado"),
            ("LLUVIOSO", "Lluvioso"),
            ("NEBLINA", "Neblina"),
        ),
    ),
    "TIPO_APOYO": (
        "Tipos de apoyo",
        (
            ("POSTE_CONCRETO", "Poste de concreto"),
            ("POSTE_FIBRA", "Poste de fibra"),
            ("POSTE_METALICO", "Poste metálico"),
            ("MURO", "Muro"),
            ("OTRO", "Otro"),
        ),
    ),
    "ANGULO_INCLINACION": (
        "Ángulos de inclinación",
        (("0", "0°"), ("5", "5°"), ("10", "10°"), ("15", "15°")),
    ),
    "DISPOSICION": (
        "Disposición",
        (
            ("UNILATERAL", "Unilateral"),
            ("CENTRAL_DOBLE", "Central doble"),
            ("BILATERAL_ALTERNADA", "Bilateral alternada"),
            ("BILATERAL_OPUESTA_SIN_SEPARADOR", "Bilateral opuesta sin separador"),
            ("BILATERAL_OPUESTA_CON_SEPARADOR", "Bilateral opuesta con separador"),
        ),
    ),
    "TIPO_SERVICIO_COBERTURA": (
        "Tipos de servicio de cobertura",
        (("VIA", "Vía"), ("PARQUE", "Parque")),
    ),
    "CARACTERISTICA_COBERTURA": (
        "Características de cobertura",
        (("SENCILLA", "Sencilla"), ("DOBLE", "Doble"), ("MULTIPLE", "Múltiple")),
    ),
}

# Variantes vistas en los datos de SAPEF -> código del maestro (para los importadores).
# SILVANIA -> SYLVANIA está [por confirmar con la sede].
ALIAS_MAESTROS: dict[str, dict[str, str]] = {
    "LUMINARIA_TECNOLOGIA": {"MH": "METAL_HALIDE"},
    "LUMINARIA_MARCA": {
        "KÜNIX": "KUNIX",
        "SCHRÉDER": "SCHREDER",
        "SHRÉDER": "SCHREDER",
        "SHREDER": "SCHREDER",
        "SILVANIA": "SYLVANIA",
    },
}

# --- Estados por proceso (RF-012, §10.2) -----------------------------------------------
# proceso -> (codigo, nombre, final, vigente). Los no vigentes solo sirven para migrar.
ESTADOS: dict[str, tuple[tuple[str, str, bool, bool], ...]] = {
    "luminaria": (
        ("121", "Activo en operación", False, True),
        ("122", "Activo PQR", False, True),
        ("124", "Bodega buena", False, True),
        ("123", "Bodega de baja", False, True),
        ("125", "Bodega en garantía", False, True),
        ("112", "Desmontada", False, True),
        ("126", "Disposición final", True, True),
        ("127", "Otros", False, True),
        # 110 lo usa la luminaria comodín «sin identificar» (RN-016).
        ("110", "Sin identificar", False, True),
        ("101", "Bueno", False, False),
        ("102", "Apagada", False, False),
        ("103", "Intermitente", False, False),
        ("104", "Sulfatada", False, False),
        ("105", "Directa 24 h", False, False),
        ("106", "Desconectada", False, False),
        ("107", "Colgando", False, False),
        ("108", "Robada / desaparecida", False, False),
        ("109", "Dañada por accidente", False, False),
        ("111", "Requiere poda", False, False),
        ("113", "Chatarrizada", True, False),
        ("120", "Reubicación", False, False),
    ),
    "pqrs": (
        ("301", "En elaboración", False, True),
        ("302", "En proceso", False, True),
        ("305", "En mantenimiento", False, True),
        ("303", "Atendida", True, True),
        ("304", "Anulado", True, True),
    ),
    "orden": (
        ("201", "En elaboración", False, True),
        ("202", "En proceso", False, True),
        ("205", "En mantenimiento", False, True),
        ("203", "Cerrado", True, True),
        ("204", "Anulado", True, True),
    ),
    "solicitud": (
        ("401", "En elaboración", False, True),
        ("402", "En proceso", False, True),
        ("403", "Atendida", True, True),
        ("404", "Anulado", True, True),
    ),
}

# --- Zonas y barrios (RF-011, §13.3) -------------------------------------------------------
# Se cargan tal cual; los posibles duplicados de §13.3 se depuran con la sede antes de migrar.
ZONAS_BARRIOS: dict[str, dict[str, tuple[str, ...]]] = {
    "montelibano": {
        "Centro": (
            "El Centro", "San Felipe", "Pablo VI Primera Etapa", "Pablo VI Segunda Etapa",
            "Obrero Comunal", "Buenaventura", "Piñalito", "La Paz", "Calle 16",
        ),
        "Centro Occidente": ("11 de noviembre", "Loma Fresca", "Ancízar Flórez"),
        "Centro Oriente": (
            "La Libertad", "El Mirador", "Musa Náder 1 etapa", "Musa Náder 2 Etapa",
            "Altos del Líbano", "El Recreo", "Unidad Vecinal el Recreo", "San Jorge",
            "Nuevo Horizonte", "San Carlos", "Veintisiete de Julio",
            "Avenida de Los Estudiantes", "AV DE LOS ESTUDIANTES",
        ),
        "Ciudadelas Cerro Matoso": ("Paimaná", "Tacasaluma", "Jagua", "Jaraguay"),
        "Noroccidente": (
            "La Pesquera", "Muchajagua", "La Esperanza", "Avenida Ancizar Flórez",
        ),
        "Nororiente": (
            "La Candelaria 2 Etapa", "San Isidro", "Los Laureles", "San Bernardo",
            "San Gregorio", "El Campestre", "El Triángulo",
        ),
        "Norte": (
            "La Candelaria 1 Etapa", "Villa Florida", "La Lucha", "Villa Matoso", "San Luis",
            "San José", "Tierra Grata", "Vía Industrial", "Vía El Pindo",
        ),
        "Rurales": (
            "Los Córdobas", "El Anclar", "El Palmar", "Las Margaritas", "Pica Pica Nuevo",
            "Puerto Ánchica", "Puerto Nuevo", "San Francisco del Rayo", "Tierradentro",
            "Villa Carminia", "BOCAS DE SAN MATEO",
        ),
        "Sur": (
            "San Francisco", "El Paraíso", "Corina Uribe", "Villa Marcela", "La Unión",
            "César Cura", "San Rafael", "Villa Mery", "Villa Carriazo", "Porvenir",
            "Villa del Rosario", "Villa Delfa", "La Fe", "Porvenir Inurbe", "Belén",
            "Villa Clemen", "El 50", "Vía Altomira", "LA LUCHA", "Villa Olimpica",
            "Sitio Nuevo",
        ),
        "Suroccidente": (
            "Por ti Montelíbano", "Marcella", "Cancún", "Villa Hermosa", "Calle 15",
        ),
        "Suroriente": (
            "Altomira", "El Tiempo", "Valle Lindo", "Santa Mónica", "Portal de Alcalá",
            "Urbanización El Camino Correcto", "La Victoria", "Emmanuel", "Brisas del Sur",
            "Poblado 1", "Poblado 2", "Emanuel", "27 de Julio", "VILLA MARCELLA", "El Triunfo",
        ),
    },
}

# --- Parámetros (RF-013) -------------------------------------------------------------------
# codigo -> (nombre, valor, editable). Ninguna credencial: esas van en variables de entorno.
PARAMETROS_POR_SEDE: dict[str, tuple[str, object, bool]] = {
    # [PENDIENTE P-12] valores provisionales de §9.4: verde ≤ 3 días, amarillo 4–7, rojo > 7.
    "semaforo_pqrs_umbrales": (
        "Umbrales del semáforo de luminarias pendientes (días)",
        {"verde_max_dias": 3, "amarillo_max_dias": 7},
        True,
    ),
    # §11.12: si un anexo nominal pasa de este tope, la descarga se detiene (no se recorta).
    "comercial_anexo_max_filas": (
        "Máximo de filas por hoja del anexo nominal comercial",
        50000,
        True,
    ),
}

# Parámetros globales informativos: su valor lo fija la configuración del servidor
# (variable de entorno) y la semilla lo actualiza en cada ejecución.
PARAMETROS_SISTEMA: dict[str, str] = {
    "archivo_tamano_max_evidencia_mb": "Tamaño máximo de una evidencia (MiB)",
}

# --- Plantillas de correo (RF-014, §13.4) --------------------------------------------------
# codigo -> (nombre, asunto, cuerpo_html, variables)
PLANTILLAS_CORREO: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "MAIL_RECUPERAR_CUENTA": (
        "Recuperación de cuenta",
        "Recuperación de su contraseña",
        "<p>Hola {{nombre}}:</p>"
        "<p>Recibimos una solicitud para restablecer su contraseña. Use este enlace; vence "
        "en {{minutos_validez}} minutos y solo sirve una vez:</p>"
        '<p><a href="{{enlace}}">Restablecer contraseña</a></p>'
        "<p>Si usted no lo pidió, ignore este mensaje.</p>",
        ("nombre", "enlace", "minutos_validez"),
    ),
    "MAIL_PQRS": (
        "Nueva PQRS",
        "Su solicitud {{numero}} fue registrada",
        "<p>Hola {{nombre}}:</p>"
        "<p>Registramos su solicitud número <strong>{{numero}}</strong> el {{fecha}}. "
        "Estado actual: {{estado}}.</p>",
        ("nombre", "numero", "fecha", "estado"),
    ),
    "MAIL.MANTENIMIENTO_LUMINARIA": (
        "Mantenimiento de luminaria",
        "Atendimos su solicitud {{numero}}",
        "<p>Hola {{nombre}}:</p>"
        "<p>El {{fecha}} realizamos el mantenimiento de la luminaria {{luminaria}} "
        "reportada en su solicitud <strong>{{numero}}</strong>.</p>",
        ("nombre", "numero", "luminaria", "fecha"),
    ),
    "MAIL.INSTALACION_LUMINARIA": (
        "Instalación de luminaria",
        "Instalamos la luminaria {{luminaria}}",
        "<p>Hola {{nombre}}:</p>"
        "<p>El {{fecha}} instalamos la luminaria {{luminaria}} en el barrio {{barrio}}.</p>",
        ("nombre", "luminaria", "barrio", "fecha"),
    ),
}

# --- Acuerdos tarifarios 2026 (RF-015, §11.6 y §11.7) -------------------------------------

TARIFAS_AFINIA_2026: tuple[tuple[str, Decimal, Decimal], ...] = (
    # tarifa canónica, factor UVT mínimo, % del costo variable (como fracción)
    ("AP_Comerciales_Nivel_1", Decimal("0.30"), Decimal("0.12")),
    ("AP_Comerciales_Nivel_2", Decimal("0.30"), Decimal("0.12")),
    ("AP_Industriales_Nivel_1", Decimal("0.30"), Decimal("0.12")),
    ("AP_Industriales_Nivel_2", Decimal("0.30"), Decimal("0.12")),
    ("AP_Oficiales_Nivel_1", Decimal("0.30"), Decimal("0.12")),
    ("AP_Oficiales_Nivel_2", Decimal("0.30"), Decimal("0.12")),
    ("AP_Residenciales_Estrato_1", Decimal("0.04"), Decimal("0.02")),
    ("AP_Residenciales_Estrato_2", Decimal("0.06"), Decimal("0.03")),
    ("AP_Residenciales_Estrato_3", Decimal("0.07"), Decimal("0.04")),
    ("AP_Residenciales_Estrato_4", Decimal("0.09"), Decimal("0.05")),
    ("AP_Residenciales_Estrato_5", Decimal("0.12"), Decimal("0.06")),
    ("AP_Residenciales_Estrato_6", Decimal("0.14"), Decimal("0.07")),
)

# tarifa, tipo de regla, % del VCE (fracción), valor urbano, valor rural
# Los nombres de tarifa de Celsia son [PROPUESTA]: alinear con OPainn en SPIKE-04.
TARIFAS_CELSIA_2026: tuple[
    tuple[str, str, Decimal | None, Decimal | None, Decimal | None], ...
] = (
    ("RESIDENCIAL_ESTRATO_1", "fija", None, Decimal("3994.50"), Decimal("2349.20")),
    ("RESIDENCIAL_ESTRATO_2", "fija", None, Decimal("7989.00"), Decimal("2349.20")),
    ("RESIDENCIAL_ESTRATO_3", "mayor_porcentaje_minimo", Decimal("0.10"),
     Decimal("13205.16"), Decimal("10564.99")),
    ("RESIDENCIAL_ESTRATO_4", "mayor_porcentaje_minimo", Decimal("0.10"),
     Decimal("20417.51"), Decimal("16333.15")),
    ("RESIDENCIAL_ESTRATO_5", "mayor_porcentaje_minimo", Decimal("0.10"),
     Decimal("26074.42"), Decimal("20860.39")),
    ("RESIDENCIAL_ESTRATO_6", "mayor_porcentaje_minimo", Decimal("0.10"),
     Decimal("31908.91"), Decimal("25526.70")),
    ("NO_RESIDENCIAL_NIVEL_1", "mayor_porcentaje_minimo", Decimal("0.10"),
     Decimal("18228.77"), Decimal("16405.90")),
    ("SERVICIOS_ESPECIALES", "porcentaje", Decimal("0.15"), None, None),
)

ACUERDOS_2026: tuple[dict[str, object], ...] = (
    {
        "sede": "montelibano",
        "comercializador": "afinia",
        "anio": 2026,
        "uvt": Decimal("52374"),
        "umbral_kwh": Decimal("173"),
        "tolerancia": Decimal("1.00"),
        "base_costo_variable": "valor_consumo_antes",
        "reglas": {},
        "fuente": "Parámetros vigentes en OPainn para Montelíbano/Afinia 2026 (§11.6)",
        "tarifas": [
            {"tarifa": t, "factor_uvt_minimo": f, "porcentaje_costo_variable": p}
            for t, f, p in TARIFAS_AFINIA_2026
        ],
    },
    {
        "sede": "alcala",
        "comercializador": "celsia",
        "anio": 2026,
        "uvt": None,
        "umbral_kwh": None,
        "tolerancia": Decimal("100.00"),
        "base_costo_variable": "vce",
        "reglas": {"topes_se_duplican_en_bimestral": True},
        "fuente": "Carta municipal «Actualización tarifas» del 14-01-2026 (§11.7)",
        "tarifas": [
            {
                "tarifa": t,
                "tipo_regla": r,
                "porcentaje_costo_variable": p,
                "valor_urbano": u,
                "valor_rural": ru,
            }
            for t, r, p, u, ru in TARIFAS_CELSIA_2026
        ],
    },
)

# --- Catálogos comerciales de Afinia (§13.5) -----------------------------------------------
# codigo -> descripcion. Solo CI400 entra al cálculo (control tarifario); CI401 y CI851
# se publican como señal (§11.6).
CONCEPTOS_AFINIA: dict[str, str] = {
    "CI030": "Total declarado (+)",
    "CI031": "Total declarado (−)",
    "CI032": "Suma real de los recibos cobrados (+)",
    "CI033": "Suma real de los recibos cobrados (−)",
    "CI034": "Importe total de recibo (+)",
    "CI035": "Importe total de recibo (−)",
    "CI036": "Importe parcial pagado de recibo (+)",
    "CI037": "Importe parcial pagado de recibo (−)",
    "CI060": "Importe cobro erróneo (+)",
    "CI061": "Importe cobro erróneo (−)",
    "CI070": "Importe total del cheque",
    "CI100": "Contribución",
    "CI101": "Ajuste a contribución (−)",
    "CI102": "Interés por mora",
    "CI110": "IVA",
    "CI111": "IVA por servicio",
    "CI200": "Cargo fijo",
    "CI202": "Consumo",
    "CI203": "Ajuste a consumo (−)",
    "CI204": "Consumo no regulados",
    "CI206": "Peaje",
    "CI300": "Amortización de cuotas de convenios",
    "CI302": "Intereses de amortización de convenios",
    "CI306": "Cuota de convenio",
    "CI400": "Impuesto alumbrado público",
    "CI401": "Ajuste a impuesto de alumbrado (−)",
    "CI410": "Impuesto aseo",
    "CI420": "Impuesto vigilancia",
    "CI421": "Ajuste impuesto de vigilancia (−)",
    "CI501": "Subsidio",
    "CI503": "Bonificaciones madres comunitarias",
    "CI800": "Servicios varios (+)",
    "CI801": "Servicios varios (−)",
    "CI802": "Instalación de medidores",
    "CI804": "Venta de medidores",
    "CI806": "Venta de otros materiales",
    "CI808": "Reconexiones",
    "CI810": "Conexiones",
    "CI812": "Conexiones temporales",
    "CI814": "Expedientes",
    "CI816": "Cargo vario de otros conceptos",
    "CI818": "Factura de importe reducido (+)",
    "CI819": "Factura de importe reducido (−)",
    "CI820": "Fraudes",
    "CI822": "Sanciones varias",
    "CI823": "Descuento por pago de contado fraudes",
    "CI825": "Descuento interés de mora",
    "CI830": "Ajustes varios (+)",
    "CI831": "Ajustes varios (−)",
    "CI832": "Ajuste por redondeo (+)",
    "CI833": "Ajuste por redondeo (−)",
    "CI834": "Anticipos facturados",
    "CI835": "Devolución de anticipos",
    "CI836": "Cuota de garantía provisionales",
    "CI837": "Crédito por pago duplicado",
    "CI839": "Créditos varios",
    "CI841": "Compensación indicador DES de calidad",
    "CI842": "Nota débito compensación DES",
    "CI843": "Compensación indicador FES de calidad",
    "CI844": "Nota débito compensación FES",
    "CI845": "Crédito terceros",
    "CI848": "Débito terceros",
    "CI851": "Ajuste por refactura",
    "CI999": "Concepto inactivo",
}
CONCEPTOS_AFINIA_EN_CALCULO: frozenset[str] = frozenset({"CI400"})

OPERACIONES_AFINIA: dict[str, str] = {
    "OC100": "Puesta al cobro de recibos",
    "OC105": "Puesta al cobro: refactura",
    "OC110": "Recaudos – ingresos",
    "OC119": "Recaudos de cuotas – ingresos",
    "OC120": "Recaudos – egresos",
    "OC123": "Recaudos de cuotas – egresos",
    "OC130": "Anulación de facturación",
    "OC135": "Convenios de pago – inclusión de deuda",
    "OC136": "Convenios de pago – exclusión de deuda",
    "OC140": "Anulación de cobro por refacturación (egresos)",
    "OC141": "Anulación de cobro por refacturación (ingresos)",
    "OC142": "Cobro por refacturación (ingresos)",
    "OC143": "Cobro por refacturación (egresos)",
    "OC160": "Recaudos de recibos de anticipos",
    "OC161": "Recaudos de recibos de anticipos",
    "OC170": "Puesta al cobro de recibos de cuotas (TR030)",
    "OC171": "Recaudos de recibos de cuotas (TR030)",
    "OC172": "Recaudos de recibos de cuotas (TR030)",
    "OC200": "Recaudos de cargos varios (cobranza anticipada)",
    "OC201": "Recaudos de cargos varios (cobranza anticipada)",
    "OC202": "Cobro por refacturación – ajuste",
    "OC203": "Anulación de NC por exceso de pago",
    "OC300": "Gestión de cobro (conciliación bancaria)",
    "OC310": "Gestión de cobro (cierre de oficina)",
    "OC600": "Cobro erróneo – inclusión",
    "OC610": "Cobro erróneo – eliminación",
    "OC611": "Cobro erróneo – resolución",
    "OC612": "Cobro erróneo – traspaso",
    "OC613": "Cobro erróneo – faltantes y sobrantes",
    "OC710": "Devoluciones de cheques",
    "OC800": "Recaudos de expedientes – cargos varios",
    "OC810": "Recaudos de expedientes – IVA",
    "OC999": "Operación válida sin peso contable",
}
