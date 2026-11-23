"""Opaque-box HTTP client (pure-stdlib live mode + Starlette TestClient in-process mode)."""

from __future__ import annotations

import http.cookiejar
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, Self

_LEAK_MARKERS = (
    "traceback (most recent call last)",
    "sqlalchemy.exc.",
    "psycopg.",
    "hash_clave",
    "secret_key",
    "vapid_private_key",
    "mailpasswd",
)

FileTuple = tuple[str, bytes, str] | tuple[str, bytes]
MultipartFileItem = tuple[str, str, bytes, str]


@dataclass
class ApiResponse:
    """Uniform HTTP response wrapper across stdlib urllib and Starlette TestClient."""

    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    content: bytes = b""
    url: str = ""

    def header(self, name: str, default: str | None = None) -> str | None:
        target = name.lower()
        for key, value in self.headers.items():
            if key.lower() == target:
                return value
        return default

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))

    @property
    def content_type(self) -> str:
        return self.header("content-type", "") or ""

    @property
    def request_id(self) -> str | None:
        return self.header("x-request-id")


def assert_problem_json(
    resp: ApiResponse,
    expected_status: int | tuple[int, ...] | None = None,
    *,
    require_request_id: bool = True,
) -> dict[str, Any]:
    """Strictly verify RFC 9457 application/problem+json response without leaked internals."""
    if expected_status is not None:
        if isinstance(expected_status, int):
            assert resp.status_code == expected_status, (
                f"Expected HTTP {expected_status}, got {resp.status_code}: {resp.text}"
            )
        else:
            assert resp.status_code in expected_status, (
                f"Expected HTTP in {expected_status}, got {resp.status_code}: {resp.text}"
            )

    ctype = resp.content_type.lower()
    assert ctype.startswith("application/problem+json"), (
        f"Expected Content-Type 'application/problem+json', got {ctype!r} (body={resp.text})"
    )

    body = resp.json()
    assert isinstance(body, dict), f"Problem JSON must be an object, got {type(body)}"
    for required_key in ("type", "title", "status"):
        assert required_key in body, f"Missing RFC 9457 key {required_key!r} in {body}"
    assert body["status"] == resp.status_code, (
        f"Problem status {body['status']} != HTTP status {resp.status_code}"
    )

    if require_request_id:
        req_id = body.get("requestId")
        assert isinstance(req_id, str) and req_id.strip(), (
            f"Missing non-empty 'requestId' in RFC 9457 body: {body}"
        )
        hdr_rid = resp.request_id
        if hdr_rid is not None:
            assert hdr_rid == req_id, (
                f"Header X-Request-Id {hdr_rid!r} != body requestId {req_id!r}"
            )

    lowered = resp.text.lower()
    for marker in _LEAK_MARKERS:
        assert marker not in lowered, (
            f"Response leaked internal marker {marker!r}: {resp.text[:300]}"
        )
    return body


def _encode_multipart(
    fields: Mapping[str, Any] | None,
    files: Sequence[MultipartFileItem] | Mapping[str, FileTuple],
) -> tuple[bytes, str]:
    boundary = f"----sapefE2E{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    if fields:
        for key, value in fields.items():
            if value is None:
                continue
            chunks.append(f"--{boundary}\r\n".encode("ascii"))
            chunks.append(
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
            )
            chunks.append(str(value).encode())
            chunks.append(b"\r\n")

    normalized_files: list[MultipartFileItem] = []
    if isinstance(files, Mapping):
        for field_name, spec in files.items():
            if len(spec) == 2:
                fname, payload = spec
                mime = "application/octet-stream"
            else:
                fname, payload, mime = spec
            normalized_files.append((field_name, fname, payload, mime))
    else:
        normalized_files = list(files)

    for field_name, filename, payload, content_type in normalized_files:
        safe_name = filename.replace('"', "_")
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        chunks.append(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{safe_name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n".encode()
        )
        chunks.append(payload)
        chunks.append(b"\r\n")

    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent automatic redirect following so E2E assertions see exact status codes."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SapefClient:
    """Opaque-box HTTP client supporting cookies, X-Sede, Idempotency-Key, Range, and multipart."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        inprocess: bool = False,
        app: Any | None = None,
        default_sede: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.inprocess = inprocess
        self.default_sede = default_sede
        self.timeout = timeout
        self._app = app
        self._test_client: Any | None = None
        self._cookie_jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookie_jar),
            _NoRedirectHandler(),
        )
        if self.inprocess:
            self._init_inprocess_client()

    def _init_inprocess_client(self) -> None:
        if self._app is None:
            backend_dir = str(Path(__file__).resolve().parent.parent.parent / "backend")
            if backend_dir not in sys.path:
                sys.path.insert(0, backend_dir)
            from app.main import crear_app  # type: ignore[import-not-found]

            self._app = crear_app()
        from starlette.testclient import TestClient

        self._test_client = TestClient(self._app, raise_server_exceptions=False)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._test_client is not None:
            self._test_client.close()
            self._test_client = None

    def set_sede(self, sede: str | None) -> None:
        self.default_sede = sede

    def clear_cookies(self) -> None:
        self._cookie_jar.clear()
        if self._test_client is not None:
            self._test_client.cookies.clear()

    def get_cookie(self, name: str) -> str | None:
        if self._test_client is not None:
            return self._test_client.cookies.get(name)
        for cookie in self._cookie_jar:
            if cookie.name == name:
                return cookie.value
        return None

    def cookie_names(self) -> list[str]:
        if self._test_client is not None:
            return list(self._test_client.cookies.keys())
        return [cookie.name for cookie in self._cookie_jar]

    def clone(self, *, sede: str | None = None) -> SapefClient:
        """Return a fresh client sharing target URL/app but with an isolated cookie jar."""
        return SapefClient(
            base_url=self.base_url,
            inprocess=self.inprocess,
            app=self._app,
            default_sede=sede if sede is not None else self.default_sede,
            timeout=self.timeout,
        )

    @staticmethod
    def assert_problem_json(
        resp: ApiResponse,
        expected_status: int | tuple[int, ...] | None = None,
        *,
        require_request_id: bool = True,
    ) -> dict[str, Any]:
        return assert_problem_json(
            resp,
            expected_status=expected_status,
            require_request_id=require_request_id,
        )

    def _build_url(self, path: str, params: Mapping[str, Any] | None) -> str:
        rel = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{rel}" if not self.inprocess else rel
        if params:
            pairs: list[tuple[str, str]] = []
            for key, value in params.items():
                if value is None:
                    continue
                if isinstance(value, (list, tuple)):
                    for item in value:
                        pairs.append((key, str(item)))
                else:
                    pairs.append((key, str(value)))
            if pairs:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}{urllib.parse.urlencode(pairs)}"
        return url

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        data: Mapping[str, Any] | bytes | None = None,
        files: Sequence[MultipartFileItem] | Mapping[str, FileTuple] | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        sede: str | None = None,
        omit_sede: bool = False,
        idempotency_key: str | None = None,
        request_id: str | None = None,
        byte_range: str | None = None,
    ) -> ApiResponse:
        hdrs: dict[str, str] = {}
        if headers:
            hdrs.update(headers)

        effective_sede = None if omit_sede else (sede if sede is not None else self.default_sede)
        if effective_sede and not any(k.lower() == "x-sede" for k in hdrs):
            hdrs["X-Sede"] = effective_sede
        if idempotency_key and not any(k.lower() == "idempotency-key" for k in hdrs):
            hdrs["Idempotency-Key"] = idempotency_key
        if request_id and not any(k.lower() == "x-request-id" for k in hdrs):
            hdrs["X-Request-Id"] = request_id
        if byte_range and not any(k.lower() == "range" for k in hdrs):
            hdrs["Range"] = byte_range

        url = self._build_url(path, params)

        if self._test_client is not None:
            return self._request_inprocess(method, url, json_body, data, files, hdrs)
        return self._request_live(method, url, json_body, data, files, hdrs)

    def _request_inprocess(
        self,
        method: str,
        url: str,
        json_body: Any,
        data: Mapping[str, Any] | bytes | None,
        files: Sequence[MultipartFileItem] | Mapping[str, FileTuple] | None,
        headers: dict[str, str],
    ) -> ApiResponse:
        assert self._test_client is not None
        kwargs: dict[str, Any] = {"headers": headers}
        if files is not None:
            fields = dict(data) if isinstance(data, Mapping) else None
            raw_body, ctype = _encode_multipart(fields, files)
            kwargs["content"] = raw_body
            kwargs["headers"] = {**headers, "Content-Type": ctype}
        elif json_body is not None:
            kwargs["json"] = json_body
        elif isinstance(data, bytes):
            kwargs["content"] = data
        elif isinstance(data, Mapping):
            kwargs["data"] = dict(data)

        resp = self._test_client.request(method.upper(), url, **kwargs)
        return ApiResponse(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            content=resp.content,
            url=str(resp.url),
        )

    def _request_live(
        self,
        method: str,
        url: str,
        json_body: Any,
        data: Mapping[str, Any] | bytes | None,
        files: Sequence[MultipartFileItem] | Mapping[str, FileTuple] | None,
        headers: dict[str, str],
    ) -> ApiResponse:
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"Unsupported URL scheme for SapefClient: {url!r}")

        body_bytes: bytes | None = None
        req_headers = dict(headers)
        if files is not None:
            fields = dict(data) if isinstance(data, Mapping) else None
            body_bytes, ctype = _encode_multipart(fields, files)
            req_headers["Content-Type"] = ctype
        elif json_body is not None:
            body_bytes = json.dumps(json_body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        elif isinstance(data, bytes):
            body_bytes = data
        elif isinstance(data, Mapping):
            body_bytes = urllib.parse.urlencode(
                {k: "" if v is None else str(v) for k, v in data.items()}
            ).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

        req = urllib.request.Request(
            url=url,
            data=body_bytes,
            headers=req_headers,
            method=method.upper(),
        )
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return ApiResponse(
                    status_code=resp.status,
                    headers=dict(resp.headers.items()),
                    content=resp.read(),
                    url=resp.geturl(),
                )
        except urllib.error.HTTPError as exc:
            content = exc.read() if exc.fp is not None else b""
            resp_headers = dict(exc.headers.items()) if exc.headers else {}
            return ApiResponse(
                status_code=exc.code,
                headers=resp_headers,
                content=content,
                url=url,
            )

    def get(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("DELETE", path, **kwargs)

    def login(
        self,
        usuario: str,
        clave: str,
        *,
        tipo_cliente: str = "web",
        expect_ok: bool = True,
    ) -> ApiResponse:
        resp = self.post(
            "/api/v1/auth/ingresar",
            json_body={"usuario": usuario, "clave": clave, "tipo_cliente": tipo_cliente},
            omit_sede=True,
        )
        if expect_ok:
            assert resp.status_code == 200, (
                f"Login failed for {usuario!r}: HTTP {resp.status_code} {resp.text}"
            )
        return resp

    def logout(self) -> ApiResponse:
        resp = self.post("/api/v1/auth/salir", omit_sede=True)
        return resp
