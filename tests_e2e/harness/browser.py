"""Real headless Chromium driver using Playwright (if installed) or pure-stdlib CDP WebSocket.

Supports navigate(), eval_js(), wait_for_selector(), click(), fill(), set_offline(),
IndexedDB inspection, ServiceWorker state inspection, and canvas/SVG presence checks
for apps/web and apps/campo.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import http.client
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import uuid
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from harness.config import discover_browser_binary

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_get_json(url: str, timeout: float = 2.0) -> Any:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http":
        raise ValueError(f"Unsupported CDP HTTP URL: {url!r}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return json.loads(resp.read().decode("utf-8"))
    finally:
        conn.close()


class _StdlibWebSocket:
    """Minimal RFC 6455 client over stdlib socket for Chrome DevTools Protocol."""

    def __init__(self, ws_url: str, timeout: float = 15.0) -> None:
        parsed = urllib.parse.urlparse(ws_url)
        if parsed.scheme != "ws":
            raise ValueError(f"Unsupported WebSocket scheme: {ws_url!r}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)

        key_bytes = os.urandom(16)
        sec_key = base64.b64encode(key_bytes).decode("ascii")
        expected_accept = base64.b64encode(
            hashlib.sha1((sec_key + _WS_GUID).encode("ascii"), usedforsecurity=False).digest()
        ).decode("ascii")

        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {sec_key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(handshake.encode("ascii"))

        buf = bytearray()
        while b"\r\n\r\n" not in buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket handshake closed before completion")
            buf.extend(chunk)
        header_end = buf.index(b"\r\n\r\n")
        header_text = bytes(buf[:header_end]).decode("latin-1")
        if "101 " not in header_text.splitlines()[0]:
            raise ConnectionError(f"WebSocket upgrade failed: {header_text}")
        if expected_accept not in header_text:
            raise ConnectionError("Invalid Sec-WebSocket-Accept from CDP server")
        self._extra = bytes(buf[header_end + 4 :])

    def _recv_exact(self, n: int) -> bytes:
        out = bytearray()
        if self._extra:
            take = min(n, len(self._extra))
            out.extend(self._extra[:take])
            self._extra = self._extra[take:]
        while len(out) < n:
            chunk = self._sock.recv(n - len(out))
            if not chunk:
                raise ConnectionError("WebSocket closed unexpectedly while reading frame")
            out.extend(chunk)
        return bytes(out)

    def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray([0x81])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def _send_pong(self, data: bytes) -> None:
        mask = os.urandom(4)
        length = len(data)
        header = bytearray([0x8A, 0x80 | length])
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self._sock.sendall(bytes(header) + masked)

    def recv_text(self) -> str:
        fragments: list[bytes] = []
        while True:
            b1, b2 = struct.unpack("!BB", self._recv_exact(2))
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                (length,) = struct.unpack("!H", self._recv_exact(2))
            elif length == 127:
                (length,) = struct.unpack("!Q", self._recv_exact(8))
            mask_key = self._recv_exact(4) if masked else b""
            data = self._recv_exact(length)
            if masked:
                data = bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))

            if opcode == 0x8:  # close
                raise ConnectionError("CDP WebSocket closed by browser")
            if opcode == 0x9:  # ping
                self._send_pong(data)
                continue
            if opcode == 0xA:  # pong
                continue
            fragments.append(data)
            if fin:
                return b"".join(fragments).decode("utf-8")

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._sock.close()


class BrowserDriver:
    """Headless Chromium driver (Playwright when available, pure-stdlib CDP fallback)."""

    def __init__(
        self,
        *,
        binary_path: Path | None = None,
        timeout: float = 15.0,
        prefer_playwright: bool = True,
    ) -> None:
        self.binary_path = binary_path or discover_browser_binary()
        self.timeout = timeout
        self.prefer_playwright = prefer_playwright
        self.backend: str = "uninitialized"
        self.events: list[dict[str, Any]] = []

        self._pw: Any = None
        self._pw_browser: Any = None
        self._pw_context: Any = None
        self._pw_page: Any = None

        self._proc: subprocess.Popen[bytes] | None = None
        self._profile_dir: Path | None = None
        self._ws: _StdlibWebSocket | None = None
        self._cmd_id = 0

        self._start()

    def _start(self) -> None:
        if self.prefer_playwright:
            try:
                from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

                self._pw = sync_playwright().start()
                launch_kwargs: dict[str, Any] = {"headless": True}
                if self.binary_path is not None:
                    launch_kwargs["executable_path"] = str(self.binary_path)
                self._pw_browser = self._pw.chromium.launch(**launch_kwargs)
                self._pw_context = self._pw_browser.new_context()
                self._pw_page = self._pw_context.new_page()
                self.backend = "playwright"
                return
            except ImportError:
                pass

        if self.binary_path is None or not self.binary_path.is_file():
            raise RuntimeError(
                "No Chromium/Chrome/Edge binary found for headless browser E2E. "
                "Set SAPEF_E2E_BROWSER_BIN or install Playwright chromium."
            )

        port = _find_free_port()
        try:
            self._profile_dir = Path(tempfile.mkdtemp(prefix="sapef_e2e_cdp_"))
        except PermissionError:
            fallback_root = Path(__file__).resolve().parent.parent / ".e2e_tmp"
            fallback_root.mkdir(parents=True, exist_ok=True)
            self._profile_dir = fallback_root / f"cdp_{uuid.uuid4().hex[:8]}"
            self._profile_dir.mkdir(parents=True, exist_ok=True)
        is_headless_shell = "headless" in self.binary_path.name.lower()
        headless_flag = "--headless" if is_headless_shell else "--headless=new"

        cmd = [
            str(self.binary_path),
            headless_flag,
            "--no-sandbox",
            "--disable-crash-reporter",
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={self._profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "--disable-background-networking",
            "about:blank",
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.monotonic() + self.timeout
        ws_url: str | None = None
        list_url = f"http://127.0.0.1:{port}/json/list"
        while time.monotonic() < deadline:
            try:
                targets = _http_get_json(list_url, timeout=1.0)
                if isinstance(targets, list):
                    for target in targets:
                        if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                            ws_url = str(target["webSocketDebuggerUrl"])
                            break
                    if ws_url:
                        break
            except (urllib.error.URLError, OSError, json.JSONDecodeError):
                pass
            time.sleep(0.15)

        if not ws_url:
            self.close()
            raise TimeoutError("Chromium CDP endpoint did not become ready in time")

        self._ws = _StdlibWebSocket(ws_url, timeout=self.timeout)
        self.backend = "cdp"
        self.cdp("Page.enable")
        self.cdp("Runtime.enable")
        self.cdp("DOM.enable")
        self.cdp("Network.enable")

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def cdp(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a raw Chrome DevTools Protocol command and return its result payload."""
        if self._ws is None:
            raise RuntimeError("CDP WebSocket is not active (backend=" + self.backend + ")")
        self._cmd_id += 1
        cid = self._cmd_id
        payload = {"id": cid, "method": method, "params": params or {}}
        self._ws.send_text(json.dumps(payload))
        while True:
            msg = json.loads(self._ws.recv_text())
            if msg.get("id") == cid:
                if "error" in msg:
                    raise RuntimeError(f"CDP error for {method}: {msg['error']}")
                return dict(msg.get("result", {}))
            if "method" in msg:
                self.events.append(msg)

    def navigate(self, url: str, *, wait_load: bool = True, timeout: float | None = None) -> None:
        wait_s = timeout or self.timeout
        if self.backend == "playwright":
            self._pw_page.goto(url, wait_until="load" if wait_load else "commit")
            return

        self.cdp("Page.navigate", {"url": url})
        if wait_load:
            deadline = time.monotonic() + wait_s
            while time.monotonic() < deadline:
                state = self.eval_js("document.readyState")
                if state == "complete":
                    return
                time.sleep(0.1)
            raise TimeoutError(f"Timed out waiting for page load at {url}")

    def current_url(self) -> str:
        if self.backend == "playwright":
            return str(self._pw_page.url)
        return str(self.eval_js("window.location.href"))

    def eval_js(self, expression: str, *, await_promise: bool = True) -> Any:
        if self.backend == "playwright":
            if await_promise:
                return self._pw_page.evaluate(f"() => ({expression})")
            return self._pw_page.evaluate(f"() => ({expression})")

        res = self.cdp(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
            },
        )
        if "exceptionDetails" in res:
            details = res["exceptionDetails"]
            raise RuntimeError(f"JS evaluation error: {json.dumps(details)}")
        remote = res.get("result", {})
        return remote.get("value")

    def wait_for_selector(self, selector: str, *, timeout: float | None = None) -> bool:
        wait_s = timeout or self.timeout
        if self.backend == "playwright":
            self._pw_page.wait_for_selector(selector, timeout=int(wait_s * 1000))
            return True

        deadline = time.monotonic() + wait_s
        sel_json = json.dumps(selector)
        while time.monotonic() < deadline:
            found = self.eval_js(f"document.querySelector({sel_json}) !== null")
            if found:
                return True
            time.sleep(0.1)
        raise TimeoutError(f"Selector {selector!r} did not appear within {wait_s}s")

    def click(self, selector: str, *, timeout: float | None = None) -> None:
        self.wait_for_selector(selector, timeout=timeout)
        if self.backend == "playwright":
            self._pw_page.click(selector)
            return

        sel_json = json.dumps(selector)
        self.eval_js(
            f"(() => {{ const el = document.querySelector({sel_json}); "
            "el.scrollIntoView({block: 'center'}); el.click(); return true; })()"
        )

    def fill(self, selector: str, value: str, *, timeout: float | None = None) -> None:
        self.wait_for_selector(selector, timeout=timeout)
        if self.backend == "playwright":
            self._pw_page.fill(selector, value)
            return

        sel_json = json.dumps(selector)
        val_json = json.dumps(value)
        js = (
            f"(() => {{"
            f"  const el = document.querySelector({sel_json});"
            f"  const proto = el.tagName === 'TEXTAREA' "
            f"    ? window.HTMLTextAreaElement.prototype "
            f"    : window.HTMLInputElement.prototype;"
            f"  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;"
            f"  if (setter) setter.call(el, {val_json}); else el.value = {val_json};"
            f"  el.dispatchEvent(new Event('input', {{bubbles: true}}));"
            f"  el.dispatchEvent(new Event('change', {{bubbles: true}}));"
            f"  return true;"
            f"}})()"
        )
        self.eval_js(js)

    def set_offline(self, offline: bool) -> None:
        if self.backend == "playwright":
            self._pw_context.set_offline(offline)
            return

        self.cdp(
            "Network.emulateNetworkConditions",
            {
                "offline": offline,
                "latency": 0,
                "downloadThroughput": 0 if offline else -1,
                "uploadThroughput": 0 if offline else -1,
            },
        )

    def get_indexeddb_records(self, db_name: str, store_name: str) -> list[dict[str, Any]]:
        """Read all records from an IndexedDB object store (e.g. Dexie outbox)."""
        db_json = json.dumps(db_name)
        store_json = json.dumps(store_name)
        js = (
            f"new Promise((resolve, reject) => {{"
            f"  const req = window.indexedDB.open({db_json});"
            f"  req.onerror = () => reject(req.error?.message || 'open failed');"
            f"  req.onsuccess = () => {{"
            f"    const db = req.result;"
            f"    if (!db.objectStoreNames.contains({store_json})) {{"
            f"      db.close(); resolve([]); return;"
            f"    }}"
            f"    const tx = db.transaction({store_json}, 'readonly');"
            f"    const store = tx.objectStore({store_json});"
            f"    const getAll = store.getAll();"
            f"    getAll.onerror = () => {{"
            f"      db.close(); reject(getAll.error?.message || 'getAll failed');"
            f"    }};"
            f"    getAll.onsuccess = () => {{"
            f"      const res = getAll.result || []; db.close(); resolve(res);"
            f"    }};"
            f"  }};"
            f"}})"
        )
        result = self.eval_js(js, await_promise=True)
        return list(result or [])

    def get_service_worker_state(self) -> dict[str, Any]:
        """Inspect navigator.serviceWorker controller and registration states."""
        js = (
            "new Promise((resolve) => {"
            "  if (!('serviceWorker' in navigator)) {"
            "    resolve({supported: false, controller: null, registrations: []}); return;"
            "  }"
            "  navigator.serviceWorker.getRegistrations().then((regs) => {"
            "    resolve({"
            "      supported: true,"
            "      controller: navigator.serviceWorker.controller "
            "        ? navigator.serviceWorker.controller.scriptURL : null,"
            "      registrations: regs.map((r) => ({"
            "        scope: r.scope,"
            "        active: r.active ? r.active.state : null,"
            "        waiting: r.waiting ? r.waiting.state : null,"
            "        installing: r.installing ? r.installing.state : null"
            "      }))"
            "    });"
            "  }).catch(() => resolve({supported: true, controller: null, registrations: []}));"
            "})"
        )
        res = self.eval_js(js, await_promise=True)
        return dict(res or {})

    def has_canvas_or_svg(self, selector: str = "body") -> dict[str, int]:
        """Count visible <canvas> and <svg> elements (MapLibre GL / ECharts checks)."""
        sel_json = json.dumps(selector)
        js = (
            f"(() => {{"
            f"  const root = document.querySelector({sel_json}) || document.body;"
            f"  const countVisible = (tag) => Array.from(root.querySelectorAll(tag))"
            f"    .filter((el) => {{"
            f"      const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0;"
            f"    }}).length;"
            f"  return {{canvas: countVisible('canvas'), svg: countVisible('svg')}};"
            f"}})()"
        )
        res = self.eval_js(js)
        return {"canvas": int(res.get("canvas", 0)), "svg": int(res.get("svg", 0))}

    def get_cookies(self) -> list[dict[str, Any]]:
        if self.backend == "playwright":
            return list(self._pw_context.cookies())
        res = self.cdp("Network.getCookies")
        return list(res.get("cookies", []))

    def screenshot(self, path: Path | None = None) -> bytes:
        if self.backend == "playwright":
            raw = self._pw_page.screenshot(type="png")
        else:
            res = self.cdp("Page.captureScreenshot", {"format": "png"})
            raw = base64.b64decode(res["data"])
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        return bytes(raw)

    def close(self) -> None:
        if self._pw_browser is not None:
            with contextlib.suppress(Exception):
                self._pw_browser.close()
            self._pw_browser = None
        if self._pw is not None:
            with contextlib.suppress(Exception):
                self._pw.stop()
            self._pw = None
        if self._ws is not None:
            self._ws.close()
            self._ws = None
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                with contextlib.suppress(Exception):
                    self._proc.kill()
            self._proc = None
        if self._profile_dir is not None and self._profile_dir.exists():
            shutil.rmtree(self._profile_dir, ignore_errors=True)
            self._profile_dir = None
