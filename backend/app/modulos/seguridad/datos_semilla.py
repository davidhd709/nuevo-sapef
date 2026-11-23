"""Datos semilla de seguridad: catálogo de permisos (§4.3) y roles iniciales (§4.2).

Solo datos, sin dependencias. Los roles son la propuesta inicial de la matriz §4.2
[PENDIENTE validar con el dueño]: la semilla crea los que falten y **no toca** los roles
que ya existen (el administrador puede haberlos ajustado), salvo ADMIN, que siempre
recibe todos los permisos del catálogo.
"""

# (codigo, modulo, descripcion)
PERMISOS: tuple[tuple[str, str, str], ...] = (
    # seguridad
    ("seguridad.usuario.ver", "seguridad", "Ver usuarios"),
    ("seguridad.usuario.crear", "seguridad", "Crear usuarios"),
    ("seguridad.usuario.editar", "seguridad", "Editar usuarios"),
    ("seguridad.usuario.desactivar", "seguridad", "Desactivar usuarios"),
    ("seguridad.rol.ver", "seguridad", "Ver roles y permisos"),
    ("seguridad.rol.editar", "seguridad", "Crear y editar roles"),
    ("seguridad.auditoria.ver", "seguridad", "Consultar auditoría"),
    # configuracion
    ("configuracion.sede.administrar", "configuracion", "Administrar sedes y comercializadores"),
    ("configuracion.maestro.ver", "configuracion", "Ver la administración de maestros"),
    ("configuracion.maestro.editar", "configuracion", "Crear y editar maestros"),
    ("configuracion.barrio.editar", "configuracion", "Crear y editar zonas y barrios"),
    ("configuracion.estado.editar", "configuracion", "Editar estados por proceso"),
    ("configuracion.parametro.editar", "configuracion", "Editar parámetros"),
    ("configuracion.plantilla.editar", "configuracion", "Editar plantillas de correo"),
    ("configuracion.acuerdo.ver", "configuracion", "Ver acuerdos tarifarios"),
    ("configuracion.acuerdo.editar", "configuracion", "Crear y editar acuerdos en borrador"),
    ("configuracion.acuerdo.aprobar", "configuracion", "Aprobar acuerdos tarifarios"),
    # activos
    ("activos.luminaria.ver", "activos", "Consultar luminarias"),
    ("activos.luminaria.crear", "activos", "Registrar luminarias"),
    ("activos.luminaria.editar", "activos", "Editar luminarias"),
    ("activos.luminaria.exportar", "activos", "Exportar luminarias"),
    ("activos.luminaria.mover", "activos", "Cambiar la ubicación de una luminaria"),
    ("activos.lote.crear", "activos", "Registrar lotes de luminarias"),
    ("activos.mapa.ver", "activos", "Ver el mapa"),
    # atencion
    ("atencion.pqrs.ver", "atencion", "Consultar PQRS"),
    ("atencion.pqrs.crear", "atencion", "Registrar PQRS"),
    ("atencion.pqrs.editar", "atencion", "Editar PQRS"),
    ("atencion.pqrs.anular", "atencion", "Anular PQRS"),
    ("atencion.pqrs.exportar", "atencion", "Exportar PQRS"),
    ("atencion.datos_personales.ver", "atencion", "Ver datos personales sin enmascarar"),
    # trabajos
    ("trabajos.orden.ver", "trabajos", "Consultar órdenes de trabajo"),
    ("trabajos.orden.ver_propias", "trabajos", "Consultar solo las órdenes asignadas"),
    ("trabajos.orden.crear", "trabajos", "Crear órdenes de trabajo"),
    ("trabajos.orden.asignar", "trabajos", "Asignar órdenes de trabajo"),
    ("trabajos.orden.ejecutar", "trabajos", "Ejecutar órdenes de trabajo"),
    ("trabajos.orden.cerrar", "trabajos", "Cerrar órdenes de trabajo"),
    ("trabajos.orden.anular", "trabajos", "Anular órdenes de trabajo"),
    ("trabajos.orden.exportar", "trabajos", "Exportar órdenes de trabajo"),
    ("trabajos.cargue_masivo.crear", "trabajos", "Cargar órdenes en masa desde Excel"),
    # inventario
    ("inventario.material.ver", "inventario", "Consultar materiales"),
    ("inventario.material.editar", "inventario", "Crear y editar materiales"),
    ("inventario.movimiento.crear", "inventario", "Registrar entradas y salidas"),
    ("inventario.movimiento.ajustar", "inventario", "Registrar ajustes de inventario"),
    ("inventario.bodega.ver", "inventario", "Consultar la bodega de luminarias"),
    ("inventario.bodega.editar", "inventario", "Gestionar la bodega de luminarias"),
    # comercial
    ("comercial.cargue.crear", "comercial", "Cargar archivos de comercializadores"),
    ("comercial.cargue.eliminar", "comercial", "Eliminar cargues comerciales"),
    ("comercial.analisis.ver", "comercial", "Consultar análisis comerciales"),
    ("comercial.nominal.ver", "comercial", "Consultar datos nominales (se auditan)"),
    ("comercial.entregable.generar", "comercial", "Generar entregables comerciales"),
    ("comercial.exportar", "comercial", "Exportar datos comerciales"),
    # tablero
    ("tablero.ver", "tablero", "Ver el tablero gerencial"),
    ("tablero.consolidado.ver", "tablero", "Ver el consolidado de todas las sedes"),
    # campo
    ("campo.app.usar", "campo", "Usar la app de campo y cargar evidencias"),
)

ROL_ADMIN = "ADMIN"

# codigo -> (nombre, descripcion, permisos). ADMIN recibe todos los permisos.
ROLES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    ROL_ADMIN: ("Administrador", "Administra el sistema", ()),
    "COORDINACION": (
        "Coordinación administrativa",
        "Coordina operación y servicio al cliente",
        (
            "configuracion.maestro.ver",
            "configuracion.plantilla.editar",
            "activos.luminaria.ver",
            "activos.luminaria.crear",
            "activos.luminaria.editar",
            "activos.luminaria.exportar",
            "activos.luminaria.mover",
            "activos.lote.crear",
            "activos.mapa.ver",
            "atencion.pqrs.ver",
            "atencion.pqrs.crear",
            "atencion.pqrs.editar",
            "atencion.pqrs.anular",
            "atencion.pqrs.exportar",
            "atencion.datos_personales.ver",
            "trabajos.orden.ver",
            "trabajos.orden.crear",
            "trabajos.orden.asignar",
            "trabajos.orden.cerrar",
            "trabajos.orden.anular",
            "trabajos.orden.exportar",
            "trabajos.cargue_masivo.crear",
            "inventario.material.ver",
            "inventario.material.editar",
            "inventario.movimiento.crear",
            "inventario.bodega.ver",
            "inventario.bodega.editar",
        ),
    ),
    "TECNICO": (
        "Técnico de campo",
        "Ejecuta los trabajos desde la app de campo",
        (
            "campo.app.usar",
            "activos.luminaria.ver",
            "activos.mapa.ver",
            "atencion.pqrs.ver",
            "trabajos.orden.ver_propias",
            "trabajos.orden.ejecutar",
            "inventario.movimiento.crear",
        ),
    ),
    "ANALISTA_COMERCIAL": (
        "Analista comercial",
        "Carga y analiza los archivos del comercializador de su sede",
        (
            "configuracion.acuerdo.ver",
            "configuracion.acuerdo.editar",
            "comercial.cargue.crear",
            "comercial.cargue.eliminar",
            "comercial.analisis.ver",
            "comercial.nominal.ver",
            "comercial.entregable.generar",
            "comercial.exportar",
        ),
    ),
    "COBRANZA": (
        "Cobranza / administrativo comercial",
        "Gestión comercial, cartera y contribuyentes especiales",
        (
            "configuracion.maestro.ver",
            "configuracion.maestro.editar",
            "configuracion.parametro.editar",
            "configuracion.acuerdo.ver",
            "activos.luminaria.ver",
            "atencion.pqrs.ver",
            "trabajos.orden.ver",
            "inventario.material.ver",
            "comercial.analisis.ver",
            "comercial.exportar",
        ),
    ),
    "INTERVENTORIA": (
        "Interventoría",
        "Supervisa la ejecución (solo consulta)",
        (
            "activos.luminaria.ver",
            "activos.mapa.ver",
            "atencion.pqrs.ver",
            "trabajos.orden.ver",
            "inventario.material.ver",
            "inventario.bodega.ver",
        ),
    ),
    "CENSO": (
        "Censo",
        "Levanta y verifica el censo",
        (
            "activos.luminaria.ver",
            "activos.mapa.ver",
            "atencion.pqrs.ver",
            "inventario.material.ver",
        ),
    ),
    "INVENTARIO": (
        "Inventario / almacén",
        "Bodega y materiales",
        (
            "activos.luminaria.ver",
            "activos.mapa.ver",
            "activos.lote.crear",
            "inventario.material.ver",
            "inventario.material.editar",
            "inventario.movimiento.crear",
            "inventario.movimiento.ajustar",
            "inventario.bodega.ver",
            "inventario.bodega.editar",
        ),
    ),
    "GERENTE": (
        "Gerente",
        "Tablero por sede y consolidado",
        (
            "tablero.ver",
            "tablero.consolidado.ver",
            "activos.luminaria.ver",
            "activos.mapa.ver",
            "atencion.pqrs.ver",
            "trabajos.orden.ver",
            "inventario.material.ver",
            "comercial.analisis.ver",
        ),
    ),
}
