#!/usr/bin/env python3
"""Entrypoint wrapper launching the full-stack Handraw Web 2.0 multi-channel server.

Channels served simultaneously (default base port 3080):
  - Main Portal:     http://localhost:3080
  - Creation Studio: http://localhost:3081  (or studio.handraw-style.com)
  - Creator Forum:   http://localhost:3082  (or forum.handraw-style.com)
  - Admin Console:   http://localhost:3083  (or admin.handraw-style.com)
"""
from __future__ import annotations

import sys
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent.parent
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from backend.server import (  # noqa: E402
    DualStackHTTPServer,
    HandrawRequestHandler as DemoHandler,
    build_export_zip_package,
    create_channel_server,
    init_database,
    load_image_service_config,
    main,
    size_for_ratio,
)

__all__ = [
    "DualStackHTTPServer",
    "DemoHandler",
    "build_export_zip_package",
    "create_channel_server",
    "init_database",
    "load_image_service_config",
    "main",
    "size_for_ratio",
]

if __name__ == "__main__":
    main()
