"""GitHub OAuth authorization-code flow with one-time browser-bound state.

OAuth is feature-gated by environment configuration. Existing accounts are
*never* matched or linked by email alone. The GitHub numeric account ID is the
stable login identifier. No provider token is saved in Handraw storage.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .db import utc_now_iso
from .services import ServiceError, create_session_for_user, register_user
from .security import verify_password


def github_config() -> dict[str, str] | None:
    client = os.environ.get("HANDRAW_GITHUB_CLIENT_ID", "").strip()
    secret = os.environ.get("HANDRAW_GITHUB_CLIENT_SECRET", "").strip()
    callback = os.environ.get("HANDRAW_GITHUB_CALLBACK_URL", "").strip()
    if not client or not secret or not callback:
        return None
    parsed = urllib.parse.urlsplit(callback)
    if (parsed.scheme != "https" and
            not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1"))):
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path != "/api/auth/github/callback":
        return None
    return {"id": client, "secret": secret, "callback": callback}


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _state_cookie(nonce: str, secure: bool) -> str:
    suffix = "; Secure" if secure else ""
    return "handraw_oauth_nonce=" + nonce + "; Path=/api/auth/github; HttpOnly; SameSite=Lax; Max-Age=600" + suffix


def _clear_cookie(secure: bool) -> str:
    suffix = "; Secure" if secure else ""
    return "handraw_oauth_nonce=; Path=/api/auth/github; HttpOnly; SameSite=Lax; Max-Age=0" + suffix


def _signup_cookie(ticket: str, secure: bool) -> str:
    return ("handraw_oauth_signup=" + ticket +
            "; Path=/api/auth/github; HttpOnly; SameSite=Lax; Max-Age=600" +
            ("; Secure" if secure else ""))


def _read_signup_ticket(handler: Any) -> str:
    from http.cookies import SimpleCookie
    cookie = SimpleCookie()
    try:
        cookie.load(handler.headers.get("Cookie") or "")
        item = cookie.get("handraw_oauth_signup")
        return item.value if item else ""
    except Exception:
        return ""


def signup_status(handler: Any) -> dict:
    ticket = _read_signup_ticket(handler)
    if not ticket or len(ticket) > 256:
        raise ServiceError("注册身份已过期，请重新使用 GitHub 授权", status=401, code="oauth_signup_expired")
    row = handler.db.get_conn().execute(
        "SELECT * FROM oauth_signup_tickets WHERE ticket_hash=? AND expires_at>?",
        (_digest(ticket), int(time.time()))
    ).fetchone()
    if not row:
        raise ServiceError("注册身份已过期，请重新使用 GitHub 授权", status=401, code="oauth_signup_expired")
    return {"ok": True, "provider": "GitHub", "providerLogin": row["provider_login"],
            "suggestedUsername": _oauth_username(handler.db.get_conn(), row["provider_login"], row["provider_user_id"]),
            "verifiedEmail": row["verified_email"]}


def finish_signup(handler: Any, body: dict) -> None:
    ticket = _read_signup_ticket(handler)
    if not ticket or len(ticket) > 256:
        raise ServiceError("注册身份已过期，请重新 GitHub 授权", status=401, code="oauth_signup_expired")
    username = str(body.get("username") or "").strip()
    display_name = str(body.get("displayName") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,32}", username):
        raise ServiceError("用户名需为 2～32 位字母、数字、下划线或连字符")
    if len(display_name) > 40:
        raise ServiceError("昵称不能超过 40 字符")
    with handler.db._write_lock:
        row = handler.db.get_conn().execute(
            "SELECT * FROM oauth_signup_tickets WHERE ticket_hash=? AND expires_at>?",
            (_digest(ticket), int(time.time()))
        ).fetchone()
        if not row:
            raise ServiceError("注册身份已过期，请重新授权", status=401, code="oauth_signup_expired")
        existing = handler.db.get_conn().execute(
            "SELECT 1 FROM oauth_identities WHERE provider=? AND provider_user_id=?",
            (row["provider"], row["provider_user_id"])
        ).fetchone()
        if existing:
            raise ServiceError("此 GitHub 账号已经注册，请直接登录", status=409, code="oauth_account_exists")
        created, session = register_user(
            handler.db, username, secrets.token_urlsafe(48), row["verified_email"],
            display_name=display_name or username,
            user_agent=handler.headers.get("User-Agent") or "",
            ip_addr=handler.client_address[0] if handler.client_address else "",
        )
        with handler.db.transaction() as tx:
            tx.execute(
                """INSERT INTO oauth_identities(provider,provider_user_id,user_id,provider_login,linked_at)
                   VALUES(?,?,?,?,?)""",
                (row["provider"], row["provider_user_id"], created["id"], row["provider_login"], utc_now_iso())
            )
            tx.execute(
                """INSERT INTO verified_emails(user_id,email,verified_at) VALUES(?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET email=excluded.email,verified_at=excluded.verified_at""",
                (created["id"], row["verified_email"], utc_now_iso())
            )
            tx.execute(
                "INSERT INTO auth_funnel_events(event_name,created_at,user_id,source) VALUES(?,?,?,'github')",
                ("register_success", int(time.time()), created["id"])
            )
            tx.execute("DELETE FROM oauth_signup_tickets WHERE ticket_hash=?", (_digest(ticket),))
    from .p2_growth import record_login
    record_login(handler.db, created, handler.headers.get("User-Agent") or "")
    handler._send_json({"ok": True, "message": "GitHub 注册完成，昵称已固定，不可再修改"},
                       set_cookie=handler._cookie_for_token(session))


def _read_nonce(handler: Any) -> str:
    from http.cookies import SimpleCookie
    cookie = SimpleCookie()
    try:
        cookie.load(handler.headers.get("Cookie") or "")
        item = cookie.get("handraw_oauth_nonce")
        return item.value if item else ""
    except Exception:
        return ""


def _redirect(handler: Any, dest: str, *cookies: str) -> None:
    handler.send_response(303)
    handler.send_header("Location", dest)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Referrer-Policy", "no-referrer")
    for value in cookies:
        if value:
            handler.send_header("Set-Cookie", value)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def start_github(handler: Any, mode: str = "login") -> None:
    config = github_config()
    if not config:
        raise ServiceError("尚未配置 GitHub 登录", status=503, code="social_not_configured")
    if mode not in {"login", "link"}:
        raise ServiceError("无效的授权用途")
    user = handler._current_user(required=(mode == "link"))
    if mode == "login" and user:
        raise ServiceError("当前已登录，请使用账号设置中的绑定入口", status=409)
    state = secrets.token_urlsafe(36)
    nonce = secrets.token_urlsafe(36)
    now = int(time.time())
    with handler.db.transaction() as tx:
        tx.execute("DELETE FROM oauth_flows WHERE expires_at < ?", (now,))
        tx.execute(
            """INSERT INTO oauth_flows
               (state_hash,browser_nonce_hash,provider,purpose,user_id,expires_at,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (_digest(state), _digest(nonce), "github", mode, int(user["id"]) if user else None, now+600, now),
        )
    url = "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": config["id"],
        "redirect_uri": config["callback"],
        "scope": "read:user user:email",
        "state": state,
    })
    is_https = config["callback"].startswith("https://")
    _redirect(handler, url, _state_cookie(nonce, is_https))


def _github_json(url: str, token: str = "", *, post: dict | None = None) -> Any:
    headers = {"Accept": "application/json" if post is not None else "application/vnd.github+json",
               "User-Agent": "Handraw-Web/2 OAuth"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = urllib.parse.urlencode(post).encode("utf-8") if post else None
    if body:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            if response.status != 200 or int(response.headers.get("Content-Length") or 0) > 1048576:
                raise ValueError("provider response invalid")
            return json.loads(response.read(1048576).decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ServiceError("第三方认证暂不可用，请稍后再试", status=502, code="oauth_provider_unavailable") from exc


def fetch_github_identity(config: dict[str, str], code: str) -> dict:
    result = _github_json("https://github.com/login/oauth/access_token", post={
        "client_id": config["id"], "client_secret": config["secret"],
        "code": code, "redirect_uri": config["callback"],
    })
    token = result.get("access_token") if isinstance(result, dict) else None
    if not isinstance(token, str) or len(token) < 12:
        raise ServiceError("GitHub 授权未成功，请重新尝试", status=401, code="oauth_denied")
    profile = _github_json("https://api.github.com/user", token)
    if not isinstance(profile, dict) or not isinstance(profile.get("id"), int) or profile["id"] < 1:
        raise ServiceError("GitHub 身份信息无效", status=502, code="oauth_profile_invalid")
    emails = _github_json("https://api.github.com/user/emails", token)
    verified = [
        x["email"].strip().lower() for x in emails
        if isinstance(x, dict) and x.get("primary") and x.get("verified")
        and isinstance(x.get("email"), str) and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", x["email"])
    ] if isinstance(emails, list) else []
    return {"subject": str(profile["id"]), "login": str(profile.get("login") or "")[:80],
            "email": verified[0] if verified else ""}


def _oauth_username(conn: Any, login: str, subject: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]", "", login)[:25] or "github"
    # A stable suffix avoids conflict with existing local usernames.
    stem = (slug + "-gh" + subject)[0:32]
    name = stem
    number = 2
    while conn.execute("SELECT 1 FROM users WHERE username=?", (name,)).fetchone():
        name = (stem[:29] + str(number))[:32]
        number += 1
        if number > 100:
            raise ServiceError("暂时无法创建用户名，请重试", status=503)
    return name


def complete_github(handler: Any, qs: dict[str, list[str]]) -> None:
    config = github_config()
    if not config:
        raise ServiceError("GitHub 登录尚未配置", status=503)
    state = (qs.get("state") or [""])[0]
    code = (qs.get("code") or [""])[0]
    nonce = _read_nonce(handler)
    secure = config["callback"].startswith("https://")
    if not state or len(state) > 256 or not nonce or not code or len(code) > 2048:
        raise ServiceError("授权状态无效，请重新发起 GitHub 登录", status=400, code="oauth_state_invalid")
    now = int(time.time())
    # Consumed before contacting the provider to prohibit callback replay even
    # when the upstream network call fails.
    with handler.db.transaction() as tx:
        row = tx.execute(
            "SELECT * FROM oauth_flows WHERE state_hash=?", (_digest(state),)
        ).fetchone()
        if (not row or row["expires_at"] <= now or row["provider"] != "github"
                or not secrets.compare_digest(row["browser_nonce_hash"], _digest(nonce))):
            raise ServiceError("授权已过期或浏览器状态不匹配，请重新尝试", status=400, code="oauth_state_invalid")
        tx.execute("DELETE FROM oauth_flows WHERE state_hash=?", (_digest(state),))
    identity = fetch_github_identity(config, code)
    subject = identity["subject"]
    if row["purpose"] == "link":
        user = handler._current_user(required=True)
        if int(user["id"]) != int(row["user_id"]):
            raise ServiceError("绑定会话已变化，请重新发起操作", status=403, code="oauth_session_changed")
        with handler.db.transaction() as tx:
            existing = tx.execute(
                "SELECT user_id FROM oauth_identities WHERE provider='github' AND provider_user_id=?",
                (subject,),
            ).fetchone()
            if existing and int(existing["user_id"]) != int(user["id"]):
                raise ServiceError("该 GitHub 已绑定其他账号", status=409, code="oauth_already_linked")
            other = tx.execute(
                "SELECT provider_user_id FROM oauth_identities WHERE provider='github' AND user_id=?",
                (user["id"],),
            ).fetchone()
            if other and other["provider_user_id"] != subject:
                raise ServiceError("该账号已绑定其他 GitHub 身份，请先解除旧绑定", status=409)
            tx.execute(
                """INSERT OR IGNORE INTO oauth_identities
                   (provider,provider_user_id,user_id,provider_login,linked_at)
                   VALUES('github',?,?,?,?)""",
                (subject, user["id"], identity["login"], utc_now_iso()),
            )
        _redirect(handler, "/?view=account&section=security&social=linked", _clear_cookie(secure))
        return

    with handler.db.transaction() as tx:
        linked = tx.execute(
            """SELECT u.* FROM oauth_identities o JOIN users u ON u.id=o.user_id
               WHERE o.provider='github' AND o.provider_user_id=?""", (subject,)
        ).fetchone()
        if linked and linked["status"] != "active":
            raise ServiceError("关联账号不可登录，请联系管理员", status=403, code="oauth_account_inactive")
        if not linked:
            if not identity["email"]:
                raise ServiceError("请先在 GitHub 验证主要邮箱后再注册", status=409, code="oauth_verified_email_required")
            conflict = tx.execute(
                "SELECT 1 FROM users WHERE lower(email)=?", (identity["email"],)
            ).fetchone()
            if conflict:
                raise ServiceError("当前邮箱已有 Handraw 账号，请先用密码登录后绑定 GitHub", status=409, code="oauth_link_required")
    if not linked:
        # New social users must choose their immutable nickname explicitly.
        # Store only a short-lived server-side identity claim, never an OAuth token.
        ticket = secrets.token_urlsafe(36)
        with handler.db.transaction() as tx:
            tx.execute("DELETE FROM oauth_signup_tickets WHERE expires_at<?", (now,))
            tx.execute(
                """INSERT INTO oauth_signup_tickets
                   (ticket_hash,provider,provider_user_id,provider_login,verified_email,created_at,expires_at)
                   VALUES(?,'github',?,?,?,?,?)""",
                (_digest(ticket), subject, identity["login"], identity["email"], now, now+600)
            )
        _redirect(handler, "/?view=oauth-register", _signup_cookie(ticket, secure), _clear_cookie(secure))
        return
    with handler.db.transaction() as tx:
        session_token = create_session_for_user(
            tx, int(linked["id"]),
            handler.headers.get("User-Agent") or "",
            handler.client_address[0] if handler.client_address else "",
        )
    from .p2_growth import record_login
    new_device = record_login(handler.db, dict(linked), handler.headers.get("User-Agent") or "")
    if new_device:
        from .features import try_send_security_alert
        try_send_security_alert(handler.db, dict(linked), "新设备或浏览器登录",
                                "我们发现一个新的浏览器环境使用 GitHub 登录你的账号。如果不是本人，请检查账号安全。")
    cookie = handler._cookie_for_token(session_token)
    _redirect(handler, "/?view=account&section=security&social=success", cookie, _clear_cookie(secure))


def unlink_github(db: Any, user: dict, current_password: str) -> dict:
    conn = db.get_conn()
    row = conn.execute(
        "SELECT password_hash,password_algo,discourse_salt FROM users WHERE id=? AND status='active'",
        (user["id"],),
    ).fetchone()
    if not row or not verify_password(
        current_password, row["password_hash"],
        password_algo=row["password_algo"], discourse_salt=row["discourse_salt"]
    ):
        raise ServiceError("需要正确的当前密码才能解除第三方绑定", status=403, code="incorrect_password")
    with db.transaction() as tx:
        tx.execute("DELETE FROM oauth_identities WHERE provider='github' AND user_id=?", (user["id"],))
    return {"ok": True, "message": "GitHub 绑定已解除"}


def oauth_status(db: Any, user: dict | None) -> dict:
    linked = None
    if user:
        linked = db.get_conn().execute(
            "SELECT provider_login FROM oauth_identities WHERE provider='github' AND user_id=?",
            (int(user["id"]),)
        ).fetchone()
    return {"ok": True, "githubEnabled": bool(github_config()),
            "githubLinked": bool(linked),
            "githubLogin": linked["provider_login"] if linked else ""}
