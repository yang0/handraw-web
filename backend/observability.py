"""Local single-process logging: stderr plus bounded, restart-safe files."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from .config import get_storage_root


class RedactingFormatter(logging.Formatter):
    """Remove URL queries and common credentials, including in tracebacks.

    Callers must still avoid logging bodies, headers, or provider responses.
    This formatter is a second line of defense, not an arbitrary-secret detector.
    """

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        text = re.sub(r"(https?://[^\s?'\"<>]+)\?[^\s'\"<>]*", r"\1?[redacted]", text)
        text = re.sub(r"(://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", text)
        text = re.sub(r"(?i)\b(Bearer\s+)[^\s,;]+", r"\1[redacted]", text)
        text = re.sub(
            r"(?i)\b((?:api_key|client_secret|access_token|refresh_token|password)\s*[=:]\s*)[^\s,;]+",
            r"\1[redacted]", text,
        )
        return text


def configure_logging(port: int = 3080) -> None:
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
