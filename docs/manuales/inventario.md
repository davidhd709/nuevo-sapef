# Manual de inventario y almacén

## Materiales y kárdex

- **Materiales:** código, categoría, descripción, unidad, existencias mínimas. Marque **Solo bajo
  el mínimo** para ver lo que hay que reponer.
- **Movimientos:** cada entrada, salida o ajuste queda en el kárdex con las existencias que
  resultaron, quién lo hizo y cuándo.
  - **Entrada:** lo que llega al almacén.
  - **Salida:** lo que sale sin orden de trabajo. Lo que se usa en una orden se descuenta solo al
    cerrarla.
  - **Ajuste** (solo almacén): corrige un conteo físico; puede ser positivo o negativo.
- Las existencias **nunca** quedan negativas: si una salida o un cierre de orden pide más de lo
  que hay, se rechaza completo.

## Bodega de luminarias

- Muestra las luminarias en bodega: **buena** (124, lista para instalar), **de baja** (123),
  **en garantía** (125), **desmontada** (112) y **disposición final** (126, ya no se mueve).
- Cambie el estado cuando revise una luminaria (por ejemplo, de desmontada a bodega buena).
- **Cargue desde Excel:** para cambiar muchas a la vez. Columnas: código de la luminaria, estado
  de destino y observación.
