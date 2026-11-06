"""Centralized, rotating application logs with safe request identifiers.

Set HANDRAW_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR|CRITICAL (default INFO).
Set HANDRAW_LOG_MAX_BYTES and HANDRAW_LOG_BACKUPS for rotation.
Files live under HANDRAW_LOG_DIR or <private storage>/logs.
Never log headers, cookies, authorization codes, query strings or request bodies.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LEVELS = {name: getattr(logging, name) for name in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")}
_LOCK = threading.Lock()
_CONFIGURED = False


class _SensitiveDataFilter(logging.Filter):
    """Redact common credentials that may accidentally appear in exception text."""
    _patterns = (
        (re.compile(r"(?i)(client_secret|api[_-]?key|access_token|refresh_token|password|authorization|cookie)(\s*[=:]\s*)([^\s,;&]+)"), r"\1\2[REDACTED]"),
        (re.compile(r"(?i)(postgres(?:ql)?://[^:/\s]+:)[^@/\s]+(@)"), r"\1[REDACTED]\2"),
        (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+"), r"\1[REDACTED]"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        # Format first so redaction applies to interpolated arguments as well.
        message = record.getMessage()
        for pattern, replacement in self._patterns:
            message = pattern.sub(replacement, message)
        record.msg = message
        record.args = ()
        return True


class _ErrorOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.ERROR


def _int_env(name: str, default: int, low: int, high: int) -> int:
    try:
        return min(high, max(low, int(os.environ.get(name, str(default)))))
    except (ValueError, TypeError):
        return default


def configure_logging(private_storage: str | Path | None = None) -> Path:
    """Configure process-wide Handraw logs exactly once; return log directory."""
    global _CONFIGURED
    with _LOCK:
        log_dir = Path(os.environ.get("HANDRAW_LOG_DIR") or (
            Path(private_storage) / "logs" if private_storage else Path(".local") / "logs"
        )).resolve()
        log_dir.mkdir(parents=True, exist_ok=True)
        if _CONFIGURED:
            return log_dir

        level_name = os.environ.get("HANDRAW_LOG_LEVEL", "INFO").strip().upper()
        level = _LEVELS.get(level_name, logging.INFO)
        max_bytes = _int_env("HANDRAW_LOG_MAX_BYTES", 10 * 1024 * 1024, 1024, 100 * 1024 * 1024)
        backup_count = _int_env("HANDRAW_LOG_BACKUPS", 5, 1, 30)
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s [%(process)d:%(threadName)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
        root = logging.getLogger()
        root.setLevel(level)

        for filename, handler_level, error_only in (
            ("handraw.log", level, False),
            ("handraw-error.log", logging.ERROR, True),
        ):
            handler = RotatingFileHandler(
                log_dir / filename, maxBytes=max_bytes,
                backupCount=backup_count, encoding="utf-8",
            )
            handler.setLevel(handler_level)
            handler.setFormatter(formatter)
            handler.addFilter(_SensitiveDataFilter())
            if error_only:
                handler.addFilter(_ErrorOnlyFilter())
            root.addHandler(handler)

        stderr = logging.StreamHandler(sys.stderr)
        stderr.setLevel(level)
        stderr.setFormatter(formatter)
        stderr.addFilter(_SensitiveDataFilter())
        root.addHandler(stderr)
        _CONFIGURED = True
        logging.getLogger(__name__).info(
            "logging_initialized level=%s dir=%s max_bytes=%d backups=%d",
            level_name if level_name in _LEVELS else "INFO", log_dir, max_bytes, backup_count,
        )
        return log_dir
