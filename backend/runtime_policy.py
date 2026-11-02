"""Runtime safety policy shared by the HTTP entrypoint.

Demo behaviour is opt-in.  This module also owns the small validation helpers
used at the request boundary so the server does not accidentally expose local
developer state in production.
"""
from __future__ import annotations

import base64
import binascii
import html
import os
import re
import threading
import time
from collections import OrderedDict
from html.parser import HTMLParser
from typing import Mapping
from urllib.parse import urlparse

MAX_JSON_BODY_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024
_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "y", "enable", "enabled"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", "n", "disable", "disabled"})


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default


def demo_mode_enabled() -> bool:
    return env_flag("HANDRAW_DEMO_MODE") or env_flag("HANDRAW_ALLOW_DEMO_ROUTES")


def recharge_enabled() -> bool:
    # There is no payment provider/settlement adapter in this repository.
    # Even a stray HANDRAW_ENABLE_RECHARGE=1 must not mint credits in a real
    # environment; the flag is retained only for an explicitly isolated demo.
    return demo_mode_enabled() and env_flag("HANDRAW_ENABLE_RECHARGE", False)


def include_private_benchmark_assets() -> bool:
    return env_flag("HANDRAW_INCLUDE_PRIVATE_CUSTOM_ASSETS", False)


def bind_host(requested: str | None = None) -> str:
    """Wildcard binds require HANDRAW_ALLOW_PUBLIC_BIND=1."""
    raw = (requested or os.environ.get("HANDRAW_BIND_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    if raw in {"0.0.0.0", "::", "*"} and not env_flag("HANDRAW_ALLOW_PUBLIC_BIND", False):
        return "127.0.0.1"
    return raw


def _split_origins(raw: str) -> set[str]:
    result: set[str] = set()
    for item in re.split(r"[,;\s]+", raw.strip()):
        clean = item.strip().rstrip("/").lower()
        if not clean:
            continue
        parsed = urlparse(clean)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
            continue
        result.add(f"{parsed.scheme}://{parsed.netloc}")
    return result


def trusted_origins() -> frozenset[str]:
    configured = os.environ.get("HANDRAW_ALLOWED_ORIGINS")
    if configured is not None:
        return frozenset(_split_origins(configured))
    defaults = {
        "https://handraw-style.com",
        "https://www.handraw-style.com",
        "https://studio.handraw-style.com",
        "https://forum.handraw-style.com",
        "https://admin.handraw-style.com",
    }
    for host in ("localhost", "127.0.0.1", "[::1]"):
        defaults.add(f"http://{host}:3080")
    return frozenset(defaults)


def normalize_origin(value: str | None) -> str:
    raw = (value or "").strip().rstrip("/").lower()
    if raw == "null":
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def origin_allowed(value: str | None) -> bool:
    origin = normalize_origin(value)
    return bool(origin and origin in trusted_origins())


def _header_ci(headers: Mapping[str, str], name: str) -> str:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return str(value or "")
    return ""


def check_write_origin(headers: Mapping[str, str], *, allow_missing_for_bearer: bool = True) -> tuple[bool, str]:
    """Check Origin/Referer for cookie writes; token clients may omit it."""
    origin = _header_ci(headers, "Origin")
    if origin:
        return (True, "") if origin_allowed(origin) else (False, "untrusted_origin")
    referer = _header_ci(headers, "Referer")
    if referer:
        parsed = urlparse(referer)
        ref_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
        return (True, "") if origin_allowed(ref_origin) else (False, "untrusted_referer")
    if allow_missing_for_bearer and any(
        _header_ci(headers, key)
        for key in ("Authorization", "X-Handraw-Token", "Api-Key")
    ):
        return True, ""
    if _header_ci(headers, "Cookie"):
        return False, "missing_origin"
    return True, ""


class _TokenBucketLimiter:
    """Bounded, thread-safe token buckets for unauthenticated auth endpoints."""

    def __init__(self, capacity: float, refill_seconds: float, max_keys: int = 2048) -> None:
        self.capacity = float(capacity)
        self.refill_rate = 1.0 / max(1.0, float(refill_seconds))
        self.max_keys = max(64, int(max_keys))
        self._lock = threading.Lock()
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def allow(self, key: str, cost: float = 1.0) -> bool:
        clean = (key or "anonymous").strip()[:180]
        now = time.monotonic()
        with self._lock:
            tokens, previous = self._buckets.pop(clean, (self.capacity, now))
            tokens = min(self.capacity, tokens + max(0.0, now - previous) * self.refill_rate)
            permitted = tokens >= cost
            if permitted:
                tokens -= cost
            self._buckets[clean] = (tokens, now)
            while len(self._buckets) > self.max_keys:
                self._buckets.popitem(last=False)
            return permitted


_AUTH_LIMITERS = {
    "login": _TokenBucketLimiter(8, 300),
    "register": _TokenBucketLimiter(5, 900),
    "reset": _TokenBucketLimiter(5, 900),
    "verification": _TokenBucketLimiter(5, 900),
}


def check_auth_rate_limit(scope: str, key: str) -> bool:
    limiter = _AUTH_LIMITERS.get(scope) or _AUTH_LIMITERS["login"]
    return limiter.allow(f"{scope}:{key}")


_ALLOWED_IMAGE_MIMES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def image_extension_for_mime(mime: str) -> str:
    clean = (mime or "").split(";", 1)[0].strip().lower()
    if clean not in _ALLOWED_IMAGE_MIMES:
        raise ValueError("仅支持 PNG、JPEG 或 WebP 图片")
    return _ALLOWED_IMAGE_MIMES[clean]


def validate_image_bytes(raw: bytes, mime: str = "") -> tuple[bytes, str]:
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise ValueError("图片内容为空")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("单张图片不能超过 15MB")
    clean_mime = (mime or "").split(";", 1)[0].strip().lower()
    ext = image_extension_for_mime(clean_mime)
    payload = bytes(raw)
    if clean_mime == "image/png" and not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG 图片签名无效")
    if clean_mime == "image/jpeg" and not payload.startswith(b"\xff\xd8\xff"):
        raise ValueError("JPEG 图片签名无效")
    if clean_mime == "image/webp" and not (payload.startswith(b"RIFF") and payload[8:12] == b"WEBP"):
        raise ValueError("WebP 图片签名无效")
    return payload, ext


def decode_data_image_url(data_url: str) -> tuple[bytes, str, str]:
    raw = (data_url or "").strip()
    match = re.fullmatch(r"data:([^;,\s]+);base64,([A-Za-z0-9+/=\r\n]+)", raw, flags=re.IGNORECASE)
    if not match:
        raise ValueError("无效的图片上传格式（需为 data:image/png|jpeg|webp;base64）")
    mime = match.group(1).lower()
    try:
        payload = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("图片 Base64 解码失败") from exc
    payload, ext = validate_image_bytes(payload, mime)
    return payload, ext, mime


def sanitize_media_url(value: str, *, allow_data: bool = False) -> str:
    clean = (value or "").strip()
    if not clean or any(ord(ch) < 0x20 for ch in clean):
        return ""
    if allow_data and clean.lower().startswith("data:image/"):
        try:
            decode_data_image_url(clean)
        except ValueError:
            return ""
        return clean
    # Disallow protocol-relative // or backslash tricks /\ or \\
    if clean.startswith("/") and not clean.startswith(("//", "/\\")) and "\\" not in clean:
        return clean
    parsed = urlparse(clean)
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        return clean
    return ""


_ALLOWED_HTML_TAGS = frozenset(
    {
        "a", "b", "blockquote", "br", "code", "div", "em", "figcaption", "figure",
        "h1", "h2", "h3", "i", "img", "li", "ol", "p", "pre", "s", "span", "strong",
        "u", "ul",
    }
)
_VOID_HTML_TAGS = frozenset({"br", "img"})
_DROP_CONTENT_TAGS = frozenset({"script", "style", "iframe", "object", "embed", "template", "svg", "math"})
# Their tags go, but the words inside them are the author's and stay.
_UNWRAP_TAGS = frozenset({"form", "noscript", "button", "select", "textarea", "label", "fieldset", "legend", "option"})
_SAFE_ATTRS = frozenset({"alt", "class", "height", "id", "loading", "rel", "src", "target", "title", "width"})


class _SafeHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._drop_depth = 0
        self._open_tags: list[str] = []

    def _attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        output: list[str] = []
        for key, value in attrs:
            name = (key or "").lower()
            if not value or name.startswith("on") or name == "style" or name.startswith("xmlns"):
                continue
            if re.fullmatch(r"data-card-[a-z0-9_-]{1,48}", name) or name == "data-media-url":
                if any(ord(ch) < 0x20 for ch in value) or len(value) > 400:
                    continue
                if name == "data-media-url" or name.endswith("-url"):
                    safe_data_url = sanitize_media_url(value)
                    if not safe_data_url:
                        continue
                    value = safe_data_url
                output.append(f' {name}="{html.escape(value, quote=True)}"')
                continue
            if name == "href" and tag == "a":
                safe = sanitize_media_url(value)
                if not safe:
                    continue
            elif name == "src" and tag == "img":
                safe = sanitize_media_url(value)
                if not safe:
                    continue
            elif name not in _SAFE_ATTRS:
                continue
            if name in {"id", "class"} and not re.fullmatch(r"[A-Za-z0-9_:. -]{1,120}", value):
                continue
            if name in {"width", "height"} and not re.fullmatch(r"\d{1,5}", value):
                continue
            if name == "target" and value not in {"_blank", "_self"}:
                continue
            output.append(f' {name}="{html.escape(value, quote=True)}"')
        if tag == "a" and any(part.startswith(' target="_blank"') for part in output) and not any(
            part.startswith(' rel="') for part in output
        ):
            output.append(' rel="noopener noreferrer"')
        return "".join(output)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._drop_depth:
            self._drop_depth += 1
            return
        if tag in _DROP_CONTENT_TAGS:
            self._drop_depth = 1
            return
        if tag in _UNWRAP_TAGS:
            return
        if tag in _ALLOWED_HTML_TAGS:
            attrs_str = self._attrs(tag, attrs)
            if tag == "a" and ' href="' not in attrs_str:
                # Omit <a> wrapper if href was unsafe/missing
                return
            if tag == "img" and ' src="' not in attrs_str:
                # Omit <img> tag if src was unsafe/missing
                return
            self.parts.append(f"<{tag}{attrs_str}>")
            if tag not in _VOID_HTML_TAGS:
                self._open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._drop_depth:
            self._drop_depth -= 1
            return
        if tag in _UNWRAP_TAGS:
            return
        if tag in _ALLOWED_HTML_TAGS and tag not in _VOID_HTML_TAGS:
            if tag in self._open_tags:
                self._open_tags.remove(tag)
                self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._drop_depth:
            self.parts.append(html.escape(data, quote=False))

    def close(self) -> None:
        super().close()
        while self._open_tags:
            t = self._open_tags.pop()
            self.parts.append(f"</{t}>")


def sanitize_rich_html(value: str, *, max_chars: int = 60000) -> str:
    """Strip executable markup while preserving a small editorial HTML set."""
    raw = str(value or "")[:max_chars]
    parser = _SafeHTMLParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return html.escape(re.sub(r"<[^>]*>", " ", raw), quote=False)[:max_chars]
    return "".join(parser.parts)[:max_chars]


# Alias kept intentionally small for feature handlers and future API modules.
sanitize_html = sanitize_rich_html


def sanitize_plain_text(value: Any, *, max_chars: int = 3000) -> str:
    """Sanitize user plain-text input: remove executable markup/tags, control characters, and normalize."""
    if value is None:
        return ""
    raw = str(value)
    if not raw:
        return ""
    # 1. Strip null bytes and non-printable control chars (preserving \n, \r, \t)
    clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw)
    # 2. Drop dangerous blocks and their contents (script, style, iframe, object, embed, svg, math, form)
    clean = re.sub(
        r"<\s*(script|style|iframe|object|embed|svg|math|form|template|noscript)[^>]*>[\s\S]*?(?:<\s*/\s*\1\s*>|$)",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    # 3. Strip real HTML tags. The name must be followed by `>`, or by attributes
    #    and then `>`, so ordinary prose like "a<b 且 c>d" keeps its brackets.
    clean = re.sub(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^<>]*)?/?>", "", clean)
    # 4. Strip a trailing unclosed tag such as `<img src=x` (attributes present).
    clean = re.sub(r"<\s*/?[a-zA-Z][a-zA-Z0-9]*\s[^<>]*$", "", clean)
    clean = clean.strip()
    return clean[:max_chars]


def sanitize_submission_body(body: Mapping[str, object]) -> dict[str, object]:
    out = dict(body)
    rich_fields = {
        "body", "bodyHtml", "body_html", "contentHtml", "content_html", "lockedBody",
        "lockedBodyHtml", "summary", "summaryHtml", "description", "descriptionHtml",
    }
    plain_fields = {"title", "name", "notes", "bio", "displayName", "text"}
    for key in rich_fields:
        value = out.get(key)
        if isinstance(value, str):
            out[key] = sanitize_rich_html(value)
    for key in plain_fields:
        value = out.get(key)
        if isinstance(value, str):
            out[key] = sanitize_plain_text(value)
    return out

