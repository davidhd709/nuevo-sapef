# Manual del administrador

El administrador tiene todos los permisos: configura el sistema, crea usuarios y hace la
migración desde SAPEF.

## Usuarios y roles (Seguridad)

- **Usuarios → Nuevo usuario:** nombre de usuario, nombre completo, identificación, correo, rol
  y sedes. Si no pone contraseña inicial, el usuario la crea en su primer ingreso.
- Para **retirar** a alguien, desactívelo (no se borra: su historia queda en la auditoría).
- **Roles y permisos:** cada rol es una lista de permisos del tipo `modulo.recurso.accion`. Cree
  roles nuevos en vez de cambiar los de fábrica si una persona necesita algo especial.
- **Auditoría:** quién creó, cambió, anuló o consultó datos personales, cuándo y en qué sede.

## Configuración

- **Sedes:** al crear una sede, usted queda con acceso a ella. Asigne a los demás desde Usuarios.
- **Zonas y barrios** de la sede activa. Un barrio pertenece a una sola zona.
- **Maestros:** marcas, tecnologías, potencias, tipos de intervención, canales de PQRS, etc.
- **Estados:** nombres de los estados de luminaria, PQRS y orden (los códigos no se cambian).
- **Parámetros:** por ejemplo, los días del semáforo de PQRS.
- **Acuerdos tarifarios:** uno por sede, comercializador y año. Se trabaja en borrador y se
  aprueba; el aprobado reemplaza al anterior.

## Migración desde SAPEF

Menú **Migración**. Siga el orden numerado de las tarjetas y el plan de corte
(`docs/operacion/plan-de-corte.md`).

1. Elija la **sede** correcta arriba: todo se importa a esa sede.
2. En cada tarjeta, elija el archivo exportado de SAPEF (CSV tal como sale de SAPEF, o la
   plantilla en Excel) y pulse **Importar**. El archivo queda **en cola** y se procesa en segundo
   plano; puede seguir trabajando.
3. En **Ejecuciones** verá el estado: En cola → Procesando → Completada, Con errores o Falló.
4. Haga clic en una ejecución para ver:
   - **Conciliación:** cuántas filas se leyeron, cuántas se crearon o actualizaron y cuántas no
     entraron.
   - **Errores:** filas que no se importaron, con el número de fila del archivo y el motivo.
   - **Advertencias:** filas que sí entraron pero conviene revisar (código repetido, potencia
     mayor de 1.000 W, longitud corregida, etc.).
5. Puede **repetir** una importación: no duplica datos. Lo que ya existe se actualiza (luminarias,
   materiales) o se deja igual (PQRS y órdenes históricas).

Las órdenes históricas entran **cerradas** y no cambian el estado de las luminarias ni el kárdex.
Los usuarios entran **sin contraseña**: si el archivo trae una columna de clave, se ignora.
