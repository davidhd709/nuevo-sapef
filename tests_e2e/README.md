# SAPEF MVP — Opaque-Box E2E Test Suite (`tests_e2e/`)

Requirement-driven, opaque-box End-to-End test harness and suite for SAPEF MVP (Montelíbano & Alcalá + OPainn Comercial).
Tests interact strictly through HTTP APIs (`/api/v1/...`), PostgreSQL state invariants, generated Parquet/office artifacts, and headless Chromium DOM/IndexedDB/ServiceWorker — never importing `backend/app/modulos/*` internals.

## Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAPEF_E2E_BASE_URL` | `http://127.0.0.1:8000` | Live FastAPI backend base URL |
| `SAPEF_E2E_DATABASE_URL` | `postgresql+psycopg://sapef:sapef@127.0.0.1:55432/sapef` | PostgreSQL/PostGIS DSN for readiness, Procrastinate polling, and invariant checks |
| `SAPEF_E2E_WEB_URL` | `http://127.0.0.1:5173` | Frontend Office SPA (`apps/web`) URL |
| `SAPEF_E2E_CAMPO_URL` | `http://127.0.0.1:5174` | Frontend Field PWA (`apps/campo`) URL |
| `SAPEF_E2E_INPROCESS` | `0` | Set `1` to run Fase 0 ASGI checks in-process via Starlette `TestClient(crear_app())` |
| `SAPEF_E2E_DATA_DIR` | *(random `tests_e2e/.e2e_data_<id>`, deleted at the end)* | Storage directory for E2E generated files & Parquet packages. **With the API in Docker, set it to `<repo>/.e2e_data`**: IMP-5 (OPainn import) sends this path to the API, which can only read inside `/data/importacion` (`SAPEF_IMPORTACION_HOST_DIR=../.e2e_data` and `SAPEF_COMERCIAL_IMPORTACION_ALIAS=<repo>/.e2e_data` in `.env`) |
| `SAPEF_E2E_BROWSER_BIN` | *(auto-discovered)* | Optional path to Chromium / Chrome / Edge executable |
| `SAPEF_E2E_TIMEOUT` | `30` | Default HTTP / DB polling timeout in seconds. Tier 4 s1 imports 12,000 luminaires in the worker (~1–2 min): use `180` or more |

## Canonical Commands

Run from repository root (`sapef-nuevo/`):

```powershell
# PowerShell runner (runs ruff + pytest by tier)
powershell -ExecutionPolicy Bypass -File .\tests_e2e\run_e2e.ps1 -Tier selfcheck
powershell -ExecutionPolicy Bypass -File .\tests_e2e\run_e2e.ps1 -Tier fase0 -InProcess
powershell -ExecutionPolicy Bypass -File .\tests_e2e\run_e2e.ps1 -Tier collect
powershell -ExecutionPolicy Bypass -File .\tests_e2e\run_e2e.ps1 -Tier all

# Direct lint & pytest commands
backend\.venv\Scripts\ruff.exe check tests_e2e
backend\.venv\Scripts\pytest.exe -c tests_e2e/pytest.ini tests_e2e --collect-only
backend\.venv\Scripts\pytest.exe -c tests_e2e/pytest.ini tests_e2e/test_harness_selfcheck.py -v
```

## Directory Layout

```text
tests_e2e/
├── pytest.ini                      # Strict pytest markers & pythonpath
├── README.md                       # This guide
├── run_e2e.ps1                     # Canonical PowerShell runner
├── conftest.py                     # Shared E2E fixtures (clients, DB, browser, auth)
├── harness/                        # Opaque-box client, config, DB helper, CDP/Playwright browser
├── fixtures/                       # Pure-Python OOXML, LZW .Z, media, operational & commercial builders
├── oracles/                        # Exact DECIMAL(20,4) ROUND_HALF_UP commercial mathematical oracle
├── test_harness_selfcheck.py       # Deterministic verification of builders & oracles
├── test_fase0_live_contract.py     # Fase 0 health, tasks, RFC 9457, and OpenAPI sync tests
├── tier1_features/                 # Tier 1: Happy-path feature coverage
├── tier2_boundaries/               # Tier 2: Boundary, error & security tests
├── tier3_pairwise/                 # Tier 3: Cross-feature pairwise integration workflows
└── tier4_scenarios/                # Tier 4: Real-world municipal E2E scenarios
```
