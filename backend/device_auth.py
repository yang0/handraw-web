"""Device code authorization and personal access token management.

Implements RFC 8628-style device authorization for headless/terminal clients
(e.g. Skill addon) without requiring passwords or storing long-lived credentials.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import Database, utc_now_iso
from .services import ServiceError

USER_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # 32 chars: no 0, O, 1, I, L
ALLOWED_SCOPES = {"publish", "library"}
MAX_GLOBAL_PENDING_DEVICE_CODES = 500
DEVICE_CODE_TTL_SECONDS = 600  # 10 minutes
DEFAULT_POLL_INTERVAL_SECONDS = 5

_rate_limit_lock = threading.Lock()
_ip_create_log: dict[str, list[float]] = {}


def _check_rate_limit(
    log_map: dict[str, list[float]],
    key: str,
    limit: int,
    window_seconds: float = 3600.0,
) -> bool:
    now = time.time()
    with _rate_limit_lock:
        timestamps = log_map.setdefault(key, [])
        cutoff = now - window_seconds
        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)
        if len(timestamps) >= limit:
            return False
        timestamps.append(now)
        # Periodically purge empty keys to prevent unbounded memory growth
        if len(log_map) > 4096:
            keys_to_del = [k for k, v in log_map.items() if not v or v[-1] < cutoff]
            for k in keys_to_del:
                log_map.pop(k, None)
        return True


_guess_rate_lock = threading.Lock()
_user_guess_fail_log: dict[str, list[float]] = {}
_ip_guess_fail_log: dict[str, list[float]] = {}
_last_global_cleanup: float = 0.0
MAX_GUESS_LIMITER_KEYS = 10_000


def _cleanup_guess_limiter_locked(now: float, force: bool = False) -> None:
    global _last_global_cleanup
    if force or (now - _last_global_cleanup > 60.0):
        cutoff = now - 3600.0
        for log_map in (_user_guess_fail_log, _ip_guess_fail_log):
            keys_to_del = []
            for k, timestamps in log_map.items():
                while timestamps and timestamps[0] < cutoff:
                    timestamps.pop(0)
                if not timestamps:
                    keys_to_del.append(k)
            for k in keys_to_del:
                log_map.pop(k, None)
        _last_global_cleanup = now


def _reserve_guess_slot(user_id: Any, ip_addr: str) -> dict[str, Any]:
    now = time.time()
    cutoff = now - 3600.0
    u_key = str(user_id) if user_id is not None else None
    clean_ip = str(ip_addr or "").strip()

    with _guess_rate_lock:
        # Periodic cleanup every 60s
        _cleanup_guess_limiter_locked(now)

        total_keys = len(_user_guess_fail_log) + len(_ip_guess_fail_log)
        if total_keys >= MAX_GUESS_LIMITER_KEYS:
            _cleanup_guess_limiter_locked(now, force=True)
            total_keys = len(_user_guess_fail_log) + len(_ip_guess_fail_log)
            if total_keys >= MAX_GUESS_LIMITER_KEYS:
                is_new_user = (u_key is not None and u_key not in _user_guess_fail_log)
                is_new_ip = (clean_ip and clean_ip not in _ip_guess_fail_log)
                if is_new_user or is_new_ip:
                    logging.warning("device_auth guess rate limit table capacity reached (%d keys)", MAX_GUESS_LIMITER_KEYS)
                    raise ServiceError("验证码尝试次数过多，请稍后再试", status=429, code="rate_limited")

        # Check user budget
        if u_key is not None:
            u_times = _user_guess_fail_log.get(u_key)
            if u_times:
                while u_times and u_times[0] < cutoff:
                    u_times.pop(0)
                if len(u_times) >= 20:
                    raise ServiceError("验证码尝试次数过多，请稍后再试", status=429, code="rate_limited")

        # Check IP budget
        if clean_ip:
            ip_times = _ip_guess_fail_log.get(clean_ip)
            if ip_times:
                while ip_times and ip_times[0] < cutoff:
                    ip_times.pop(0)
                if len(ip_times) >= 20:
                    raise ServiceError("验证码尝试次数过多，请稍后再试", status=429, code="rate_limited")

        # Atomically reserve pending timestamp
        if u_key is not None:
            _user_guess_fail_log.setdefault(u_key, []).append(now)
        if clean_ip:
            _ip_guess_fail_log.setdefault(clean_ip, []).append(now)

        return {
            "user_key": u_key,
            "ip_addr": clean_ip,
            "timestamp": now,
            "released": False,
        }


def _release_guess_slot(ticket: dict[str, Any] | None) -> None:
    if not ticket or ticket.get("released"):
        return
    ticket["released"] = True
    u_key = ticket.get("user_key")
    clean_ip = ticket.get("ip_addr")
    ts = ticket.get("timestamp")

    with _guess_rate_lock:
        if u_key is not None and u_key in _user_guess_fail_log:
            try:
                _user_guess_fail_log[u_key].remove(ts)
            except ValueError:
                pass
            if not _user_guess_fail_log[u_key]:
                _user_guess_fail_log.pop(u_key, None)

        if clean_ip and clean_ip in _ip_guess_fail_log:
            try:
                _ip_guess_fail_log[clean_ip].remove(ts)
            except ValueError:
                pass
            if not _ip_guess_fail_log[clean_ip]:
                _ip_guess_fail_log.pop(clean_ip, None)


def _check_guess_rate_limit(user_id: Any, ip_addr: str) -> None:
    now = time.time()
    cutoff = now - 3600.0
    u_key = str(user_id) if user_id is not None else None
    clean_ip = str(ip_addr or "").strip()
    with _guess_rate_lock:
        if u_key is not None:
            u_times = _user_guess_fail_log.get(u_key)
            if u_times:
                valid = [t for t in u_times if t >= cutoff]
                if len(valid) >= 20:
                    raise ServiceError("验证码尝试次数过多，请稍后再试", status=429, code="rate_limited")

        if clean_ip:
            ip_times = _ip_guess_fail_log.get(clean_ip)
            if ip_times:
                valid = [t for t in ip_times if t >= cutoff]
                if len(valid) >= 20:
                    raise ServiceError("验证码尝试次数过多，请稍后再试", status=429, code="rate_limited")


def _record_guess_failure(user_id: Any, ip_addr: str) -> None:
    now = time.time()
    u_key = str(user_id) if user_id is not None else None
    clean_ip = str(ip_addr or "").strip()
    with _guess_rate_lock:
        if u_key is not None:
            _user_guess_fail_log.setdefault(u_key, []).append(now)
        if clean_ip:
            _ip_guess_fail_log.setdefault(clean_ip, []).append(now)


def generate_user_code() -> str:
    raw = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_user_code(code: str) -> str:
    clean = (code or "").strip().upper().replace(" ", "").replace("-", "")
    if len(clean) == 8:
        return f"{clean[:4]}-{clean[4:]}"
    return (code or "").strip().upper()


def sanitize_client_name(name: str) -> str:
    raw = str(name or "").strip()
    clean = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", raw)
    return clean[:60]


def create_device_code(
    db: Database,
    ip_addr: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    # 1. IP Rate Limiting (10 requests / hour)
    if not _check_rate_limit(_ip_create_log, ip_addr or "unknown", limit=10, window_seconds=3600.0):
        raise ServiceError("请求过于频繁，请稍后再试", status=429, code="rate_limited")

    # 2. Scope Validation
    scopes_input = payload.get("scopes")
    if scopes_input is None:
        scopes = ["publish", "library"]
    elif isinstance(scopes_input, list):
        for s in scopes_input:
            if not isinstance(s, str) or s not in ALLOWED_SCOPES:
                raise ServiceError(f"未知权限范围：{s}", status=400, code="invalid_scope")
        scopes = sorted(set(scopes_input))
        if not scopes:
            scopes = ["publish", "library"]
    else:
        raise ServiceError("scopes 必须为权限数组", status=400, code="invalid_scope")

    client_name = sanitize_client_name(payload.get("clientName", ""))

    raw_device_code = secrets.token_urlsafe(32)
    device_code_hash = hashlib.sha256(raw_device_code.encode("utf-8")).hexdigest()

    # 3. Pending count check and insertion within the same transaction (atomic)
    with db.transaction() as tx:
        # COUNT + INSERT alone is not atomic under PostgreSQL READ COMMITTED.
        # Serialize admissions across all workers in this database.
        tx.execute("SELECT pg_advisory_xact_lock(255, 0)")
        now_iso = utc_now_iso()
        pending_count = tx.execute(
            "SELECT COUNT(*) FROM device_codes WHERE status = 'pending' AND expires_at > ?",
            (now_iso,),
        ).fetchone()[0]
        if pending_count >= MAX_GLOBAL_PENDING_DEVICE_CODES:
            raise ServiceError("服务繁忙，待处理设备码过多", status=503, code="service_busy")

        user_code = ""
        for _ in range(10):
            candidate = generate_user_code()
            exists = tx.execute("SELECT 1 FROM device_codes WHERE user_code = ?", (candidate,)).fetchone()
            if not exists:
                user_code = candidate
                break
        if not user_code:
            raise ServiceError("生成验证码失败，请重试", status=500, code="generation_failed")

        exp_dt = datetime.now(timezone.utc) + timedelta(seconds=DEVICE_CODE_TTL_SECONDS)
        expires_at = exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        tx.execute(
            """
            INSERT INTO device_codes (
                device_code_hash, user_code, client_name, scopes,
                user_id, status, created_at, expires_at, approved_at, last_polled_at, interval
            ) VALUES (?, ?, ?, ?, NULL, 'pending', ?, ?, '', '', ?)
            """,
            (device_code_hash, user_code, client_name, json.dumps(scopes), now_iso, expires_at, DEFAULT_POLL_INTERVAL_SECONDS),
        )

    verification_url = f"/?view=device&code={user_code}"
    return {
        "ok": True,
        "deviceCode": raw_device_code,
        "userCode": user_code,
        "verificationUrl": verification_url,
        "expiresIn": DEVICE_CODE_TTL_SECONDS,
        "interval": DEFAULT_POLL_INTERVAL_SECONDS,
    }


def lookup_device_code(
    db: Database,
    user: dict[str, Any] | None,
    ip_addr: str,
    user_code: str,
) -> dict[str, Any]:
    if not user or user.get("_auth_kind") != "session":
        raise ServiceError("请先登录账号后再查看设备码", status=401, code="login_required")

    user_id = user.get("id")
    ticket = _reserve_guess_slot(user_id, ip_addr)

    norm_code = normalize_user_code(user_code)
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM device_codes WHERE user_code = ?", (norm_code,)).fetchone()
    now_iso = utc_now_iso()
    if not row or row["expires_at"] <= now_iso:
        # Failure: retain reservation slot as failed guess
        raise ServiceError("设备码不存在或已过期", status=404, code="not_found")

    # Success: release reservation slot (do not count towards failures)
    _release_guess_slot(ticket)

    try:
        scopes = json.loads(row["scopes"])
    except Exception:
        scopes = [row["scopes"]]

    return {
        "ok": True,
        "clientName": row["client_name"],
        "scopes": scopes,
        "expiresAt": row["expires_at"],
        "status": row["status"],
    }


def approve_device_code(
    db: Database,
    user: dict[str, Any] | None,
    user_code: str,
    ip_addr: str = "",
) -> dict[str, Any]:
    if not user or user.get("_auth_kind") != "session":
        raise ServiceError("请先登录账号后再批准设备", status=401, code="login_required")

    user_id = user.get("id")
    ticket = _reserve_guess_slot(user_id, ip_addr)

    norm_code = normalize_user_code(user_code)
    with db.transaction() as tx:
        now_iso = utc_now_iso()
        row = tx.execute("SELECT * FROM device_codes WHERE user_code = ?", (norm_code,)).fetchone()
        if not row:
            raise ServiceError("设备码不存在", status=400, code="invalid_grant")
        if row["expires_at"] <= now_iso:
            raise ServiceError("设备码已过期", status=400, code="expired_token")
        if row["status"] != "pending":
            _release_guess_slot(ticket)
            raise ServiceError("设备码已被处理", status=400, code="invalid_grant")

        cur = tx.execute(
            """
            UPDATE device_codes
            SET user_id = ?, approved_at = ?, status = 'approved'
            WHERE user_code = ? AND status = 'pending' AND expires_at > ?
            """,
            (user["id"], now_iso, norm_code, now_iso),
        )
        if cur.rowcount == 0:
            _release_guess_slot(ticket)
            raise ServiceError("设备码不存在、已过期或已被处理", status=400, code="invalid_grant")

    _release_guess_slot(ticket)
    return {"ok": True}


def deny_device_code(
    db: Database,
    user: dict[str, Any] | None,
    user_code: str,
    ip_addr: str = "",
) -> dict[str, Any]:
    if not user or user.get("_auth_kind") != "session":
        raise ServiceError("请先登录账号后再拒绝设备", status=401, code="login_required")

    user_id = user.get("id")
    ticket = _reserve_guess_slot(user_id, ip_addr)

    norm_code = normalize_user_code(user_code)
    with db.transaction() as tx:
        now_iso = utc_now_iso()
        row = tx.execute("SELECT * FROM device_codes WHERE user_code = ?", (norm_code,)).fetchone()
        if not row:
            raise ServiceError("设备码不存在", status=400, code="invalid_grant")
        if row["expires_at"] <= now_iso:
            raise ServiceError("设备码已过期", status=400, code="expired_token")
        if row["status"] != "pending":
            _release_guess_slot(ticket)
            raise ServiceError("设备码已被处理", status=400, code="invalid_grant")

        cur = tx.execute(
            """
            UPDATE device_codes
            SET status = 'denied'
            WHERE user_code = ? AND status = 'pending' AND expires_at > ?
            """,
            (norm_code, now_iso),
        )
        if cur.rowcount == 0:
            _release_guess_slot(ticket)
            raise ServiceError("设备码不存在、已过期或已被处理", status=400, code="invalid_grant")

    _release_guess_slot(ticket)
    return {"ok": True}


def exchange_device_token(
    db: Database,
    payload: dict[str, Any],
) -> dict[str, Any]:
    raw_device_code = str(payload.get("deviceCode") or "").strip()
    if not raw_device_code:
        raise ServiceError("invalid_grant", status=400, code="invalid_grant")

    dev_hash = hashlib.sha256(raw_device_code.encode("utf-8")).hexdigest()
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM device_codes WHERE device_code_hash = ?", (dev_hash,)).fetchone()
    if not row or row["status"] == "consumed":
        raise ServiceError("invalid_grant", status=400, code="invalid_grant")

    now_iso = utc_now_iso()
    if row["expires_at"] <= now_iso:
        raise ServiceError("expired_token", status=400, code="expired_token")

    if row["status"] == "denied":
        raise ServiceError("access_denied", status=400, code="access_denied")

    # Check polling interval throttle
    current_interval = int(row["interval"])
    last_polled = row["last_polled_at"] or ""
    if last_polled:
        try:
            dt = datetime.fromisoformat(last_polled.replace("Z", "+00:00"))
            delta = (datetime.now(timezone.utc) - dt).total_seconds()
            if delta < current_interval:
                new_interval = current_interval + 5
                conn.execute(
                    "UPDATE device_codes SET interval = ?, last_polled_at = ? WHERE device_code_hash = ?",
                    (new_interval, now_iso, dev_hash),
                )
                raise ServiceError("slow_down", status=400, code="slow_down")
        except ServiceError:
            raise
        except Exception:
            pass

    conn.execute("UPDATE device_codes SET last_polled_at = ? WHERE device_code_hash = ?", (now_iso, dev_hash))

    if row["status"] == "pending":
        raise ServiceError("authorization_pending", status=400, code="authorization_pending")

    if row["status"] == "approved":
        with db.transaction() as tx:
            tx_now_iso = utc_now_iso()
            curr = tx.execute("SELECT * FROM device_codes WHERE device_code_hash = ?", (dev_hash,)).fetchone()
            if not curr or curr["status"] == "consumed":
                raise ServiceError("invalid_grant", status=400, code="invalid_grant")
            if curr["expires_at"] <= tx_now_iso:
                raise ServiceError("expired_token", status=400, code="expired_token")
            if curr["status"] != "approved":
                raise ServiceError("invalid_grant", status=400, code="invalid_grant")

            # Atomic update guarantees only one concurrent worker succeeds
            cur = tx.execute(
                """
                UPDATE device_codes
                SET status = 'consumed'
                WHERE device_code_hash = ? AND status = 'approved' AND expires_at > ?
                """,
                (dev_hash, tx_now_iso),
            )
            if cur.rowcount != 1:
                raise ServiceError("invalid_grant", status=400, code="invalid_grant")

            u = tx.execute(
                "SELECT id, username, display_name, status FROM users WHERE id = ?",
                (curr["user_id"],),
            ).fetchone()
            if not u or u["status"] != "active":
                raise ServiceError("invalid_grant", status=400, code="invalid_grant")

            token_id = "tok_" + uuid.uuid4().hex
            raw_token = "hwt_" + secrets.token_urlsafe(32)
            tok_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            client_name = sanitize_client_name(curr["client_name"] or "Skill Client")

            tx.execute(
                """
                INSERT INTO api_tokens (
                    id, user_id, name, scopes, token_hash, created_at, last_used_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, '', '')
                """,
                (token_id, u["id"], client_name, curr["scopes"], tok_hash, tx_now_iso),
            )

            try:
                scopes = json.loads(curr["scopes"])
            except Exception:
                scopes = [curr["scopes"]]

            return {
                "ok": True,
                "token": raw_token,
                "scopes": scopes,
                "user": {
                    "username": u["username"],
                    "displayName": u["display_name"],
                },
            }

    raise ServiceError("invalid_grant", status=400, code="invalid_grant")


def list_user_tokens(
    db: Database,
    user: dict[str, Any] | None,
) -> dict[str, Any]:
    if not user or user.get("_auth_kind") != "session":
        raise ServiceError("请先登录账号后再查看已授权设备", status=401, code="login_required")

    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT id, name, scopes, created_at, last_used_at
        FROM api_tokens
        WHERE user_id = ? AND revoked_at = ''
        ORDER BY created_at DESC
        """,
        (user["id"],),
    ).fetchall()

    tokens = []
    for r in rows:
        try:
            scopes = json.loads(r["scopes"])
        except Exception:
            scopes = [r["scopes"]]
        tokens.append({
            "id": r["id"],
            "name": r["name"],
            "scopes": scopes,
            "createdAt": r["created_at"],
            "lastUsedAt": r["last_used_at"],
        })

    return {"ok": True, "tokens": tokens}


def revoke_user_token(
    db: Database,
    user: dict[str, Any] | None,
    token_id: str,
) -> dict[str, Any]:
    if not user or user.get("_auth_kind") != "session":
        raise ServiceError("请先登录账号后再执行该操作", status=401, code="login_required")

    clean_id = (token_id or "").strip()
    if not clean_id:
        raise ServiceError("缺少令牌 ID", status=400, code="invalid_id")

    now_iso = utc_now_iso()
    with db.transaction() as tx:
        cur = tx.execute(
            """
            UPDATE api_tokens
            SET revoked_at = ?
            WHERE id = ? AND user_id = ? AND revoked_at = ''
            """,
            (now_iso, clean_id, user["id"]),
        )
        if cur.rowcount == 0:
            raise ServiceError("令牌不存在或无权操作", status=404, code="not_found")

    return {"ok": True}
