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


DEFAULT_PAYMENT_PACKAGES: list[dict[str, Any]] = [
    {"id":f"cash_{yuan}","purpose":"cash","title":f"生图余额 ¥{yuan}","description":"仅用于图片生成，不附赠积分","credits":0,"price_cents":yuan*100,"badge":"","product_id":f"cash_{yuan}"}
    for yuan in (10,30,100)
] + [
    {"id":f"points_{yuan*10}","purpose":"points","title":f"{yuan*10} 社区积分","description":"用于内容和资源解锁，不可兑换现金或生图余额","credits":yuan*10,"price_cents":yuan*100,"badge":"","product_id":f"points_{yuan*10}"}
    for yuan in (5,10,30)
]


def get_payment_config_path() -> Path:
    return Path(os.environ.get("HANDRAW_PAYMENT_CONFIG", str(WEB_ROOT / "payment-service.json")))


def _parse_bool_flag(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on", "enable", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disable", "disabled"}:
        return False
    return default


def _format_price_display(price_cents: int, currency: str) -> str:
    cur = (currency or "CNY").strip().upper()
    sym = "¥" if cur == "CNY" else ("€" if cur == "EUR" else ("£" if cur == "GBP" else "$"))
    raw = f"{price_cents / 100:.2f}"
    return f"{sym}{raw}".removesuffix(".00")


def load_payment_config() -> dict[str, Any]:
    """Load XorPay (or Creem) billing configuration from file and environment overrides."""
    data: dict[str, Any] = {}
    cfg_path = get_payment_config_path()
    if cfg_path.is_file():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            return {}

    provider = str(os.environ.get("HANDRAW_PAYMENT_PROVIDER") or data.get("provider") or "xorpay").strip().lower()
    currency = (
        str(
            os.environ.get("HANDRAW_PAYMENT_CURRENCY")
            or os.environ.get("HANDRAW_XORPAY_CURRENCY")
            or data.get("currency")
            or ("CNY" if provider == "xorpay" else "USD")
        )
        .strip()
        .upper()
        or ("CNY" if provider == "xorpay" else "USD")
    )

    # XorPay settings
    xorpay_aid = str(os.environ.get("HANDRAW_XORPAY_AID") or data.get("aid") or "").strip()
    xorpay_app_secret = str(os.environ.get("HANDRAW_XORPAY_APP_SECRET") or data.get("app_secret") or "").strip()
    xorpay_api_base = str(os.environ.get("HANDRAW_XORPAY_API_BASE") or data.get("api_base") or "https://xorpay.com").strip().rstrip("/")
    xorpay_notify_url = str(os.environ.get("HANDRAW_XORPAY_NOTIFY_URL") or data.get("notify_url") or "").strip()
    xorpay_pay_type = str(os.environ.get("HANDRAW_XORPAY_PAY_TYPE") or data.get("pay_type") or "alipay").strip().lower()

    # Creem settings (backward compatibility)
    creem_api_key = str(os.environ.get("HANDRAW_CREEM_API_KEY") or data.get("api_key") or "").strip()
    creem_webhook_secret = str(os.environ.get("HANDRAW_CREEM_WEBHOOK_SECRET") or data.get("webhook_secret") or "").strip()

    raw_test_flag = (
        os.environ.get("HANDRAW_PAYMENT_TEST_MODE")
        if "HANDRAW_PAYMENT_TEST_MODE" in os.environ
        else (
            os.environ.get("HANDRAW_XORPAY_TEST_MODE")
            if "HANDRAW_XORPAY_TEST_MODE" in os.environ
            else (
                os.environ.get("HANDRAW_CREEM_TEST_MODE")
                if "HANDRAW_CREEM_TEST_MODE" in os.environ
                else data.get("test_mode")
            )
        )
    )
    test_mode = _parse_bool_flag(raw_test_flag, default=(False if provider == "xorpay" else True))
    if creem_api_key.startswith("creem_test_"):
        test_mode = True

    raw_packages = data.get("packages")
    if not isinstance(raw_packages, list):
        raw_packages = DEFAULT_PAYMENT_PACKAGES

    packages: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw_packages:
        if not isinstance(item, dict):
            continue
        pack_id = str(item.get("id") or "").strip()
        product_id = str(item.get("product_id") or pack_id).strip()
        try:
            credits = int(item.get("credits") or 0)
            price_cents = int(item.get("price_cents") or 0)
        except (TypeError, ValueError):
            continue
        purpose=str(item.get("purpose") or "points")
        if purpose not in ("cash","points") or currency!="CNY":
            continue
        if purpose=="cash" and (credits!=0 or price_cents not in (1000,3000,10000)):
            continue
        if purpose=="points" and (credits not in (50,100,300) or price_cents!=credits*10):
            continue
        if not pack_id or pack_id in seen_ids or price_cents <= 0:
            continue
        seen_ids.add(pack_id)
        packages.append(
            {
                "id": pack_id,
                "title": str(item.get("title") or f"{credits} 积分加油包").strip(),
                "description": str(item.get("description") or "").strip(),
                "credits": credits,
                "purpose": purpose,
                "price_cents": price_cents,
                "price_display": str(item.get("price_display") or _format_price_display(price_cents, currency)).strip(),
                "badge": str(item.get("badge") or "").strip(),
                "product_id": product_id,
            }
        )

    if provider == "xorpay":
        configured = bool(
            xorpay_aid
            and xorpay_app_secret
            and not xorpay_aid.startswith("YOUR_")
            and not xorpay_app_secret.startswith("YOUR_")
            and packages
        )
        return {
            "provider": "xorpay",
            "aid": xorpay_aid,
            "app_secret": xorpay_app_secret,
            "api_base": xorpay_api_base,
            "notify_url": xorpay_notify_url,
            "pay_type": xorpay_pay_type,
            "currency": currency,
            "test_mode": test_mode,
            "packages": packages,
            "active_packages": packages,
            "enabled": configured,
        }

    # Creem provider branch
    active_packages = [
        p
        for p in packages
        if p["product_id"]
        and not p["product_id"].startswith("PRODUCT_ID_")
        and not p["product_id"].startswith("YOUR_")
        and p["product_id"].startswith("prod_")
    ]
    configured = bool(
        creem_api_key
        and not creem_api_key.startswith("YOUR_")
        and active_packages
    )
    return {
        "provider": provider,
        "api_key": creem_api_key,
        "webhook_secret": creem_webhook_secret,
        "currency": currency,
        "test_mode": test_mode,
        "packages": packages,
        "active_packages": active_packages,
        "enabled": configured,
    }


def get_public_billing_summary(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return non-secret public billing configuration for frontend wallet views."""
    resolved = load_payment_config() if cfg is None else cfg
    if not resolved or not resolved.get("enabled"):
        return {
            "enabled": False,
            "provider": str((resolved or {}).get("provider") or "xorpay"),
            "testMode": bool((resolved or {}).get("test_mode", False)),
            "currency": str((resolved or {}).get("currency") or "CNY"),
            "payType": str((resolved or {}).get("pay_type") or "alipay"),
            "packages": [],
        }
    return {
        "enabled": True,
        "provider": resolved["provider"],
        "testMode": bool(resolved["test_mode"]),
        "currency": resolved["currency"],
        "payType": str(resolved.get("pay_type") or "alipay"),
        "packages": [
            {
                "id": p["id"],
                "title": p["title"],
                "description": p["description"],
                "credits": int(p["credits"]),
                "purpose": p.get("purpose","points"),
                "priceCents": int(p["price_cents"]),
                "priceDisplay": p["price_display"],
                "badge": p["badge"],
            }
            for p in resolved["active_packages"]
        ],
    }

