"""Local single-process logging: stderr plus bounded, restart-safe files."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
from logging.handlers import RotatingFileHandler

from .config import WEB_ROOT, get_storage_root

_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "y", "enable", "enabled"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "n", "disable", "disabled"})


def local_debug_stacks_enabled() -> bool:
    """Return True when detailed local debug stack traces should be recorded."""
    explicit = os.environ.get("HANDRAW_LOG_STACKS")
    if explicit is not None:
        norm = explicit.strip().lower()
        if norm in _TRUE_VALUES:
            return True
        if norm in _FALSE_VALUES:
            return False
    env_name = os.environ.get("HANDRAW_ENV", "").strip().lower()
    if env_name in ("prod", "production", "staging"):
        return False
    if env_name in ("local", "dev", "development", "debug"):
        return True
    if os.environ.get("HANDRAW_ALLOW_PUBLIC_BIND", "").strip().lower() in _TRUE_VALUES:
        return False
    if os.environ.get("HANDRAW_TRUST_PROXY", "").strip().lower() in _TRUE_VALUES:
        return False
    try:
        if get_storage_root() == (WEB_ROOT / ".local").resolve():
            return True
    except Exception:
        pass
    return os.environ.get("HANDRAW_DEMO_MODE", "").strip().lower() in _TRUE_VALUES


def redact_sensitive_text(text: str) -> str:
    """Strip URL queries, embedded credentials, bearer headers, and API keys."""
    if not text:
        return ""
    out = re.sub(r"(https?://[^\s?'\"<>]+)\?[^\s'\"<>]*", r"\1?[redacted]", text)
    out = re.sub(r"(://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", out)
    out = re.sub(r"(?i)\b(Bearer\s+)[^\s,;]+", r"\1[redacted]", out)
    out = re.sub(
        r"(?i)\b((?:api_key|client_secret|access_token|refresh_token|password)\s*[=:]\s*)[^\s,;]+",
        r"\1[redacted]", out,
    )
    out = re.sub(
        r'(?i)"((?:api_key|client_secret|access_token|refresh_token|password))"\s*:\s*"[^"]*"',
        r'"\1":"[redacted]"', out,
    )
    out = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "sk-[redacted]", out)
    return out


def sanitize_log_text(text: object, max_len: int = 400) -> str:
    """Collapse control whitespace, redact credentials, and bound length for logs."""
    if text is None:
        return ""
    cleaned = re.sub(r"[\r\n\t]+", " ", str(text))
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    cleaned = redact_sensitive_text(cleaned)
    if max_len > 3 and len(cleaned) > max_len:
        return cleaned[: max_len - 3].rstrip() + "..."
    return cleaned[:max_len]


def extract_http_error_summary(raw_body: bytes | str | None, max_len: int = 300) -> str:
    """Extract a concise, redacted diagnostic summary from an upstream HTTP error body."""
    if raw_body is None:
        return ""
    if isinstance(raw_body, bytes):
        text = raw_body[:16384].decode("utf-8", errors="ignore").strip()
    else:
        text = str(raw_body)[:16384].strip()
    if not text:
        return ""

    candidate = ""
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None

    if isinstance(parsed, dict):
        err_val = parsed.get("error")
        if isinstance(err_val, dict):
            msg = str(err_val.get("message") or err_val.get("detail") or err_val.get("msg") or "").strip()
            code = str(err_val.get("code") or err_val.get("type") or "").strip()
            if msg and code and code not in msg:
                candidate = f"{msg} [{code}]"
            else:
                candidate = msg or code
        elif isinstance(err_val, str):
            candidate = err_val.strip()
        if not candidate:
            for key in ("detail", "message", "msg", "error_description"):
                val = parsed.get(key)
                if isinstance(val, str) and val.strip():
                    candidate = val.strip()
                    break

    if not candidate:
        candidate = text
        if "<" in candidate and ">" in candidate and re.search(r"<(?:html|body|title|h1|p)\b", candidate, re.I):
            candidate = re.sub(r"<[^>]+>", " ", candidate)

    return sanitize_log_text(candidate, max_len=max_len)


def log_unhandled_exception(exc_type, value, traceback) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, value, traceback)
        return
    logging.getLogger("handraw.system").critical(
        "event=process_unhandled_exception", exc_info=(exc_type, value, traceback),
    )


def log_unhandled_thread(args) -> None:
    if issubclass(args.exc_type, SystemExit):
        return
    logging.getLogger("handraw.system").critical(
        "event=thread_unhandled_exception thread=%s", getattr(args.thread, "name", "unknown"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


class RedactingFormatter(logging.Formatter):
    """Remove URL queries and common credentials, including in tracebacks.

    Callers must still avoid logging bodies, headers, or provider responses.
    This formatter is a second line of defense, not an arbitrary-secret detector.
    """

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        return redact_sensitive_text(text)


def configure_logging(port: int = 3080) -> None:
    for stream in (sys.stderr, sys.stdout):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(line_buffering=True)
        except Exception:
            pass
    root = logging.getLogger()
    if any(getattr(handler, "_handraw_logging", False) for handler in root.handlers):
        return
    log_dir = get_storage_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler = RotatingFileHandler(
        log_dir / f"web-{int(port)}.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    # Existing launchers redirect stderr into service-3080.err.log.
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    for handler in (file_handler, console):
        handler.setFormatter(formatter)
        handler._handraw_logging = True
        root.addHandler(handler)
    root.setLevel(logging.INFO)
    sys.excepthook = log_unhandled_exception
    threading.excepthook = log_unhandled_thread
