"""HTTP route handlers for device authorization and personal tokens."""
from __future__ import annotations

import re
from typing import Any

from . import device_auth as DA
from .services import ServiceError


def _client_ip(handler: Any) -> str:
    if hasattr(handler, "_client_ip"):
        return handler._client_ip()
    xff = handler.headers.get("X-Forwarded-For") or ""
    if xff:
        return xff.split(",")[0].strip()
    return handler.client_address[0] if handler.client_address else "127.0.0.1"


def handle_get(handler: Any, path: str, qs: dict[str, list[str]]) -> bool:
    if path == "/api/auth/me":
        user = handler._current_user(required=True)
        auth_kind = user.get("_auth_kind", "session")
        scopes = user.get("_token_scopes", ["*"]) if auth_kind == "token" else ["*"]
        handler._send_json({
            "ok": True,
            "username": user["username"],
            "displayName": user["display_name"],
            "authKind": auth_kind,
            "scopes": scopes,
        })
        return True

    if path == "/api/auth/device/lookup":
        code_vals = qs.get("code")
        code = code_vals[0].strip() if code_vals and code_vals[0] else ""
        if not code:
            raise ServiceError("缺少设备验证码", status=400, code="missing_code")
        user = handler._current_user(required=True)
        ip_addr = _client_ip(handler)
        result = DA.lookup_device_code(handler.db, user, ip_addr, code)
        handler._send_json(result)
        return True

    if path == "/api/auth/tokens":
        user = handler._current_user(required=True)
        result = DA.list_user_tokens(handler.db, user)
        handler._send_json(result)
        return True

    return False


def handle_post(handler: Any, path: str, body: dict[str, Any]) -> bool:
    if path == "/api/auth/device":
        ip_addr = _client_ip(handler)
        result = DA.create_device_code(handler.db, ip_addr, body)
        handler._send_json(result)
        return True

    if path == "/api/auth/device/approve":
        handler._enforce_write_origin()
        user = handler._current_user(required=True)
        code = str(body.get("code") or "").strip()
        if not code:
            raise ServiceError("缺少设备验证码", status=400, code="missing_code")
        ip_addr = _client_ip(handler)
        result = DA.approve_device_code(handler.db, user, code, ip_addr)
        handler._send_json(result)
        return True

    if path == "/api/auth/device/deny":
        handler._enforce_write_origin()
        user = handler._current_user(required=True)
        code = str(body.get("code") or "").strip()
        if not code:
            raise ServiceError("缺少设备验证码", status=400, code="missing_code")
        ip_addr = _client_ip(handler)
        result = DA.deny_device_code(handler.db, user, code, ip_addr)
        handler._send_json(result)
        return True

    if path == "/api/auth/device/token":
        # Anonymous token poll/exchange; does not require origin
        result = DA.exchange_device_token(handler.db, body)
        handler._send_json(result)
        return True

    m_revoke = re.fullmatch(r"^/api/auth/tokens/([^/]+)/revoke$", path)
    if m_revoke:
        handler._enforce_write_origin()
        user = handler._current_user(required=True)
        token_id = m_revoke.group(1)
        result = DA.revoke_user_token(handler.db, user, token_id)
        handler._send_json(result)
        return True

    return False
