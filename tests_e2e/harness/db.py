"""Pure psycopg3 helper for E2E readiness checks, Procrastinate polling, and DB invariants.

Strictly opaque-box: NEVER imports backend app.modulos.* or internal ORM models.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row

from harness.config import psycopg_dsn

_TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "aborted"}


class DbHelper:
    """Direct PostgreSQL/PostGIS inspector and Procrastinate job waiter using psycopg3."""

    def __init__(self, database_url: str) -> None:
        self.dsn = psycopg_dsn(database_url)

    def connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def is_ready(self, *, connect_timeout: int = 2) -> bool:
        try:
            with (
                psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=connect_timeout) as conn,
                conn.cursor() as cur,
            ):
                cur.execute("SELECT 1")
                row = cur.fetchone()
                return row is not None
        except psycopg.Error:
            return False

    def wait_until_ready(self, timeout: float = 30.0, poll_interval: float = 0.5) -> None:
        deadline = time.monotonic() + timeout
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with self.connect() as conn, conn.cursor() as cur:
                    cur.execute("SELECT PostGIS_Version() AS postgis")
                    row = cur.fetchone()
                    if row is not None:
                        return
            except Exception as exc:  # noqa: BLE001
                last_err = exc
            time.sleep(poll_interval)
        raise TimeoutError(f"PostgreSQL/PostGIS not ready within {timeout}s: {last_err}")

    def fetch_one(
        self,
        sql: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def fetch_all(
        self,
        sql: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def scalar(
        self,
        sql: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> Any:
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return None if row is None else row[0]

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> int:
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
            return cur.rowcount

    def wait_for_procrastinate_job(
        self,
        job_id: int,
        *,
        timeout: float = 30.0,
        poll_interval: float = 0.25,
        allow_failed: bool = False,
    ) -> dict[str, Any]:
        """Poll procrastinate_jobs until job reaches a terminal status."""
        deadline = time.monotonic() + timeout
        last_row: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            row = self.fetch_one(
                """
                SELECT id, queue_name, task_name, status, attempts, args, scheduled_at, started_at
                FROM procrastinate_jobs
                WHERE id = %s
                """,
                (job_id,),
            )
            if row is not None:
                last_row = row
                status = str(row["status"])
                if status in _TERMINAL_JOB_STATUSES:
                    if status != "succeeded" and not allow_failed:
                        raise AssertionError(
                            f"Procrastinate job {job_id} ({row['task_name']}) ended with "
                            f"status={status!r}, attempts={row['attempts']}"
                        )
                    return row
            time.sleep(poll_interval)
        raise TimeoutError(
            f"Procrastinate job {job_id} did not finish within {timeout}s (last={last_row})"
        )

    def get_procrastinate_job_args(self, job_id: int) -> dict[str, Any]:
        row = self.fetch_one("SELECT args FROM procrastinate_jobs WHERE id = %s", (job_id,))
        if row is None:
            raise LookupError(f"Procrastinate job {job_id} not found")
        args = row.get("args")
        return dict(args) if isinstance(args, dict) else {}

    def count_audit_logs(
        self,
        *,
        entidad: str | None = None,
        accion: str | None = None,
        request_id: str | None = None,
    ) -> int:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if entidad is not None:
            clauses.append("entidad = %(entidad)s")
            params["entidad"] = entidad
        if accion is not None:
            clauses.append("accion = %(accion)s")
            params["accion"] = accion
        if request_id is not None:
            clauses.append("request_id = %(request_id)s")
            params["request_id"] = request_id
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT COUNT(*) FROM seguridad.auditoria {where}"
        return int(self.scalar(sql, params) or 0)

    def count_nominal_consult_logs(
        self,
        *,
        recurso: str | None = None,
        sede_id: Any | None = None,
    ) -> int:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if recurso is not None:
            clauses.append("recurso = %(recurso)s")
            params["recurso"] = recurso
        if sede_id is not None:
            clauses.append("sede_id = %(sede_id)s")
            params["sede_id"] = sede_id
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT COUNT(*) FROM seguridad.auditoria_consulta {where}"
        return int(self.scalar(sql, params) or 0)

    def has_non_negative_stock_constraint(self) -> bool:
        """Verify PostgreSQL enforces CHECK (existencias >= 0) on inventario.material."""
        row = self.fetch_one(
            """
            SELECT pg_get_constraintdef(c.oid) AS definition
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'inventario'
              AND t.relname = 'material'
              AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) ILIKE '%existencias%'
            LIMIT 1
            """
        )
        return row is not None and ">=" in str(row.get("definition", ""))
