# Plan de corte (R1): de SAPEF al sistema nuevo

Para el administrador del sistema y el dueño. Meta de R1: **las dos sedes trabajan en el sistema
nuevo y SAPEF queda en solo lectura**. Se corta una sede a la vez: primero Montelíbano (sus
exportaciones ya se probaron), después Alcalá.

## Antes del corte (semanas previas)

1. **Servidor listo:** producción en el VPS con `infra/docker-compose.prod.yml`, Nginx del host con
   HTTPS (`infra/nginx/sapef.conf.example`), respaldo diario con copia cifrada fuera del servidor
   (`docs/operacion/respaldos.md`) y una prueba de restauración hecha.
2. **Ensayo completo en pruebas:** el mismo procedimiento de abajo, con exportaciones recientes, en
   el ambiente de pruebas. Anotar tiempos y conteos; es la línea base del día del corte.
3. **Revisar los rechazos del ensayo con la oficina.** Con las exportaciones de Montelíbano del
   23-nov-2026 quedaron por fuera:
   - 379 de 6.643 órdenes históricas: modernizaciones y reubicaciones sin luminaria instalada o
     desmontada en SAPEF (296), con «SIN NUMERO» (27), sin identificador por columnas corridas
     (47) y otros 9 con un código de luminaria que no existe. Son registros incompletos en el
     origen; quedan en el informe para consulta.
   - Ninguna luminaria ni PQRS rechazada. 92 luminarias venían repetidas (el mismo barrio en dos
     zonas en SAPEF): se tomó la primera fila.

   Decidir con el dueño si esos registros se corrigen en SAPEF antes del corte o se aceptan así.
4. **Usuarios:** preparar el libro de base (zonas, barrios y usuarios con rol y sedes). Las
   contraseñas no se migran: cada persona define la suya en el primer ingreso.
5. **Capacitación** por rol con los manuales de `docs/manuales/` en el ambiente de pruebas.
6. **Teléfonos de campo:** instalar la app de campo y hacer una orden de prueba sin señal con cada
   técnico (validación pendiente de la Fase 3).

## Día del corte (por sede)

| Hora | Paso | Responsable |
| --- | --- | --- |
| H-1 | Avisar a la oficina: desde H no se registra nada en SAPEF | Coordinación |
| H | Poner SAPEF en **solo lectura** (quitar permisos de edición a todos los roles en SAPEF) | Administrador |
| H | Exportar de SAPEF: `LUMINARIAS_LIST_DESCARGA`, `LUMINARIAS_REPARAR`, `MANTENIMIENTOS_EXPORTAR` (todo el rango de fechas), `EXPANSIONES`, `MODERNIZACIONES`, `REUBICACIONES` e inventario | Administrador |
| H+15 min | Respaldo del sistema nuevo (`respaldar.sh`) | Operación |
| H+20 min | En **Migración**, con la sede elegida, en este orden: 1) base, 2) luminarias, 3) PQRS, 4) órdenes (los 4 archivos juntos), 5) inventario | Administrador |
| — | Después de cada paso, abrir la ejecución y revisar conciliación, errores y advertencias antes de seguir | Administrador |
| H+1 h | Verificación (abajo) | Coordinación + Administrador |
| H+1,5 h | Abrir el sistema a la oficina y a campo | Coordinación |

Tiempos medidos con los datos reales de Montelíbano en desarrollo: luminarias (11.205 filas)
≈ 2 min, PQRS (72 filas) ≈ 2 s, órdenes (6.643 filas) ≈ 1 min. Los importadores se pueden repetir
sin duplicar: si algo sale mal, se corrige el archivo y se vuelve a subir.

## Verificación antes de abrir

- **Luminarias:** el total de la sede en el tablero coincide con SAPEF (Montelíbano: 11.113
  distintas en la exportación de prueba). Conteo por estado parecido al de SAPEF.
- **Mapa:** las luminarias aparecen en su sitio; las «sin coordenadas» del informe se revisan
  después (719 en la exportación de prueba).
- **PQRS pendientes:** la lista de Atención → Luminarias pendientes coincide con
  «Luminarias a reparar» de SAPEF.
- **Órdenes:** el número de órdenes por tipo coincide con el informe de la ejecución.
- **Inventario:** el informe dice «existencias conciliadas» para todos los materiales; cada
  diferencia se revisa con almacén.
- **Usuarios:** una persona de cada rol ingresa, define su contraseña y ve solo su sede.

## Si hay que volver atrás

Hasta abrir el sistema a la oficina (H+1,5 h), volver atrás es barato: SAPEF sigue intacto en
solo lectura. Se le devuelven los permisos de edición y el sistema nuevo se restaura al respaldo
de H+15 min (`restaurar.sh`). Después de abrir, lo registrado en el sistema nuevo no existe en
SAPEF: se corrige hacia adelante, no se vuelve atrás.

## Después del corte

- SAPEF queda en solo lectura como consulta histórica al menos 3 meses; no se apaga sin un
  respaldo completo del proveedor (fotos, firmas e historial no vienen en las exportaciones, R-02).
- Primera semana: revisar a diario el panel de conflictos de la app de campo (Órdenes) y las PQRS
  pendientes con semáforo rojo.
- Repetir el procedimiento con Alcalá cuando estén sus zonas y barrios (SPIKE-03) y sus
  exportaciones.
