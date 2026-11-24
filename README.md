# SAPEF — Sistema de gestión de alumbrado público

Sistema para el negocio de alumbrado público de las sedes **Montelíbano** y **Alcalá**: alumbrado en el mapa, PQRS → órdenes de trabajo, app de campo sin conexión, inventario, análisis comercial de los comercializadores (Afinia, Celsia, Vatia) y tablero gerencial.

La especificación (requerimientos, arquitectura v2.0, plan del MVP y documento maestro) **no está en este repositorio público**: incluye el análisis de seguridad de un sistema en producción. Se comparte por un canal privado. Las referencias del tipo «§9.2» o «RN-005» en el código apuntan a ese documento maestro.

## Estructura

```
sapef-nuevo/
├─ backend/     # Python 3.12 · FastAPI · SQLAlchemy · PostgreSQL + PostGIS (gestor: uv)
├─ frontend/    # React + TypeScript: apps/web (oficina) y apps/campo (PWA sin conexión)
├─ infra/       # Docker Compose de desarrollo y, más adelante, de producción
└─ docs/        # decisiones (ADR) y guías
```

## Requisitos

- Docker Desktop (con el motor encendido)
- [uv](https://docs.astral.sh/uv/) para el backend (`py -m pip install --user uv`)
- Node 22 y pnpm para el frontend

## Arranque en desarrollo

```bash
# 1. Base de datos, migraciones, API y worker en Docker
cp .env.example .env          # y poner una contraseña propia en POSTGRES_PASSWORD
docker compose -f infra/docker-compose.dev.yml --env-file .env up -d --build

# 2. Primer administrador (una sola vez; pide la contraseña por consola)
docker compose -f infra/docker-compose.dev.yml --env-file .env run --rm -it migraciones \
  python -m app.semillas admin --usuario admin --correo admin@ejemplo.co

# 3. Comprobar
curl http://127.0.0.1:8000/api/v1/salud
curl -X POST http://127.0.0.1:8000/api/v1/sistema/tareas/prueba   # encola una tarea de prueba

# 4. Web de oficina (http://localhost:5173; /api se reenvía a la API)
cd frontend && pnpm install && pnpm dev

# 5. App de campo (PWA, http://127.0.0.1:5174), en otra consola
cd frontend && pnpm dev:campo
```

Servicios de Docker: `db` (PostgreSQL 17 + PostGIS), `migraciones` (aplica Alembic y la semilla, y termina), `api` y `worker` (la misma imagen).

**Semilla** (`python -m app.semillas`, idempotente): permisos (§4.3) y roles iniciales (§4.2), sedes, comercializadores, maestros, estados, zonas y barrios de Montelíbano, parámetros, plantillas de correo, acuerdos tarifarios 2026 (Afinia y Celsia) y catálogos CI/OC. Crea lo que falta y no modifica lo existente. Solo catálogos: ningún dato personal.

> En Windows use `127.0.0.1` y no `localhost` para la base de datos: `localhost` intenta IPv6 y la conexión se cuelga.
>
> **Las pruebas del backend vacían la base** a la que apunta `SAPEF_DATABASE_URL` (hacen `TRUNCATE` en cada prueba). Después de `pytest`, vuelva a ejecutar `python -m app.semillas` y cree de nuevo el administrador.
>
> En Windows, la API fuera de Docker (`uvicorn` directo) no conecta la cola: el pool asíncrono de psycopg no funciona con el event loop de Windows. Use el servicio `api` de Docker.

### Backend (sin Docker para la API, con la base en Docker)

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload     # API
uv run python -m app.worker              # worker de tareas
uv run alembic upgrade head              # migraciones
uv run python -m app.semillas            # catálogos, permisos y roles (idempotente)
uv run python -m app.semillas admin --usuario admin --correo admin@ejemplo.co
uv run alembic revision --autogenerate -m "descripción"
uv run pytest && uv run ruff check . && uv run lint-imports
```

### Frontend

```bash
cd frontend
pnpm api          # regenera openapi.json y los tipos del cliente desde el backend (tras cambiar la API)
pnpm dev          # web en http://localhost:5173
pnpm dev:campo    # app de campo en http://127.0.0.1:5174 (con Service Worker también en desarrollo)
pnpm typecheck && pnpm test && pnpm build
```

### App de campo (`frontend/apps/campo`)

PWA para los técnicos: funciona **sin señal**. Al ingresar descarga sus órdenes asignadas, las luminarias de la sede, la bodega, los materiales, los catálogos y el mapa base PMTiles de la sede (`GET /api/v1/campo/paquete`; después, solo los cambios desde el cursor). Lo que el técnico ejecuta (checklist, materiales, fotos comprimidas, firmas, nota de voz y GPS) queda en una **bandeja de salida** en IndexedDB con un UUID generado en el teléfono, y se envía al volver la señal: primero los archivos (`POST /api/v1/archivos` con `Idempotency-Key`), después el lote (`POST /api/v1/campo/sincronizar`). Cada operación se aplica una sola vez; si la orden se anuló o reasignó mientras tanto, queda como **conflicto** y lo ven el técnico y la oficina.

- El Service Worker (Workbox) **no se actualiza mientras haya trabajo sin enviar**.
- iOS no sincroniza en segundo plano: la app sincroniza al abrir, al volver la señal, al volver a primer plano y cada minuto con señal. En iPhone debe instalarse en la pantalla de inicio.
- **Avisos push** de órdenes asignadas: generar la clave con `cd backend && uv run python -m app.semillas vapid` y poner `SAPEF_VAPID_CLAVE_PRIVADA` en `.env`. Sin clave, la API acepta suscripciones pero no envía avisos.

La integración continua (`.github/workflows/ci.yml`) falla si el cliente generado no coincide con la API, si las migraciones no suben y bajan limpias, o si un módulo rompe las fronteras.

## Reglas del proyecto

- **Un módulo por dominio** en `backend/app/modulos/`, todos con la misma forma (`router`, `esquemas`, `servicio`, `dominio`, `repositorio`, `modelos`). Un módulo solo usa el `servicio` público de otro; `import-linter` lo verifica.
- **Toda ruta valida sesión, sede y permiso** en la API; el frontend solo oculta.
- **Errores en formato RFC 9457** (`application/problem+json`), sin trazas internas.
- **Sin secretos en el repositorio**: van en `.env` (excluido de Git).
- **Las tareas en segundo plano solo reciben identificadores**, nunca datos personales: la cola los guarda y los escribe en los logs.
