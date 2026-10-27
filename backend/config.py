"""Configuration and storage paths for Handraw Web 2.0."""
from __future__ import annotations

import os
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = WEB_ROOT / "demo"
CONTENT_DIR = WEB_ROOT / "plugin" / "content"

DEFAULT_STYLE_IMAGES_DIR = Path(os.environ.get("HANDRAW_STYLE_IMAGES_DIR", r"E:\handraw-style\images"))
DEFAULT_STYLE_REFS_DIR = Path(
    os.environ.get("HANDRAW_STYLE_REFS_DIR", r"E:\handraw-style\skills\handdraw-style-prompter\references")
)

SESSION_COOKIE_NAME = "handraw_sid"
SESSION_TTL_SECONDS = 30 * 86400

# Safety defaults.  Runtime switches live in ``runtime_policy``; keeping these
# values here makes the operational boundary visible to deployment code too.
DEFAULT_BIND_HOST = "127.0.0.1"
MAX_JSON_BODY_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def get_storage_root() -> Path:
    custom = os.environ.get("HANDRAW_PRIVATE_STORAGE") or os.environ.get("HANDRAW_LOCAL_DIR")
    if custom:
        return Path(custom).resolve()
    return (WEB_ROOT / ".local").resolve()


def get_db_path() -> Path:
    explicit = os.environ.get("HANDRAW_DB_PATH")
    if explicit:
        return Path(explicit).resolve()
    return get_storage_root() / "handraw_v2.db"


def get_uploads_dir() -> Path:
    explicit = os.environ.get("HANDRAW_UPLOADS_DIR")
    if explicit:
        return Path(explicit).resolve()
    return get_storage_root() / "uploads"


def get_generated_dir() -> Path:
    explicit = os.environ.get("HANDRAW_GENERATED_DIR")
    if explicit:
        return Path(explicit).resolve()
    return get_storage_root() / "demo_generated"


def get_image_config_path() -> Path:
    return Path(os.environ.get("HANDRAW_IMAGE_CONFIG", str(WEB_ROOT / "image-service.json")))
