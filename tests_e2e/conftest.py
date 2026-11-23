"""Shared pytest fixtures for SAPEF opaque-box E2E tests (Tiers 1-4 & Fase 0)."""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from harness.browser import BrowserDriver
from harness.client import SapefClient
from harness.config import E2EConfig, load_e2e_config
from harness.db import DbHelper

_TESTS_E2E_ROOT = Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def e2e_config() -> Iterator[E2EConfig]:
    """Session-wide resolved E2E configuration with isolated storage root."""
    env_data_dir = os.environ.get("SAPEF_E2E_DATA_DIR", "").strip()
    created_temp_dir: Path | None = None
    if env_data_dir:
        data_dir = Path(env_data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
    else:
        data_dir = _TESTS_E2E_ROOT / f".e2e_data_{uuid.uuid4().hex[:8]}"
        data_dir.mkdir(parents=True, exist_ok=True)
        created_temp_dir = data_dir

    cfg = load_e2e_config(data_dir_override=data_dir)
    try:
        yield cfg
    finally:
        if created_temp_dir is not None and created_temp_dir.exists():
            shutil.rmtree(created_temp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def run_id() -> str:
    """Unique per-test-run correlation prefix (E2E_<uuid8>) to prevent entity collisions."""
    return f"E2E_{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture(scope="session")
def api_client(e2e_config: E2EConfig) -> Iterator[SapefClient]:
    """Session-scoped opaque-box HTTP client (live or in-process per SAPEF_E2E_INPROCESS)."""
    with SapefClient(
        base_url=e2e_config.base_url,
        inprocess=e2e_config.inprocess,
        timeout=e2e_config.timeout_seconds,
    ) as client:
        yield client


@pytest.fixture
def inprocess_or_live_client(e2e_config: E2EConfig) -> Iterator[SapefClient]:
    """Function-scoped isolated HTTP client with a fresh cookie jar."""
    with SapefClient(
        base_url=e2e_config.base_url,
        inprocess=e2e_config.inprocess,
        timeout=e2e_config.timeout_seconds,
    ) as client:
        yield client


@pytest.fixture(scope="session")
def db_helper(e2e_config: E2EConfig) -> DbHelper:
    """Session-scoped PostgreSQL/PostGIS & Procrastinate helper (never imports app.modulos.*)."""
    return DbHelper(e2e_config.database_url)


@pytest.fixture
def browser_driver(e2e_config: E2EConfig) -> Iterator[BrowserDriver]:
    """Function-scoped headless Chromium driver (Playwright or stdlib CDP WebSocket)."""
    driver = BrowserDriver(
        binary_path=e2e_config.browser_bin,
        timeout=e2e_config.timeout_seconds,
    )
    try:
        yield driver
    finally:
        driver.close()


@pytest.fixture(scope="session")
def auth_session_factory(
    e2e_config: E2EConfig,
) -> Iterator[Callable[..., SapefClient]]:
    """Factory creating isolated authenticated SapefClient instances per user/sede."""
    created: list[SapefClient] = []

    def _create_session(
        usuario: str,
        clave: str,
        *,
        sede: str | None = None,
        tipo_cliente: str = "web",
        expect_ok: bool = True,
    ) -> SapefClient:
        client = SapefClient(
            base_url=e2e_config.base_url,
            inprocess=e2e_config.inprocess,
            default_sede=sede,
            timeout=e2e_config.timeout_seconds,
        )
        created.append(client)
        client.login(usuario, clave, tipo_cliente=tipo_cliente, expect_ok=expect_ok)
        return client

    yield _create_session

    for client in created:
        client.close()


@pytest.fixture(scope="session")
def sede_headers() -> Callable[[str], dict[str, str]]:
    """Helper returning canonical X-Sede header dict for a given sede code."""

    def _headers(sede: str = "montelibano") -> dict[str, str]:
        return {"X-Sede": sede}

    return _headers
