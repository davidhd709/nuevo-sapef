"""Environment configuration and binary discovery for SAPEF E2E tests."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "si"}


def psycopg_dsn(database_url: str) -> str:
    """Normalize SQLAlchemy psycopg DSN (postgresql+psycopg://) to libpq/psycopg3 DSN."""
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url.removeprefix("postgresql+psycopg://")
    return database_url


def discover_browser_binary() -> Path | None:
    """Discover a local Chromium, Chrome, or Edge executable without external dependencies."""
    override = os.environ.get("SAPEF_E2E_BROWSER_BIN", "").strip()
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return candidate

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates: list[Path] = []
    if local_app_data:
        ms_pw = Path(local_app_data) / "ms-playwright"
        if ms_pw.is_dir():
            for pattern in (
                "chromium-*/chrome-win*/chrome.exe",
                "chromium_headless_shell-*/chrome-headless-shell-win*/chrome-headless-shell.exe",
                "chromium-*/chrome-linux*/chrome",
            ):
                candidates.extend(sorted(ms_pw.glob(pattern), reverse=True))

    program_files = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
    ]
    for base in program_files:
        if not base:
            continue
        base_path = Path(base)
        candidates.extend(
            [
                base_path / "Google" / "Chrome" / "Application" / "chrome.exe",
                base_path / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                base_path / "Chromium" / "Application" / "chrome.exe",
            ]
        )

    for exe_name in ("chromium", "chromium-browser", "google-chrome", "chrome", "msedge"):
        found = shutil.which(exe_name)
        if found:
            candidates.append(Path(found))

    for path in candidates:
        if path.is_file():
            return path
    return None


@dataclass(frozen=True)
class E2EConfig:
    """Resolved opaque-box E2E runtime configuration."""

    repo_root: Path
    tests_e2e_dir: Path
    backend_dir: Path
    frontend_dir: Path
    venv_python: Path
    venv_pytest: Path
    venv_ruff: Path
    base_url: str
    database_url: str
    web_url: str
    campo_url: str
    inprocess: bool
    data_dir: Path
    browser_bin: Path | None
    timeout_seconds: float
    admin_user: str
    admin_password: str

    @property
    def libpq_dsn(self) -> str:
        return psycopg_dsn(self.database_url)


def load_e2e_config(data_dir_override: Path | None = None) -> E2EConfig:
    """Load E2E configuration from SAPEF_E2E_* environment variables."""
    tests_e2e_dir = Path(__file__).resolve().parent.parent
    repo_root = tests_e2e_dir.parent
    backend_dir = repo_root / "backend"
    frontend_dir = repo_root / "frontend"

    scripts_dir = backend_dir / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    ext = ".exe" if os.name == "nt" else ""

    env_data_dir = os.environ.get("SAPEF_E2E_DATA_DIR", "").strip()
    if data_dir_override is not None:
        data_dir = data_dir_override
    elif env_data_dir:
        data_dir = Path(env_data_dir)
    else:
        data_dir = repo_root / ".e2e_data"

    timeout_raw = os.environ.get("SAPEF_E2E_TIMEOUT", "30").strip()
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError:
        timeout_seconds = 30.0

    return E2EConfig(
        repo_root=repo_root,
        tests_e2e_dir=tests_e2e_dir,
        backend_dir=backend_dir,
        frontend_dir=frontend_dir,
        venv_python=scripts_dir / f"python{ext}",
        venv_pytest=scripts_dir / f"pytest{ext}",
        venv_ruff=scripts_dir / f"ruff{ext}",
        base_url=os.environ.get("SAPEF_E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        database_url=os.environ.get(
            "SAPEF_E2E_DATABASE_URL",
            "postgresql+psycopg://sapef:sapef@127.0.0.1:55432/sapef",
        ),
        web_url=os.environ.get("SAPEF_E2E_WEB_URL", "http://127.0.0.1:5173").rstrip("/"),
        campo_url=os.environ.get("SAPEF_E2E_CAMPO_URL", "http://127.0.0.1:5174").rstrip("/"),
        inprocess=_parse_bool(os.environ.get("SAPEF_E2E_INPROCESS"), default=False),
        data_dir=data_dir,
        browser_bin=discover_browser_binary(),
        timeout_seconds=timeout_seconds,
        admin_user=os.environ.get("SAPEF_E2E_ADMIN_USER", "admin"),
        admin_password=os.environ.get("SAPEF_E2E_ADMIN_PASSWORD", ""),
    )
