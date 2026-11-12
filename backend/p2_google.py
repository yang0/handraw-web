"""Google OAuth 2.0 / OpenID Connect login using authorization code + PKCE.

Server fetches identity from Google's UserInfo endpoint using the access token
received directly from Google's token endpoint, checks verified email, and uses
the stable Google subject. No Google credentials/tokens are persisted.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from typing import Any

from .db import utc_now_iso
from .security import verify_password
from .services import ServiceError, create_session_for_user
from .p2_oauth import (
    _canonicalize_oauth_start, _digest, _redirect, _signup_cookie, _oauth_username,
    _validate_callback_fields, _validate_flow,
)


def google_config() -> dict[str, str] | None:
    client = os.environ.get("HANDRAW_GOOGLE_CLIENT_ID", "").strip()
    secret = os.environ.get("HANDRAW_GOOGLE_CLIENT_SECRET", "").strip()
    callback = os.environ.get("HANDRAW_GOOGLE_CALLBACK_URL", "").strip()
    if not client or not secret or not callback:
        return None
    parsed = urllib.parse.urlsplit(callback)
    if (parsed.scheme != "https" and
        not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})):
        return None
    if (parsed.username or parsed.password or parsed.query or parsed.fragment
        or parsed.path != "/api/auth/google/callback"):
        return None
    return {"id": client, "secret": secret, "callback": callback}


def _cookie(nonce: str, secure: bool) -> str:
    return ("handraw_google_nonce=" + nonce +
            "; Path=/api/auth/google; HttpOnly; SameSite=Lax; Max-Age=600" +
            ("; Secure" if secure else ""))


def clear_cookie(secure: bool) -> str:
    return ("handraw_google_nonce=; Path=/api/auth/google; HttpOnly; SameSite=Lax; Max-Age=0" +
            ("; Secure" if secure else ""))


def _nonce(handler: Any) -> str:
    cookie = SimpleCookie()
    try:
        cookie.load(handler.headers.get("Cookie") or "")
        return cookie["handraw_google_nonce"].value if "handraw_google_nonce" in cookie else ""
    except Exception:
        return ""


def start_google(handler: Any, mode: str = "login") -> None:
    cfg = google_config()
    if not cfg:
        raise ServiceError("Google 登录尚未配置", status=503, code="social_not_configured")
    if mode not in {"login", "link"}:
        raise ServiceError("授权用途无效")
    if _canonicalize_oauth_start(handler, cfg["callback"], "google", mode):
        return
    user = handler._current_user(required=(mode == "link"))
    if mode == "login" and user:
        _redirect(handler, "/")
        return
    state = secrets.token_urlsafe(36)
    nonce = secrets.token_urlsafe(36)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    now = int(time.time())
    with handler.db.transaction() as tx:
        tx.execute("DELETE FROM oauth_flows WHERE expires_at<?", (now,))
        tx.execute(
            """INSERT INTO oauth_flows
               (state_hash,browser_nonce_hash,provider,purpose,user_id,expires_at,created_at,code_verifier)
               VALUES(?,?,?,?,?,?,?,?)""",
            (_digest(state), _digest(nonce), "google", mode,
             int(user["id"]) if user else None, now+600, now, verifier)
        )
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cfg["id"], "redirect_uri": cfg["callback"],
        "response_type": "code", "scope": "openid email profile",
        "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "access_type": "online",
    })
    _redirect(handler, url, _cookie(nonce, cfg["callback"].startswith("https://")))


def fetch_google_identity(cfg: dict, code: str, verifier: str) -> dict:
    post = urllib.parse.urlencode({
        "client_id": cfg["id"], "client_secret": cfg["secret"],
        "code": code, "code_verifier": verifier,
        "redirect_uri": cfg["callback"], "grant_type": "authorization_code",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", post,
        headers={"Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "Handraw-Web/2"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status != 200:
                raise ValueError("token exchange failed")
            tokens = json.loads(response.read(65536))
        token = tokens.get("access_token") if isinstance(tokens, dict) else None
        if not isinstance(token, str) or len(token) < 12:
            raise ValueError("missing access token")
        userinfo_request = urllib.request.Request(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/json", "User-Agent": "Handraw-Web/2"},
        )
        with urllib.request.urlopen(userinfo_request, timeout=8) as response:
            if response.status != 200:
                raise ValueError("userinfo response failed")
            identity = json.loads(response.read(65536))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ServiceError("Google 授权服务暂不可用，请稍后重试",
                           status=502, code="oauth_provider_unavailable") from exc
    if not isinstance(identity, dict):
        raise ServiceError("Google 身份信息无效", status=502, code="oauth_profile_invalid")
    subject = str(identity.get("sub") or "")
    email = str(identity.get("email") or "").strip().lower()
    if not re.fullmatch(r"[0-9A-Za-z_-]{6,255}", subject):
        raise ServiceError("Google 身份信息无效", status=502, code="oauth_profile_invalid")
    if identity.get("email_verified") is not True or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ServiceError("请先在 Google 验证登录邮箱", status=409,
                           code="oauth_verified_email_required")
    return {"subject": subject, "email": email,
            "login": str(identity.get("name") or email.split("@")[0])[:80]}


def complete_google(handler: Any, qs: dict[str, list[str]]) -> None:
    cfg = google_config()
    if not cfg:
        raise ServiceError("Google 登录尚未配置", status=503, code="social_not_configured")
    state = (qs.get("state") or [""])[0]
    code = (qs.get("code") or [""])[0]
    nonce = _nonce(handler)
    secure = cfg["callback"].startswith("https://")
    _validate_callback_fields(handler, state, code, nonce)
    now = int(time.time())
    with handler.db.transaction() as tx:
        row = tx.execute("SELECT * FROM oauth_flows WHERE state_hash=?", (_digest(state),)).fetchone()
        _validate_flow(handler, row, "google", now, nonce, pkce=True)
        tx.execute("DELETE FROM oauth_flows WHERE state_hash=?", (_digest(state),))
    identity = fetch_google_identity(cfg, code, row["code_verifier"])
    subject = identity["subject"]
    if row["purpose"] == "link":
        user = handler._current_user(required=True)
        if int(user["id"]) != int(row["user_id"]):
            raise ServiceError("账号绑定会话已变化，请重新尝试", status=403, code="oauth_session_changed")
        with handler.db.transaction() as tx:
            taken = tx.execute(
                "SELECT user_id FROM oauth_identities WHERE provider='google' AND provider_user_id=?",
                (subject,)
            ).fetchone()
            if taken and int(taken["user_id"]) != int(user["id"]):
                raise ServiceError("该 Google 身份已绑定其他账号", status=409,
                                   code="oauth_already_linked")
            current = tx.execute(
                "SELECT provider_user_id FROM oauth_identities WHERE provider='google' AND user_id=?",
                (user["id"],)
            ).fetchone()
            if current and current["provider_user_id"] != subject:
                raise ServiceError("此账号已有其他 Google 身份绑定", status=409)
            tx.execute(
                """INSERT INTO oauth_identities
                   (provider,provider_user_id,user_id,provider_login,linked_at)
                   VALUES('google',?,?,?,?) ON CONFLICT DO NOTHING""",
                (subject, user["id"], identity["email"], utc_now_iso())
            )
            tx.execute(
                """INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
                   VALUES(?,'security','Google 登录已绑定','','',?)""",
                (user["id"], utc_now_iso())
            )
        from .features import try_send_security_alert
        try_send_security_alert(handler.db, user, "Google 已绑定",
                                "你的账号刚刚绑定了 Google 登录。如非本人，请立即检查账号安全。")
        _redirect(handler, "/?view=account&section=security&social=linked", clear_cookie(secure))
        return

    conn = handler.db.get_conn()
    linked = conn.execute(
        """SELECT u.* FROM oauth_identities o JOIN users u ON u.id=o.user_id
           WHERE o.provider='google' AND o.provider_user_id=?""", (subject,)
    ).fetchone()
    if linked and linked["status"] != "active":
        raise ServiceError("关联账号当前无法登录，请联系管理员", status=403,
                           code="oauth_account_inactive")
    if not linked:
        if conn.execute("SELECT 1 FROM users WHERE lower(email)=?", (identity["email"],)).fetchone():
            raise ServiceError("此邮箱已有 Handraw 账号，请先用密码登录再绑定 Google",
                               status=409, code="oauth_link_required")
        ticket = secrets.token_urlsafe(36)
        with handler.db.transaction() as tx:
            tx.execute("DELETE FROM oauth_signup_tickets WHERE expires_at<?", (now,))
            tx.execute(
                """INSERT INTO oauth_signup_tickets
                   (ticket_hash,provider,provider_user_id,provider_login,verified_email,created_at,expires_at)
                   VALUES(?,'google',?,?,?,?,?)""",
                (_digest(ticket), subject, identity["login"], identity["email"], now, now+600)
            )
        _redirect(handler, "/?view=oauth-register", _signup_cookie(ticket, secure), clear_cookie(secure))
        return

    with handler.db.transaction() as tx:
        session = create_session_for_user(
            tx, int(linked["id"]), handler.headers.get("User-Agent") or "",
            handler.client_address[0] if handler.client_address else "",
        )
        tx.execute(
            "INSERT INTO auth_funnel_events(event_name,created_at,user_id,source) VALUES(?,?,?,'google')",
            ("login_success", now, linked["id"])
        )
    from .p2_growth import record_login
    new_browser = record_login(handler.db, dict(linked), handler.headers.get("User-Agent") or "")
    if new_browser:
        from .features import try_send_security_alert
        try_send_security_alert(handler.db, dict(linked), "新浏览器 Google 登录",
                                "有新的浏览器环境通过 Google 登录你的账号。如非本人，请立即检查账号安全。")
    _redirect(handler, "/",
              handler._cookie_for_token(session), clear_cookie(secure))


def unlink_google(db: Any, user: dict, password: str) -> dict:
    row = db.get_conn().execute(
        "SELECT password_hash,password_algo,discourse_salt FROM users WHERE id=? AND status='active'",
        (user["id"],)
    ).fetchone()
    if not row or not verify_password(password, row["password_hash"],
                                      password_algo=row["password_algo"],
                                      discourse_salt=row["discourse_salt"]):
        raise ServiceError("解绑 Google 需要当前账号密码", status=403,
                           code="incorrect_password")
    with db.transaction() as tx:
        deleted = tx.execute(
            "DELETE FROM oauth_identities WHERE provider='google' AND user_id=?", (user["id"],)
        )
        if deleted.rowcount:
            tx.execute(
                """INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
                   VALUES(?,'security','Google 登录已解绑','','',?)""",
                (user["id"], utc_now_iso())
            )
    if deleted.rowcount:
        from .features import try_send_security_alert
        try_send_security_alert(db, user, "Google 已解绑",
                                "你的账号刚刚解除 Google 登录。如非本人，请立即检查账号安全。")
    return {"ok": True, "message": "Google 绑定已解除"}


def google_status(db: Any, user: dict | None) -> dict:
    linked = None
    if user:
        linked = db.get_conn().execute(
            "SELECT provider_login FROM oauth_identities WHERE provider='google' AND user_id=?",
            (int(user["id"]),)
        ).fetchone()
    return {"googleEnabled": bool(google_config()),
            "googleLinked": bool(linked),
            "googleLogin": linked["provider_login"] if linked else ""}
