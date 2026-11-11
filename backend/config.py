"""Configuration and storage paths for Handraw Web 2.0."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

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


_OPENAI_IMAGE_PROTOCOLS = {"openai", "openai-images", "openai_images", "v1", "images"}
_LEGACY_IMAGE_PROTOCOLS = {"image-tasks", "image_tasks", "chatgpt2api", "async"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def normalize_image_protocol(raw: Any, *, raw_url: str = "", model: str = "") -> str:
    """Resolve gateway protocol to 'openai' or 'image-tasks'.

    Explicit protocol/api_style always wins. When omitted, standard /v1
    endpoints paired with an explicit non-chatgpt2api model resolve to
    OpenAI-compatible /v1/images/* while legacy chatgpt2api configs keep
    /api/image-tasks/*.
    """
    val = str(raw or "").strip().lower()
    if val in _OPENAI_IMAGE_PROTOCOLS:
        return "openai"
    if val in _LEGACY_IMAGE_PROTOCOLS:
        return "image-tasks"
    clean_url = str(raw_url or "").strip().rstrip("/")
    host = (urllib.parse.urlparse(clean_url).hostname or "").lower()
    if clean_url.endswith("/v1") and "chatgpt2api" not in host and str(model or "").strip():
        return "openai"
    return "image-tasks"


def load_image_config() -> dict[str, Any]:
    """Load normalized local image gateway config from file or environment."""
    data: dict[str, Any] = {}
    cfg_path = get_image_config_path()
    if cfg_path.is_file():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            return {}
    elif os.environ.get("HANDRAW_IMAGE_KEY"):
        data = {
            "url": os.environ.get("HANDRAW_IMAGE_URL", "https://chatgpt2api.handraw-style.com"),
            "key": os.environ.get("HANDRAW_IMAGE_KEY", ""),
            "model": os.environ.get("HANDRAW_IMAGE_MODEL", ""),
            "protocol": os.environ.get("HANDRAW_IMAGE_PROTOCOL", ""),
            "quality": os.environ.get("HANDRAW_IMAGE_QUALITY", ""),
            "timeout": os.environ.get("HANDRAW_IMAGE_TIMEOUT", ""),
        }
    else:
        return {}

    key = str(data.get("key") or data.get("api_key") or "").strip()
    if not key:
        return {}
    raw_url = str(data.get("url") or data.get("base_url") or "https://chatgpt2api.handraw-style.com").strip().rstrip("/")
    base = raw_url[:-3] if raw_url.endswith("/v1") else raw_url
    api_base = raw_url if raw_url.endswith("/v1") else f"{raw_url}/v1"
    model = str(data.get("model") or os.environ.get("HANDRAW_IMAGE_MODEL") or "").strip()
    protocol = normalize_image_protocol(data.get("protocol") or data.get("api_style"), raw_url=raw_url, model=model)
    quality = str(data.get("quality") or "").strip()
    timeout_sec: int | None = None
    timeout_raw = data.get("timeout")
    if timeout_raw not in (None, ""):
        try:
            parsed_t = int(timeout_raw)
            if parsed_t > 0:
                timeout_sec = parsed_t
        except (TypeError, ValueError):
            pass

    out: dict[str, Any] = {
        "base_url": base,
        "api_base_url": api_base,
        "key": key,
        "protocol": protocol,
    }
    if model:
        out["model"] = model
    if quality:
        out["quality"] = quality
    if timeout_sec is not None:
        out["timeout"] = timeout_sec
    return out


def resolve_gateway_model(
    settings: dict[str, Any] | None = None,
    image_cfg: dict[str, Any] | None = None,
) -> str:
    """Resolve effective image model, prioritizing explicit config file settings."""
    cfg = load_image_config() if image_cfg is None else image_cfg
    cfg_model = str(cfg.get("model") or "").strip() if isinstance(cfg, dict) else ""
    if cfg_model:
        return cfg_model
    gw_settings = (settings or {}).get("gateway")
    if isinstance(gw_settings, dict):
        gw_model = str(gw_settings.get("model") or "").strip()
        if gw_model:
            return gw_model
    return "gpt-image-2"


def open_url(
    req: urllib.request.Request,
    *,
    timeout: float,
    extra_handlers: tuple[urllib.request.BaseHandler, ...] = (),
):
    """Open a urllib Request, bypassing system proxies for loopback destinations."""
    host = (urllib.parse.urlparse(req.full_url).hostname or "").lower()
    handlers: list[urllib.request.BaseHandler] = list(extra_handlers)
    if host in _LOOPBACK_HOSTS:
        handlers.append(urllib.request.ProxyHandler({}))
    if handlers:
        return urllib.request.build_opener(*handlers).open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def get_ai_config_path() -> Path:
    return Path(os.environ.get("HANDRAW_AI_CONFIG", str(WEB_ROOT / "ai-service.json")))


def load_ai_config() -> dict:
    p = get_ai_config_path()
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "url": os.environ.get("HANDRAW_AI_URL", "http://127.0.0.1:3065/v1"),
        "key": os.environ.get("HANDRAW_AI_KEY", ""),
        "model": os.environ.get("HANDRAW_AI_MODEL", "deepseek-v4.1-flash"),
    }

