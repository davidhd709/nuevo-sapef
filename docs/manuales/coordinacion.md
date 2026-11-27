# Manual de coordinación administrativa

Coordinación recibe las PQRS, crea y asigna las órdenes de trabajo, las cierra cuando se hicieron
desde la oficina y mantiene al día las luminarias.

## Atención (PQRS)

- **Registrar PQRS:** busque al ciudadano por cédula o nombre (si no existe, créelo), elija el
  canal (WhatsApp, presencial, teléfono, correo), la prioridad y las luminarias reportadas.
  - Si el ciudadano no sabe el código de la luminaria, use **SIN-IDENTIFICAR**: la oficina la
    identifica después.
  - Marque «Notificar al ciudadano por correo» si dejó correo.
- Al registrarla, cada luminaria queda en **Activo PQR** (122).
- **Luminarias pendientes:** todas las luminarias reportadas que faltan por reparar, con
  semáforo: verde (al día), amarillo y rojo (atrasadas) según los días configurados.
- Una PQRS queda **Atendida** sola cuando todas sus luminarias están reparadas.
- **Anular** pide un motivo y queda en la auditoría.
- Los datos personales (teléfono, correo, dirección) solo los ven los roles autorizados; cada
  consulta queda registrada.

## Órdenes de trabajo

- **Nueva orden:** tipo (mantenimiento, expansión, modernización o reubicación), prioridad,
  luminarias y, si viene de una PQRS, la PQRS.
- **Asignar** a un técnico o a una cuadrilla: le llega un aviso al teléfono.
- **Cerrar orden** desde la oficina (cuando el técnico no usó la app): observación técnica, sitio
  del arreglo, quién recibe, materiales usados y foto de evidencia.
  - Mantenimiento con **desmonte**: indique la causal y la luminaria de bodega que la reemplaza.
  - Expansión, modernización y reubicación: barrio, poste y coordenadas de la luminaria nueva.
  - El cierre descuenta los materiales del kárdex. Si falta material, **no se cierra nada**:
    primero registre la entrada en Inventario.
- **Conflictos de la app de campo:** trabajos enviados desde el teléfono que no se pudieron
  aplicar (orden anulada o reasignada, material insuficiente). Revíselos a diario.
- **Cargue masivo:** para registrar muchas expansiones, modernizaciones o reubicaciones ya
  hechas, descargue la plantilla, llénela y súbala. Se aplica todo o nada.

## Luminarias y mapa

- **Luminarias:** buscar por código, filtrar por barrio, estado, tecnología o potencia; crear y
  editar. En la hoja de vida puede asignar coordenadas verificadas a una luminaria sin ubicación.
  Los cambios de ubicación guardan la posición anterior en el historial.
- **Mapa:** muestra las luminarias con coordenadas de la sede. Las banderas distinguen PQR activa,
  tecnología y rango de potencia; la leyenda explica los colores. Acerque el mapa para separar los
  grupos y haga clic en una bandera para ver la ficha. Puede filtrar por estado, tecnología,
  potencia, marca, tipo de intervención, zona, barrio, bodega, validación y tránsito, o buscar por
  texto. El mapa base de OpenStreetMap muestra calles, parques y negocios que tengan nombre en sus
  datos; la cobertura varía según el municipio. Las luminarias sin coordenadas no aparecen hasta
  que se registre su ubicación. Si tiene permiso para mover luminarias, seleccione una bandera,
  pulse **Corregir ubicación**, arrastre el marcador rojo y guarde la nueva posición. El botón de
  ubicación del mapa centra la vista en su posición si el navegador tiene permiso de GPS.
- **Exportar:** genera un Excel en segundo plano con los filtros actuales.
