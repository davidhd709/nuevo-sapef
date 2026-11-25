# Manual comercial (analista comercial y cobranza)

El módulo **Comercial** analiza la facturación y el recaudo del impuesto de alumbrado de cada
comercializador de la sede: Afinia en Montelíbano; Celsia y Vatia en Alcalá.

## Cargues (analista comercial)

1. Elija el **comercializador** y el **periodo** (AAAAMM).
2. Suba los **archivos del corte** tal como los entrega el comercializador.
3. El cargue se procesa en segundo plano. Si el periodo ya existía, se reemplaza completo.
4. Un cargue con errores no publica nada: corrija el archivo y vuelva a subirlo.

## Análisis

- **Análisis:** indicadores del periodo, serie histórica, ausencias (usuarios que dejaron de
  aparecer), cartera, convenios y segmentación.
- **Control tarifario:** por cada NIC o cuenta, lo facturado frente a lo que dice el acuerdo
  municipal del año: **CORRECTO**, **POR ENCIMA**, **POR DEBAJO**, **NO VALIDABLE** o
  **REQUIERE REVISIÓN**. Lo cobrado de más y de menos se suma por separado.
- **Trazabilidad de un NIC:** su historia mes a mes. Es una consulta nominal: queda registrada.
- **Hallazgos:** registre lo que hay que revisar con el comercializador, con responsable y
  decisión.

## Entregables

Informes en Word, Excel, PDF o HTML del periodo (gerencial, requerimiento, anexos). Se generan en
segundo plano y se descargan desde la misma pantalla.

## Cobranza

Cobranza consulta los análisis y exporta, y mantiene los maestros y parámetros comerciales. No
carga archivos.
