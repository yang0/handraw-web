"""Navigation-safe error pages and bounded, privacy-conscious client events."""
from __future__ import annotations

import html
import logging
import os
import re
from urllib.parse import urlsplit, urlunsplit

from .services import ServiceError

logger = logging.getLogger(__name__)


def wants_error_page(headers) -> bool:
    if headers.get("Sec-Fetch-Mode", "").lower() == "navigate":
        return True
    accept = headers.get("Accept", "").lower()
    return "text/html" in accept and "application/json" not in accept


def canonical_local_page(handler, parsed) -> bool:
    """Avoid separate login/logout sessions on local browser entry points.

    APIs and OAuth callbacks are never forwarded with their credentials.
    Production subdomain routing is deliberately unaffected.
    """
    if parsed.path.startswith(("/api/", "/assets/", "/data/", "/uploads/", "/images/")):
        return False
    if not wants_error_page(handler.headers):
        return False
    # OAuth cookies must return to the same host even if an older launcher
    # supplied a different public URL for local previews.
    configured = (os.environ.get("HANDRAW_GOOGLE_CALLBACK_URL") or os.environ.get("HANDRAW_GITHUB_CALLBACK_URL") or
                  os.environ.get("HANDRAW_PUBLIC_URL") or os.environ.get("HANDRAW_BASE_URL") or "")
    try:
        target = urlsplit(configured)
        incoming = urlsplit("http://" + (handler.headers.get("Host") or ""))
        local_hosts = {"localhost", "127.0.0.1"}
        if (target.scheme != "http" or target.hostname not in local_hosts or
                incoming.hostname not in local_hosts or target.username or target.password or
                target.hostname == incoming.hostname or (target.port or 80) != (incoming.port or 80)):
            return False
    except ValueError:
        return False
    from .p2_oauth import _redirect
    logger.info("event=local_page_origin_redirect request_id=%s", getattr(handler, "_request_id", "unavailable"))
    _redirect(handler, urlunsplit((target.scheme, target.netloc, parsed.path, parsed.query, "")))
    return True


def render_error_page(status: int, message: str, request_id: str) -> bytes:
    title = "服务暂时遇到问题" if status >= 500 else "暂时无法完成操作"
    if status == 401:
        title = "请先登录后继续"
    elif status == 404:
        title = "这个页面暂时找不到"
    detail = "请稍后再试。你可以保留问题编号，方便我们定位原因。" if status >= 500 else str(message)[:500]
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · Handraw</title>
<style>body{{margin:0;background:#f8f5ed;color:#2b2925;font:16px/1.7 system-ui,sans-serif}}
main{{max-width:580px;margin:12vh auto;padding:36px;background:#fffdf8;border:1px solid #e4ddd0;border-radius:18px}}
.brand{{letter-spacing:.15em;color:#a63d24;font-size:13px}}h1{{font-family:Georgia,"Noto Serif SC",serif;font-size:30px;line-height:1.4}}
p{{color:#625d54}}nav{{display:flex;gap:12px;flex-wrap:wrap;margin-top:28px}}a{{padding:10px 18px;border-radius:8px;text-decoration:none;color:#a63d24;border:1px solid #d8c7b9}}
a:first-child{{background:#b74227;color:white;border-color:#b74227}}small{{display:block;margin-top:26px;color:#756c60}}code{{overflow-wrap:anywhere;user-select:all}}
@media(max-width:640px){{main{{margin:8vh 18px;padding:26px}}h1{{font-size:25px}}}}</style></head>
<body><main><div class="brand">HANDRAW · 手绘风</div><h1>{title}</h1>
<p role="alert">{html.escape(detail)}</p><nav><a href="/">返回首页</a><a href="/?view=auth">前往登录</a></nav>
<small>问题编号：<code>{html.escape(request_id)}</code></small></main></body></html>'''.encode("utf-8")


def record_client_error(handler, body: dict) -> None:
    """Only allow bounded metadata, never arbitrary error messages or stacks."""
    allowed = {"kind", "errorType", "channel", "script", "line", "column", "status", "relatedRequestId", "eventId"}
    if set(body) - allowed:
        raise ServiceError("错误报告格式无效", status=400, code="invalid_client_error")
    kind = body.get("kind")
    if not isinstance(kind, str) or kind not in {"runtime", "unhandledrejection", "resource", "api", "boot", "render"}:
        raise ServiceError("错误报告类型无效", status=400, code="invalid_client_error")
    error_type = body.get("errorType")
    if not isinstance(error_type, str) or error_type not in {"Error", "TypeError", "ReferenceError", "SyntaxError", "RangeError", "AbortError", "NetworkError", "ResourceError", "HTTPError"}:
        error_type = "UnknownError"
    raw_channel = body.get("channel")
    channel = raw_channel if isinstance(raw_channel, str) and raw_channel in {"main", "studio", "forum", "admin"} else "main"
    script = body.get("script")
    script = script if isinstance(script, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}\.js", script) else "unknown"
    def number(key, limit):
        value = body.get(key)
        return value if type(value) is int and 0 <= value <= limit else 0
    def identifier(key):
        value = body.get(key)
        return value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value) else "unavailable"
    logger.warning(
        "event=client_error kind=%s type=%s channel=%s script=%s line=%s column=%s status=%s "
        "request_id=%s related_request_id=%s client_event_id=%s",
        kind, error_type, channel, script, number("line", 1000000), number("column", 1000000),
        number("status", 599), handler._request_id, identifier("relatedRequestId"), identifier("eventId"),
    )
    handler._send_json({"ok": True, "requestId": handler._request_id}, status=202)
