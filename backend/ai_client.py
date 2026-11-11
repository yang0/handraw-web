"""Unified AI client for Handraw Web 2.0.

Provides standard chat completions with unified timeout, single retry on
transient network/5xx errors, and structured execution metadata.
Per AGENTS.md and security policy:
- Never log message bodies, prompt contents, or API keys.
- 不读取代理环境变量；网关需直连可达。
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import socket
import ssl
import threading
import time
import traceback
import urllib.parse
from typing import Any

from backend.config import load_ai_config
from backend.observability import extract_http_error_summary, local_debug_stacks_enabled

logger = logging.getLogger(__name__)


MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2MB hard limit


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _resolve_host(host: str, port: int, timeout: float) -> tuple[str, bool]:
    if _is_ip_literal(host):
        return host, True

    resolved_ip: str | None = None

    def _worker() -> None:
        nonlocal resolved_ip
        try:
            infos = socket.getaddrinfo(host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
            if infos:
                resolved_ip = infos[0][4][0]
        except Exception:
            pass

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(timeout=max(0.001, timeout))
    if th.is_alive():
        return "", False
    if resolved_ip:
        return resolved_ip, True
    return "", False


class DirectHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, connect_ip: str, port: int | None = None, **kwargs: Any) -> None:
        super().__init__(host, port=port, **kwargs)
        self.connect_ip = connect_ip

    def connect(self) -> None:
        self.sock = self._create_connection(
            (self.connect_ip, self.port), self.timeout, self.source_address
        )


class DirectHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, connect_ip: str, port: int | None = None, **kwargs: Any) -> None:
        super().__init__(host, port=port, **kwargs)
        self.connect_ip = connect_ip

    def connect(self) -> None:
        self.sock = self._create_connection(
            (self.connect_ip, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def chat(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    timeout: float = 60.0,
    json_mode: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Execute a chat completion request against the configured AI service.

    Returns:
        (response_text, meta)
        meta contains:
            ok (bool): True if response succeeded and content is non-empty.
            reason (str): Empty string on success, or one of:
                'no_key', 'timeout', 'network', 'empty', 'http_<code>', 'too_large', 'invalid_json'
            elapsed_ms (int): Total round-trip time in milliseconds.
    """
    start_time = time.monotonic()
    deadline = start_time + max(0.01, timeout)

    def _meta(ok: bool, reason: str = "") -> dict[str, Any]:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        return {
            "ok": ok,
            "reason": reason,
            "elapsed_ms": elapsed_ms,
        }

    cfg = load_ai_config()
    base = str(cfg.get("url") or "").rstrip("/")
    key = str(cfg.get("key") or "").strip()
    model = str(cfg.get("model") or "deepseek-v4.1-flash").strip()

    if not base or not key:
        logger.info("AI call skipped: no key or endpoint configured")
        return "", _meta(False, "no_key")

    api_url = f"{base}/chat/completions"
    u = urllib.parse.urlsplit(api_url)
    scheme = (u.scheme or "http").lower()
    host = u.hostname or "127.0.0.1"
    port = u.port
    path = u.path or "/chat/completions"
    if u.query:
        path = f"{path}?{u.query}"

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Host": host if port is None else f"{host}:{port}",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "Handraw-AIClient/1.0",
        "Content-Length": str(len(data_bytes)),
    }

    max_attempts = 2
    attempt = 0
    last_reason = ""

    while attempt < max_attempts:
        attempt += 1
        rem = deadline - time.monotonic()
        if rem <= 0:
            return "", _meta(False, "timeout")

        # 1. Resolve host with deadline (IP literals skip worker thread)
        connect_ip = host
        if not _is_ip_literal(host):
            resolve_ip, ok = _resolve_host(host, port or (443 if scheme == "https" else 80), rem)
            if not ok:
                return "", _meta(False, "timeout")
            connect_ip = resolve_ip

        rem = deadline - time.monotonic()
        if rem <= 0:
            return "", _meta(False, "timeout")

        # 2. Establish connection object
        if scheme == "https":
            context = ssl.create_default_context()
            conn: http.client.HTTPConnection = DirectHTTPSConnection(
                host, connect_ip, port=port, context=context, timeout=max(0.01, rem)
            )
        else:
            conn = DirectHTTPConnection(host, connect_ip, port=port, timeout=max(0.01, rem))

        timed_out = False
        active_sock: socket.socket | None = None

        def _abort() -> None:
            nonlocal timed_out
            timed_out = True
            sock = active_sock or getattr(conn, "sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    sock.close()
                except Exception:
                    pass
            try:
                conn.close()
            except Exception:
                pass

        timer = threading.Timer(max(0.001, rem), _abort)
        timer.daemon = True
        timer.start()

        try:
            conn.connect()
            active_sock = conn.sock

            # 3. Connection established: Check deadline again BEFORE sending request!
            if timed_out or time.monotonic() >= deadline:
                try:
                    conn.close()
                except Exception:
                    pass
                return "", _meta(False, "timeout")

            conn.request("POST", path, body=data_bytes, headers=headers)
            response = conn.getresponse()
            if active_sock is None:
                active_sock = getattr(conn, "sock", None)
            if active_sock is None and hasattr(response, "fp") and hasattr(response.fp, "raw"):
                active_sock = getattr(response.fp.raw, "_sock", None)

            status_code = response.status

            if status_code < 200 or status_code >= 300:
                err_raw = b""
                if not timed_out and time.monotonic() < deadline:
                    try:
                        chunk = response.read(16384)
                        if isinstance(chunk, bytes):
                            err_raw = chunk
                        elif isinstance(chunk, str):
                            err_raw = chunk.encode("utf-8", errors="ignore")
                    except Exception:
                        err_raw = b""
                err_summary = extract_http_error_summary(err_raw)
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                logger.warning(
                    "AI HTTP error %d on attempt %d for %s (model: %s, elapsed_ms=%d, body_len=%d): %s",
                    status_code,
                    attempt,
                    api_url,
                    model,
                    elapsed_ms,
                    len(err_raw),
                    err_summary or "-",
                )
                if local_debug_stacks_enabled():
                    logging.getLogger("handraw.trace").info(
                        "ai_http_error status=%d attempt=%d url=%s model=%s\n%s",
                        status_code,
                        attempt,
                        api_url,
                        model,
                        "".join(traceback.format_stack(limit=15)).rstrip(),
                    )
                rem_after = deadline - time.monotonic()
                if 500 <= status_code <= 599 and attempt < max_attempts and rem_after > 0.05 and not timed_out:
                    last_reason = f"http_{status_code}"
                    if rem_after > 0.1:
                        time.sleep(0.05)
                    continue
                if timed_out or rem_after <= 0:
                    return "", _meta(False, "timeout")
                return "", _meta(False, f"http_{status_code}")

            # Read response body in 64KB chunks
            chunks: list[bytes] = []
            total_read = 0
            while True:
                if timed_out or time.monotonic() >= deadline:
                    return "", _meta(False, "timeout")
                chunk = response.read(65536)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > MAX_RESPONSE_BYTES:
                    logger.warning("AI response exceeded %d bytes limit", MAX_RESPONSE_BYTES)
                    return "", _meta(False, "too_large")
                chunks.append(chunk)

            if timed_out or time.monotonic() >= deadline:
                return "", _meta(False, "timeout")

            resp_bytes = b"".join(chunks)

            # V3: Parse JSON; return invalid_json on decode failure without retrying
            try:
                data = json.loads(resp_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as j_err:
                logger.warning(
                    "AI response is not valid JSON on attempt %d (elapsed_ms=%d): %s",
                    attempt,
                    int((time.monotonic() - start_time) * 1000),
                    j_err,
                    exc_info=True,
                )
                return "", _meta(False, "invalid_json")

            choices = data.get("choices") or []
            if not choices:
                return "", _meta(False, "empty")

            content = str(choices[0].get("message", {}).get("content") or "")
            if not content:
                return "", _meta(False, "empty")

            return content, _meta(True, "")

        except (socket.timeout, TimeoutError):
            logger.warning(
                "AI request timed out on attempt %d (elapsed_ms=%d)",
                attempt,
                int((time.monotonic() - start_time) * 1000),
                exc_info=True,
            )
            return "", _meta(False, "timeout")

        except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError, socket.error) as exc:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            if timed_out or time.monotonic() >= deadline:
                logger.warning(
                    "AI request timed out on attempt %d (aborted by timer, elapsed_ms=%d)",
                    attempt,
                    elapsed_ms,
                    exc_info=True,
                )
                return "", _meta(False, "timeout")

            rem_after = deadline - time.monotonic()
            logger.warning(
                "AI connection error on attempt %d (%s) for %s (model: %s, elapsed_ms=%d)",
                attempt,
                type(exc).__name__,
                api_url,
                model,
                elapsed_ms,
                exc_info=True,
            )
            if attempt < max_attempts and rem_after > 0.05:
                last_reason = "network"
                if rem_after > 0.1:
                    time.sleep(0.05)
                continue
            if rem_after <= 0:
                return "", _meta(False, "timeout")
            return "", _meta(False, "network")

        except Exception as exc:
            if timed_out or time.monotonic() >= deadline:
                return "", _meta(False, "timeout")
            logger.warning(
                "AI unretryable error on attempt %d (%s, elapsed_ms=%d)",
                attempt,
                exc,
                int((time.monotonic() - start_time) * 1000),
                exc_info=True,
            )
            return "", _meta(False, "network")

        finally:
            timer.cancel()
            try:
                conn.close()
            except Exception:
                pass

    return "", _meta(False, last_reason or "timeout")
