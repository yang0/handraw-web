"""Core domain services for Handraw Web 2.0 (Auth, Boot, Economy, Catalog, Works, Forum, Studio, Skill-Addon)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import threading
import time
import uuid
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .postgres_db import PgConnection

logger = logging.getLogger("backend.services")

from .config import CONTENT_DIR, SESSION_COOKIE_NAME, SESSION_TTL_SECONDS, get_public_billing_summary, resolve_gateway_model
from .db import Database, local_today_str, utc_now_iso
from .seed import DEFAULT_SITE_SETTINGS, DEMO_DEFAULT_PASSWORD, is_demo_mode, is_seed_username, seed_ids
from .runtime_policy import sanitize_media_url, sanitize_plain_text, sanitize_rich_html, env_flag
from .security import (
    generate_api_key,
    generate_session_token,
    hash_password,
    hash_session_token,
    parse_cookie_header,
    verify_password,
)


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request", extra: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.extra = extra or {}


CREATOR_HONOR_TIERS = [
    # ``boost``/``boostText`` were exposure multipliers.  Ranking is now purely
    # interaction-based (see ``ranking.py``), so honour no longer buys priority.
    # The fields stay for API compatibility but are no longer used for ordering.
    {"tier": 4, "minCount": 6, "key": "hall", "badge": "👑 殿堂共创官", "shortBadge": "👑 殿堂", "boost": 1.0, "boostText": "", "sealClass": "honor-hall"},
    {"tier": 3, "minCount": 3, "key": "gold", "badge": "🏅 金牌主理人", "shortBadge": "🏅 金牌", "boost": 1.0, "boostText": "", "sealClass": "honor-gold"},
    {"tier": 2, "minCount": 2, "key": "pioneer", "badge": "🌟 先锋开荒者", "shortBadge": "🌟 先锋", "boost": 1.0, "boostText": "", "sealClass": "honor-pioneer"},
    {"tier": 1, "minCount": 1, "key": "rookie", "badge": "🌱 新锐创作者", "shortBadge": "🌱 新锐", "boost": 1.0, "boostText": "", "sealClass": "honor-rookie"},
    {"tier": 0, "minCount": 0, "key": "member", "badge": "✨ 灵感探索者", "shortBadge": "探索者", "boost": 1.0, "boostText": "", "sealClass": "honor-member"},
]

FORUM_BOARDS: list[dict[str, str]] = [
    {"key": "all", "label": "📋 全区总版主", "shortLabel": "全区总版", "desc": "跨全论坛所有板块享有置顶、加精、移版与违规治理权限"},
    {"key": "showcase", "label": "🎨 作品讨论", "shortLabel": "作品讨论版", "desc": "公开作品收到首条有效评论后进入本版，作品与讨论一对一关联"},
    {"key": "tuning", "label": "🎯 作品求调优 / 悬赏", "shortLabel": "调优悬赏版", "desc": "负责实测翻车诊断、提示词调优与求改悬赏帖秩序"},
    {"key": "experience", "label": "📘 实战经验与变现", "shortLabel": "实战变现版", "desc": "负责商单交付 SOP、小红书/公众号起号复盘与精选加精"},
    {"key": "assets", "label": "🎨 画风与图型专区", "shortLabel": "画风图型版", "desc": "负责 370+ 画风与 170+ 图型参数研讨、新风格共创交流"},
    {"key": "tools", "label": "🛠️ 工具流与问答", "shortLabel": "工具问答版", "desc": "负责无限画布工作流、Skill 插件排障与日常创作问答"},
]
FORUM_BOARD_LABELS: dict[str, str] = {b["key"]: b["label"] for b in FORUM_BOARDS}
FORUM_BOARD_SHORT_LABELS: dict[str, str] = {b["key"]: b["shortLabel"] for b in FORUM_BOARDS}


def _seed_filter(column: str, kind: str) -> tuple[str, tuple[str, ...]]:
    """Build a parameterized exclusion for known demo IDs in normal mode."""
    if is_demo_mode():
        return "1 = 1", ()
    ids = sorted(seed_ids(kind))
    if not ids:
        return "1 = 1", ()
    placeholders = ", ".join("?" for _ in ids)
    return f"{column} NOT IN ({placeholders})", tuple(ids)


def _default_asset_social_baseline(code: str) -> tuple[int, int]:
    """Return synthetic social baselines only for an explicitly demo boot."""
    if not is_demo_mode():
        return (0, 0)
    up = (code or "").strip().upper()
    h = sum((i + 1) * ord(ch) for i, ch in enumerate(up))
    return (12 + (h % 29), 7 + ((h * 3) % 21))


def _infer_asset_kind(code: str, fallback: str = "style") -> str:
    up = (code or "").strip().upper()
    if re.match(r"^(SC|IG|SB|IP|EC|LX|USR-L)", up):
        return "layout"
    if re.match(r"^(F[A-Z]|S-|USR-S)", up):
        return "style"
    return "layout" if fallback == "layout" else "style"


def compute_honor_tier(total_published: int, honor_override: int | None = None) -> dict[str, Any]:
    if honor_override is not None:
        for t in CREATOR_HONOR_TIERS:
            if t["tier"] == int(honor_override):
                return t
    cnt = max(0, int(total_published))
    for t in CREATOR_HONOR_TIERS:
        if cnt >= int(t["minCount"]):
            return t
    return CREATOR_HONOR_TIERS[-1]


def format_short_time(iso_or_label: str) -> str:
    if not iso_or_label:
        return "刚刚"
    if "T" not in iso_or_label:
        return iso_or_label
    try:
        dt = datetime.fromisoformat(iso_or_label.replace("Z", "+00:00")).astimezone()
        today = datetime.now().astimezone().date()
        if dt.date() == today:
            return f"今天 {dt.strftime('%H:%M')}"
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return iso_or_label


def format_relative_cn(published_at_ms: int, fallback: str = "刚刚") -> str:
    if not published_at_ms:
        return fallback or "刚刚"
    diff_sec = max(0, int(time.time() - published_at_ms / 1000.0))
    if diff_sec < 90:
        return "刚刚"
    if diff_sec < 3600:
        return f"{max(1, diff_sec // 60)} 分钟前"
    if diff_sec < 86400:
        return f"{max(1, diff_sec // 3600)} 小时前"
    return f"{max(1, diff_sec // 86400)} 天前"


NEW_RELEASE_WINDOW_MS = 72 * 60 * 60 * 1000


def is_new_release_active(published_at_ms: int | None, now_ms: int | None = None) -> bool:
    """Use publication time as the single source of truth for the 72h badge."""
    try:
        published = int(published_at_ms or 0)
    except (TypeError, ValueError):
        return False
    if published <= 0:
        return False
    current = int(now_ms if now_ms is not None else time.time() * 1000)
    age = current - published
    return 0 <= age < NEW_RELEASE_WINDOW_MS


def get_site_settings(conn: PgConnection) -> dict[str, Any]:
    out = json.loads(json.dumps(DEFAULT_SITE_SETTINGS))
    rows = conn.execute("SELECT key, value_json FROM site_settings").fetchall()
    for r in rows:
        try:
            parsed = json.loads(r["value_json"])
            if isinstance(parsed, dict) and isinstance(out.get(r["key"]), dict):
                out[r["key"]].update(parsed)
            else:
                out[r["key"]] = parsed
        except Exception:
            pass
    return out


def record_audit_log(
    tx: PgConnection,
    actor: dict[str, Any] | None,
    action: str,
    target_type: str,
    target_id: str,
    reason: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    tx.execute(
        """
        INSERT INTO audit_logs (actor_id, actor_username, actor_role, action, target_type, target_id, reason, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            actor["id"] if actor else None,
            actor["username"] if actor else "system",
            actor["role"] if actor else "system",
            action,
            target_type,
            str(target_id),
            reason or "",
            json.dumps(details or {}, ensure_ascii=False),
            utc_now_iso(),
        ),
    )


def apply_wallet_delta(
    tx: PgConnection,
    user_id: int,
    delta: int,
    kind: str,
    reason: str,
    event_key: str | None = None,
    ref_type: str = "",
    ref_id: str = "",
    actor_id: int | None = None,
    allow_negative: bool = False,
) -> tuple[int, bool]:
    """Atomically apply credit delta and write append-only ledger. Returns (new_balance, applied)."""
    # These old engagement actions must never mint spendable points.
    if kind in {"welcome", "invite_invitee", "invite_inviter", "publish_work", "honor_upgrade", "first_collect", "first_cheer", "discourse_migration"}:
        row = tx.execute("SELECT balance FROM wallets WHERE user_id=?", (user_id,)).fetchone()
        return (int(row[0]) if row else 0), False
    if kind == "publish_asset":
        from .points import reward
        granted = reward(tx, user_id, "asset", ref_id, actor_id)
        return int(tx.execute("SELECT balance FROM wallets WHERE user_id=?", (user_id,)).fetchone()[0]), bool(granted)
    now = utc_now_iso()
    # PostgreSQL transactions must lock the wallet row before reading its
    # balance. The database lock protects separate worker processes.
    # The ledger and balance update remain in the same database transaction.
    wallet_sql = "SELECT balance, locked FROM wallets WHERE user_id = ?"
    wallet_sql += " FOR UPDATE"
    w = tx.execute(wallet_sql, (user_id,)).fetchone()
    if not w:
        tx.execute(
            "INSERT INTO wallets (user_id, balance, free_quota_date, free_quota_used, checkin_date, locked, updated_at) VALUES (?, 0, '', 0, '', 0, ?)",
            (user_id, now),
        )
        cur_balance = 0
        locked = 0
    else:
        cur_balance = int(w["balance"])
        locked = int(w["locked"])

    if locked and delta < 0 and not allow_negative:
        raise ServiceError("积分钱包当前处于风控锁定状态，请联系管理员", status=403, code="wallet_locked")

    if event_key:
        dup = tx.execute("SELECT id FROM ledgers WHERE user_id = ? AND event_key = ?", (user_id, event_key)).fetchone()
        if dup:
            return cur_balance, False

    new_balance = cur_balance + int(delta)
    if new_balance < 0 and not allow_negative:
        raise ServiceError(f"积分不足（需 {abs(delta)} 积分，当前可用 {cur_balance} 积分）", status=400, code="insufficient_credits")

    tx.execute("UPDATE wallets SET balance = ?, updated_at = ? WHERE user_id = ?", (new_balance, now, user_id))
    ledger = tx.execute(
        """
        INSERT INTO ledgers (user_id, delta, balance_after, kind, event_key, reason, ref_type, ref_id, actor_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id
        """,
        (user_id, int(delta), new_balance, kind, event_key, reason, ref_type, str(ref_id), actor_id, now),
    ).fetchone()
    from .points import track_delta
    track_delta(tx, user_id, ledger[0], int(delta), kind, ref_type, str(ref_id))
    return new_balance, True


def get_wallet_quota_state(conn: PgConnection, user_id: int, settings: dict[str, Any]) -> dict[str, Any]:
    from .economy import quota, cash
    q = quota(conn,user_id,"1k")
    w = conn.execute("SELECT balance,checkin_date,locked FROM wallets WHERE user_id=?",(user_id,)).fetchone()
    return {"balance":int(w["balance"]) if w else 0,"freeQuotaMax":q["total"],
            "freeQuotaRemaining":q["remaining"],"dailyCheckedIn":bool(w and w["checkin_date"]==local_today_str()),
            "locked":bool(w and w["locked"]),"cash":cash(conn,user_id),"quotaResolution":"1k"}


def _count_user_published_items(conn: PgConnection, username: str) -> int:
    work_filter, work_ids = _seed_filter("id", "works")
    asset_filter, asset_ids = _seed_filter("code", "assets")
    w_cnt = int(
        conn.execute(
            f"SELECT COUNT(*) FROM works WHERE author_username = ? AND status = 'published' AND images_json IS NOT NULL AND TRIM(images_json) NOT IN ('', '[]', 'null') AND (images_json IS JSON ARRAY) AND {work_filter}",
            (username, *work_ids),
        ).fetchone()[0]
    )
    a_cnt = int(
        conn.execute(
            f"SELECT COUNT(*) FROM catalog_assets WHERE author_username = ? AND source_type = 'community' AND status = 'published' AND {asset_filter}",
            (username, *asset_ids),
        ).fetchone()[0]
    )
    return w_cnt + a_cnt


# ======================== AUTHENTICATION & SESSIONS ========================

def _header_ci_val(headers: dict[str, str], name: str) -> str:
    target = name.lower()
    for k, v in headers.items():
        if k.lower() == target:
            return str(v or "")
    return ""


def _has_header_ci(headers: dict[str, str], name: str) -> bool:
    target = name.lower()
    for k in headers.keys():
        if k.lower() == target:
            return True
    return False


def authenticate_request(db: Database, headers: dict[str, str]) -> dict[str, Any] | None:
    conn = db.get_conn()
    now_ts = int(time.time())

    # 1. Bearer token, X-Handraw-Token, or Api-Key
    has_auth_hdr = _has_header_ci(headers, "Authorization")
    has_x_hdr = _has_header_ci(headers, "X-Handraw-Token")
    has_api_key_hdr = _has_header_ci(headers, "Api-Key")

    # If ANY Authorization, X-Handraw-Token, or Api-Key header is provided (regardless of casing,
    # empty value, scheme, or format), ONLY token auth is evaluated.
    # Invalid/malformed/revoked/unknown tokens or conflicting headers MUST return None immediately
    # without ever falling back to Session Cookie.
    if has_auth_hdr or has_x_hdr or has_api_key_hdr:
        extracted: dict[str, str | None] = {}

        if has_auth_hdr:
            raw_auth = _header_ci_val(headers, "Authorization").strip()
            if raw_auth.lower().startswith("bearer "):
                extracted["auth"] = raw_auth[7:].strip()
            else:
                # Non-Bearer scheme (e.g. Basic), empty string, or malformed Authorization header
                extracted["auth"] = None

        if has_x_hdr:
            extracted["x"] = _header_ci_val(headers, "X-Handraw-Token").strip()

        if has_api_key_hdr:
            raw_api = _header_ci_val(headers, "Api-Key").strip()
            if raw_api.lower().startswith("bearer "):
                extracted["api_key"] = raw_api[7:].strip()
            else:
                extracted["api_key"] = raw_api

        # If any provided header is malformed (None) or empty:
        # Invalid credential provided; reject immediately without fallback to cookie.
        if None in extracted.values() or "" in extracted.values():
            return None

        # Conflicting credentials check: all present credential headers must specify the exact same token
        valid_tokens = [tok for tok in extracted.values() if tok is not None and tok != ""]
        if len(set(valid_tokens)) != 1:
            return None

        token = valid_tokens[0]

        # Deprecated legacy keys are strictly rejected
        if token.startswith("hwk_"):
            return None

        # Personal access token (hwt_...)
        if token.startswith("hwt_"):
            tok_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            tok_row = conn.execute(
                "SELECT * FROM api_tokens WHERE token_hash = ? AND revoked_at = ''",
                (tok_hash,),
            ).fetchone()
            if not tok_row:
                return None
            if "expires_at" in tok_row.keys() and tok_row["expires_at"]:
                exp_val = tok_row["expires_at"]
                if isinstance(exp_val, (int, float)) and exp_val <= now_ts:
                    return None
                elif isinstance(exp_val, str) and exp_val and exp_val <= utc_now_iso():
                    return None
            u = conn.execute(
                "SELECT * FROM users WHERE id = ? AND status = 'active'",
                (tok_row["user_id"],),
            ).fetchone()
            if not u:
                return None

            # Explicit exception to the "GET does not write to database" rule:
            # We track last_used_at for token auditing in user device management UI.
            # To reduce writes on frequent read queries (e.g. Skill sync),
            # this update is throttled to at most once every 5 minutes (300 seconds).
            last_used = tok_row["last_used_at"] or ""
            should_update = True
            if last_used:
                try:
                    dt = datetime.fromisoformat(last_used.replace("Z", "+00:00"))
                    if (datetime.now(timezone.utc) - dt).total_seconds() < 300:
                        should_update = False
                except Exception:
                    pass
            if should_update:
                now_iso = utc_now_iso()
                conn.execute("UPDATE api_tokens SET last_used_at = ? WHERE id = ?", (now_iso, tok_row["id"]))

            user_dict = dict(u)
            user_dict["_auth_kind"] = "token"
            user_dict["_token_id"] = tok_row["id"]
            try:
                scopes = json.loads(tok_row["scopes"])
                if not isinstance(scopes, list):
                    scopes = [str(scopes)]
            except Exception:
                scopes = [s.strip() for s in tok_row["scopes"].split(",") if s.strip()]
            user_dict["_token_scopes"] = scopes
            return user_dict

        # If Api-Key was provided, only hwt_ personal access tokens are accepted
        if has_api_key_hdr:
            return None

        # Bearer session token (e.g. session token passed via Authorization or X-Handraw-Token header)
        tok_hash = hash_session_token(token)
        row = conn.execute(
            """
            SELECT u.*
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (tok_hash, now_ts),
        ).fetchone()
        if not row or row["status"] != "active":
            return None
        result = dict(row)
        result["_session_token"] = token
        result["_auth_kind"] = "session"
        result["_token_scopes"] = ["*"]
        return result

    # 2. Session Cookie (only evaluated when NO Authorization, X-Handraw-Token, or Api-Key header is present)
    cookie_str = _header_ci_val(headers, "Cookie")
    cookies = parse_cookie_header(cookie_str)
    sess_token = (cookies.get(SESSION_COOKIE_NAME) or "").strip()
    if not sess_token:
        return None

    sess_hash = hash_session_token(sess_token)
    row = conn.execute(
        """
        SELECT u.*
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ? AND s.expires_at > ?
        """,
        (sess_hash, now_ts),
    ).fetchone()
    if not row or row["status"] != "active":
        return None
    result = dict(row)
    result["_session_token"] = sess_token
    result["_auth_kind"] = "session"
    result["_token_scopes"] = ["*"]
    return result


def create_session_for_user(tx: PgConnection, user_id: int, user_agent: str = "", ip_addr: str = "") -> str:
    token = generate_session_token()
    token_hash = hash_session_token(token)
    now_iso = utc_now_iso()
    exp = int(time.time()) + SESSION_TTL_SECONDS
    tx.execute(
        "INSERT INTO sessions (token, user_id, user_agent, ip_addr, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (token_hash, user_id, (user_agent or "")[:200], (ip_addr or "")[:64], exp, now_iso),
    )
    tx.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso, user_id))
    return token


def register_user(
    db: Database,
    username: str,
    password: str,
    email: str = "",
    display_name: str = "",
    invite_code: str = "",
    user_agent: str = "",
    ip_addr: str = "",
) -> tuple[dict[str, Any], str]:
    uname = re.sub(r"[^a-zA-Z0-9_\-]", "", (username or "").strip())
    if len(uname) < 2 or len(uname) > 32:
        raise ServiceError("用户名需为 2~32 位字母、数字、下划线或连字符")
    if len(password or "") < 8:
        raise ServiceError("登录密码至少 8 位")

    clean_email = (email or f"{uname}@handraw-style.com").strip().lower()
    clean_dname = sanitize_plain_text(display_name, max_chars=40)
    dname = clean_dname if clean_dname else uname
    ref_code = (invite_code or "").strip()
    now_iso = utc_now_iso()

    with db.transaction() as tx:
        exists = tx.execute(
            "SELECT id FROM users WHERE username = ? OR (email != '' AND email = ?)",
            (uname, clean_email),
        ).fetchone()
        if exists:
            raise ServiceError("该用户名或邮箱已被注册，请直接登录或更换用户名")

        settings = get_site_settings(tx)
        econ = settings.get("economy", {})
        welcome = int(econ.get("welcome_credits", 20))
        inviter_bonus = int(econ.get("invite_inviter_credits", 15))
        invitee_bonus = int(econ.get("invite_invitee_credits", 10))

        inviter_row = None
        if ref_code:
            inviter_row = tx.execute(
                "SELECT id, username, display_name FROM users WHERE invite_code = ? AND status = 'active'",
                (ref_code,),
            ).fetchone()

        pw_hash = hash_password(password)
        api_key = ""
        cur = tx.execute(
            """
            INSERT INTO users (
                username, display_name, email, password_hash, password_algo,
                role, status, bio, invite_code, invited_by, api_key, created_at, last_login_at, nickname_locked
            ) VALUES (?, ?, ?, ?, 'pbkdf2_sha256', 'user', 'active', 'Handraw 新锐社区创作者', ?, ?, ?, ?, ?, ?) RETURNING id
            """,
            (uname, dname, clean_email, pw_hash, uname, inviter_row["username"] if inviter_row else "", api_key or None, now_iso, now_iso, 1),
        )
        uid = int(cur.fetchone()[0])
        tx.execute(
            "INSERT INTO wallets (user_id, balance, free_quota_date, free_quota_used, checkin_date, locked, updated_at) VALUES (?, 0, '', 0, '', 0, ?)",
            (uid, now_iso),
        )
        if welcome > 0:
            apply_wallet_delta(tx, uid, welcome, "welcome", "新用户注册欢迎礼（可解锁配方或云端生图）", event_key=f"welcome_{uid}")

        if inviter_row and inviter_row["id"] != uid:
            if invitee_bonus > 0:
                apply_wallet_delta(
                    tx,
                    uid,
                    invitee_bonus,
                    "invite_invitee",
                    f"受好友 @{inviter_row['display_name']} 邀请注册加赠礼",
                    event_key=f"invitee_{uid}",
                )
            if inviter_bonus > 0:
                apply_wallet_delta(
                    tx,
                    int(inviter_row["id"]),
                    inviter_bonus,
                    "invite_inviter",
                    f"成功邀请新创作者 @{dname} 注册奖励",
                    event_key=f"inviter_{inviter_row['id']}_{uid}",
                    ref_type="user",
                    ref_id=str(uid),
                )

        token = create_session_for_user(tx, uid, user_agent=user_agent, ip_addr=ip_addr)
        user_row = dict(tx.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())
    return user_row, token


def login_user(
    db: Database,
    identifier: str,
    password: str,
    user_agent: str = "",
    ip_addr: str = "",
) -> tuple[dict[str, Any], str]:
    ident = (identifier or "").strip()
    if not ident or not password:
        raise ServiceError("请输入用户名/邮箱与密码")

    with db.transaction() as tx:
        row = tx.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?",
            (ident, ident.lower()),
        ).fetchone()
        if not row:
            raise ServiceError("账号不存在或密码不正确", status=401, code="invalid_credentials")
        if row["status"] != "active":
            raise ServiceError("该账号已被冻结，如有疑问请联系社区管理员", status=403, code="account_frozen")
        if row["password_algo"] == "reset_required":
            raise ServiceError("这是老论坛迁移的账号，请先通过邮件重设密码", status=401, code="password_reset_required")
        if (
            not is_demo_mode()
            and password == DEMO_DEFAULT_PASSWORD
            and is_seed_username(row["username"])
            and not row["discourse_user_id"]
        ):
            raise ServiceError("演示账号默认凭据已停用，请先完成真实账号接管", status=401, code="seed_credentials_disabled")

        ok = verify_password(
            password,
            row["password_hash"],
            password_algo=row["password_algo"],
            discourse_salt=row["discourse_salt"],
        )
        if not ok:
            raise ServiceError("账号不存在或密码不正确", status=401, code="invalid_credentials")

        # Transparent upgrade from imported Discourse hash to native PBKDF2-SHA256
        if row["password_algo"] != "pbkdf2_sha256":
            tx.execute(
                "UPDATE users SET password_hash = ?, password_algo = 'pbkdf2_sha256', discourse_salt = '' WHERE id = ?",
                (hash_password(password), int(row["id"])),
            )

        token = create_session_for_user(tx, int(row["id"]), user_agent=user_agent, ip_addr=ip_addr)
        user_row = dict(tx.execute("SELECT * FROM users WHERE id = ?", (int(row["id"]),)).fetchone())
    return user_row, token


def logout_session(db: Database, token: str) -> None:
    if not token:
        return
    token_hash = hash_session_token(token)
    with db.transaction() as tx:
        tx.execute("DELETE FROM sessions WHERE token = ?", (token_hash,))


def sandbox_switch_account(db: Database, target_username: str, user_agent: str = "", ip_addr: str = "") -> tuple[dict[str, Any] | None, str]:
    """Local dev/testing quick account switcher (yang0 / ops_lin / reviewer_su / su_editorial / guest)."""
    if not target_username or target_username == "guest":
        return None, ""
    with db.transaction() as tx:
        row = tx.execute("SELECT * FROM users WHERE username = ?", (target_username,)).fetchone()
        if not row:
            raise ServiceError(f"未找到测试账号：{target_username}", status=404)
        if row["status"] != "active":
            raise ServiceError(f"账号 {target_username} 当前已被冻结", status=403)
        token = create_session_for_user(tx, int(row["id"]), user_agent=user_agent, ip_addr=ip_addr)
        return dict(row), token


def update_my_profile(db: Database, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Update biography and rotate password; registration nickname stays immutable.

    Email changes require separate proof-of-mail flow; this endpoint never
    directly overwrites the account's recovery address.
    """
    uid = int(user["id"])
    with db.transaction() as tx:
        row = tx.execute("SELECT * FROM users WHERE id = ? AND status='active'", (uid,)).fetchone()
        if not row:
            raise ServiceError("账号不存在", status=404)

        name = row["display_name"]
        locked = True
        last_nickname_change = int(row["nickname_changed_at"] or 0)
        # Display names are chosen at registration (falling back to username).
        # Do not reopen legacy nickname_locked=0 accounts for editing.
        if "displayName" in body:
            requested = sanitize_plain_text(str(body.get("displayName") or ""), max_chars=40)
            if requested != name:
                raise ServiceError("创作者昵称在注册完成后不可修改",
                                   status=409, code="nickname_locked")

        if "email" in body and str(body.get("email") or "").strip().lower() != str(row["email"] or "").lower():
            raise ServiceError("请使用邮箱换绑验证流程，新邮箱验证后才会生效", status=409, code="email_verification_required")

        bio = sanitize_plain_text(
            body.get("bio") if body.get("bio") is not None else (row["bio"] or ""), max_chars=300
        )
        new_pw = str(body.get("newPassword") or "")
        pwd_hash, algo, salt = row["password_hash"], row["password_algo"], row["discourse_salt"]
        if new_pw:
            if len(new_pw) < 8 or len(new_pw) > 128:
                raise ServiceError("新密码需要 8～128 个字符")
            old_pw = str(body.get("currentPassword") or "")
            if not verify_password(old_pw, pwd_hash, password_algo=algo, discourse_salt=salt):
                raise ServiceError("当前密码不正确", status=403, code="incorrect_password")
            if verify_password(new_pw, pwd_hash, password_algo=algo, discourse_salt=salt):
                raise ServiceError("新密码不能与原密码相同", code="password_reused")
            pwd_hash, algo, salt = hash_password(new_pw), "pbkdf2_sha256", ""

        api_key = generate_api_key() if body.get("regenerateApiKey") else row["api_key"]
        tx.execute(
            """UPDATE users SET display_name=?, nickname_locked=?, nickname_changed_at=?, bio=?, password_hash=?,
                password_algo=?, discourse_salt=?, api_key=? WHERE id=?""",
            (name, int(locked), last_nickname_change, bio, pwd_hash, algo, salt, api_key, uid),
        )
        if name != row["display_name"]:
            tx.execute("UPDATE works SET author_name=? WHERE author_username=?", (name, row["username"]))
            tx.execute("UPDATE forum_topics SET author_name=? WHERE author_username=?", (name, row["username"]))
            tx.execute(
                "UPDATE catalog_assets SET author_name=? WHERE author_username=? AND source_type='community'",
                (name, row["username"]),
            )
        if name != row["display_name"]:
            tx.execute("INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at) VALUES(?,?,?,?,?,?)",
                       (uid, "security", "你的创作者昵称已更新。如果不是本人操作，请检查账号安全。", "", "", utc_now_iso()))
        if new_pw:
            tx.execute("INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at) VALUES(?,?,?,?,?,?)",
                       (uid, "security", "你的登录密码已修改，其他网页登录会话已退出。", "", "", utc_now_iso()))
            # Keep the current browser session so the user can see success,
            # revoke every other device/session. API-token requests have no
            # browser session, therefore revoke all browser sessions.
            raw_token = str(user.get("_session_token") or "")
            if raw_token:
                tx.execute("DELETE FROM sessions WHERE user_id=? AND token!=?",
                           (uid, hash_session_token(raw_token)))
            else:
                tx.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        updated = dict(tx.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    return {"ok": True, "boot": build_boot_payload(db, updated),
            "sessionsRevoked": bool(new_pw)}


# ======================== BOOT PAYLOAD & STRICT SERVER GATES ========================

def _serialize_catalog_asset(row: dict[str, Any], unlocked_set: set[str], current_user: dict[str, Any] | None) -> dict[str, Any]:
    code = row["code"]
    source_type = row["source_type"]
    cost = int(row["unlock_cost"] or 0)
    is_staff = bool(current_user and current_user.get("role") in ("admin", "operator", "reviewer"))
    is_author = bool(current_user and current_user.get("username") == row["author_username"])
    is_unlocked = cost <= 0 or (code in unlocked_set) or is_author or is_staff

    # NEVER leak secret_blackbox_prompt to frontend!
    if source_type == "exclusive":
        public_def = row["definition"] or f"[CLOUD_BLACKBOX::{code}] 仅限在线创作工坊云端生图自动注入底层视觉参数。"
    elif not is_unlocked:
        public_def = f"[LOCKED_ASSET::{code}] 付费共创资产（需 {cost} 积分解锁后可在线上创作台使用）"
    elif cost > 0 and not (is_author or is_staff):
        public_def = f"[CLOUD_BLACKBOX::{code}] 付费共创资产（已解锁，仅限在线创作工坊云端生图自动注入底层视觉参数）"
    else:
        public_def = row["definition"] or row["description"] or ""

    try:
        stamps = json.loads(row["stamp_counts_json"] or "{}")
    except Exception:
        stamps = {}

    return {
        "id": code,
        "code": code,
        "kind": row["kind"],
        "sourceType": source_type,
        "tier": row["tier"],
        "unlockCost": cost,
        "author": row["author_username"],
        "authorName": row["author_name"] or row["author_username"],
        "createdAt": row["created_label"] or format_relative_cn(int(row["published_at_ms"])),
        "isNewRelease": is_new_release_active(row["published_at_ms"]),
        "featured": bool(row["featured"]),
        "publishedAtMs": int(row["published_at_ms"]),
        "cheers": int(row["cheers"]),
        "tips": int(row["tips"]),
        "stampCounts": stamps,
        "name": row["name"],
        "group": row["group_name"],
        "description": row["description"],
        "definition": public_def,
        "image": row["image_url"],
    }


class SecretsScanError(ServiceError):
    """Raised when catalog secrets cannot be queried (fail-closed, G1)."""
    def __init__(self, message: str = "资源安全扫描查询失败") -> None:
        super().__init__(message, status=500, code="secrets_scan_failed")


_SECRETS_CACHE: dict[str, Any] = {
    "hash": "",
    "secrets": [],
    "windows": set(),
    "loaded_at": 0.0,
}
_LAST_SCANNED_SECRETS_HASH = ""

# The running server binds its database for private prompt/black-box scans.
# Security-sensitive reads must use the same authority as request handling.
_RUNTIME_DB: Any | None = None


def bind_runtime_database(db: Any) -> None:
    global _RUNTIME_DB
    _RUNTIME_DB = db


def _runtime_connection(conn: Any | None) -> Any | None:
    if conn is not None:
        return conn
    if _RUNTIME_DB is not None:
        return _RUNTIME_DB.get_conn()
    return None


def get_secrets_cache(conn: PgConnection | None = None, force: bool = False) -> tuple[str, list[str], set[str]]:
    global _SECRETS_CACHE
    now = time.time()
    secrets: list[str] = []
    conn = _runtime_connection(conn)
    if conn is None:
        raise SecretsScanError("Runtime database is not bound; cannot inspect protected prompts")
    try:
        rows = conn.execute(
            "SELECT DISTINCT secret_blackbox_prompt FROM catalog_assets WHERE secret_blackbox_prompt IS NOT NULL AND TRIM(secret_blackbox_prompt) <> ''"
        ).fetchall()
        secrets = [str(r[0]).strip() for r in rows if r[0] and str(r[0]).strip()]
    except Exception as exc:
        raise SecretsScanError(f"Failed to query catalog secrets: {exc}") from exc

    secrets.sort()
    vhash = hashlib.sha256(repr(secrets).encode("utf-8")).hexdigest()
    if vhash == _SECRETS_CACHE["hash"] and _SECRETS_CACHE["secrets"]:
        _SECRETS_CACHE["loaded_at"] = now
        return _SECRETS_CACHE["hash"], _SECRETS_CACHE["secrets"], _SECRETS_CACHE["windows"]

    windows: set[str] = set()
    for s in secrets:
        if len(s) >= 20:
            for i in range(len(s) - 19):
                windows.add(s[i : i + 20])

    _SECRETS_CACHE = {
        "hash": vhash,
        "secrets": secrets,
        "windows": windows,
        "loaded_at": now,
    }
    return vhash, secrets, windows


def check_text_has_secret(
    text: str,
    conn: PgConnection | None = None,
    preloaded: tuple[str, list[str], set[str]] | None = None,
    extra_secrets: list[str] | None = None,
) -> bool:
    """Return True if text contains any whole secret or any 20-character window of one.
    Raises SecretsScanError if querying catalog secrets fails (fail-closed, G1).
    """
    if not text or not isinstance(text, str):
        return False
    if extra_secrets:
        for es in extra_secrets:
            if not es or not isinstance(es, str):
                continue
            es_clean = es.strip()
            if not es_clean:
                continue
            if es_clean in text:
                return True
            if len(es_clean) >= 20:
                for i in range(len(es_clean) - 19):
                    if es_clean[i : i + 20] in text:
                        return True
    if preloaded is not None:
        vhash, secrets, windows = preloaded
    else:
        vhash, secrets, windows = get_secrets_cache(conn)
    if not secrets:
        return False
    for s in secrets:
        if s in text:
            return True
    for w in windows:
        if w in text:
            return True
    return False


def extract_strings_from_obj(obj: Any) -> list[str]:
    """Recursively collect all decoded string values from arbitrary data structures (G5)."""
    strings: list[str] = []
    if isinstance(obj, str):
        strings.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            strings.extend(extract_strings_from_obj(v))
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            strings.extend(extract_strings_from_obj(item))
    return strings


def check_obj_has_secret(
    obj: Any,
    conn: PgConnection | None = None,
    preloaded: tuple[str, list[str], set[str]] | None = None,
) -> bool:
    """Check if any decoded string in obj contains a secret or 20-char window (G5)."""
    if not obj:
        return False
    strings = extract_strings_from_obj(obj)
    for s in strings:
        if s and check_text_has_secret(s, conn, preloaded=preloaded):
            return True
    return False


_RECIPE_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_RECIPE_RATIO_PATTERN = re.compile(r"^\d+(?:\.\d+)?:\d+(?:\.\d+)?$")
_RECIPE_COLOR_PATTERN = re.compile(r"^[A-Za-z0-9_#-]{1,32}$")

_STATIC_CATALOG_CODES: dict[str, set[str]] | None = None


def _get_static_catalog_codes() -> dict[str, set[str]]:
    global _STATIC_CATALOG_CODES
    if _STATIC_CATALOG_CODES is not None:
        return _STATIC_CATALOG_CODES

    styles: set[str] = set()
    layouts: set[str] = set()
    colors: set[str] = set()
    tones: set[str] = set()

    cat_file = CONTENT_DIR / "catalog.json"
    if cat_file.is_file():
        try:
            cat_data = json.loads(cat_file.read_text(encoding="utf-8"))
            for item in cat_data.get("resources", []):
                code = str(item.get("id") or "").strip().upper()
                kind = str(item.get("kind") or "").strip().lower()
                if not code:
                    continue
                if kind == "style":
                    styles.add(code)
                elif kind == "layout":
                    layouts.add(code)
                elif kind == "color":
                    colors.add(code)
        except Exception:
            pass

    opt_file = CONTENT_DIR / "studio-options.json"
    if opt_file.is_file():
        try:
            opt_data = json.loads(opt_file.read_text(encoding="utf-8"))
            for t in opt_data.get("tones", []):
                tid = str(t.get("id") or "").strip().upper()
                if tid:
                    tones.add(tid)
            for s_id in opt_data.get("styles", {}):
                sid = str(s_id).strip().upper()
                if sid:
                    styles.add(sid)
            for a_id in opt_data.get("assets", {}):
                aid = str(a_id).strip().upper()
                if aid:
                    styles.add(aid)
        except Exception:
            pass

    try:
        from .seed import SERVER_EXCLUSIVE_BLACKBOX, SEED_JSON_PATH

        for code in SERVER_EXCLUSIVE_BLACKBOX:
            c = code.strip().upper()
            if c.startswith("F"):
                styles.add(c)
            elif c.startswith("L"):
                layouts.add(c)

        if SEED_JSON_PATH.is_file():
            seed_raw = json.loads(SEED_JSON_PATH.read_text(encoding="utf-8"))
            for r in seed_raw.get("exclusiveResources", []) + seed_raw.get("communityResources", []):
                c = str(r.get("id") or "").strip().upper()
                k = str(r.get("kind") or "").strip().lower()
                if not c:
                    continue
                if k == "style":
                    styles.add(c)
                elif k == "layout":
                    layouts.add(c)
                elif k == "color":
                    colors.add(c)
                elif k == "tone":
                    tones.add(c)
    except Exception:
        pass

    _STATIC_CATALOG_CODES = {
        "styles": styles,
        "layouts": layouts,
        "colors": colors,
        "tones": tones,
        "all": styles | layouts | colors | tones,
    }
    return _STATIC_CATALOG_CODES


def get_valid_catalog_codes(conn: PgConnection | None = None) -> dict[str, set[str]]:
    """Return dictionary of real catalog codes {styles, layouts, colors, tones, all} (J2, J3)."""
    static = _get_static_catalog_codes()
    styles = set(static["styles"])
    layouts = set(static["layouts"])
    colors = set(static["colors"])
    tones = set(static["tones"])

    rows: list[Any] = []
    conn = _runtime_connection(conn)
    if conn is None:
        return static
    try:
        rows = conn.execute("SELECT code, kind FROM catalog_assets").fetchall()
    except Exception:
        rows = []

    for r in rows:
        code = str(r[0] if isinstance(r, (tuple, list)) else r["code"]).strip().upper()
        raw_kind = (r[1] if isinstance(r, (tuple, list)) else r["kind"]) or ""
        kind = str(raw_kind).strip().lower()
        if not code:
            continue
        if kind == "style":
            styles.add(code)
        elif kind == "layout":
            layouts.add(code)
        elif kind == "color":
            colors.add(code)
        elif kind == "tone":
            tones.add(code)
        else:
            styles.add(code)
            layouts.add(code)

    return {
        "styles": styles,
        "layouts": layouts,
        "colors": colors,
        "tones": tones,
        "all": styles | layouts | colors | tones,
    }


def _rebuild_recipe_dict(d: dict[str, Any], catalog_codes: dict[str, set[str]] | None = None) -> dict[str, Any]:
    """Rebuild a recipe or card dict by strictly validating and copying typed fields only (H1, J1-J3).
    - J1/J2: Does NOT output moods, whitespace, or references at all (stripped entirely).
    - J3: Style, layout, color, tone IDs must exist in the real catalog codes set; invalid/non-catalog dropped.
    """
    if catalog_codes is None:
        catalog_codes = get_valid_catalog_codes()
    valid_styles = catalog_codes["styles"]
    valid_layouts = catalog_codes["layouts"]
    valid_colors = catalog_codes["colors"]
    valid_tones = catalog_codes["tones"]
    valid_all = catalog_codes["all"]

    out: dict[str, Any] = {}

    raw_id = d.get("id")
    if isinstance(raw_id, str) and _RECIPE_CODE_PATTERN.fullmatch(raw_id.strip()):
        clean_id = raw_id.strip()
        if clean_id.upper() in valid_all or re.fullmatch(r"^(?:rcp|card)[-_][A-Za-z0-9_-]{1,32}$", clean_id, re.IGNORECASE):
            out["id"] = clean_id

    raw_kind = d.get("kind")
    if raw_kind in ("single", "batch", "article_card"):
        out["kind"] = raw_kind

    raw_styles = (
        d.get("styleIds")
        if d.get("styleIds") is not None
        else (d.get("styles") if d.get("styles") is not None else d.get("style_ids"))
    )
    if isinstance(raw_styles, list):
        clean_styles = []
        for s in raw_styles:
            if isinstance(s, str) and _RECIPE_CODE_PATTERN.fullmatch(s.strip()):
                clean_s = s.strip()
                if clean_s.upper() in valid_styles or clean_s.upper() in valid_all:
                    clean_styles.append(clean_s)
        out["styleIds"] = clean_styles
    elif isinstance(raw_styles, str) and _RECIPE_CODE_PATTERN.fullmatch(raw_styles.strip()):
        clean_s = raw_styles.strip()
        if clean_s.upper() in valid_styles or clean_s.upper() in valid_all:
            out["styleIds"] = [clean_s]

    raw_layout = (
        d.get("layoutId")
        if d.get("layoutId") is not None
        else (
            d.get("layout_id")
            if d.get("layout_id") is not None
            else (d.get("layout") if d.get("layout") is not None else d.get("layout_code"))
        )
    )
    if isinstance(raw_layout, str) and _RECIPE_CODE_PATTERN.fullmatch(raw_layout.strip()):
        clean_l = raw_layout.strip()
        if clean_l.upper() in valid_layouts or clean_l.upper() in valid_all:
            out["layoutId"] = clean_l

    raw_colors = (
        d.get("colors")
        if d.get("colors") is not None
        else (d.get("color") if d.get("color") is not None else d.get("color_code"))
    )
    if isinstance(raw_colors, list):
        clean_colors = []
        for c in raw_colors:
            if isinstance(c, str) and _RECIPE_COLOR_PATTERN.fullmatch(c.strip()):
                clean_c = c.strip()
                if clean_c.upper() in valid_colors:
                    clean_colors.append(clean_c)
        out["colors"] = clean_colors
    elif isinstance(raw_colors, str) and _RECIPE_COLOR_PATTERN.fullmatch(raw_colors.strip()):
        clean_c = raw_colors.strip()
        if clean_c.upper() in valid_colors:
            out["colors"] = [clean_c]

    raw_tones = (
        d.get("tones")
        if d.get("tones") is not None
        else (d.get("tone") if d.get("tone") is not None else d.get("tone_code"))
    )
    if isinstance(raw_tones, list):
        clean_tones = []
        for t in raw_tones:
            if isinstance(t, str) and _RECIPE_CODE_PATTERN.fullmatch(t.strip()):
                clean_t = t.strip()
                if clean_t.upper() in valid_tones:
                    clean_tones.append(clean_t)
        out["tones"] = clean_tones
    elif isinstance(raw_tones, str) and _RECIPE_CODE_PATTERN.fullmatch(raw_tones.strip()):
        clean_t = raw_tones.strip()
        if clean_t.upper() in valid_tones:
            out["tones"] = [clean_t]

    # J1: moods and whitespace are entirely omitted from output for masked recipes.

    raw_ratio = d.get("ratio")
    if isinstance(raw_ratio, str) and _RECIPE_RATIO_PATTERN.fullmatch(raw_ratio.strip()):
        out["ratio"] = raw_ratio.strip()

    raw_mode = d.get("mode")
    if isinstance(raw_mode, str) and _RECIPE_CODE_PATTERN.fullmatch(raw_mode.strip()):
        clean_mode = raw_mode.strip()
        if clean_mode in ("pure", "graphic-text", "poster", "article-illust", "article-cover", "photo"):
            out["mode"] = clean_mode

    for cnt_key in ("cardCount", "totalCards", "count", "revision"):
        raw_cnt = d.get(cnt_key)
        if isinstance(raw_cnt, int) and not isinstance(raw_cnt, bool):
            out[cnt_key] = raw_cnt

    raw_cards = d.get("cards")
    if isinstance(raw_cards, list):
        clean_cards = []
        for c in raw_cards:
            if isinstance(c, dict):
                clean_cards.append(_rebuild_recipe_dict(c, catalog_codes=catalog_codes))
        out["cards"] = clean_cards

    raw_sc = d.get("sharedCard")
    if isinstance(raw_sc, dict):
        out["sharedCard"] = _rebuild_recipe_dict(raw_sc, catalog_codes=catalog_codes)

    # J2: references and refImages are entirely omitted from output for masked recipes.

    out["prompt"] = ""
    out["promptMasked"] = True
    return out


KNOWN_SKILL_INSTRUCTION_RE = re.compile(
    r"【\s*如果主题直白包含画面元素那就按主题出图[，,]\s*文案由你来升华[，,]\s*但是不要直接描述画面[。.]\s*"
    r"如果主题比较概念化[，,]\s*那么文案和主题尽量保持一致[，,]\s*"
    r"如果文案较长由你提炼[，,]\s*由你先设计画面隐喻[（(]人类和非人类都行[）)]\s*再出图\s*[。.]\s*"
    r"文字参与构图[，,]\s*图文一体\s*】"
)


def filter_display_prompt(text: str | None) -> str:
    """Filter out known skill instruction blocks for presentation/copy/summary without mutating stored prompts."""
    if not text:
        return ""
    cleaned = KNOWN_SKILL_INSTRUCTION_RE.sub("", str(text))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def mask_recipe_data(data: Any, conn: PgConnection | None = None) -> dict[str, Any]:
    """Rebuild masked recipe from typed fields only; drop all free-text fields and non-dict shapes (H1, J1-J3)."""
    if not isinstance(data, dict):
        return {"prompt": "", "promptMasked": True}
    catalog_codes = get_valid_catalog_codes(conn=conn)
    return _rebuild_recipe_dict(data, catalog_codes=catalog_codes)


def get_generation_visible_prompt(row: dict[str, Any] | None) -> tuple[str, bool]:
    """Return (visible_prompt, prompt_masked) for a studio_generations row.

    Reads never scan for secrets.
    If visible_prompt is NOT NULL -> return it (with promptMasked when prompt_masked == 1).
    If visible_prompt is NULL -> return ('', True) [fail-closed].
    """
    if row is None:
        return "", False
    has_col = "visible_prompt" in row.keys() if hasattr(row, "keys") else ("visible_prompt" in row)
    if has_col:
        vis = row["visible_prompt"]
        if vis is not None:
            has_mask = "prompt_masked" in row.keys() if hasattr(row, "keys") else ("prompt_masked" in row)
            masked = bool(row["prompt_masked"]) if has_mask else False
            return str(vis), masked
    # NULL or column missing -> fail closed
    return "", True


def get_work_client_prompt(row: dict[str, Any] | None, is_admin_route: bool = False) -> tuple[str, bool]:
    """Return (prompt, prompt_masked) for a works row.

    Reads never scan for secrets.
    If is_admin_route: returns stored prompt, False.
    Otherwise:
      If prompt_has_secret == 0: returns stored prompt, False.
      If prompt_has_secret in (1, None) or missing: returns ('', True) [fail-closed].
    """
    if row is None:
        return "", False
    stored = str(row["prompt"] or "") if ("prompt" in row.keys() if hasattr(row, "keys") else "prompt" in row) else ""
    if is_admin_route:
        return stored, False
    has_col = "prompt_has_secret" in row.keys() if hasattr(row, "keys") else ("prompt_has_secret" in row)
    if has_col:
        flag = row["prompt_has_secret"]
        if flag == 0:
            return stored, False
    # Flag is 1, NULL, or column missing -> fail closed
    return "", True


def get_topic_client_recipe_json(
    row: dict[str, Any] | None,
    is_admin_route: bool = False,
    conn: PgConnection | None = None,
) -> tuple[dict | list | None, bool]:
    """Return (recipe_data, prompt_masked) for a forum_topics row.

    Reads never scan for secrets.
    If recipe_json is empty: returns (None, False).
    If is_admin_route: returns parsed recipe, False.
    If recipe_has_secret == 0: returns parsed recipe, False.
    If recipe_has_secret in (1, None): masks prompt and free-text fields (G5, J1-J3), returns (recipe, True).
    """
    if row is None:
        return None, False
    has_col = "recipe_json" in row.keys() if hasattr(row, "keys") else ("recipe_json" in row)
    raw = row["recipe_json"] if has_col else None
    if not raw:
        return None, False
    try:
        recipe = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None, False
    if is_admin_route:
        return recipe, False
    has_flag = "recipe_has_secret" in row.keys() if hasattr(row, "keys") else ("recipe_has_secret" in row)
    flag = row["recipe_has_secret"] if has_flag else None
    if flag == 0:
        return recipe, False
    # Flag is 1 or NULL: keep only structure, mask all free-text fields
    return mask_recipe_data(recipe, conn=conn), True


def sanitize_items_json_for_client(items: Any, visible_prompt: str, was_masked: bool) -> list[Any]:
    """Ensure all client-facing items in items_json derive prompt strictly from the row's visible prompt.
    Preserves string URLs as strings to keep polling and replay images compatible (G12).
    """
    if not isinstance(items, list):
        return []
    cleaned_items = []
    for it in items:
        if isinstance(it, dict):
            it_copy = dict(it)
            it_copy["prompt"] = visible_prompt
            if was_masked:
                it_copy["promptMasked"] = True
            cleaned_items.append(it_copy)
        elif isinstance(it, str):
            cleaned_items.append(it)
        else:
            cleaned_items.append(it)
    return cleaned_items


def sanitize_prompt_for_client(prompt: str, conn: PgConnection | None = None) -> tuple[str, bool]:
    """Compatibility adapter: returns ('', True) if text contains secret, else (prompt, False)."""
    if not prompt or not isinstance(prompt, str):
        return "", False
    try:
        if check_text_has_secret(prompt, conn):
            return "", True
    except Exception:
        return "", True
    return prompt, False


def _resolve_generation_visible_prompt(row: dict[str, Any], conn: PgConnection | None = None) -> tuple[str, bool]:
    """Compatibility adapter for get_generation_visible_prompt."""
    return get_generation_visible_prompt(row)


def _strip_injection_suffix_only(raw_p: str, secrets: list[str]) -> str:
    """Strip only the exact trailing injected notes suffix; never remove secrets from middle of user text (G10, H7).
    Matches only "\n\n" + s at the very end. Never strips single newline or mid-text.
    """
    if not raw_p:
        return ""
    cleaned = raw_p
    changed = True
    while changed:
        changed = False
        for s in secrets:
            if not s:
                continue
            suffix1 = "\n\n" + s
            if cleaned.endswith(suffix1):
                cleaned = cleaned[:-len(suffix1)].rstrip()
                changed = True
                break
    return cleaned


def run_blackbox_backfill(db: Database, force: bool = False) -> dict[str, int]:
    """Batched, idempotent backfill for legacy rows without scanning at read time.
    Processes in batches of 200 rows with LIMIT queries and conditional writes (G3, G11).
    Loads secrets once per backfill round (H8).
    Persists scanned secrets hash in site_settings only if entirely error-free (G2, H2).
    Rescans generation rows when secrets set changes (H5).
    """
    global _LAST_SCANNED_SECRETS_HASH
    conn = db.get_conn()
    try:
        vhash, secrets, windows = get_secrets_cache(conn, force=True)
    except Exception:
        logger.warning("run_blackbox_backfill aborted: failed to query catalog secrets (fail-closed, G1)", exc_info=True)
        return {"generations": 0, "works": 0, "topics": 0}

    preloaded = (vhash, secrets, windows)

    # Check persisted hash from site_settings (G2)
    try:
        st_row = conn.execute("SELECT value_json FROM site_settings WHERE key = 'blackbox_secrets_hash'").fetchone()
        stored_hash = ""
        if st_row and st_row["value_json"]:
            try:
                pj = json.loads(st_row["value_json"])
                stored_hash = pj.get("hash") if isinstance(pj, dict) else str(pj)
            except Exception:
                pass
        if stored_hash != vhash:
            force = True
    except Exception:
        pass

    counts = {"generations": 0, "works": 0, "topics": 0}
    BATCH_SIZE = 200
    has_errors = False

    # 1. Backfill studio_generations:
    # If force: rescan ALL generation rows (H5)
    # If not force: scan rows where visible_prompt IS NULL
    last_id = ""
    while True:
        if force:
            gen_sql = (
                "SELECT id, prompt, visible_prompt, prompt_masked FROM studio_generations WHERE id > ? ORDER BY id ASC LIMIT ?"
            )
        else:
            gen_sql = (
                "SELECT id, prompt, visible_prompt, prompt_masked FROM studio_generations WHERE visible_prompt IS NULL AND id > ? ORDER BY id ASC LIMIT ?"
            )
        gen_rows = conn.execute(gen_sql, (last_id, BATCH_SIZE)).fetchall()
        if not gen_rows:
            break
        last_id = gen_rows[-1]["id"]
        gen_updates = []
        for row in gen_rows:
            gid = row["id"]
            raw_p = row["prompt"] or ""
            curr_vis = row["visible_prompt"]
            curr_masked = row["prompt_masked"]
            try:
                if curr_vis is None:
                    # Legacy or pending generation:
                    if not check_text_has_secret(raw_p, conn, preloaded=preloaded):
                        vis = raw_p
                        masked = 0
                    else:
                        cleaned = _strip_injection_suffix_only(raw_p, secrets)
                        if cleaned and not check_text_has_secret(cleaned, conn, preloaded=preloaded):
                            vis = cleaned
                            masked = 0
                        else:
                            vis = ""
                            masked = 1
                    gen_updates.append((vis, masked, gid, raw_p))
                else:
                    # Row already has visible_prompt: check if secret set change impacts it (H5)
                    if curr_vis and check_text_has_secret(curr_vis, conn, preloaded=preloaded):
                        # Masked because visible prompt contains secret
                        vis = ""
                        masked = 1
                        gen_updates.append((vis, masked, gid, raw_p))
                    elif curr_masked == 0 and check_text_has_secret(raw_p, conn, preloaded=preloaded):
                        # Row was not masked, but prompt contains secret (e.g. newly added secret)
                        cleaned = _strip_injection_suffix_only(raw_p, secrets)
                        if cleaned and not check_text_has_secret(cleaned, conn, preloaded=preloaded):
                            vis = cleaned
                            masked = 0
                        else:
                            vis = ""
                            masked = 1
                        if vis != curr_vis or masked != curr_masked:
                            gen_updates.append((vis, masked, gid, raw_p))
                    elif curr_masked == 1:
                        # Row was previously masked: check if secrets were removed and row is now clean
                        if not check_text_has_secret(raw_p, conn, preloaded=preloaded):
                            vis = raw_p
                            masked = 0
                            gen_updates.append((vis, masked, gid, raw_p))
                        else:
                            cleaned = _strip_injection_suffix_only(raw_p, secrets)
                            if cleaned and not check_text_has_secret(cleaned, conn, preloaded=preloaded):
                                vis = cleaned
                                masked = 0
                                gen_updates.append((vis, masked, gid, raw_p))
            except Exception:
                logger.warning("run_blackbox_backfill generation scan failed for id=%s", gid, exc_info=True)
                has_errors = True
                continue

        if gen_updates:
            try:
                with db.transaction() as tx:
                    tx.executemany(
                        "UPDATE studio_generations SET visible_prompt = ?, prompt_masked = ? WHERE id = ? AND COALESCE(prompt, '') = ?",
                        gen_updates,
                    )
                counts["generations"] += len(gen_updates)
            except Exception:
                logger.warning("run_blackbox_backfill generation batch update failed (%d rows)", len(gen_updates), exc_info=True)
                has_errors = True

    # 2. Backfill works where prompt_has_secret IS NULL (or all if force)
    last_wid = ""
    while True:
        if force:
            work_sql = "SELECT id, prompt, subject FROM works WHERE id > ? ORDER BY id ASC LIMIT ?"
            work_rows = conn.execute(work_sql, (last_wid, BATCH_SIZE)).fetchall()
        else:
            work_sql = "SELECT id, prompt, subject FROM works WHERE prompt_has_secret IS NULL AND id > ? ORDER BY id ASC LIMIT ?"
            work_rows = conn.execute(work_sql, (last_wid, BATCH_SIZE)).fetchall()
        if not work_rows:
            break
        last_wid = work_rows[-1]["id"]
        work_updates = []
        for row in work_rows:
            wid = row["id"]
            raw_p = row["prompt"] or ""
            raw_s = (row["subject"] if "subject" in row.keys() else "") or ""
            try:
                has_sec = 1 if (check_text_has_secret(raw_p, conn, preloaded=preloaded) or check_text_has_secret(raw_s, conn, preloaded=preloaded)) else 0
                work_updates.append((has_sec, wid, raw_p))
            except Exception:
                logger.warning("run_blackbox_backfill work scan failed for id=%s", wid, exc_info=True)
                has_errors = True
                continue

        if work_updates:
            try:
                with db.transaction() as tx:
                    tx.executemany("UPDATE works SET prompt_has_secret = ? WHERE id = ? AND COALESCE(prompt, '') = ?", work_updates)
                counts["works"] += len(work_updates)
            except Exception:
                logger.warning("run_blackbox_backfill work batch update failed (%d rows)", len(work_updates), exc_info=True)
                has_errors = True

    # 3. Backfill forum_topics where recipe_has_secret IS NULL (or all if force)
    last_tid = ""
    while True:
        if force:
            topic_sql = "SELECT id, recipe_json FROM forum_topics WHERE id > ? ORDER BY id ASC LIMIT ?"
            topic_rows = conn.execute(topic_sql, (last_tid, BATCH_SIZE)).fetchall()
        else:
            topic_sql = "SELECT id, recipe_json FROM forum_topics WHERE recipe_has_secret IS NULL AND id > ? ORDER BY id ASC LIMIT ?"
            topic_rows = conn.execute(topic_sql, (last_tid, BATCH_SIZE)).fetchall()
        if not topic_rows:
            break
        last_tid = topic_rows[-1]["id"]
        topic_updates = []
        for row in topic_rows:
            tid = row["id"]
            raw_rj = row["recipe_json"] or ""
            try:
                if raw_rj:
                    parsed_rj = json.loads(raw_rj) if isinstance(raw_rj, str) else raw_rj
                    has_sec = 1 if check_obj_has_secret(parsed_rj, conn, preloaded=preloaded) else 0
                else:
                    has_sec = 0
                topic_updates.append((has_sec, tid, raw_rj))
            except Exception:
                logger.warning("run_blackbox_backfill topic scan failed for id=%s", tid, exc_info=True)
                has_errors = True
                continue

        if topic_updates:
            try:
                with db.transaction() as tx:
                    tx.executemany("UPDATE forum_topics SET recipe_has_secret = ? WHERE id = ? AND COALESCE(recipe_json, '') = ?", topic_updates)
                counts["topics"] += len(topic_updates)
            except Exception:
                logger.warning("run_blackbox_backfill topic batch update failed (%d rows)", len(topic_updates), exc_info=True)
                has_errors = True

    # Persist the scanned hash in site_settings only if no errors occurred (G2, H2)
    if not has_errors:
        now_iso = utc_now_iso()
        try:
            with db.transaction() as tx:
                tx.execute(
                    """
                    INSERT INTO site_settings (key, value_json, updated_by, updated_at)
                    VALUES ('blackbox_secrets_hash', ?, 'system', ?)
                    ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
                    """,
                    (json.dumps({"hash": vhash}), now_iso),
                )
            _LAST_SCANNED_SECRETS_HASH = vhash
        except Exception:
            logger.warning("Failed to persist blackbox_secrets_hash to site_settings", exc_info=True)
    else:
        logger.warning("run_blackbox_backfill completed with errors; scan hash NOT persisted so next run will rescan (H2)")

    return counts


def start_blackbox_backfill(db: Database) -> threading.Thread:
    """Launch backfill in background thread to never block startup."""
    def _worker():
        try:
            run_blackbox_backfill(db)
        except Exception:
            logger.warning("Blackbox backfill worker encountered error", exc_info=True)
    t = threading.Thread(target=_worker, name="blackbox-backfill", daemon=True)
    t.start()
    return t


def _serialize_work(
    row: dict[str, Any],
    comments_by_work: dict[str, list[dict[str, Any]]],
    unlocked_set: set[str],
    current_user: dict[str, Any] | None,
    conn: PgConnection | None = None,
) -> dict[str, Any]:
    wid = row["id"]
    price = 0

    full_prompt, was_masked = get_work_client_prompt(row, is_admin_route=False)
    try:
        raw_subject = str(row["subject"] or "")
    except (KeyError, IndexError):
        raw_subject = ""

    if not was_masked:
        safe_prompt = full_prompt
        safe_subject = raw_subject
    else:
        safe_prompt = ""
        safe_subject = ""

    try:
        stamps = json.loads(row["stamp_counts_json"] or "{}")
    except Exception:
        stamps = {}

    row_keys = row.keys() if hasattr(row, "keys") else row
    cover_url = ""
    if conn is not None and "cover_media_id" in row_keys and row["cover_media_id"]:
        cover = conn.execute(
            "SELECT storage_key FROM media_assets WHERE id=?",
            (row["cover_media_id"],),
        ).fetchone()
        if cover:
            cover_url = str(cover["storage_key"] or "")
    batch_id = row["batch_id"] if "batch_id" in row_keys else None
    batch_total = int(row["batch_total"]) if "batch_total" in row_keys and row["batch_total"] is not None else 1
    batch_index = int(row["batch_rank"]) if "batch_rank" in row_keys and row["batch_rank"] is not None else (
        int(row["batch_index"]) if "batch_index" in row_keys and row["batch_index"] is not None else 1
    )

    return {
        "id": wid,
        "title": row["title"],
        "author": row["author_username"],
        "authorName": row["author_name"],
        "createdAt": row["created_label"] or format_relative_cn(int(row["published_at_ms"])),
        "isNewRelease": is_new_release_active(row["published_at_ms"]),
        "featured": bool(row["featured"]),
        "publishedAtMs": int(row["published_at_ms"]),
        "cheers": int(row["cheers"]),
        "images": json.loads(row["images_json"] or "[]"),
        "coverUrl": cover_url,
        "styles": json.loads(row["styles_json"] or "[]"),
        "layout": row["layout_code"] or None,
        "sc021Type": row["sc021_type"] or "",
        "color": row["color_code"] or "C-15",
        "tone": row["tone_code"] or "T-01",
        "ratio": row["ratio"] or "3:4",
        "mode": row["mode"] or "graphic-text",
        "shootType": row["shoot_type"] or "",
        "mood": row["mood"] or "治愈",
        "price": price,
        "likes": int(row["likes"]),
        "favorites": int(row["favorites"]),
        "forks": int(row["forks"]),
        "tips": int(row["tips"]),
        "views": int(row["views"]),
        "stampCounts": stamps,
        "prompt": safe_prompt,
        "subject": safe_subject,
        "promptMasked": bool(was_masked),
        "reproducible": bool(str(row["prompt"] or "").strip()),
        "notes": row["notes"] or "",
        "comments": comments_by_work.get(wid, []),
        "batchId": batch_id,
        "batchTotal": batch_total,
        "batchIndex": batch_index,
    }


def _serialize_topic(
    row: dict[str, Any],
    replies_by_topic: dict[str, list[dict[str, Any]]],
    unlocked_set: set[str],
    current_user: dict[str, Any] | None,
    conn: PgConnection | None = None,
    tips_by_topic: dict[str, int] | None = None,
) -> dict[str, Any]:
    tid = row["id"]
    price = int(row["price"] or 0)
    is_staff = bool(current_user and current_user.get("role") in ("admin", "operator", "reviewer"))
    is_author = bool(current_user and current_user.get("username") == row["author_username"])
    is_unlocked = price <= 0 or (tid in unlocked_set) or is_author or is_staff

    recipe, was_masked = get_topic_client_recipe_json(row, is_admin_route=False, conn=conn)
    shared_card = None
    if isinstance(recipe, dict) and "sharedCard" in recipe:
        shared_card = recipe["sharedCard"]

    tips = 0
    if tips_by_topic is not None:
        tips = int(tips_by_topic.get(tid, 0))
    elif conn is not None:
        try:
            row_tip = conn.execute(
                "SELECT COALESCE(SUM(delta), 0) AS total FROM ledgers WHERE kind = 'tip_in' AND ref_type = 'topic' AND ref_id = ?",
                (tid,),
            ).fetchone()
            tips = int(row_tip["total"]) if row_tip else 0
        except Exception:
            tips = 0

    return {
        "id": tid,
        "category": row["category"],
        "categoryLabel": row["category_label"],
        "pinned": bool(row["pinned"]),
        "featured": bool(row["featured"]),
        "title": row["title"],
        "author": row["author_username"],
        "authorName": row["author_name"],
        "createdAt": row["created_label"] or format_relative_cn(int(row["published_at_ms"])),
        "publishedAtMs": int(row["published_at_ms"]),
        "views": int(row["views"]),
        "likes": int(row["likes"]),
        "favorites": int(row["favorites"]),
        "tips": tips,
        "price": price,
        "bounty": int(row["bounty"]),
        "bountyStatus": row["bounty_status"],
        "solved": bool(row["solved"]),
        "acceptedReplyId": row["accepted_reply_id"] or "",
        "images": json.loads(row["images_json"] or "[]"),
        "styles": json.loads(row["styles_json"] or "[]"),
        "layout": row["layout_code"] or None,
        "workId": row["work_id"] or None,
        "sharedCard": shared_card,
        "recipe": recipe,
        "summary": filter_display_prompt(row["summary"]),
        "lockedBody": (row["locked_body"] or "") if is_unlocked else "",
        "replies": replies_by_topic.get(tid, []),
    }


def compute_public_asset_counts_and_creators(conn: PgConnection) -> tuple[dict[str, int], int, int, list[dict[str, Any]]]:
    """Compute exact counts per style/layout and creator honor summaries WITHOUT exposing any work images or prompts."""
    asset_counts: dict[str, int] = {}
    creator_stats: dict[str, dict[str, Any]] = {}

    users_map = {
        r["username"]: {"display_name": r["display_name"], "honor_override": r["honor_override"],
                         "avatar_url": r["avatar_url"]}
        for r in conn.execute("SELECT username, display_name, honor_override, avatar_url FROM users WHERE status = 'active'").fetchall()
    }

    def ensure_rec(uname: str, aname: str) -> dict[str, Any]:
        rec = creator_stats.get(uname)
        if not rec:
            uinfo = users_map.get(uname, {})
            clean_name = uinfo.get("display_name") or aname or uname
            rec = {
                "username": uname,
                "authorName": clean_name,
                "avatarUrl": uinfo.get("avatar_url") or "/assets/avatar-default.svg",
                "stylesCount": 0,
                "layoutsCount": 0,
                "worksCount": 0,
                "topicsCount": 0,
                "totalCheers": 0,
                "totalFavorites": 0,
                "totalForks": 0,
                "hasFresh": False,
                "honorOverride": uinfo.get("honor_override"),
            }
            creator_stats[uname] = rec
        return rec

    asset_filter, asset_ids = _seed_filter("code", "assets")
    work_filter, work_ids = _seed_filter("id", "works")
    topic_filter, topic_ids = _seed_filter("id", "topics")
    for r in conn.execute(
        f"SELECT * FROM catalog_assets WHERE status = 'published' AND source_type = 'community' AND {asset_filter}",
        asset_ids,
    ).fetchall():
        rec = ensure_rec(r["author_username"], r["author_name"])
        if r["kind"] == "layout":
            rec["layoutsCount"] += 1
        else:
            rec["stylesCount"] += 1
        rec["totalCheers"] += int(r["cheers"] or 0)
        if is_new_release_active(r["published_at_ms"]):
            rec["hasFresh"] = True

    work_rows = conn.execute(
        f"SELECT author_username, author_name, styles_json, layout_code, cheers, likes, favorites, forks, is_new_release, published_at_ms FROM works WHERE status = 'published' AND images_json IS NOT NULL AND TRIM(images_json) NOT IN ('', '[]', 'null') AND (images_json IS JSON ARRAY) AND {work_filter}",
        work_ids,
    ).fetchall()
    total_works = len(work_rows)
    total_cheers = 0

    for w in work_rows:
        styles = json.loads(w["styles_json"] or "[]")
        for sid in styles:
            if sid:
                asset_counts[sid] = asset_counts.get(sid, 0) + 1
        lcode = (w["layout_code"] or "").strip()
        if lcode:
            asset_counts[lcode] = asset_counts.get(lcode, 0) + 1

        ch = int(w["cheers"] or 0)
        total_cheers += ch
        rec = ensure_rec(w["author_username"], w["author_name"])
        rec["worksCount"] += 1
        rec["totalCheers"] += ch
        rec["totalFavorites"] += int(w["favorites"] or 0)
        rec["totalForks"] += int(w["forks"] or 0)
        if is_new_release_active(w["published_at_ms"]):
            rec["hasFresh"] = True

    from .resource_discussions import topic_visibility_sql
    reply_filter, reply_ids = _seed_filter("r.id", "forum_replies")
    vis_filter = topic_visibility_sql(reply_filter=reply_filter, admin=False)
    for tp in conn.execute(
        f"SELECT author_username, author_name FROM forum_topics WHERE status = 'published' AND TRIM(author_username) <> '' AND {topic_filter} AND {vis_filter}",
        (*topic_ids, *reply_ids),
    ).fetchall():
        rec = ensure_rec(tp["author_username"], tp["author_name"])
        rec["topicsCount"] += 1

    return asset_counts, total_works, total_cheers, list(creator_stats.values())


def build_boot_payload(db: Database, current_user: dict[str, Any] | None) -> dict[str, Any]:
    conn = db.get_conn()
    settings = get_site_settings(conn)
    asset_counts, total_works_count, total_cheers_count, public_creators = compute_public_asset_counts_and_creators(conn)

    unlocked_set: set[str] = set()
    collections: dict[str, list[str]] = {"styles": [], "layouts": [], "works": [], "topics": [], "generations": []}
    cheered_ids: list[str] = []
    liked_ids: list[str] = []
    ledger_list: list[dict[str, Any]] = []
    wallet_info = {
        "balance": 0,
        "freeQuotaMax": int(settings.get("economy", {}).get("daily_free_quota", 3)),
        "freeQuotaRemaining": 0,
        "dailyCheckedIn": False,
        "locked": False,
    }

    if current_user:
        uid = int(current_user["id"])
        wallet_info = get_wallet_quota_state(conn, uid, settings)

        collection_filter, collection_ids = _seed_filter("target_id", "assets")
        collection_work_filter, collection_work_ids = _seed_filter("target_id", "works")
        collection_topic_filter, collection_topic_ids = _seed_filter("target_id", "topics")

        for r in conn.execute(
            f"""
            SELECT c.bucket, c.target_id
            FROM collections c
            WHERE c.user_id = ?
              AND (
                (c.bucket IN ('styles', 'layouts') AND {collection_filter})
                OR (c.bucket = 'works' AND {collection_work_filter})
                OR (c.bucket = 'topics' AND {collection_topic_filter})
              )
            ORDER BY c.created_at DESC
            """,
            (uid, *collection_ids, *collection_work_ids, *collection_topic_ids),
        ).fetchall():
            b = r["bucket"]
            if b in collections:
                collections[b].append(r["target_id"])

        unlock_filter, unlock_ids = _seed_filter("target_id", "works")
        asset_unlock_filter, asset_unlock_ids = _seed_filter("target_id", "assets")
        for r in conn.execute(
            f"SELECT target_id FROM unlocks WHERE user_id = ? AND status = 'settled' AND ((target_type = 'work' AND {unlock_filter}) OR (target_type = 'asset' AND {asset_unlock_filter}) OR target_type NOT IN ('work', 'asset'))",
            (uid, *unlock_ids, *asset_unlock_ids),
        ).fetchall():
            unlocked_set.add(r["target_id"])

        # Own works, topics, and community assets are always unlocked for the author
        uname = current_user["username"]
        own_work_filter, own_work_ids = _seed_filter("id", "works")
        own_topic_filter, own_topic_ids = _seed_filter("id", "topics")
        own_asset_filter, own_asset_ids = _seed_filter("code", "assets")
        for r in conn.execute(
            f"SELECT id FROM works WHERE author_username = ? AND {own_work_filter}",
            (uname, *own_work_ids),
        ).fetchall():
            unlocked_set.add(r["id"])
        for r in conn.execute(
            f"SELECT id FROM forum_topics WHERE author_username = ? AND {own_topic_filter}",
            (uname, *own_topic_ids),
        ).fetchall():
            unlocked_set.add(r["id"])
        for r in conn.execute(
            f"SELECT code FROM catalog_assets WHERE author_username = ? AND {own_asset_filter}",
            (uname, *own_asset_ids),
        ).fetchall():
            unlocked_set.add(r["code"])

        interaction_asset_filter, interaction_asset_ids = _seed_filter("target_id", "assets")
        interaction_work_filter, interaction_work_ids = _seed_filter("target_id", "works")
        interaction_topic_filter, interaction_topic_ids = _seed_filter("target_id", "topics")
        for r in conn.execute(
            f"""
            SELECT i.target_type, i.target_id, i.stamp_label
            FROM interactions i
            WHERE i.user_id = ?
              AND (
                (i.target_type IN ('like_style', 'like_layout') AND {interaction_asset_filter})
                OR (i.target_type = 'like_work' AND {interaction_work_filter})
                OR (i.target_type = 'like_topic' AND {interaction_topic_filter})
                OR i.target_type NOT IN ('like_style', 'like_layout', 'like_work', 'like_topic')
              )
            """,
            (uid, *interaction_asset_ids, *interaction_work_ids, *interaction_topic_ids),
        ).fetchall():
            ttype = str(r["target_type"] or "")
            if ttype.startswith("like_"):
                liked_ids.append(f"{ttype[5:]}:{r['target_id']}")
            else:
                key = f"{r['target_id']}::{r['stamp_label']}" if r["stamp_label"] else r["target_id"]
                cheered_ids.append(key)

        ledger_filter, ledger_ids = _seed_filter("event_key", "ledger_events")
        for r in conn.execute(
            f"SELECT id, delta, reason, created_at FROM ledgers WHERE user_id = ? AND {ledger_filter} ORDER BY id DESC LIMIT 60",
            (uid, *ledger_ids),
        ).fetchall():
            ledger_list.append(
                {
                    "id": f"led_{r['id']}",
                    "time": format_short_time(r["created_at"]),
                    "reason": r["reason"],
                    "delta": int(r["delta"]),
                }
            )

    # Catalog overlays (exclusive + community + official overrides)
    catalog_filter, catalog_ids = _seed_filter("code", "assets")
    cat_rows = conn.execute(
        f"SELECT * FROM catalog_assets WHERE status = 'published' AND {catalog_filter} ORDER BY published_at_ms DESC",
        catalog_ids,
    ).fetchall()
    exclusive_resources = []
    community_resources = []
    official_overrides = []
    official_resources = []
    for r in cat_rows:
        ser = _serialize_catalog_asset(r, unlocked_set, current_user)
        if r["source_type"] == "exclusive":
            exclusive_resources.append(ser)
        elif r["source_type"] == "community":
            community_resources.append(ser)
        elif r["source_type"] == "official":
            official_resources.append(ser)
        else:
            official_overrides.append(ser)

    my_resources: list[dict[str, Any]] = []
    pending_resources: list[dict[str, Any]] = []
    if current_user:
        uid = int(current_user["id"])
        my_sub_rows = conn.execute(
            """
            SELECT s.target_id, s.kind, s.owner_username, s.status, v.payload_json
            FROM curation_submissions s
            JOIN curation_versions v ON v.submission_id = s.id AND v.revision = s.current_revision
            WHERE s.owner_user_id = ? AND s.status IN ('pending', 'changes_requested') AND s.kind IN ('style', 'layout')
            ORDER BY s.updated_at DESC
            """,
            (uid,),
        ).fetchall()
        for sr in my_sub_rows:
            try:
                p = json.loads(sr["payload_json"] or "{}")
            except Exception:
                p = {}
            cover = p.get("cover") or p.get("image") or ""
            imgs = p.get("images") or []
            if not cover and imgs:
                f = imgs[0]
                cover = f.get("url", "") if isinstance(f, dict) else str(f or "")
            my_resources.append({
                "id": sr["target_id"],
                "code": sr["target_id"],
                "name": p.get("name") or sr["target_id"],
                "kind": sr["kind"],
                "sourceType": "pending",
                "source": "pending",
                "status": sr["status"],
                "image": sanitize_media_url(cover),
                "cover": sanitize_media_url(cover),
                "description": p.get("description") or "",
                "definition": p.get("definition") or "",
                "unlockCost": 0,
                "author": sr["owner_username"],
                "authorName": current_user.get("display_name") or sr["owner_username"],
                "isMine": True,
                "canUse": True,
                "access": {
                    "canRead": True,
                    "canUse": True,
                    "hiddenBy": None,
                },
            })

        fav_codes = set(collections.get("styles", [])) | set(collections.get("layouts", []))
        my_codes = {r["code"] for r in my_resources}
        published_codes = {r["code"] for r in cat_rows}
        other_pending_codes = list(fav_codes - my_codes - published_codes)
        if other_pending_codes:
            placeholders = ",".join("?" for _ in other_pending_codes)
            other_sub_rows = conn.execute(
                f"""
                SELECT s.target_id, s.kind, s.owner_username, s.status, v.payload_json
                FROM curation_submissions s
                JOIN curation_versions v ON v.submission_id = s.id AND v.revision = s.current_revision
                WHERE (s.target_id IN ({placeholders}) OR UPPER(s.target_id) IN ({placeholders}))
                  AND s.status IN ('pending', 'changes_requested') AND s.kind IN ('style', 'layout')
                ORDER BY s.updated_at DESC
                """,
                (*other_pending_codes, *other_pending_codes),
            ).fetchall()
            seen_other = set()
            for sr in other_sub_rows:
                tid = sr["target_id"]
                if tid in seen_other:
                    continue
                seen_other.add(tid)
                try:
                    p = json.loads(sr["payload_json"] or "{}")
                except Exception:
                    p = {}
                cover = p.get("cover") or p.get("image") or ""
                imgs = p.get("images") or []
                if not cover and imgs:
                    f = imgs[0]
                    cover = f.get("url", "") if isinstance(f, dict) else str(f or "")
                p_cost = int(p.get("unlock_cost") or p.get("unlockCost") or 0)
                is_staff = bool(current_user and current_user.get("role") in ("admin", "operator", "reviewer"))
                can_read = (p_cost <= 0) or is_staff
                pending_resources.append({
                    "id": tid,
                    "code": tid,
                    "name": p.get("name") or tid,
                    "kind": sr["kind"],
                    "sourceType": "pending",
                    "source": "pending",
                    "status": sr["status"],
                    "image": sanitize_media_url(cover),
                    "cover": sanitize_media_url(cover),
                    "description": p.get("description") or "",
                    "definition": (p.get("definition") or "") if can_read else None,
                    "unlockCost": p_cost,
                    "author": sr["owner_username"],
                    "authorName": sr["owner_username"],
                    "isMine": False,
                    "canUse": True,
                    "access": {
                        "canRead": can_read,
                        "canUse": True,
                        "hiddenBy": None if can_read else "pending",
                    },
                })

    # Forum topics & replies (publicly visible, paid lockedBody masked unless unlocked!)
    replies_by_topic: dict[str, list[dict[str, Any]]] = {}
    reply_filter, reply_ids = _seed_filter("id", "forum_replies")
    reply_topic_filter, reply_topic_ids = _seed_filter("topic_id", "topics")
    for rp in conn.execute(
        f"SELECT * FROM forum_replies WHERE status = 'published' AND {reply_filter} AND {reply_topic_filter} ORDER BY created_at ASC, id ASC",
        (*reply_ids, *reply_topic_ids),
    ).fetchall():
        replies_by_topic.setdefault(rp["topic_id"], []).append(
            {
                "id": rp["id"],
                "user": rp["author_username"],
                "name": rp["author_name"],
                "time": rp["time_label"] or format_short_time(rp["created_at"]),
                "text": rp["text"],
                "mountedStyle": rp["mounted_style"] or "",
                "mountedLayout": rp["mounted_layout"] or "",
                "likes": int(rp["likes"]),
                "accepted": bool(rp["accepted"]),
            }
        )

    from .resource_discussions import topic_visibility_sql
    topic_filter, topic_ids = _seed_filter("id", "topics")
    reply_seed_filter, reply_seed_ids = _seed_filter("r.id", "forum_replies")
    topic_vis_filter = topic_visibility_sql(reply_filter=reply_seed_filter, admin=False)
    topic_rows = conn.execute(
        f"SELECT * FROM forum_topics WHERE status = 'published' AND {topic_filter} AND {topic_vis_filter} ORDER BY pinned DESC, COALESCE(listed_at_ms, published_at_ms) DESC, id DESC",
        (*topic_ids, *reply_seed_ids),
    ).fetchall()
    try:
        tips_by_topic = {
            str(r["ref_id"]): int(r["total"] or 0)
            for r in conn.execute(
                "SELECT ref_id, COALESCE(SUM(delta), 0) AS total FROM ledgers WHERE kind = 'tip_in' AND ref_type = 'topic' GROUP BY ref_id"
            ).fetchall()
        }
    except Exception:
        tips_by_topic = {}
    topics_out = [_serialize_topic(r, replies_by_topic, unlocked_set, current_user, conn=conn, tips_by_topic=tips_by_topic) for r in topic_rows]

    # A work's discussion topic reports the work's counters.  Without this the
    # same piece shows one number in the square (works.likes) and another in the
    # forum (forum_topics.likes).  The topic's own columns stay untouched.
    work_primary_topic = {
        str(r["topic_id"]): str(r["target_id"])
        for r in conn.execute(
            "SELECT target_id, topic_id FROM curation_resource_topics WHERE kind = 'work'"
        ).fetchall()
    }
    if work_primary_topic:
        work_counters = {
            str(r["id"]): (int(r["likes"] or 0), int(r["favorites"] or 0), int(r["tips"] or 0))
            for r in conn.execute("SELECT id, likes, favorites, tips FROM works").fetchall()
        }
        for topic in topics_out:
            work_id = work_primary_topic.get(topic["id"])
            if not work_id:
                continue
            likes, favorites, w_tips = work_counters.get(work_id, (0, 0, 0))
            topic["likes"] = likes
            topic["favorites"] = favorites
            topic["tips"] = w_tips
            topic["workId"] = work_id

    # PUBLIC SEO-FRIENDLY WORKS SQUARE:
    # Published works are visible to both anonymous visitors & crawlers; paid prompts (price > 0) remain masked unless unlocked.
    comments_by_work: dict[str, list[dict[str, Any]]] = {}
    comment_filter, comment_ids = _seed_filter("id", "work_comments")
    comment_work_filter, comment_work_ids = _seed_filter("work_id", "works")
    for cm in conn.execute(
        f"SELECT * FROM work_comments WHERE status = 'published' AND {comment_filter} AND {comment_work_filter} ORDER BY created_at ASC, id ASC",
        (*comment_ids, *comment_work_ids),
    ).fetchall():
        comments_by_work.setdefault(cm["work_id"], []).append(
            {
                "id": cm["id"],
                "user": cm["author_username"],
                "name": cm["author_name"],
                "text": cm["text"],
                "time": cm["time_label"] or format_short_time(cm["created_at"]),
            }
        )
    work_filter, work_ids = _seed_filter("w.id", "works")
    work_rows = conn.execute(
        f"""
        SELECT w.* FROM works w
        WHERE w.status = 'published'
              AND w.images_json IS NOT NULL
              AND TRIM(w.images_json) NOT IN ('', '[]', 'null')
              AND (w.images_json IS JSON ARRAY)
              AND {work_filter}
        ORDER BY featured DESC, published_at_ms DESC, id DESC
        """,
        work_ids,
    ).fetchall()
    works_out: list[dict[str, Any]] = [_serialize_work(w, comments_by_work, unlocked_set, current_user, conn=conn) for w in work_rows]

    # Active Official Studio Presets
    preset_rows = conn.execute(
        "SELECT id, title, blueprint, scenario_badge, scenario_desc, sort_order FROM studio_workflows WHERE is_official_preset = 1 AND enabled = 1 ORDER BY sort_order ASC"
    ).fetchall()
    official_presets = [dict(r) for r in preset_rows]

    # Asset Comments, Seeded Baselines & Live Likes/Favorites for ALL Styles & Layouts
    asset_comments: dict[str, list[dict[str, Any]]] = {}
    asset_comment_filter, asset_comment_ids = _seed_filter("id", "asset_comments")
    asset_comment_asset_filter, asset_comment_asset_ids = _seed_filter("asset_code", "assets")
    for ac in conn.execute(
        f"SELECT * FROM asset_comments WHERE status = 'published' AND {asset_comment_filter} AND {asset_comment_asset_filter} ORDER BY created_at ASC, id ASC",
        (*asset_comment_ids, *asset_comment_asset_ids),
    ).fetchall():
        asset_comments.setdefault(ac["asset_code"], []).append(
            {
                "id": ac["id"],
                "user": ac["author_username"],
                "name": ac["author_name"],
                "text": ac["text"],
                "time": ac["time_label"] or format_short_time(ac["created_at"]),
            }
        )

    # ``asset_social_seeds`` is synthetic by construction: every row in it is a
    # fabricated baseline, independent of whether the code happens to be listed
    # in the demo seed registry.  In normal mode it must contribute nothing, so
    # running a demo seed once can never leak fake likes into a real library.
    asset_seed_metrics = {}
    if is_demo_mode():
        asset_seed_filter, asset_seed_ids = _seed_filter("asset_code", "assets")
        asset_seed_metrics = {
            r["asset_code"]: {"likes": int(r["base_likes"]), "favorites": int(r["base_favorites"])}
            for r in conn.execute(
                f"SELECT asset_code, base_likes, base_favorites FROM asset_social_seeds WHERE {asset_seed_filter}",
                asset_seed_ids,
            ).fetchall()
        }
    live_asset_filter, live_asset_ids = _seed_filter("target_id", "assets")
    asset_live_likes = {
        r["target_id"]: int(r["cnt"])
        for r in conn.execute(
            f"SELECT target_id, COUNT(*) AS cnt FROM interactions WHERE target_type IN ('like_style', 'like_layout') AND {live_asset_filter} GROUP BY target_id",
            live_asset_ids,
        ).fetchall()
    }
    asset_live_favorites = {
        r["target_id"]: int(r["cnt"])
        for r in conn.execute(
            f"SELECT target_id, COUNT(*) AS cnt FROM collections WHERE bucket IN ('styles', 'layouts') AND {live_asset_filter} GROUP BY target_id",
            live_asset_ids,
        ).fetchall()
    }

    # Active Forum Board Moderators (publicly displayed on boards & author badges)
    if is_demo_mode():
        moderator_seed_clause, moderator_seed_params = "1 = 1", ()
    else:
        seed_user_names = sorted(item.lower() for item in seed_ids("users"))
        moderator_seed_clause = f"LOWER(fm.username) NOT IN ({', '.join('?' for _ in seed_user_names)})"
        moderator_seed_params = tuple(seed_user_names)
    mod_rows = conn.execute(
        f"""
        SELECT fm.id, fm.user_id, fm.username, fm.category, fm.title, fm.note, fm.created_at,
               u.display_name, u.role
        FROM forum_moderators fm
        JOIN users u ON u.id = fm.user_id
        WHERE u.status = 'active' AND {moderator_seed_clause}
        ORDER BY CASE fm.category WHEN 'all' THEN 0 ELSE 1 END, fm.id ASC
        """,
        moderator_seed_params,
    ).fetchall()
    forum_moderators = [
        {
            "id": int(r["id"]),
            "userId": int(r["user_id"]),
            "username": r["username"],
            "displayName": r["display_name"],
            "userRole": r["role"],
            "category": r["category"],
            "categoryLabel": FORUM_BOARD_LABELS.get(r["category"], r["category"]),
            "shortBoardLabel": FORUM_BOARD_SHORT_LABELS.get(r["category"], r["category"]),
            "title": r["title"] or "版主",
            "note": r["note"] or "",
        }
        for r in mod_rows
    ]

    user_payload: dict[str, Any] = {
        "loggedIn": False,
        "username": "guest",
        "name": "未登录访客",
        "displayName": "未登录访客",
        "role": "guest",
        "managementRole": "none",
        "canAccessAdmin": False,
        "level": "访客",
        "inviteCode": "handraw",
        "moderatedBoards": [],
        "openReportsCount": 0,
        "managementCapabilities": {},
    }
    if current_user:
        pub_cnt = _count_user_published_items(conn, current_user["username"])
        honor = compute_honor_tier(pub_cnt, current_user.get("honor_override"))
        my_mod_boards = [m["category"] for m in forum_moderators if m["username"].lower() == current_user["username"].lower()]
        raw_u_role = str(current_user.get("role") or "user")
        u_role = "operator" if raw_u_role == "reviewer" else raw_u_role
        if u_role in ("admin", "operator"):
            mgmt_role = u_role
        elif my_mod_boards:
            mgmt_role = "moderator"
        else:
            mgmt_role = "none"

        report_filter, report_ids = _seed_filter("target_id", "reports")
        if mgmt_role in ("admin", "operator"):
            open_reports_count = int(
                conn.execute(f"SELECT COUNT(*) FROM reports WHERE status = 'open' AND {report_filter}", report_ids).fetchone()[0]
            )
        elif mgmt_role == "moderator":
            if "all" in my_mod_boards:
                open_reports_count = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM reports WHERE status = 'open' AND target_type IN ('topic', 'reply') AND {report_filter}",
                        report_ids,
                    ).fetchone()[0]
                )
            else:
                ph = ",".join("?" for _ in my_mod_boards)
                open_reports_count = int(conn.execute(
                    f"SELECT COUNT(*) FROM reports WHERE status = 'open' AND target_type IN ('topic', 'reply') AND ("
                    f"  ((target_type = 'topic' AND target_id IN (SELECT id FROM forum_topics WHERE category IN ({ph}))) "
                    f"  OR (target_type = 'reply' AND target_id IN (SELECT fr.id FROM forum_replies fr JOIN forum_topics ft ON ft.id = fr.topic_id WHERE ft.category IN ({ph}))))"
                    f" AND {report_filter}"
                    f")",
                    (*my_mod_boards, *my_mod_boards, *report_ids),
                ).fetchone()[0])
        else:
            open_reports_count = 0

        user_payload = {
            "loggedIn": True,
            "id": int(current_user["id"]),
            "username": current_user["username"],
            "name": current_user["display_name"],
            "displayName": current_user["display_name"],
            "avatarUrl": current_user.get("avatar_url") or "/assets/avatar-default.svg",
            "nicknameLocked": bool(current_user.get("nickname_locked", 1)),
            "nicknameNextChangeAt": 0,
            "email": current_user.get("email") or "",
            "bio": current_user.get("bio") or "",
            "role": u_role,
            "managementRole": mgmt_role,
            "canAccessAdmin": mgmt_role != "none",
            "level": honor["badge"],
            "inviteCode": current_user["invite_code"],
            "honorOverride": current_user.get("honor_override"),
            "moderatedBoards": my_mod_boards,
            "openReportsCount": open_reports_count,
            "managementCapabilities": {
                "canModerateContent": mgmt_role in ("admin", "operator"),
                "canModerateForum": mgmt_role in ("admin", "operator", "moderator"),
                "canDeleteGlobalContent": mgmt_role in ("admin", "operator"),
                "canFreezeUser": mgmt_role in ("admin", "operator"),
                "canManageRedeemCodes": mgmt_role in ("admin", "operator"),
                "canEditAnnouncement": mgmt_role in ("admin", "operator"),
                "canAdministerUsers": mgmt_role == "admin",
                "canViewBlackbox": mgmt_role == "admin",
                "canAdjustCredits": mgmt_role == "admin",
            },
            "apiKey": current_user.get("api_key") or "",
            "apiKeyMasked": (current_user["api_key"][:8] + "…" + current_user["api_key"][-4:]) if current_user.get("api_key") else "",
        }

    # Only send avatar URLs for members who appear in public content or
    # the current session; merely uploading an avatar must not disclose a
    # private/non-publishing account in the anonymous boot API.
    visible_avatar_users = {
        str(pc.get("username") or "") for pc in public_creators
    }
    visible_avatar_users.update(str(w.get("author") or "") for w in works_out)
    visible_avatar_users.update(str(t.get("author") or "") for t in topics_out)
    visible_avatar_users.update(str(c.get("author") or "") for c in community_resources)
    for work in works_out:
        visible_avatar_users.update(
            str(comment.get("user") or comment.get("author") or "")
            for comment in (work.get("comments") or []) if isinstance(comment, dict)
        )
    for topic in topics_out:
        visible_avatar_users.update(
            str(reply.get("user") or reply.get("author") or "")
            for reply in (topic.get("replies") or []) if isinstance(reply, dict)
        )
    if current_user:
        visible_avatar_users.add(str(current_user["username"]))

    from .economy import account_summary
    payload = {
        "version": 4,
        "pointPriceOptions": {r["kind"]:r["options_json"] for r in conn.execute("SELECT * FROM point_price_options").fetchall()},
        "serverBacked": True,
        "demoMode": is_demo_mode(),
        "loggedIn": bool(current_user),
        "user": user_payload,
        "economy": account_summary(conn,current_user["id"]) if current_user else None,
        "credits": wallet_info["balance"],
        "freeQuotaRemaining": wallet_info["freeQuotaRemaining"],
        "freeQuotaMax": wallet_info["freeQuotaMax"],
        "dailyCheckedIn": wallet_info["dailyCheckedIn"],
        "collections": collections,
        "unlockedIds": sorted(unlocked_set),
        "cheeredIds": cheered_ids,
        "likedIds": liked_ids,
        "works": works_out,
        "totalWorksCount": total_works_count,
        "totalCheersCount": total_cheers_count,
        "publicCreators": public_creators,
        # Show an avatar for creators who only comment or reply, too; do not
        # expose private emails, passwords or non-public profile fields.
        "creatorAvatars": {
            r["username"]: r["avatar_url"]
            for r in conn.execute(
                "SELECT username, avatar_url FROM users WHERE status='active' AND avatar_url!=''"
            ).fetchall()
            if r["username"] in visible_avatar_users
        },
        "topics": topics_out,
        "forumBoards": FORUM_BOARDS,
        "forumModerators": forum_moderators,
        "exclusiveResources": exclusive_resources,
        "communityResources": community_resources,
        "officialOverrides": official_overrides,
        "officialResources": official_resources,
        "myResources": my_resources,
        "pendingResources": pending_resources,
        "officialPresets": official_presets,
        "assetCounts": asset_counts,
        "assetComments": asset_comments,
        "assetSeedMetrics": asset_seed_metrics,
        "assetLiveLikes": asset_live_likes,
        "assetLiveFavorites": asset_live_favorites,
        "ledger": ledger_list,
        "siteSettings": {
            "announcement": settings.get("announcement", {}),
            "economy": settings.get("economy", {}),
            "forum": {
                "featured_sidebar_limit": max(1, min(5, int(settings.get("forum", {}).get("featured_sidebar_limit", 5)))),
            },
        },
    }


# ======================== USER INTERACTIONS & ATOMIC ECONOMY ========================

    from .resource_discussions import apply_boot
    from .curation import public_submissions, review_access
    payload=apply_boot(db,payload,current_user)
    grouped={}
    for item in public_submissions(db,[t['id'] for t in payload['topics']]):
        grouped.setdefault(item['topicId'],[]).append(item)
    for topic in payload['topics']:
        topic['submissions']=grouped.get(topic['id'],[])
    payload["billing"] = get_public_billing_summary()
    if current_user:
        payload['user']['reviewAccess']=review_access(db,current_user)
    return payload


def perform_daily_checkin(db: Database, user: dict[str, Any]) -> dict[str, Any]:
    uid = int(user["id"])
    today = local_today_str()
    now = utc_now_iso()
    with db.transaction() as tx:
        settings = get_site_settings(tx)
        w = tx.execute("SELECT checkin_date FROM wallets WHERE user_id=? FOR UPDATE",(uid,)).fetchone()
        if w and w["checkin_date"]==today:
            raise ServiceError("今日已签到")
        from .points import reward
        bonus=reward(tx,uid,"checkin",str(uid)+":"+today)
        tx.execute("UPDATE wallets SET checkin_date=?,updated_at=? WHERE user_id=?",(today,now,uid))
        new_bal=int(tx.execute("SELECT balance FROM wallets WHERE user_id=?",(uid,)).fetchone()[0])
        q_state=get_wallet_quota_state(tx,uid,settings)
    return {"ok": True, "bonus": bonus, "credits": new_bal, **q_state}


def redeem_code_for_user(db: Database, user: dict[str, Any], raw_code: str) -> dict[str, Any]:
    code = (raw_code or "").strip().upper()
    if not code:
        raise ServiceError("请输入积分兑换码")
    uid = int(user["id"])
    today = local_today_str()
    now = utc_now_iso()

    with db.transaction() as tx:
        rc = tx.execute("SELECT * FROM redeem_codes WHERE code = ?", (code,)).fetchone()
        if not rc or not int(rc["active"]):
            raise ServiceError("兑换码无效或已停用")
        if rc["expires_at"] and rc["expires_at"] < today:
            raise ServiceError("该兑换码已过期")
        if int(rc["used_count"]) >= int(rc["max_uses"]):
            raise ServiceError("该兑换码已被领完")
        used = tx.execute("SELECT 1 FROM redeem_code_uses WHERE code = ? AND user_id = ?", (code, uid)).fetchone()
        if used:
            raise ServiceError("你已经兑换过该礼券码啦")

        credits = int(rc["credits"])
        tx.execute("UPDATE redeem_codes SET used_count = used_count + 1 WHERE code = ?", (code,))
        tx.execute("INSERT INTO redeem_code_uses (code, user_id, used_at) VALUES (?, ?, ?)", (code, uid, now))
        new_bal, _ = apply_wallet_delta(
            tx,
            uid,
            credits,
            "redeem_code",
            f"兑换积分礼券码 {code}" + (f"（{rc['note']}）" if rc["note"] else ""),
            event_key=f"redeem_{uid}_{code}",
            ref_type="redeem_code",
            ref_id=code,
        )
    return {"ok": True, "code": code, "added": credits, "credits": new_bal}


def topup_credits_for_user(db: Database, user: dict[str, Any], amount: int) -> dict[str, Any]:
    raise ServiceError("请通过购买订单完成支付，不能直接发放充值积分",status=410,code="checkout_required")


def _extract_images_from_items_json(items_json_str: Any) -> list[str]:
    if not items_json_str:
        return []
    try:
        raw = json.loads(items_json_str) if isinstance(items_json_str, str) else items_json_str
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    images = []
    for it in raw:
        if isinstance(it, str) and it.strip():
            images.append(it.strip())
        elif isinstance(it, dict) and it.get("imageUrl") and str(it["imageUrl"]).strip():
            images.append(str(it["imageUrl"]).strip())
    return images


def check_generation_social_accessible(
    row: dict[str, Any] | None,
    viewer: dict[str, Any] | None = None,
    *,
    allow_own: bool = False,
) -> bool:
    """Shared permission & visibility check across list, detail, and social interaction endpoints.

    Others can only access generations that are:
    1. status == 'success'
    2. COALESCE(deleted_at, '') == '' (not deleted)
    3. engine != 'demo'
    4. visibility == 'public' (or viewer is the author when allow_own is True)
    5. Has valid, non-empty images
    """
    if not row:
        return False
    row_keys = row.keys() if hasattr(row, "keys") else row
    status = str(row["status"] or "") if "status" in row_keys else ""
    if status != "success":
        return False
    deleted_at = row["deleted_at"] if "deleted_at" in row_keys else None
    if deleted_at:
        return False
    engine = str(row["engine"] or "") if "engine" in row_keys else ""
    if engine == "demo":
        return False

    vuid = int(viewer["id"]) if viewer and viewer.get("id") is not None else None
    row_uid = int(row["user_id"]) if "user_id" in row_keys and row["user_id"] is not None else None
    is_owner = (vuid is not None and row_uid is not None and vuid == row_uid)

    vis = str(row["visibility"] or "") if "visibility" in row_keys else "public"
    if not (vis == "public" or (allow_own and is_owner)):
        return False

    raw_items = row["items_json"] if "items_json" in row_keys else "[]"
    imgs = _extract_images_from_items_json(raw_items)
    if not imgs:
        return False

    return True


def _generation_work_id(conn: PgConnection, identifier: str) -> str:
    """Resolve a Web execution ID, V3 run ID, or work ID to one real work.

    All generation-history interactions are recorded against works.id.
    No legacy per-image likes, generation collection bucket or duplicate
    forum interactions are created in new V3 databases.
    """
    key = str(identifier or "").strip()
    if not key:
        raise ServiceError("缺少作品编号", status=400, code="work_required")
    work = conn.execute(
        "SELECT id FROM works WHERE id=? AND status='published'", (key,),
    ).fetchone()
    if work:
        return str(work["id"])
    work = conn.execute(
        """SELECT w.id FROM works w JOIN generation_runs r ON r.id=w.run_id
           WHERE r.id=? AND w.status='published'""",
        (key,),
    ).fetchone()
    if work:
        return str(work["id"])
    source = conn.execute(
        """SELECT user_id,COALESCE(NULLIF(batch_id,''),id) AS external_run_id
           FROM studio_generations WHERE id=?""",
        (key,),
    ).fetchone()
    if source:
        work = conn.execute(
            """SELECT w.id FROM works w JOIN generation_runs r ON r.id=w.run_id
               WHERE r.user_id=? AND r.source='web'
                 AND r.external_run_id=? AND w.status='published'""",
            (int(source["user_id"]), source["external_run_id"]),
        ).fetchone()
        if work:
            return str(work["id"])
    raise ServiceError("作品不存在或已下架", status=404, code="work_not_found")


def attach_generation_social_counts(
    conn: PgConnection,
    items: list[dict[str, Any]],
    viewer: dict[str, Any] | None = None,
) -> None:
    """One generated work has ONE set of likes/favorites, on works.id only."""
    if not items:
        return
    linked: dict[str, str] = {}
    for item in items:
        identity = str(item.get("workId") or "").strip()
        if not identity:
            try:
                identity = _generation_work_id(conn, str(item.get("id") or ""))
            except ServiceError:
                identity = ""
        linked[str(item.get("id") or "")] = identity
    work_ids = sorted({wid for wid in linked.values() if wid})
    works: dict[str, dict[str, Any]] = {}
    viewer_likes: set[str] = set()
    viewer_favs: set[str] = set()
    if work_ids:
        placeholders = ",".join("?" for _ in work_ids)
        for row in conn.execute(
            f"SELECT id,likes,favorites FROM works WHERE status='published' "
            f"AND id IN ({placeholders})",
            tuple(work_ids),
        ).fetchall():
            works[str(row["id"])] = dict(row)
        if viewer and viewer.get("id"):
            user_id = int(viewer["id"])
            viewer_likes = {
                str(row["target_id"]) for row in conn.execute(
                    f"SELECT target_id FROM interactions "
                    f"WHERE target_type='like_work' AND user_id=? "
                    f"AND target_id IN ({placeholders})",
                    (user_id, *work_ids),
                ).fetchall()
            }
            viewer_favs = {
                str(row["target_id"]) for row in conn.execute(
                    f"SELECT target_id FROM collections "
                    f"WHERE bucket='works' AND user_id=? "
                    f"AND target_id IN ({placeholders})",
                    (user_id, *work_ids),
                ).fetchall()
            }

    for item in items:
        wid = linked.get(str(item.get("id") or ""), "")
        row = works.get(wid)
        item["workId"] = wid or None
        item["likes"] = int(row["likes"] or 0) if row else 0
        item["favorites"] = int(row["favorites"] or 0) if row else 0
        item["liked"] = bool(wid in viewer_likes)
        item["favorited"] = bool(wid in viewer_favs)


def _lock_social_wallet(tx, user_id: int) -> int:
    # Serialize changes from the same actor before reading their interaction state.
    query = "SELECT balance FROM wallets WHERE user_id = ?"
    query += " FOR UPDATE"
    row = tx.execute(query, (user_id,)).fetchone()
    return int(row["balance"]) if row else 0


def toggle_user_collection(
    db: Database,
    user: dict[str, Any],
    bucket: str,
    target_id: str,
    title_label: str = "",
    action: str | None = None,
) -> dict[str, Any]:
    if bucket not in ("styles", "layouts", "works", "topics", "generations"):
        raise ServiceError("收藏夹分类无效")
    from_generation_history = bucket == "generations"
    tid = (target_id or "").strip()
    if not tid:
        raise ServiceError("缺少收藏目标 ID")
    uid = int(user["id"])
    now = utc_now_iso()
    act = (action or "").strip().lower()

    resource_entry = None
    if bucket in ("styles", "layouts"):
        from . import resource_registry
        resource_entry = resource_registry.resolve(db.get_conn(), tid, viewer=user, purpose="collect")
        if not resource_entry:
            raise ServiceError("未找到目标内容", status=404)
        tid = resource_entry["code"]

    # Favouriting a work's discussion topic means favouriting the work, so the
    # square and the forum cannot report different favourite counts.
    if bucket == "topics":
        primary = db.get_conn().execute(
            "SELECT target_id FROM curation_resource_topics WHERE kind = 'work' AND topic_id = ?",
            (tid,),
        ).fetchone()
        if primary:
            bucket = "works"
            tid = str(primary["target_id"])

    if bucket == "works":
        w_chk = db.get_conn().execute("SELECT status FROM works WHERE id = ?", (tid,)).fetchone()
        if not w_chk or str(w_chk["status"]) != "published":
            raise ServiceError("作品不存在或已下架", status=404)

    if bucket == "generations":
        # Generation history is only a view of the canonical work.
        bucket = "works"
        tid = _generation_work_id(db.get_conn(), tid)

    with db.transaction() as tx:
        bal = _lock_social_wallet(tx, uid)
        existing = tx.execute(
            "SELECT 1 FROM collections WHERE user_id = ? AND bucket = ? AND target_id = ?",
            (uid, bucket, tid),
        ).fetchone()

        if act in ("unset", "uncollect", "remove"):
            should_collect = False
        elif act in ("set", "collect", "add"):
            should_collect = True
        else:
            should_collect = not bool(existing)

        rewarded = counter_delta = 0
        if existing and not should_collect:
            counter_delta = -tx.execute(
                "DELETE FROM collections WHERE user_id = ? AND bucket = ? AND target_id = ?", (uid, bucket, tid),
            ).rowcount
            collected = False
        elif not existing and should_collect:
            if bucket in ("styles", "layouts") and resource_entry and not resource_entry.get("canCollect"):
                raise ServiceError("该资源暂不支持收藏", status=403)
            counter_delta = tx.execute(
                """INSERT INTO collections (user_id, bucket, target_id, created_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT (user_id, bucket, target_id) DO NOTHING""",
                (uid, bucket, tid, now),
            ).rowcount
            collected = True

            # Generation-history favorites now share the works bucket, but
            # an alias must not grant first-collect bonus credits. Preserve
            # the original API's no-reward rule after canonicalization.
            if counter_delta and not from_generation_history:
                claimed = tx.execute(
                    "UPDATE users SET first_collect_rewarded = 1 WHERE id = ? AND first_collect_rewarded = 0", (uid,),
                ).rowcount
                if claimed:
                    settings = get_site_settings(tx)
                    bonus = int(settings.get("economy", {}).get("first_collect_credits", 2))
                    if bonus > 0:
                        bal, applied = apply_wallet_delta(
                            tx,
                            uid,
                            bonus,
                            "first_collect",
                            f"首次使用云端收藏夹激励（{title_label or tid}）",
                            event_key=f"first_collect_{uid}",
                        )
                        rewarded = bonus if applied else 0
        else:
            collected = bool(existing)

        if bucket in ("works", "topics"):
            norm_type, table = ("work", "works") if bucket == "works" else ("topic", "forum_topics")
            if counter_delta:
                count_row = tx.execute(
                    f"UPDATE {table} SET favorites = GREATEST(0, favorites + ?) WHERE id = ? RETURNING favorites",
                    (counter_delta, tid),
                ).fetchone()
            else:
                count_row = tx.execute(f"SELECT favorites FROM {table} WHERE id = ?", (tid,)).fetchone()
            if not count_row:
                raise ServiceError("未找到目标内容", status=404)
            new_favorites = int(count_row["favorites"])
        elif bucket == "generations":
            norm_type = "generation"
            fav_cnt = tx.execute(
                "SELECT COUNT(*) FROM collections WHERE bucket = 'generations' AND target_id = ?",
                (tid,),
            ).fetchone()[0]
            new_favorites = int(fav_cnt)
        else:
            norm_type = _infer_asset_kind(tid, fallback=("layout" if bucket == "layouts" else "style"))
            if is_demo_mode():
                seed_row = tx.execute("SELECT base_favorites FROM asset_social_seeds WHERE asset_code = ?", (tid,)).fetchone()
                base_fav = int(seed_row["base_favorites"]) if seed_row else _default_asset_social_baseline(tid)[1]
            else:
                base_fav = 0
            live_fav = int(
                tx.execute(
                    "SELECT COUNT(*) FROM collections WHERE bucket IN ('styles', 'layouts') AND target_id = ?",
                    (tid,),
                ).fetchone()[0]
            )
            new_favorites = base_fav + live_fav

        return {
            "ok": True,
            "targetType": norm_type,
            "targetId": tid,
            "collected": collected,
            "favorites": new_favorites,
            "rewarded": rewarded,
            "credits": bal,
        }


# Authority ranks for visibility decisions.  A decision may only be reversed by
# someone of the same or a higher rank, so a board moderator cannot undo an
# operator's hide and an operator cannot undo an admin's.
#
# Product rule (M9), chosen as the safer default and pending founder
# confirmation: **admin wins**.  When an admin hides or pauses something, only
# an admin can bring it back.  Deleting is always allowed for anyone already
# authorised to delete, because it only makes content less visible.
ACTOR_RANK = {"": 0, "author": 1, "moderator": 2, "operator": 3, "admin": 4}


def staff_actor_role(user: dict[str, Any] | None, *, board_moderator: bool = False) -> str:
    """Map a user to the rank recorded with a visibility decision."""
    role = str((user or {}).get("role") or "")
    if role == "admin":
        return "admin"
    if role in ("operator", "reviewer"):
        return "operator"
    if board_moderator:
        return "moderator"
    return "author"


def actor_may_override(current_actor: str, actor_role: str) -> bool:
    return ACTOR_RANK.get(str(actor_role or ""), 0) >= ACTOR_RANK.get(str(current_actor or ""), 0)


def _decision_locked(current_actor: str) -> ServiceError:
    label = {"admin": "超级管理员", "operator": "运营审查员", "moderator": "版主"}.get(current_actor, current_actor)
    return ServiceError(
        f"该内容由{label}处理，需同级或更高权限才能变更", status=403, code="decision_locked"
    )


# status_source values on a thread that record a decision about the thread
# itself.  Automation ('report' and 'work') never overrides them.
_THREAD_HUMAN_SOURCES = ("moderator", "author")


def set_topic_visibility(
    tx,
    topic_id: str,
    status: str,
    now_iso: str,
    *,
    source: str = "moderator",
    reason: str = "",
    actor_role: str = "",
    automated: bool = False,
    allow_from: tuple[str, ...] | None = None,
    allow_sources: tuple[str, ...] | None = None,
) -> bool:
    """The single place a discussion thread's visibility changes.

    Every writer of ``forum_topics.status`` calls this: both moderation entries
    (``/api/admin/topics/...`` and ``/api/forum/moderate``), author and admin
    deletion, report auto-pause, report confirm and dismissal, and the
    work-to-thread mirror in ``set_work_visibility``.

    ``source`` says why: 'moderator' (a human decided about this thread),
    'author' (the author deleted it), 'report' (abuse-report automation) or
    'work' (mirroring the linked work).  ``actor_role`` is the rank of the
    human, '' for automation.

    Rules, in order:
      1. ``deleted`` is terminal.  Human callers get 409 ``topic_deleted``.
      2. ``allow_from`` / ``allow_sources`` are explicit preconditions, used by
         the report flow to say exactly which state it may undo.  When given,
         rule 3 is not consulted: the caller has stated what it overrides.
      3. Precedence: automation never overrides a human decision on the
         thread, and the work mirror never overrides the thread's own report
         hold (that hold ends with its own dismissal or confirmation).
      4. Rank: a human may not reverse a higher-ranked human's decision
         (403 ``decision_locked``).  Deleting is exempt.
      5. Publishing requires the linked work to be published.

    Automated callers (``automated=True``) get ``False`` instead of an error
    when a rule refuses the change.  Returns True when the row changed.
    """
    current = tx.execute(
        "SELECT status, status_source, status_actor_role FROM forum_topics WHERE id = ?", (topic_id,)
    ).fetchone()
    if not current:
        if automated:
            return False
        raise ServiceError("帖子不存在", status=404)
    cur_status = str(current["status"] or "")
    cur_source = str(current["status_source"] or "")
    cur_actor = str(current["status_actor_role"] or "")

    def refuse(error: ServiceError) -> bool:
        if automated:
            return False
        raise error

    if cur_status == "deleted":
        if status == "deleted":
            return False
        return refuse(ServiceError("该帖子已删除，不能恢复", status=409, code="topic_deleted"))

    if allow_from is not None and cur_status not in allow_from:
        return False
    if allow_sources is not None and cur_source not in allow_sources:
        return False

    if allow_sources is None and source in ("report", "work") and cur_status != "published":
        # A non-published thread with no recorded source predates provenance;
        # treat it as a human decision rather than guess.
        human_hold = cur_source in _THREAD_HUMAN_SOURCES or cur_source == ""
        report_hold = cur_source == "report"
        if human_hold or (source == "work" and report_hold):
            return False

    # Mirrored state is the work's decision; rank was checked on the work.
    if (
        status != "deleted"
        and cur_status != "published"
        and cur_source != "work"
        and source not in ("report", "work")
        and not actor_may_override(cur_actor, actor_role)
    ):
        return refuse(_decision_locked(cur_actor))

    if status == "published":
        linked = tx.execute(
            "SELECT target_id FROM curation_resource_topics WHERE kind = 'work' AND topic_id = ?",
            (topic_id,),
        ).fetchone()
        if linked:
            # Deleting a work deletes this mapping, so a missing work here only
            # happens with inconsistent data; refuse rather than publish.
            work = tx.execute(
                "SELECT status FROM works WHERE id = ?", (str(linked["target_id"]),)
            ).fetchone()
            if work is None or str(work["status"]) != "published":
                return refuse(ServiceError(
                    "该主帖关联的作品当前不可见，请先恢复作品", status=409, code="work_not_published"
                ))
        tx.execute(
            "UPDATE forum_topics SET status = 'published', status_source = '', status_reason = '', "
            "status_actor_role = '', updated_at = ? WHERE id = ?",
            (now_iso, topic_id),
        )
        return True

    tx.execute(
        "UPDATE forum_topics SET status = ?, status_source = ?, status_reason = ?, "
        "status_actor_role = ?, updated_at = ? WHERE id = ?",
        (status, source, reason, actor_role, now_iso, topic_id),
    )
    return True


def release_topic_report_hold(tx, topic_id: str, now_iso: str) -> bool:
    """Undo an automatic report pause on a thread, and nothing else.

    The thread returns to what its work allows: published when the work is
    published (or there is no work), otherwise the work's own state as a
    mirror.  Publishing outright used to expose a thread whose work was still
    paused (M7).
    """
    linked = tx.execute(
        "SELECT w.status, w.status_reason, w.status_actor_role FROM curation_resource_topics m "
        "JOIN works w ON w.id = m.target_id WHERE m.kind = 'work' AND m.topic_id = ?",
        (topic_id,),
    ).fetchone()
    if linked is not None and str(linked["status"]) != "published":
        return set_topic_visibility(
            tx, topic_id, str(linked["status"]), now_iso,
            source="work", reason=str(linked["status_reason"] or ""),
            actor_role=str(linked["status_actor_role"] or ""), automated=True,
            allow_from=("paused", "hidden"), allow_sources=("report",),
        )
    return set_topic_visibility(
        tx, topic_id, "published", now_iso, source="report", automated=True,
        allow_from=("paused", "hidden"), allow_sources=("report",),
    )


def set_work_visibility(
    tx,
    work_id: str,
    status: str,
    now_iso: str,
    *,
    source: str = "moderator",
    reason: str = "",
    actor_role: str = "",
    automated: bool = False,
    allow_from: tuple[str, ...] | None = None,
    allow_sources: tuple[str, ...] | None = None,
) -> bool:
    """Change a work's status and keep its discussion thread in step.

    Every path that hides, pauses or restores a work must go through here.

    ``source`` records who caused the change: ``'report'`` for the abuse-report
    threshold, ``'moderator'`` for a human decision.  Restoring passes
    ``allow_sources=('report',)`` so a dismissed report only undoes an automatic
    pause — never an admin's hide, and never a human pause.  ``allow_from``
    guards the previous status in the same way.

    ``actor_role`` is the human's rank; a lower rank may not reverse a higher
    rank's decision (403 ``decision_locked``, or ``False`` when ``automated``).

    The thread mirrors the work with ``status_source='work'``, so a decision a
    moderator made about the thread itself survives any change to the work.
    Returns True when the work row was changed.
    """
    current = tx.execute(
        "SELECT status, status_source, status_actor_role FROM works WHERE id = ?", (work_id,)
    ).fetchone()
    if not current:
        return False
    if allow_from is not None and str(current["status"]) not in allow_from:
        return False
    if allow_sources is not None and str(current["status_source"] or "") not in allow_sources:
        return False
    cur_actor = str(current["status_actor_role"] or "")
    if str(current["status"]) != "published" and not actor_may_override(cur_actor, actor_role):
        if automated:
            return False
        raise _decision_locked(cur_actor)

    publishing = status == "published"
    tx.execute(
        "UPDATE works SET status = ?, status_source = ?, status_reason = ?, status_actor_role = ?, "
        "updated_at = ? WHERE id = ?",
        (
            status,
            "" if publishing else source,
            "" if publishing else reason,
            "" if publishing else actor_role,
            now_iso,
            work_id,
        ),
    )
    mapped = tx.execute(
        "SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?",
        (work_id,),
    ).fetchone()
    if mapped:
        set_topic_visibility(
            tx, str(mapped["topic_id"]), status, now_iso,
            source="work", reason="" if publishing else reason,
            actor_role="" if publishing else actor_role, automated=True,
        )
    try:
        from .home_scenarios import invalidate_scenarios_cache
        invalidate_scenarios_cache()
    except Exception:
        pass
    return True


_COMMENT_TABLES = ("forum_replies", "work_comments", "asset_comments")


def set_comment_visibility(tx, table: str, comment_id: str, status: str, actor_role: str) -> bool:
    """Hide or publish a reply/comment, recording who decided (R4).

    The same rank rule as threads: a board moderator cannot republish a reply
    an admin or operator hid, for instance after confirming a report.
    """
    if table not in _COMMENT_TABLES:
        raise ServiceError("无效的评论类型")
    row = tx.execute(f"SELECT status, status_actor_role FROM {table} WHERE id = ?", (comment_id,)).fetchone()
    if not row:
        return False
    cur_actor = str(row["status_actor_role"] or "")
    if str(row["status"]) != "published" and not actor_may_override(cur_actor, actor_role):
        raise _decision_locked(cur_actor)
    tx.execute(
        f"UPDATE {table} SET status = ?, status_actor_role = ? WHERE id = ?",
        (status, "" if status == "published" else actor_role, comment_id),
    )
    return True


def _insert_interaction(tx, user_id: int, interaction_type: str, target_id: str, created_at: str) -> bool:
    return bool(tx.execute(
        """INSERT INTO interactions (user_id, target_type, target_id, stamp_label, created_at)
           VALUES (?, ?, ?, '', ?)
           ON CONFLICT (user_id, target_type, target_id, stamp_label) DO NOTHING""",
        (user_id, interaction_type, target_id, created_at),
    ).rowcount)


def _grant_first_cheer(tx, user_id: int, balance: int, reason: str) -> tuple[int, int]:
    claimed = tx.execute(
        "UPDATE users SET first_cheer_rewarded = 1 WHERE id = ? AND first_cheer_rewarded = 0", (user_id,),
    ).rowcount
    if not claimed:
        return balance, 0
    settings = get_site_settings(tx)
    bonus = int(settings.get("economy", {}).get("first_cheer_credits", 2))
    if bonus <= 0:
        return balance, 0
    balance, applied = apply_wallet_delta(
        tx, user_id, bonus, "first_cheer", reason, event_key=f"first_cheer_{user_id}",
    )
    return balance, bonus if applied else 0


def toggle_user_like(
    db: Database,
    user: dict[str, Any],
    target_type: str,
    target_id: str,
    action: str | None = None,
) -> dict[str, Any]:
    """Toggle 👍 Like on any Style, Layout, Work, Forum Topic, or Generation."""
    raw_type = (target_type or "").strip().lower()
    tid = (target_id or "").strip()
    if not tid:
        raise ServiceError("缺少点赞目标 ID")

    if raw_type in ("style", "layout", "asset"):
        tid = tid.upper().lstrip("#")
        norm_type = _infer_asset_kind(tid, fallback=("layout" if raw_type == "layout" else "style"))
    elif raw_type in ("work", "topic"):
        norm_type = raw_type
    elif raw_type in ("generation", "like_generation"):
        norm_type = "work"
        tid = _generation_work_id(db.get_conn(), tid)
    else:
        raise ServiceError("不支持的点赞目标类型")

    uid = int(user["id"])
    now = utc_now_iso()
    act = (action or "").strip().lower()
    itype = f"like_{norm_type}"

    # A work's discussion topic is a view of the work, not a second object.
    # Liking it must record against the work so the square and the forum show
    # the same number.
    if norm_type == "topic":
        primary = db.get_conn().execute(
            "SELECT target_id FROM curation_resource_topics WHERE kind = 'work' AND topic_id = ?",
            (tid,),
        ).fetchone()
        if primary:
            norm_type = "work"
            tid = str(primary["target_id"])
            itype = "like_work"

    with db.transaction() as tx:
        bal = _lock_social_wallet(tx, uid)
        if norm_type == "work":
            w_row = tx.execute("SELECT title, author_username, run_id, status FROM works WHERE id = ?", (tid,)).fetchone()
            if not w_row or str(w_row["status"]) != "published":
                raise ServiceError("作品不存在或已下架", status=404)
            # Generated works have one canonical social identity. Do not let
            # creators like their own run via either "generation" or "work".
            if (w_row["run_id"] and
                    str(w_row["author_username"]).casefold() == str(user.get("username") or "").casefold()):
                raise ServiceError("不能为自己的生图历史点赞", status=403, code="self_like_forbidden")
            title_lbl = w_row["title"]
        elif norm_type == "topic":
            t_row = tx.execute("SELECT title FROM forum_topics WHERE id = ?", (tid,)).fetchone()
            if not t_row:
                raise ServiceError("帖子不存在", status=404)
            title_lbl = t_row["title"]
        elif norm_type == "generation":
            g_row = tx.execute("SELECT * FROM studio_generations WHERE id = ?", (tid,)).fetchone()
            if not check_generation_social_accessible(g_row, viewer=user, allow_own=False):
                raise ServiceError("生图记录不存在或不可见", status=404, code="not_found")
            if int(g_row["user_id"] or 0) == uid:
                raise ServiceError("不能为自己的生图历史点赞", status=403, code="self_like_forbidden")
            title_lbl = g_row["subject"] or tid
        else:
            title_lbl = tid

        existing = tx.execute(
            "SELECT 1 FROM interactions WHERE user_id = ? AND target_type = ? AND target_id = ? AND stamp_label = ''",
            (uid, itype, tid),
        ).fetchone()

        if act in ("unset", "unlike", "remove"):
            should_like = False
        elif act in ("set", "like", "add"):
            should_like = True
        else:
            should_like = not bool(existing)

        rewarded = counter_delta = 0
        if existing and not should_like:
            counter_delta = -tx.execute(
                "DELETE FROM interactions WHERE user_id = ? AND target_type = ? AND target_id = ? AND stamp_label = ''",
                (uid, itype, tid),
            ).rowcount
            liked = False
        elif not existing and should_like:
            counter_delta = int(_insert_interaction(tx, uid, itype, tid, now))
            liked = True

            if counter_delta and norm_type != "generation":
                bal, rewarded = _grant_first_cheer(tx, uid, bal, f"友善社区互动：首次点赞《{title_lbl[:20]}》")
        else:
            liked = bool(existing)

        if norm_type in ("work", "topic"):
            table = "works" if norm_type == "work" else "forum_topics"
            if counter_delta:
                count_row = tx.execute(
                    f"UPDATE {table} SET likes = GREATEST(0, likes + ?) WHERE id = ? RETURNING likes",
                    (counter_delta, tid),
                ).fetchone()
            else:
                count_row = tx.execute(f"SELECT likes FROM {table} WHERE id = ?", (tid,)).fetchone()
            if not count_row:
                raise ServiceError("未找到目标内容", status=404)
            new_likes = int(count_row["likes"])
        elif norm_type == "generation":
            new_likes = int(
                tx.execute(
                    "SELECT COUNT(*) FROM interactions WHERE target_type = 'like_generation' AND target_id = ?",
                    (tid,),
                ).fetchone()[0]
            )
        else:
            if is_demo_mode():
                seed_row = tx.execute("SELECT base_likes FROM asset_social_seeds WHERE asset_code = ?", (tid,)).fetchone()
                base_likes = int(seed_row["base_likes"]) if seed_row else _default_asset_social_baseline(tid)[0]
            else:
                base_likes = 0
            live_cnt = int(
                tx.execute(
                    "SELECT COUNT(*) FROM interactions WHERE target_type IN ('like_style', 'like_layout') AND target_id = ?",
                    (tid,),
                ).fetchone()[0]
            )
            new_likes = base_likes + live_cnt

    return {
        "ok": True,
        "targetType": norm_type,
        "targetId": tid,
        "liked": liked,
        "likes": new_likes,
        "rewarded": rewarded,
        "credits": bal,
    }


def toggle_user_cheer(db: Database, user: dict[str, Any], target_type: str, target_id: str, stamp_label: str = "") -> dict[str, Any]:
    if target_type not in ("work", "asset"):
        raise ServiceError("不支持的鼓励对象类型")
    if (stamp_label or "").strip():
        raise ServiceError("印章功能已下线", status=400, code="stamp_retired")
    tid = (target_id or "").strip()
    uid = int(user["id"])
    now = utc_now_iso()

    with db.transaction() as tx:
        bal = _lock_social_wallet(tx, uid)
        if target_type == "work":
            target = tx.execute("SELECT author_name FROM works WHERE id = ?", (tid,)).fetchone()
            if not target:
                raise ServiceError("未找到目标内容", status=404)
            author_name = target["author_name"]
            target_predicate, target_params = "target_id = ?", (tid,)
        else:
            clean_code = tid.upper().lstrip("#")
            from . import resource_registry
            cat_res = resource_registry.resolve(tx, clean_code, viewer=user, purpose="stamp")
            if not cat_res:
                raise ServiceError("未找到目标内容", status=404)
            if not cat_res.get("canStamp", True):
                raise ServiceError("该资源暂不支持盖章", status=403)
            tid = cat_res["code"]
            target = tx.execute(
                "SELECT code AS id, author_name FROM catalog_assets WHERE code = ? OR UPPER(code) = ?",
                (tid, tid.upper()),
            ).fetchone()
            author_name = target["author_name"] if target else (
                cat_res.get("author_name") or cat_res.get("author") or "官方资源"
            )
            target_predicate, target_params = "(target_id = ? OR UPPER(target_id) = ?)", (tid, tid.upper())

        interaction_filter = f"target_type = ? AND {target_predicate} AND stamp_label = ''"
        existing = tx.execute(
            f"SELECT 1 FROM interactions WHERE user_id = ? AND {interaction_filter} LIMIT 1",
            (uid, target_type, *target_params),
        ).fetchone()
        cheered = not bool(existing)
        rewarded = 0
        if cheered:
            delta = int(_insert_interaction(tx, uid, target_type, tid, now))
            if delta:
                bal, rewarded = _grant_first_cheer(tx, uid, bal, f"友善社区互动：首次送上鼓励支持 @{author_name}")
        else:
            delta = -tx.execute(
                f"DELETE FROM interactions WHERE user_id = ? AND {interaction_filter}",
                (uid, target_type, *target_params),
            ).rowcount

        if target_type == "work":
            row = tx.execute(
                "UPDATE works SET cheers = GREATEST(0, cheers + ?) WHERE id = ? RETURNING cheers", (delta, tid),
            ).fetchone()
            if not row:
                raise ServiceError("未找到目标内容", status=404)
            new_cheers = int(row["cheers"])
        elif target:
            row = tx.execute(
                "UPDATE catalog_assets SET cheers = GREATEST(0, cheers + ?) WHERE code = ? RETURNING cheers",
                (delta, target["id"]),
            ).fetchone()
            if not row:
                raise ServiceError("未找到目标内容", status=404)
            new_cheers = int(row["cheers"])
        else:
            new_cheers = int(tx.execute(
                f"SELECT COUNT(*) FROM interactions WHERE {interaction_filter}",
                (target_type, *target_params),
            ).fetchone()[0])

    return {"ok": True, "cheered": cheered, "cheers": new_cheers, "rewarded": rewarded, "credits": bal}


def get_official_tip_payee(settings: dict[str, Any]) -> str:
    val = settings.get("economy", {}).get("official_tip_payee")
    if not val:
        val = settings.get("official_tip_payee")
    return str(val or "").strip()


def send_encourage_tip(
    db: Database,
    user: dict[str, Any],
    target_type: str,
    target_id: str,
    amount: Any = 2,
    request_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    raw_type = str(target_type or "").strip().lower()
    tid = str(target_id or "").strip()
    if not tid:
        raise ServiceError("缺少赞赏目标 ID")

    uid = int(user["id"])
    if user.get("status") not in (None, "", "active"):
        raise ServiceError("账号状态异常，无法进行赞赏", status=403)

    if amount is None:
        amt = 2
    elif isinstance(amount, bool) or not isinstance(amount, int):
        raise ServiceError("赞赏金额必须为 1–50✦ 整数", status=400, code="invalid_tip_amount")
    elif amount < 1 or amount > 50:
        raise ServiceError("赞赏金额必须在 1–50✦ 之间", status=400, code="invalid_tip_amount")
    else:
        amt = int(amount)

    now = utc_now_iso()
    now_ts = str(created_at or "").strip() or now
    clean_req_id = str(request_id or "").strip() or None

    with db.transaction() as tx:
        viewer_balance = _lock_social_wallet(tx, uid)
        # Resolve binding if target is topic
        if raw_type == "topic":
            mapping = tx.execute(
                "SELECT kind, target_id FROM curation_resource_topics WHERE topic_id = ?",
                (tid,),
            ).fetchone()
            if mapping:
                if mapping["kind"] == "work":
                    raw_type = "work"
                    tid = str(mapping["target_id"])
                elif mapping["kind"] in ("style", "layout"):
                    raw_type = "asset"
                    tid = str(mapping["target_id"])
            else:
                t_chk = tx.execute("SELECT work_id FROM forum_topics WHERE id = ?", (tid,)).fetchone()
                if t_chk and t_chk["work_id"]:
                    raw_type = "work"
                    tid = str(t_chk["work_id"])
        elif raw_type == "asset":
            clean_code = str(tid or "").strip().upper().lstrip("#")
            tid = clean_code

        # Idempotency check with request_id (prior to rate limits)
        if clean_req_id:
            prev_req = tx.execute(
                "SELECT target_type, target_id, amount FROM tip_requests WHERE user_id = ? AND request_id = ?",
                (uid, clean_req_id),
            ).fetchone()
            if not prev_req:
                dup_ledger = tx.execute(
                    "SELECT ref_type, ref_id, delta FROM ledgers WHERE user_id = ? AND event_key = ?",
                    (uid, f"tip_out_{clean_req_id}"),
                ).fetchone()
                if dup_ledger:
                    prev_req = {
                        "target_type": dup_ledger["ref_type"],
                        "target_id": dup_ledger["ref_id"],
                        "amount": abs(int(dup_ledger["delta"])),
                    }
            if prev_req:
                p_type = str(prev_req["target_type"]).strip().lower()
                p_id = str(prev_req["target_id"]).strip()
                p_amt = int(prev_req["amount"])
                if p_type == raw_type and p_id == tid and p_amt == amt:
                    return {
                        "ok": True,
                        "credits": viewer_balance,
                        "amount": amt,
                        "duplicate": True,
                        "targetType": raw_type,
                        "targetId": tid,
                    }
                else:
                    raise ServiceError("请求参数与原请求不一致", status=409, code="tip_conflict")

        is_official = False
        target = None

        if raw_type == "topic":
            t_row = tx.execute("SELECT id, title, author_username, author_name, price, status FROM forum_topics WHERE id = ?", (tid,)).fetchone()
            if not t_row or t_row["status"] != "published":
                raise ServiceError("帖子不存在或不可访问", status=404)

            tf, tp = _seed_filter("id", "topics")
            t_valid = tx.execute(f"SELECT 1 FROM forum_topics WHERE id = ? AND {tf}", (tid, *tp)).fetchone()
            if not t_valid:
                raise ServiceError("帖子不存在或不可访问", status=404)

            if int(t_row["price"] or 0) > 0:
                raise ServiceError("付费帖不支持赞赏", status=400, code="paid_topic_no_tip")

            if t_row["author_username"] == user["username"]:
                raise ServiceError("不能给自己赞赏积分哦", status=400, code="self_tip_not_allowed")

            target = {
                "id": tid,
                "title": t_row["title"],
                "author_username": t_row["author_username"],
                "author_name": t_row["author_name"],
            }

        elif raw_type == "work":
            w_row = tx.execute("SELECT id, title, author_username, author_name, status FROM works WHERE id = ?", (tid,)).fetchone()
            if not w_row or w_row["status"] != "published":
                raise ServiceError("作品不存在或不可访问", status=404)

            wf, wp = _seed_filter("id", "works")
            w_valid = tx.execute(f"SELECT 1 FROM works WHERE id = ? AND {wf}", (tid, *wp)).fetchone()
            if not w_valid:
                raise ServiceError("作品不存在或不可访问", status=404)

            if w_row["author_username"] == user["username"]:
                raise ServiceError("不能给自己赞赏积分哦", status=400, code="self_tip_not_allowed")

            target = dict(w_row)

        elif raw_type == "asset":
            from . import resource_registry
            cat_res = resource_registry.resolve(tx, tid, viewer=user, purpose="tip")
            if not cat_res:
                raise ServiceError("目标不存在", status=404)
            if cat_res.get("source") == "pending" or cat_res.get("status") in ("pending", "changes_requested"):
                raise ServiceError("未收录资源不接受赞赏", status=400)
            clean_code = cat_res["code"]
            tid = clean_code
            row = tx.execute("SELECT code AS id, name AS title, author_username, author_name, source_type FROM catalog_assets WHERE code = ? OR UPPER(code) = ?", (clean_code, clean_code)).fetchone()
            target = dict(row) if row else None
            if not target:
                if cat_res.get("source") in ("official", "override", "exclusive"):
                    is_official = True
                    target = {
                        "id": clean_code,
                        "title": cat_res.get("name") or clean_code,
                        "author_username": "",
                        "author_name": "官方团队",
                        "source_type": "official",
                    }
                else:
                    raise ServiceError("目标不存在", status=404)
            elif target.get("source_type") in ("official", "exclusive") or not target.get("author_username"):
                is_official = True
            else:
                if target["author_username"] == user["username"]:
                    raise ServiceError("不能给自己赞赏积分哦", status=400, code="self_tip_not_allowed")
        else:
            raise ServiceError("不支持的赞赏类型")

        if not target:
            raise ServiceError("目标不存在", status=404)

        tid = target["id"]

        # Persistent server-side rate limits
        now_dt = datetime.fromisoformat(now_ts.replace("Z", "+00:00"))
        sixty_sec_ago = (now_dt - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 1. Same actual target within 60s
        cnt_target = tx.execute(
            "SELECT COUNT(*) FROM tip_requests WHERE user_id = ? AND target_type = ? AND target_id = ? AND created_at >= ?",
            (uid, raw_type, tid, sixty_sec_ago),
        ).fetchone()[0]
        if cnt_target > 0:
            raise ServiceError("对同一目标的赞赏过于频繁，每 60 秒最多一次", status=429, code="rate_limited")

        # 2. Total across all targets within 60s (max 5 per minute)
        cnt_total = tx.execute(
            "SELECT COUNT(*) FROM tip_requests WHERE user_id = ? AND created_at >= ?",
            (uid, sixty_sec_ago),
        ).fetchone()[0]
        if cnt_total >= 5:
            raise ServiceError("赞赏过于频繁，每分钟最多赞赏 5 次", status=429, code="rate_limited")

        if is_official:
            settings = get_site_settings(tx)
            payee_name = get_official_tip_payee(settings)
            if not payee_name:
                raise ServiceError("官方资源赞赏暂未开放", status=400, code="official_tips_disabled")

            payee_row = tx.execute(
                "SELECT id, username, display_name, status FROM users WHERE username = ? OR id = ?",
                (payee_name, int(payee_name) if payee_name.isascii() and payee_name.isdecimal()
                 and len(payee_name) <= 19 and int(payee_name) <= 9223372036854775807 else None),
            ).fetchone()
            if not payee_row or payee_row["status"] != "active":
                raise ServiceError("官方资源赞赏暂未开放", status=400, code="official_tips_disabled")

            payee_uid = int(payee_row["id"])
            if payee_uid == uid:
                raise ServiceError("不能赞赏自己管理的官方资源", status=400)

            event_key_out = f"tip_out_{clean_req_id}" if clean_req_id else None
            new_bal, applied = apply_wallet_delta(
                tx,
                uid,
                -amt,
                "tip_official_out",
                f"🎁 赞赏官方资源《{target['title']}》（{tid}）",
                event_key=event_key_out,
                ref_type=raw_type,
                ref_id=tid,
            )
            if not applied:
                return {"ok": True, "credits": new_bal, "amount": amt, "duplicate": True}

            event_key_in = f"tip_in_{clean_req_id}" if clean_req_id else None
            apply_wallet_delta(
                tx,
                payee_uid,
                amt,
                "tip_official_in",
                f"🎁 收到 @{user['display_name']} 对官方资源《{target['title']}》（{tid}）的赞赏",
                event_key=event_key_in,
                ref_type=raw_type,
                ref_id=tid,
            )

            tx.execute("UPDATE catalog_assets SET cheers = cheers + 3, tips = tips + ? WHERE code = ? OR UPPER(code) = ?", (amt, tid, tid))
        else:
            # Community target (work, topic, or asset)
            if target["author_username"] == user["username"]:
                raise ServiceError("不能给自己赞赏积分哦", status=400, code="self_tip_not_allowed")

            event_key_out = f"tip_out_{clean_req_id}" if clean_req_id else None
            new_bal, applied = apply_wallet_delta(
                tx,
                uid,
                -amt,
                "tip_out",
                f"🎁 赞赏鼓励 @{target['author_name']} 的《{target['title']}》（100% 直达作者）",
                event_key=event_key_out,
                ref_type=raw_type,
                ref_id=tid,
            )
            if not applied:
                return {"ok": True, "credits": new_bal, "amount": amt, "duplicate": True}

            author_row = tx.execute("SELECT id FROM users WHERE username = ?", (target["author_username"],)).fetchone()
            if not author_row:
                raise ServiceError("作者账号不存在或已注销", status=404)

            event_key_in = f"tip_in_{clean_req_id}" if clean_req_id else None
            apply_wallet_delta(
                tx,
                int(author_row["id"]),
                amt,
                "tip_in",
                f"🎁 收到 @{user['display_name']} 对《{target['title']}》的赞赏鼓励",
                event_key=event_key_in,
                ref_type=raw_type,
                ref_id=tid,
            )

            if raw_type == "work":
                tx.execute("UPDATE works SET cheers = cheers + 3, tips = tips + ? WHERE id = ?", (amt, tid))
            elif raw_type == "asset":
                tx.execute("UPDATE catalog_assets SET cheers = cheers + 3, tips = tips + ? WHERE code = ? OR UPPER(code) = ?", (amt, tid, tid))

        # Attached like (Rule 4: "赞赏附带一次点赞；已经点赞过不重复加，之后再次赞赏也不重复加赞")
        if raw_type == "work":
            itype = "like_work"
        elif raw_type == "topic":
            itype = "like_topic"
        else:
            norm_asset = _infer_asset_kind(tid)
            itype = f"like_{norm_asset}"

        if _insert_interaction(tx, uid, itype, tid, now_ts):
            if raw_type == "work":
                tx.execute("UPDATE works SET likes = likes + 1 WHERE id = ?", (tid,))
            elif raw_type == "topic":
                tx.execute("UPDATE forum_topics SET likes = likes + 1 WHERE id = ?", (tid,))

        # Also maintain generic interaction record for cheers
        _insert_interaction(tx, uid, raw_type, tid, now_ts)

        # Record in tip_requests table for idempotency and persistent rate limiting
        tx.execute(
            """
            INSERT INTO tip_requests (user_id, request_id, target_type, target_id, amount, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (uid, clean_req_id, raw_type, tid, amt, now_ts),
        )

        return {"ok": True, "credits": new_bal, "amount": amt, "targetType": raw_type, "targetId": tid}


def unlock_paid_item(db: Database, user: dict[str, Any], target_type: str, target_id: str) -> dict[str, Any]:
    tid = (target_id or "").strip()
    uid = int(user["id"])
    now = utc_now_iso()
    raw_type = (target_type or "").strip().lower()

    if raw_type == "work":
        raise ServiceError("作品无需付费解锁", status=400, code="work_not_unlockable")

    with db.transaction() as tx:
        if not raw_type and tx.execute("SELECT 1 FROM works WHERE id = ?", (tid,)).fetchone():
            raise ServiceError("作品无需付费解锁", status=400, code="work_not_unlockable")

        resource_topic = tx.execute(
            "SELECT m.kind,m.target_id,t.status FROM curation_resource_topics m JOIN forum_topics t ON t.id=m.topic_id WHERE m.topic_id=?",
            (tid,),
        ).fetchone()
        if resource_topic:
            if resource_topic["kind"] == "work":
                raise ServiceError("作品无需付费解锁", status=400, code="work_not_unlockable")
            if resource_topic["status"] != "published":
                raise ServiceError("内容已下架，不能解锁", status=409)
            tid = resource_topic["target_id"]

        # Auto-detect target_type if generic
        resolved_type = target_type
        cost = 0
        title = tid
        author_uname = ""
        author_name = ""
        unlocked_content = ""
        was_masked = False

        t_row = tx.execute("SELECT * FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        a_row = tx.execute("SELECT * FROM catalog_assets WHERE code = ?", (tid.upper(),)).fetchone() if not t_row else None

        if t_row:
            resolved_type = "topic"
            if t_row["status"]!="published":
                raise ServiceError("内容已下架，不能解锁",status=409)
            cost = int(t_row["price"] or 0)
            title = t_row["title"]
            author_uname = t_row["author_username"]
            author_name = t_row["author_name"]
            unlocked_content = t_row["locked_body"]
        elif a_row:
            resolved_type = "asset"
            tid = a_row["code"]
            if a_row["status"]!="published":
                raise ServiceError("资源已下架，不能解锁",status=409)
            cost = int(a_row["unlock_cost"] or 0)
            title = f"{a_row['code']} {a_row['name']}"
            author_uname = a_row["author_username"] if a_row["source_type"] == "community" else ""
            author_name = a_row["author_name"] if a_row["source_type"] == "community" else ""
            unlocked_content = ""
        else:
            raise ServiceError("未找到待解锁内容", status=404)

        import hashlib
        lock_key=int.from_bytes(hashlib.sha256(f"unlock:{uid}:{resolved_type}:{tid}".encode()).digest()[:8],"big",signed=True)
        tx.execute("SELECT pg_advisory_xact_lock(?)",(lock_key,))
        existing = tx.execute(
            "SELECT status,purchase_seq FROM unlocks WHERE user_id = ? AND target_type = ? AND target_id = ?",
            (uid, resolved_type, tid),
        ).fetchone()
        if existing and existing["status"] == "settled":
            bal = int(tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()["balance"])
            res = {"ok": True, "alreadyUnlocked": True, "credits": bal, "unlockedContent": unlocked_content, "targetType": resolved_type, "targetId": tid}
            if was_masked:
                res["promptMasked"] = True
            return res

        if cost <= 0 or author_uname == user["username"]:
            if cost <= 0 and resolved_type == "asset":
                tx.execute(
                    "INSERT INTO unlocks(user_id,author_username,target_type,target_id,cost,author_share,status,created_at) VALUES(?,?,'asset',?,0,0,'settled',?) ON CONFLICT(user_id,target_type,target_id) DO NOTHING",
                    (uid,author_uname,tid,now),
                )
            bal = int(tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()["balance"])
            res = {"ok": True, "alreadyUnlocked": True, "credits": bal, "unlockedContent": unlocked_content, "targetType": resolved_type, "targetId": tid}
            if was_masked:
                res["promptMasked"] = True
            return res

        cycle=int(existing["purchase_seq"])+1 if existing else 1
        author_share = cost * 80 // 100 if author_uname else 0
        new_bal, _ = apply_wallet_delta(
            tx,
            uid,
            -cost,
            "unlock_spend",
            f"解锁{f' @{author_name} 的' if author_name else ''}「{title}」" + ("（80%作者积分分成，7天后结算）" if author_uname else ""),
            event_key=f"unlock_{uid}_{resolved_type}_{tid}_{cycle}",
            ref_type=resolved_type,
            ref_id=tid,
        )


        if existing:
            tx.execute(
                "UPDATE unlocks SET status = 'settled', cost = ?, author_share = ?, refund_reason = '', refunded_at = NULL WHERE user_id = ? AND target_type = ? AND target_id = ?",
                (cost, author_share, uid, resolved_type, tid),
            )
        else:
            tx.execute(
                """
                INSERT INTO unlocks (user_id, author_username, target_type, target_id, cost, author_share, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'settled', ?)
                """,
                (uid, author_uname, resolved_type, tid, cost, author_share, now),
            )

        tx.execute("UPDATE unlocks SET purchase_seq=? WHERE user_id=? AND target_type=? AND target_id=?",(cycle,uid,resolved_type,tid))
        if author_uname and author_share>0:
            author=tx.execute("SELECT id FROM users WHERE username=?",(author_uname,)).fetchone()
            unlock=tx.execute("SELECT id FROM unlocks WHERE user_id=? AND target_type=? AND target_id=?",(uid,resolved_type,tid)).fetchone()
            tx.execute("UPDATE unlocks SET purchase_seq=? WHERE id=?",(cycle,unlock[0]))
            if author and author[0]!=uid:
                tx.execute("INSERT INTO creator_point_earnings(unlock_id,purchase_seq,author_id,units) VALUES(?,?,?,?) ON CONFLICT(unlock_id,purchase_seq) DO NOTHING",(unlock[0],cycle,author[0],author_share))

    res = {
        "ok": True,
        "credits": new_bal,
        "cost": cost,
        "targetType": resolved_type,
        "targetId": tid,
        "unlockedContent": unlocked_content,
    }
    if was_masked:
        res["promptMasked"] = True
    return res


# ======================== PUBLISHING: WORKS, ASSETS, FORUM & BOUNTIES ========================

def publish_user_work(db, user, body, *, listed: bool = False):
    # Works publish immediately (D-02).  Double review stays for styles and
    # layouts, which feed the shared catalogue.
    from .curation import publish_work_direct
    # Explicit work publishing keeps its discussion unlisted until the first valid comment.
    return publish_work_direct(db, user, body, listed=False)



def add_comment_to_work(db,user,work_id,text):
    from .resource_discussions import comment
    return comment(db,user,'work',work_id,text)



def add_comment_to_asset(db,user,asset_code,text,asset_kind=''):
    from .resource_discussions import comment
    return comment(db,user,_infer_asset_kind(asset_code,asset_kind),asset_code,text)



def publish_user_community_asset(db, user, body):
    from .curation import submit
    result=submit(db,user,{'title':body.get('name') or body.get('title'),'text':body.get('description'),'requestId':body.get('requestId'),'items':[body]})
    return dict(result,status='pending',rewarded=0)



PLACEHOLDER_TOPIC_TITLES = {
    "图文模式",
    "纯图模式",
    "纯图",
    "生成结果",
    "当前工作流",
    "未命名",
    "无标题",
    "默认草稿",
    "画布创作",
    "云端生图",
    "生图结果",
    "图片展示",
    "作品展示",
}

RESOURCE_CODE_PATTERN = re.compile(r"(?:USR-)?[A-Z]{1,4}-[A-Z0-9]+", re.IGNORECASE)
PUNCTUATION_AND_CONNECTORS = re.compile(r"[\s\-_+|｜·#/\\#()（）\[\]【】\d+＋]+", re.IGNORECASE)


def validate_topic_title(title: Any) -> str:
    raw = sanitize_plain_text(title, max_chars=140)
    non_ws = re.sub(r"\s+", "", raw)
    if len(non_ws) < 4:
        raise ServiceError("帖子标题至少需要 4 个非空白字符", status=400, code="title_too_short")

    stripped_placeholder = PUNCTUATION_AND_CONNECTORS.sub("", raw)
    if raw in PLACEHOLDER_TOPIC_TITLES or non_ws in PLACEHOLDER_TOPIC_TITLES or stripped_placeholder in PLACEHOLDER_TOPIC_TITLES:
        raise ServiceError("标题不能使用默认占位词，请填写具体的主题或说明", status=400, code="title_placeholder_disallowed")

    residual = RESOURCE_CODE_PATTERN.sub("", raw)
    residual_meaningful = PUNCTUATION_AND_CONNECTORS.sub("", residual)
    if not residual_meaningful:
        raise ServiceError("标题不能仅由编号组成，请添加具体的主题或说明", status=400, code="title_only_resource_code")

    return raw


def publish_forum_topic_post(db: Database, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    cat = str(body.get("category") or "experience")
    cat_map = {
        "tuning": "🎯 作品求调优 / 悬赏",
        "experience": "📘 实战经验与变现",
        "assets": "🎨 画风与图型专区",
        "tools": "🛠️ 工具流与问答",
    }
    if cat not in cat_map:
        cat = "experience"

    title = validate_topic_title(body.get("title"))[:140]
    raw_body = str(body.get("body") or body.get("bodyHtml") or body.get("lockedBody") or body.get("summary") or "附上我的实战配置与思考，欢迎交流！").strip()[:60000]
    clean_body = sanitize_rich_html(raw_body, max_chars=60000)
    price_val = body.get("price")
    if price_val is not None and str(price_val).strip() != "":
        try:
            raw_price = int(price_val)
        except (ValueError, TypeError):
            raise ServiceError("帖子价格必须为有效整数", status=400)
        if raw_price < 0 or raw_price > 100:
            raise ServiceError("帖子价格范围须为 0–100 积分", status=400)
        price = raw_price
    else:
        price = 0

    from .points import validate_price
    validate_price(db.get_conn(),"topic",price)
    if price > 0:
        if "hw-paywall-divider" not in raw_body and "hw-paywall-divider" not in clean_body:
            raise ServiceError("付费帖子缺少付费分界线", status=400)
        divider_match = re.search(
            r"<div[^>]*class=[\"'][^\"']*hw-paywall-divider[^\"']*[\"'][^>]*>.*?</div>\s*</div>|<(?:div|hr)[^>]*class=[\"'][^\"']*hw-paywall-divider[^\"']*[\"'][^>]*>(?:.*?</div>)?|<[^>]*hw-paywall-divider[^>]*>",
            clean_body if "hw-paywall-divider" in clean_body else raw_body,
            flags=re.DOTALL,
        )
        if divider_match:
            after_part = (clean_body if "hw-paywall-divider" in clean_body else raw_body)[divider_match.end():]
        else:
            parts = (clean_body if "hw-paywall-divider" in clean_body else raw_body).split("hw-paywall-divider", 1)
            after_part = parts[1] if len(parts) > 1 else ""
        after_text = re.sub(r"<[^>]+>", " ", after_part).strip()
        has_media = any(tag in after_part for tag in ("<img", "hw-intext-media", "hw-intext-card"))
        if len(after_text) < 4 and not has_media:
            raise ServiceError("付费分界线下方缺少收费正文", status=400)

    bounty = max(0, min(200, int(body.get("bounty") or 0)))
    shared_card = body.get("sharedCard")
    styles = [str(s).strip().upper().lstrip("#") for s in (body.get("styles") or []) if str(s).strip()][:3]
    layout_code = str(body.get("layout") or "").strip().upper().lstrip("#")
    work_id = str(body.get("workId") or "").strip()[:64]

    if isinstance(shared_card, dict):
        card_kind = str(shared_card.get("kind") or "")
        card_id = str(shared_card.get("id") or "").strip()
        if card_kind == "work" and card_id and not work_id:
            work_id = card_id[:64]
        elif card_kind == "style" and card_id and not styles:
            styles = [card_id.upper().lstrip("#")]
        elif card_kind == "layout" and card_id and not layout_code:
            layout_code = card_id.upper().lstrip("#")

    raw_images = body.get("images") or []
    sanitized_images: list[Any] = []
    for item in raw_images:
        if isinstance(item, str):
            safe_u = sanitize_media_url(item, allow_data=True)
            if safe_u:
                sanitized_images.append(safe_u)
        elif isinstance(item, dict):
            raw_u = item.get("url")
            safe_u = sanitize_media_url(str(raw_u or ""), allow_data=True) if raw_u else ""
            if safe_u:
                entry = dict(item)
                entry["url"] = safe_u
                if "tag" in entry:
                    entry["tag"] = sanitize_plain_text(entry.get("tag"), max_chars=100)
                sanitized_images.append(entry)
    images = sanitized_images
    recipe = body.get("recipe")
    if isinstance(shared_card, dict):
        if not recipe or not isinstance(recipe, dict):
            recipe = {"sharedCard": shared_card}
        else:
            recipe["sharedCard"] = shared_card

    # Standalone forum posts can embed a work card, but must never claim the
    # canonical work discussion or bypass its first-comment listing rule.
    # The sharedCard stays inside recipe metadata for visual reference.
    work_id = ""

    uid = int(user["id"])
    now_iso = utc_now_iso()
    now_ms = int(time.time() * 1000)
    tid = f"topic_{now_ms}_{uuid.uuid4().hex[:4]}"

    incoming_summary = str(body.get("summary") or "").strip()
    if incoming_summary:
        summary = sanitize_rich_html(incoming_summary, max_chars=60000)
    elif price > 0 and len(clean_body) > 60:
        clean_text = re.sub(r"<[^>]+>", " ", clean_body).strip()
        summary = (clean_text[:120] if len(clean_text) > 120 else clean_text) + "……（以下为核心实战干货，需付费解锁查看）"
    else:
        summary = clean_body
    locked_raw = (str(body.get("lockedBody") or raw_body)).strip()[:60000] if price > 0 else ""
    locked_body = sanitize_rich_html(locked_raw, max_chars=60000) if locked_raw else ""

    with db.transaction() as tx:
        settings = get_site_settings(tx)
        topic_reward = int(settings.get("economy", {}).get("topic_publish_credits", 0))

        if bounty > 0:
            new_bal, _ = apply_wallet_delta(
                tx,
                uid,
                -bounty,
                "bounty_escrow",
                f"发布求调优悬赏帖《{title[:22]}》托管赏金",
                event_key=f"bounty_escrow_{tid}",
                ref_type="topic",
                ref_id=tid,
            )
            bounty_status = "open"
        else:
            bounty_status = "none"
            if topic_reward > 0:
                new_bal, _ = apply_wallet_delta(
                    tx,
                    uid,
                    topic_reward,
                    "publish_topic",
                    f"发布社区交流帖《{title[:22]}》激励",
                    event_key=f"pub_topic_{tid}",
                    ref_type="topic",
                    ref_id=tid,
                )
            else:
                row = tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
                if row:
                    new_bal = int(row["balance"])
                else:
                    tx.execute(
                        "INSERT INTO wallets (user_id, balance, free_quota_date, free_quota_used, checkin_date, locked, updated_at) VALUES (?, 0, '', 0, '', 0, ?)",
                        (uid, now_iso),
                    )
                    new_bal = 0

        recipe_str = json.dumps(recipe, ensure_ascii=False) if recipe else ""
        try:
            recipe_has_sec = 1 if (recipe and check_obj_has_secret(recipe, tx)) else 0
        except Exception:
            recipe_has_sec = None
        tx.execute(
            """
            INSERT INTO forum_topics (
                id, category, category_label, pinned, featured, title, author_username, author_name,
                views, likes, favorites, price, bounty, bounty_status, solved, accepted_reply_id,
                images_json, styles_json, layout_code, work_id, recipe_json, recipe_has_secret, summary, locked_body,
                status, published_at_ms, created_label, created_at, updated_at, listed_at_ms
            ) VALUES (?, ?, ?, 0, 0, ?, ?, ?, 0, 0, 0, ?, ?, ?, 0, '', ?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, '刚刚', ?, ?, ?)
            """,
            (
                tid,
                cat,
                cat_map[cat],
                title,
                user["username"],
                user["display_name"],
                price,
                bounty,
                bounty_status,
                json.dumps(images[:9], ensure_ascii=False),
                json.dumps(styles, ensure_ascii=False),
                layout_code,
                work_id,
                recipe_str,
                recipe_has_sec,
                summary,
                locked_body,
                now_ms,
                now_iso,
                now_iso,
                now_ms,
            ),
        )

    return {"ok": True, "topicId": tid, "topic": {"id": tid, "price": price}, "credits": new_bal, "bounty": bounty}


def publish_forum_reply_post(
    db: Database,
    user: dict[str, Any],
    topic_id: str,
    text: str,
    mounted_style: str = "",
    mounted_layout: str = "",
    direct: bool = False,
) -> dict[str, Any]:
    from .resource_discussions import find_topic_source, comment, record_atomic_reply_and_listing, ensure_topic
    if not direct:
        source=find_topic_source(db,topic_id)
        if source and source['origin']!='submission':
            return comment(db,user,source['kind'],source['target_id'],text)
    clean = sanitize_plain_text(text, max_chars=3000)
    if not clean:
        raise ServiceError("请输入回复内容")
    clean_style = re.sub(r"[^A-Za-z0-9_-]", "", str(mounted_style or "").strip())[:32].upper().lstrip("#")
    clean_layout = re.sub(r"[^A-Za-z0-9_-]", "", str(mounted_layout or "").strip())[:32].upper().lstrip("#")

    with db.transaction() as tx:
        tp = tx.execute("SELECT id, title FROM forum_topics WHERE id = ? AND status = 'published'", (topic_id,)).fetchone()
        if not tp:
            # Fallback for historical missing topic addressed by work_id
            m_row = tx.execute("SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?", (topic_id,)).fetchone()
            if m_row:
                topic_id = str(m_row["topic_id"])
                tp = tx.execute("SELECT id, title FROM forum_topics WHERE id = ? AND status = 'published'", (topic_id,)).fetchone()
            else:
                w_row = tx.execute("SELECT * FROM works WHERE id = ? AND status = 'published'", (topic_id,)).fetchone()
                if w_row:
                    topic_id = ensure_topic(tx, "work", topic_id, dict(w_row), initial_origin="submission")
                    tp = tx.execute("SELECT id, title FROM forum_topics WHERE id = ? AND status = 'published'", (topic_id,)).fetchone()
            if not tp:
                raise ServiceError("帖子不存在或已下架", status=404)

        rid, cur_bal = record_atomic_reply_and_listing(
            tx,
            topic_id,
            user,
            clean,
            mounted_style=clean_style,
            mounted_layout=clean_layout,
        )

    return {"ok": True, "replyId": rid, "rewarded": 0, "credits": cur_bal}


def accept_forum_bounty_reply(db: Database, user: dict[str, Any], topic_id: str, reply_id: str) -> dict[str, Any]:
    now_iso = utc_now_iso()
    with db.transaction() as tx:
        tp = tx.execute("SELECT * FROM forum_topics WHERE id = ?", (topic_id,)).fetchone()
        if not tp:
            raise ServiceError("帖子不存在", status=404)
        is_staff = user.get("role") in ("admin", "operator", "reviewer")
        if tp["author_username"] != user["username"] and not is_staff:
            raise ServiceError("仅发帖楼主或管理员可采纳悬赏答案", status=403)
        if int(tp["bounty"] or 0) <= 0 or tp["bounty_status"] != "open" or int(tp["solved"]):
            raise ServiceError("该悬赏已结算或未开启悬赏")

        rp = tx.execute("SELECT * FROM forum_replies WHERE id = ? AND topic_id = ?", (reply_id, topic_id)).fetchone()
        if not rp:
            raise ServiceError("未找到对应回复", status=404)
        if rp["author_username"] == tp["author_username"] and not is_staff:
            raise ServiceError("楼主不能采纳自己的回复领赏哦")

        bounty = int(tp["bounty"])
        tx.execute(
            "UPDATE forum_topics SET solved = 1, bounty_status = 'settled', accepted_reply_id = ?, updated_at = ? WHERE id = ?",
            (reply_id, now_iso, topic_id),
        )
        tx.execute("UPDATE forum_replies SET accepted = 1 WHERE id = ?", (reply_id,))

        winner = tx.execute("SELECT id FROM users WHERE username = ?", (rp["author_username"],)).fetchone()
        if winner:
            apply_wallet_delta(
                tx,
                int(winner["id"]),
                bounty,
                "bounty_win",
                f"🏆 调优方案被采纳！获得《{tp['title'][:16]}…》悬赏金",
                event_key=f"bounty_win_{topic_id}",
                ref_type="topic",
                ref_id=topic_id,
            )

        bal = int(tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (int(user["id"]),)).fetchone()["balance"])
    return {"ok": True, "bounty": bounty, "winnerName": rp["author_name"], "credits": bal}


def forum_moderator_action(db: Database, user: dict[str, Any] | None, body: dict[str, Any]) -> dict[str, Any]:
    """Board-scoped moderation & front-stage deletion endpoint for Authors, Forum Moderators, Operators, and Super Admins."""
    if not user or user.get("status") != "active":
        raise ServiceError("请先登录账号", status=401, code="login_required")

    topic_id = str(body.get("topicId") or "").strip()
    action = str(body.get("action") or body.get("op") or "").strip().lower()
    reason = str(body.get("reason") or "").strip()[:200]
    if not topic_id or not action:
        raise ServiceError("缺少帖子 ID 或操作动作")

    uid = int(user["id"])
    u_role = str(user.get("role") or "user")
    norm_role = "operator" if u_role == "reviewer" else u_role
    is_admin = norm_role == "admin"
    is_staff = norm_role in ("admin", "operator")
    now_iso = utc_now_iso()

    with db.transaction() as tx:
        tp = tx.execute("SELECT * FROM forum_topics WHERE id = ?", (topic_id,)).fetchone()
        if not tp:
            raise ServiceError("目标帖子不存在", status=404)

        board_key = str(tp["category"] or "experience")
        mod_row = tx.execute(
            "SELECT * FROM forum_moderators WHERE user_id = ? AND category IN ('all', ?) ORDER BY CASE category WHEN 'all' THEN 0 ELSE 1 END LIMIT 1",
            (uid, board_key),
        ).fetchone()

        is_topic_author = (user["username"].lower() == str(tp["author_username"] or "").lower())
        reply_id = str(body.get("replyId") or "").strip()
        rp = None
        reply_table='forum_replies'
        mapping=tx.execute("SELECT kind,target_id FROM curation_resource_topics WHERE topic_id=? AND origin!='submission' LIMIT 1",(topic_id,)).fetchone()
        if mapping:
            reply_table='work_comments' if mapping['kind']=='work' else 'asset_comments'
        is_reply_author = False
        if reply_id:
            if reply_table=='forum_replies':
                rp=tx.execute("SELECT * FROM forum_replies WHERE id=? AND topic_id=?",(reply_id,topic_id)).fetchone()
            elif reply_table=='work_comments':
                rp=tx.execute('SELECT * FROM work_comments WHERE id=? AND work_id=?',(reply_id,mapping['target_id'])).fetchone()
            else:
                rp=tx.execute('SELECT * FROM asset_comments WHERE id=? AND asset_code=? AND asset_kind=?',(reply_id,mapping['target_id'],mapping['kind'])).fetchone()
            if rp:
                is_reply_author = (user["username"].lower() == str(rp["author_username"] or "").lower())

        is_authorized = False
        if action in ("delete", "delete_topic"):
            is_authorized = is_topic_author or is_staff or bool(mod_row)
        elif action in ("delete_reply",):
            is_authorized = is_reply_author or is_staff or bool(mod_row)
        else:
            is_authorized = is_staff or bool(mod_row)

        if not is_authorized:
            board_lbl = FORUM_BOARD_LABELS.get(board_key, board_key)
            raise ServiceError(f"权限不足：你不是「{board_lbl}」板块版主或作者本人，无法执行该操作", status=403, code="not_authorized")

        # Anti-self-review for operators on pin/feature
        if action in ("pin", "feature") and not is_admin and is_topic_author:
            raise ServiceError("风控限制：运营审查员禁止自审自荐本人发布的内容（如加精、置顶）", status=403, code="self_review_forbidden")

        actor_for_audit = user if is_staff else (dict(user, role=f"moderator:{mod_row['category']}") if mod_row else user)
        actor_role = staff_actor_role(user, board_moderator=bool(mod_row))

        if action == "pin":
            tx.execute("UPDATE forum_topics SET pinned = 1, updated_at = ? WHERE id = ?", (now_iso, topic_id))
        elif action == "unpin":
            tx.execute("UPDATE forum_topics SET pinned = 0, updated_at = ? WHERE id = ?", (now_iso, topic_id))
        elif action == "feature":
            tx.execute("UPDATE forum_topics SET featured = 1, updated_at = ? WHERE id = ?", (now_iso, topic_id))
        elif action == "unfeature":
            tx.execute("UPDATE forum_topics SET featured = 0, updated_at = ? WHERE id = ?", (now_iso, topic_id))
        elif action == "move":
            target_cat = str(body.get("targetCategory") or "").strip()
            valid_cats = {
                "tuning": "🎯 作品求调优 / 悬赏",
                "experience": "📘 实战经验与变现",
                "assets": "🎨 画风与图型专区",
                "tools": "🛠️ 工具流与问答",
            }
            if target_cat not in valid_cats:
                raise ServiceError("目标板块无效")
            tx.execute(
                "UPDATE forum_topics SET category = ?, category_label = ?, updated_at = ? WHERE id = ?",
                (target_cat, valid_cats[target_cat], now_iso, topic_id),
            )
        elif action == "hide":
            author_u = tx.execute("SELECT role FROM users WHERE username = ?", (tp["author_username"],)).fetchone()
            if not is_admin and author_u and author_u["role"] == "admin":
                raise ServiceError("无权隐藏超级管理员发布的公告或帖子", status=403)
            set_topic_visibility(
                tx, topic_id, "hidden", now_iso,
                source="moderator", reason=str(body.get("reason") or "")[:200] or "版主隐藏",
                actor_role=actor_role,
            )
        elif action == "publish":
            # Every rule lives in set_topic_visibility, shared with the admin
            # entry, so the two cannot disagree about a deleted or job-blocked
            # thread.
            set_topic_visibility(tx, topic_id, "published", now_iso, source="moderator", actor_role=actor_role)
        elif action in ("delete", "delete_topic"):
            if not is_admin and not is_topic_author:
                author_u = tx.execute("SELECT role FROM users WHERE username = ?", (tp["author_username"],)).fetchone()
                if author_u and author_u["role"] == "admin":
                    raise ServiceError("无权删除超级管理员发布的帖子", status=403)
            tx.execute("DELETE FROM forum_replies WHERE topic_id = ?", (topic_id,))
            tx.execute("DELETE FROM collections WHERE bucket = 'topics' AND target_id = ?", (topic_id,))
            mapped=tx.execute('SELECT 1 FROM curation_resource_topics WHERE topic_id=?',(topic_id,)).fetchone()
            if mapped:
                # A resource thread keeps its row so the mapping stays valid;
                # 'deleted' with a source means no later work change revives it.
                set_topic_visibility(
                    tx, topic_id, "deleted", now_iso,
                    source="author" if is_topic_author and not (is_staff or mod_row) else "moderator",
                    reason="作者删除" if is_topic_author else (reason or "版主删除"),
                    actor_role=actor_role,
                )
            else:
                tx.execute("DELETE FROM forum_topics WHERE id = ?", (topic_id,))
        elif action == "hide_reply":
            if not rp:
                raise ServiceError("未找到目标回复", status=404)
            rp_author_u = tx.execute("SELECT role FROM users WHERE username = ?", (rp["author_username"],)).fetchone()
            if not is_admin and rp_author_u and rp_author_u["role"] == "admin":
                raise ServiceError("无权隐藏超级管理员的回复", status=403)
            set_comment_visibility(tx, reply_table, reply_id, "hidden", actor_role)
        elif action == "publish_reply":
            if not rp:
                raise ServiceError("未找到目标回复", status=404)
            set_comment_visibility(tx, reply_table, reply_id, "published", actor_role)
        elif action == "delete_reply":
            if not rp:
                raise ServiceError("未找到目标回复", status=404)
            if not is_admin and not is_reply_author:
                rp_author_u = tx.execute("SELECT role FROM users WHERE username = ?", (rp["author_username"],)).fetchone()
                if rp_author_u and rp_author_u["role"] == "admin":
                    raise ServiceError("无权删除超级管理员的回复", status=403)
            tx.execute(f"DELETE FROM {reply_table} WHERE id=?", (reply_id,))
            tx.execute("UPDATE forum_topics SET accepted_reply_id = NULL, solved = 0 WHERE id = ? AND accepted_reply_id = ?", (topic_id, reply_id))
        else:
            raise ServiceError(f"不支持的帖子操作：{action}")

        record_audit_log(
            tx,
            actor_for_audit,
            f"forum.mod.{action}",
            "topic",
            topic_id,
            reason or f"论坛治理操作：{action}",
            {
                "board": board_key,
                "title": tp["title"],
                "targetCategory": body.get("targetCategory"),
                "replyId": reply_id,
            },
        )
    return {"ok": True, "topicId": topic_id, "action": action}


def submit_abuse_report(db: Database, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    target_type = str(body.get("targetType") or "work")
    if target_type not in ("work", "topic", "asset", "reply", "comment", "dm_message"):
        raise ServiceError("不支持的举报目标类型")
    target_id = str(body.get("targetId") or "").strip()
    reason = str(body.get("reason") or "内容疑似违规或标注不实").strip()[:120]
    detail = str(body.get("detail") or "").strip()[:600]
    if not target_id:
        raise ServiceError("缺少举报对象 ID")

    now_iso = utc_now_iso()
    uid = int(user["id"])

    with db.transaction() as tx:
        settings = get_site_settings(tx)
        threshold = max(1, int(settings.get("moderation", {}).get("auto_pause_report_threshold", 3)))

        target_title = target_id
        if target_type == "work":
            r = tx.execute("SELECT title FROM works WHERE id = ?", (target_id,)).fetchone()
            if r:
                target_title = r["title"]
        elif target_type == "topic":
            r = tx.execute("SELECT title FROM forum_topics WHERE id = ?", (target_id,)).fetchone()
            if r:
                target_title = r["title"]
        elif target_type == "asset":
            r = tx.execute("SELECT name FROM catalog_assets WHERE code = ?", (target_id,)).fetchone()
            if r:
                target_title = f"{target_id} {r['name']}"
        elif target_type == "dm_message":
            from .messaging import handle_dm_report_target
            target_title, detail = handle_dm_report_target(tx, uid, target_id, detail)

        # One open report per account per target.  Counting rows let a single
        # account pause any content by reporting it `threshold` times.
        duplicate = tx.execute(
            "SELECT 1 FROM reports WHERE reporter_id = ? AND target_type = ? AND target_id = ? AND status = 'open'",
            (uid, target_type, target_id),
        ).fetchone() is not None
        if not duplicate:
            tx.execute(
                """
                INSERT INTO reports (reporter_id, reporter_username, target_type, target_id, target_title, reason, detail, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
                """,
                (uid, user["username"], target_type, target_id, target_title, reason, detail, now_iso),
            )

        # The threshold counts distinct reporters, so legacy duplicate rows
        # cannot reach it either.
        open_cnt = int(
            tx.execute(
                "SELECT COUNT(DISTINCT reporter_id) FROM reports WHERE target_type = ? AND target_id = ? AND status = 'open'",
                (target_type, target_id),
            ).fetchone()[0]
        )
        auto_paused = False
        if open_cnt >= threshold and not duplicate:
            if target_type == "work":
                # Only auto-pause a live work.  A work an admin already hid must
                # not be downgraded to "paused", because a later rejection would
                # then republish it.
                auto_paused = set_work_visibility(
                    tx, target_id, "paused", now_iso,
                    source="report", reason=f"举报达到阈值（{open_cnt} 人）",
                    automated=True, allow_from=("published",), allow_sources=("",),
                )
            elif target_type == "topic":
                # Only a live thread is paused; anything already dark (hidden by
                # a human, deleted, mirroring a hidden work) is left alone.
                auto_paused = set_topic_visibility(
                    tx, target_id, "paused", now_iso,
                    source="report", reason=f"举报达到阈值（{open_cnt} 人）",
                    automated=True, allow_from=("published",),
                )
            elif target_type == "asset":
                cursor = tx.execute("UPDATE catalog_assets SET status = 'paused', updated_at = ? WHERE code = ? AND status = 'published'", (now_iso, target_id))
                auto_paused = cursor.rowcount > 0
        if auto_paused:
            record_audit_log(
                tx,
                None,
                "moderation.auto_pause",
                target_type,
                target_id,
                f"累计待处理举报达 {open_cnt} 次，触发自动保护性暂停展示",
                {"openReports": open_cnt, "threshold": threshold},
            )

    return {"ok": True, "openReports": open_cnt, "autoPaused": auto_paused}


# ======================== STUDIO CLOUD PERSISTENCE & QUOTA/BLACKBOX ENGINE ========================

def sanitize_client_error_msg(error_msg: Any, status: Any = None) -> str:
    """Map client-facing error message to generic status/code, never leaking raw stored text (H4)."""
    if status not in ("failed", "error") and not error_msg:
        return ""
    err_str = str(error_msg or "").strip()
    m = re.search(r"\b(4\d\d|5\d\d)\b", err_str)
    if m:
        return f"网关请求失败 (HTTP {m.group(1)})"
    if "4000" in err_str or "prompt_too_long" in err_str:
        return "提示词加上系统说明后超过 4000 字上限，请精简提示词"
    if "timeout" in err_str.lower() or "超时" in err_str:
        return "云端任务超时，请稍后重试"
    return "云端生成失败，请稍后重试"


def serialize_public_generation_history(
    row: dict[str, Any],
    conn: PgConnection | None = None,
) -> dict[str, Any]:
    row_keys = row.keys() if hasattr(row, "keys") else row
    raw_id = str(row["id"])
    author = str(row["username"] or "") if "username" in row_keys else ""
    created_at = str(row["created_at"]) if "created_at" in row_keys else ""

    raw_items_str = row["items_json"] if "items_json" in row_keys else "[]"
    try:
        raw_items = json.loads(raw_items_str or "[]")
    except Exception:
        raw_items = []
    images: list[str] = []
    for it in (raw_items if isinstance(raw_items, list) else []):
        if isinstance(it, str) and it.strip():
            images.append(it.strip())
        elif isinstance(it, dict) and it.get("imageUrl"):
            images.append(str(it["imageUrl"]).strip())

    topic = ""
    if "subject" in row_keys and row["subject"]:
        topic = str(row["subject"]).strip()
    elif "recipe_id" in row_keys and row["recipe_id"] and conn:
        try:
            rcp = conn.execute("SELECT subject FROM studio_recipes WHERE id = ?", (row["recipe_id"],)).fetchone()
            if rcp and rcp["subject"]:
                topic = str(rcp["subject"]).strip()
        except Exception:
            pass
    if not topic:
        for it in (raw_items if isinstance(raw_items, list) else []):
            if isinstance(it, dict) and it.get("subject"):
                topic = str(it["subject"]).strip()
                break
            if isinstance(it, dict) and isinstance(it.get("recipeSnapshot"), dict) and it["recipeSnapshot"].get("subject"):
                topic = str(it["recipeSnapshot"]["subject"]).strip()
                break
    if not topic:
        topic = "手绘创作"

    raw_tab = str(row["tab_title"] or "") if "tab_title" in row_keys else ""
    ratio = raw_tab if re.match(r"^\d+:\d+$", raw_tab) else "3:4"
    mode = str(row["mode"] or "graphic-text") if "mode" in row_keys else "graphic-text"

    CODE_RE = re.compile(r"^(?:USR-)?[A-Z]{1,4}-[A-Z0-9]+$")

    codes: list[str] = []

    # Priority 1: Trusted server snapshot in system_append_json
    if "system_append_json" in row_keys and row["system_append_json"]:
        try:
            s_data = json.loads(row["system_append_json"])
            if isinstance(s_data, dict):
                sys_app = s_data.get("systemAppend") or s_data.get("system_append") or []
                if isinstance(sys_app, list):
                    for it in sys_app:
                        if isinstance(it, dict):
                            raw_c = str(it.get("code") or "").strip().upper().lstrip("#")
                            if CODE_RE.match(raw_c) and raw_c not in codes:
                                codes.append(raw_c)
                snap = s_data.get("recipeSnapshot")
                if isinstance(snap, dict):
                    for k in ("style1", "style2", "layout"):
                        raw_c = str(snap.get(k) or "").strip().upper().lstrip("#")
                        if CODE_RE.match(raw_c) and raw_c not in codes:
                            codes.append(raw_c)
            elif isinstance(s_data, list):
                for it in s_data:
                    if isinstance(it, dict):
                        raw_c = str(it.get("code") or "").strip().upper().lstrip("#")
                        if CODE_RE.match(raw_c) and raw_c not in codes:
                            codes.append(raw_c)
        except Exception:
            pass

    # Priority 2: Linked recipe record if codes still empty
    if not codes and "recipe_id" in row_keys and row["recipe_id"] and conn:
        try:
            rcp = conn.execute("SELECT style_ids, layout_id FROM studio_recipes WHERE id = ?", (row["recipe_id"],)).fetchone()
            if rcp:
                try:
                    s_ids = json.loads(rcp["style_ids"] or "[]")
                    if isinstance(s_ids, list):
                        for s in s_ids:
                            raw_c = str(s).strip().upper().lstrip("#")
                            if CODE_RE.match(raw_c) and raw_c not in codes:
                                codes.append(raw_c)
                except Exception:
                    pass
                lay_c = str(rcp["layout_id"] or "").strip().upper().lstrip("#")
                if CODE_RE.match(lay_c) and lay_c not in codes:
                    codes.append(lay_c)
        except Exception:
            pass

    # Priority 3: Clean tokens from recipe_summary (only exact CODE_RE matches, NO eval or fuzzy guessing)
    if not codes and "recipe_summary" in row_keys and row["recipe_summary"]:
        raw_summary = str(row["recipe_summary"]).strip()
        tokens = re.split(r"[\s/·,]+", raw_summary)
        for t in tokens:
            raw_c = t.strip().upper().lstrip("#")
            if CODE_RE.match(raw_c) and raw_c not in codes:
                codes.append(raw_c)

    from . import resource_registry
    styles: list[dict[str, str]] = []
    layouts: list[dict[str, str]] = []
    seen_codes: set[str] = set()
    for c in codes:
        if c in seen_codes:
            continue
        seen_codes.add(c)
        name = c
        kind = "style"
        if conn:
            res_meta = resource_registry.resolve(conn, c, viewer=None, purpose="view")
            if res_meta:
                name = str(res_meta.get("name") or c).strip()
                kind = str(res_meta.get("kind") or "style").strip()
        else:
            cat = resource_registry.static_catalog().get(c)
            if cat:
                name = str(cat.get("name") or c).strip()
                kind = str(cat.get("kind") or "style").strip()
        entry = {"code": c, "name": name or c}
        if kind == "layout" or c.startswith(("SC-", "IG-", "SB-", "IP-", "EC-", "LAY-", "USR-L")):
            layouts.append(entry)
        else:
            styles.append(entry)

    fork_src = None
    if "fork_generation_id" in row_keys and row["fork_generation_id"]:
        fid = str(row["fork_generation_id"]).strip()
        if fid:
            if conn:
                s_row = conn.execute(
                    "SELECT id, user_id, username, visibility, status, deleted_at, engine FROM studio_generations WHERE id = ?",
                    (fid,),
                ).fetchone()
                if (
                    s_row
                    and str(s_row["status"] or "") == "success"
                    and not s_row["deleted_at"]
                    and str(s_row["engine"] or "") != "demo"
                    and str(s_row["visibility"] or "") == "public"
                ):
                    u_row = conn.execute("SELECT display_name FROM users WHERE username = ?", (s_row["username"],)).fetchone()
                    fork_src = {
                        "generationId": s_row["id"],
                        "itemId": str(row["fork_item_id"]) if "fork_item_id" in row_keys else "",
                        "author": s_row["username"],
                        "authorName": u_row["display_name"] if (u_row and u_row["display_name"]) else s_row["username"],
                        "visible": True,
                    }
                else:
                    fork_src = {"visible": False}
            else:
                fork_src = {"visible": False}

    return {
        "id": raw_id,
        "author": author,
        "createdAt": format_short_time(created_at) if created_at else "",
        "created_at": created_at,
        "images": images,
        "topic": topic,
        "title": topic,
        "subject": topic,
        "ratio": ratio,
        "mode": mode,
        "styles": styles,
        "layouts": layouts,
        "imageCount": len(images),
        "fork": fork_src,
    }


def get_public_generation_history(
    db: Database,
    history_id: str = "",
    *,
    limit: int = 40,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Global public generated works, never raw gateway executions."""
    conn = db.get_conn()
    query = """
        SELECT r.id AS run_id,r.user_id,r.source,r.external_run_id,r.created_at,
               w.id AS work_id,w.title AS work_title,w.author_username
        FROM generation_runs r JOIN works w ON w.run_id=r.id
        WHERE w.status='published'
    """
    params: list[Any] = []
    if history_id:
        try:
            wid = _generation_work_id(conn, history_id)
        except ServiceError:
            return None
        query += " AND w.id=?"
        params.append(wid)
    query += " ORDER BY r.created_at DESC,r.id DESC LIMIT ?"
    params.append(1 if history_id else max(1, min(100, int(limit))))
    rows = conn.execute(query, tuple(params)).fetchall()
    if history_id and not rows:
        return None
    items = [_serialize_public_run_work(conn, row) for row in rows]
    attach_generation_social_counts(conn, items, viewer=None)
    return items[0] if history_id else items


def _serialize_public_run_work(
    conn: PgConnection, row: dict[str, Any],
) -> dict[str, Any]:
    """The public creator-history card is a view of one published work/run."""
    from .generation_v3 import work_images

    uid = int(row["user_id"])
    run_id = str(row["run_id"])
    wid = str(row["work_id"])
    images = work_images(conn, wid)
    source = str(row["source"])
    metadata: dict[str, Any] = {}
    if source == "web":
        gateway = conn.execute(
            """
            SELECT * FROM studio_generations
            WHERE user_id=? AND status='success'
              AND (id=? OR (batch_id<>'' AND batch_id=?))
              AND COALESCE(deleted_at,'')=''
            ORDER BY batch_index ASC,created_at ASC,id ASC LIMIT 1
            """,
            (uid, row["external_run_id"], row["external_run_id"]),
        ).fetchone()
        if gateway:
            metadata = serialize_public_generation_history(gateway, conn)
            metadata["sourceGenerationId"] = str(gateway["id"])
    if not metadata:
        metadata = {
            "styles": [], "layouts": [], "fork": None, "mode": source,
            "ratio": "3:4", "createdAt": "",
        }
    # No generation-record likes, favorite buckets or duplicated public
    # media arrays. All media and interactions come from this ONE work.
    subject = str(row["work_title"] or "手绘创作")
    metadata.update({
        "id": run_id,
        "runId": run_id,
        "workId": wid,
        "author": str(row["author_username"]),
        "created_at": str(row["created_at"]),
        "createdAt": format_short_time(row["created_at"]),
        "images": images,
        "imageCount": len(images),
        "topic": subject,
        "title": subject,
        "subject": subject,
        "originClient": source,
    })
    return metadata


def get_user_public_generations(
    db: Database,
    username: str,
    *,
    cursor: str = "",
    limit: int = 24,
    viewer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Public creator history: one row per published logical run and work."""
    conn = db.get_conn()
    u_row = conn.execute(
        "SELECT id FROM users WHERE username=?", (str(username or "").strip(),),
    ).fetchone()
    if not u_row:
        raise ServiceError("创作者不存在", status=404, code="user_not_found")
    uid = int(u_row["id"])
    safe_limit = max(1, min(60, int(limit)))
    since = None
    if cursor:
        try:
            import base64
            since = base64.urlsafe_b64decode(str(cursor).encode("ascii")).decode("utf-8").split("|", 1)
        except (ValueError, UnicodeError):
            raise ServiceError("无效的分页游标", status=400, code="invalid_cursor") from None
        if len(since) != 2 or not all(since):
            raise ServiceError("无效的分页游标", status=400, code="invalid_cursor")

    sql = """
        SELECT r.id AS run_id,r.user_id,r.source,r.external_run_id,r.created_at,
               w.id AS work_id,w.title AS work_title,w.author_username
        FROM generation_runs r JOIN works w ON w.run_id=r.id
        WHERE r.user_id=? AND w.status='published'
    """
    params: list[Any] = [uid]
    if since:
        sql += " AND (r.created_at<? OR (r.created_at=? AND r.id<?))"
        params.extend([since[0], since[0], since[1]])
    sql += " ORDER BY r.created_at DESC,r.id DESC LIMIT ?"
    params.append(safe_limit + 1)
    rows = conn.execute(sql, tuple(params)).fetchall()
    visible = rows[:safe_limit]
    items = [_serialize_public_run_work(conn, row) for row in visible]
    attach_generation_social_counts(conn, items, viewer=viewer)
    next_cursor = None
    if len(rows) > safe_limit and visible:
        import base64
        last = visible[-1]
        next_cursor = base64.urlsafe_b64encode(
            f"{last['created_at']}|{last['run_id']}".encode("utf-8")
        ).decode("ascii")
    total_row = conn.execute(
        """
        SELECT COUNT(*) FROM generation_runs r JOIN works w ON w.run_id=r.id
        WHERE r.user_id=? AND w.status='published'
        """,
        (uid,),
    ).fetchone()
    return {
        "ok": True, "generations": items, "nextCursor": next_cursor,
        "hasMore": len(rows) > safe_limit,
        "total": int(total_row[0]) if total_row else len(items),
    }


def get_user_public_generation_by_id(
    db: Database,
    username: str,
    generation_id: str,
    *,
    viewer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the public work, not a single Web gateway subrequest."""
    conn = db.get_conn()
    u_row = conn.execute(
        "SELECT id FROM users WHERE username=?", (str(username or "").strip(),),
    ).fetchone()
    if not u_row:
        raise ServiceError("创作者不存在", status=404, code="user_not_found")
    uid = int(u_row["id"])
    identifier = str(generation_id or "").strip()
    try:
        wid = _generation_work_id(conn, identifier)
    except ServiceError:
        raise ServiceError("生图作品不存在或不可见", status=404, code="not_found") from None
    row = conn.execute(
        """
        SELECT r.id AS run_id,r.user_id,r.source,r.external_run_id,r.created_at,
               w.id AS work_id,w.title AS work_title,w.author_username
        FROM works w JOIN generation_runs r ON r.id=w.run_id
        WHERE w.id=? AND r.user_id=? AND w.status='published'
        """,
        (wid, uid),
    ).fetchone()
    if not row:
        raise ServiceError("生图作品不存在或不可见", status=404, code="not_found")
    item = _serialize_public_run_work(conn, row)
    attach_generation_social_counts(conn, [item], viewer=viewer)
    return {"ok": True, "generation": item}


def get_user_collected_generations(
    db: Database,
    user: dict[str, Any],
    limit: int = 60,
) -> dict[str, Any]:
    """Generated works in the ONE canonical favorites bucket ('works')."""
    conn = db.get_conn()
    uid = int(user["id"])
    safe_limit = max(1, min(100, int(limit)))
    rows = conn.execute(
        """
        SELECT r.id AS run_id,r.user_id,r.source,r.external_run_id,r.created_at,
               w.id AS work_id,w.title AS work_title,w.author_username
        FROM collections c JOIN works w ON w.id=c.target_id
        JOIN generation_runs r ON r.id=w.run_id
        WHERE c.user_id=? AND c.bucket='works' AND w.status='published'
        ORDER BY c.created_at DESC,w.id DESC LIMIT ?
        """,
        (uid, safe_limit),
    ).fetchall()
    items = [_serialize_public_run_work(conn, row) for row in rows]
    attach_generation_social_counts(conn, items, viewer=user)
    return {"ok": True, "generations": items}


def fork_generation_recipe(
    db: Database,
    user: dict[str, Any],
    generation_id: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare a studio draft from an existing visible generation record without charging or generating."""
    conn = db.get_conn()
    uid = int(user["id"])
    gen_id = str(generation_id or "").strip()
    body = body or {}

    row = conn.execute(
        "SELECT * FROM studio_generations WHERE id = ?",
        (gen_id,),
    ).fetchone()

    if not check_generation_social_accessible(row, viewer=user, allow_own=True):
        raise ServiceError("生图记录不存在或不可见", status=404, code="not_found")

    raw_items_str = row["items_json"] if "items_json" in row.keys() else "[]"
    try:
        raw_items = json.loads(raw_items_str or "[]")
    except Exception:
        raw_items = []
    if not isinstance(raw_items, list) or not raw_items:
        raise ServiceError("生图记录不存在或无结果图片", status=404, code="not_found")

    req_item_id = str(body.get("itemId") or body.get("item_id") or "").strip()
    chosen_item = None
    chosen_item_id = ""

    if req_item_id:
        for idx, it in enumerate(raw_items):
            cur_id = it.get("id") if isinstance(it, dict) else f"{gen_id}_{idx}"
            cur_url = it.get("imageUrl") if isinstance(it, dict) else it
            if cur_id == req_item_id or cur_url == req_item_id:
                chosen_item = it
                chosen_item_id = str(cur_id)
                break
        if chosen_item is None:
            raise ServiceError("未找到指定的图片条目，无法复刻", status=400, code="item_not_found")
    else:
        chosen_item = raw_items[0]
        chosen_item_id = chosen_item.get("id") if isinstance(chosen_item, dict) else f"{gen_id}_0"

    CODE_RE = re.compile(r"^(?:USR-)?[A-Z]{1,4}-[A-Z0-9]+$")

    style_ids: list[str] = []
    layout_id = ""
    colors: list[str] = []
    tones: list[str] = []
    moods: list[str] = []
    whitespace = ""
    ratio = "3:4"
    mode = str(row["mode"] or "graphic-text") if "mode" in row.keys() else "graphic-text"
    raw_tab = str(row["tab_title"] or "") if "tab_title" in row.keys() else ""
    if re.match(r"^\d+:\d+$", raw_tab):
        ratio = raw_tab

    # 1. Check chosen_item if it carries its own recipe (e.g. batch item)
    if isinstance(chosen_item, dict):
        if chosen_item.get("ratio"):
            ratio = str(chosen_item["ratio"])
        if chosen_item.get("mode"):
            mode = str(chosen_item["mode"])
        if chosen_item.get("styleIds") and isinstance(chosen_item["styleIds"], list):
            for s in chosen_item["styleIds"]:
                c = str(s).strip().upper().lstrip("#")
                if CODE_RE.match(c) and c not in style_ids:
                    style_ids.append(c)
        if chosen_item.get("layoutId"):
            c = str(chosen_item["layoutId"]).strip().upper().lstrip("#")
            if CODE_RE.match(c):
                layout_id = c
        if chosen_item.get("recipeSnapshot") and isinstance(chosen_item["recipeSnapshot"], dict):
            snap = chosen_item["recipeSnapshot"]
            for k in ("style1", "style2"):
                c = str(snap.get(k) or "").strip().upper().lstrip("#")
                if CODE_RE.match(c) and c not in style_ids:
                    style_ids.append(c)
            if not layout_id and snap.get("layout"):
                c = str(snap["layout"]).strip().upper().lstrip("#")
                if CODE_RE.match(c):
                    layout_id = c

    # 2. Check row's system_append_json
    if not style_ids and not layout_id and "system_append_json" in row.keys() and row["system_append_json"]:
        try:
            s_data = json.loads(row["system_append_json"])
            if isinstance(s_data, dict):
                snap = s_data.get("recipeSnapshot")
                if isinstance(snap, dict):
                    for k in ("style1", "style2"):
                        c = str(snap.get(k) or "").strip().upper().lstrip("#")
                        if CODE_RE.match(c) and c not in style_ids:
                            style_ids.append(c)
                    if snap.get("layout"):
                        c = str(snap["layout"]).strip().upper().lstrip("#")
                        if CODE_RE.match(c):
                            layout_id = c
                sys_app = s_data.get("systemAppend") or s_data.get("system_append") or []
                if isinstance(sys_app, list):
                    for it in sys_app:
                        if isinstance(it, dict):
                            c = str(it.get("code") or "").strip().upper().lstrip("#")
                            if CODE_RE.match(c):
                                if c.startswith(("SC-", "IG-", "SB-", "IP-", "EC-", "LAY-", "USR-L")):
                                    if not layout_id:
                                        layout_id = c
                                elif c not in style_ids:
                                    style_ids.append(c)
        except Exception:
            pass

    # 3. Check row's recipe_id
    if (not style_ids or not layout_id) and "recipe_id" in row.keys() and row["recipe_id"]:
        try:
            rcp = conn.execute("SELECT * FROM studio_recipes WHERE id = ?", (row["recipe_id"],)).fetchone()
            if rcp:
                try:
                    s_list = json.loads(rcp["style_ids"] or "[]")
                    for s in s_list:
                        c = str(s).strip().upper().lstrip("#")
                        if CODE_RE.match(c) and c not in style_ids:
                            style_ids.append(c)
                except Exception:
                    pass
                if not layout_id and rcp["layout_id"]:
                    c = str(rcp["layout_id"]).strip().upper().lstrip("#")
                    if CODE_RE.match(c):
                        layout_id = c
                if rcp["colors"]:
                    try:
                        colors = json.loads(rcp["colors"] or "[]")
                    except Exception:
                        pass
                if rcp["tones"]:
                    try:
                        tones = json.loads(rcp["tones"] or "[]")
                    except Exception:
                        pass
                if rcp["moods"]:
                    try:
                        moods = json.loads(rcp["moods"] or "[]")
                    except Exception:
                        pass
                if rcp["whitespace"]:
                    whitespace = str(rcp["whitespace"])
                if rcp["ratio"]:
                    ratio = str(rcp["ratio"])
                if rcp["mode"]:
                    mode = str(rcp["mode"])
        except Exception:
            pass

    # 4. Check row's recipe_summary
    if not style_ids and not layout_id and "recipe_summary" in row.keys() and row["recipe_summary"]:
        tokens = re.split(r"[\s/·,]+", str(row["recipe_summary"]).strip())
        for t in tokens:
            c = t.strip().upper().lstrip("#")
            if CODE_RE.match(c):
                if c.startswith(("SC-", "IG-", "SB-", "IP-", "EC-", "LAY-", "USR-L")):
                    if not layout_id:
                        layout_id = c
                elif c not in style_ids:
                    style_ids.append(c)

    # 5. Must be reliably restorable
    if not style_ids and not layout_id:
        raise ServiceError("该记录缺少可复刻的配方参数，无法可靠还原", status=400, code="cannot_fork")

    # Subject extraction
    user_subject = ""
    if "subject" in row.keys() and row["subject"]:
        user_subject = str(row["subject"]).strip()
    if not user_subject:
        user_subject = "手绘创作"

    u_author = conn.execute("SELECT display_name FROM users WHERE username = ?", (row["username"],)).fetchone()
    author_name = (u_author["display_name"] if (u_author and u_author["display_name"]) else row["username"])

    return {
        "ok": True,
        "draft": {
            "kind": "single",
            "styleIds": style_ids,
            "layoutId": layout_id,
            "colors": colors,
            "tones": tones,
            "moods": moods,
            "whitespace": whitespace,
            "ratio": ratio,
            "mode": mode,
            "subject": user_subject,
            "subjectHint": user_subject,
            "references": [],
            "prompt": "",
            "promptCustomized": False,
            "promptStale": False,
        },
        "source": {
            "generationId": row["id"],
            "itemId": chosen_item_id,
            "author": row["username"],
            "authorName": author_name,
        },
    }


def _canonical_studio_history(
    conn: PgConnection, legacy_ui_entries: list[dict[str, Any]], *, runs,
) -> list[dict[str, Any]]:
    """Use generation_runs/items as the only logical task/media truth.

    studio_generations contains gateway executions, reservation receipts and
    recipe snapshots, but not independent user-facing generation histories.
    A batch's output order, success/failure state, and work ownership all
    come from the V3 run/items tables. No legacy data migration is performed.
    """
    by_web_key = {
        str(entry.get("batchId") or entry.get("id") or ""): entry
        for entry in legacy_ui_entries
    }
    slots_by_run = {}
    run_ids = [r["id"] for r in runs]
    if run_ids:
        for slot in conn.execute(
            """SELECT i.run_id,i.id,i.position,i.status,i.error_code,
                      COALESCE(result.storage_key,primary_media.storage_key) AS image_url,
                      am.ordinal AS output_ordinal,
                      billing.settled_cents,billing.held_cents,billing.free_used,billing.free_held,billing.charge_count
               FROM generation_items i
               LEFT JOIN LATERAL (
                 SELECT g.id FROM studio_generations g WHERE g.item_id=i.id AND g.status='success'
                 ORDER BY g.attempt_no DESC,g.id DESC LIMIT 1
               ) attempt ON true
               LEFT JOIN generation_attempt_media am ON am.attempt_id=attempt.id
               LEFT JOIN media_assets result ON result.id=am.media_id
               LEFT JOIN media_assets primary_media ON primary_media.id=i.media_id
               LEFT JOIN LATERAL (
                 SELECT COALESCE(sum(c.amount_cents) FILTER(WHERE c.status='settled'),0) settled_cents,
                        COALESCE(sum(c.amount_cents) FILTER(WHERE c.status='reserved'),0) held_cents,
                        count(*) FILTER(WHERE c.status='settled' AND c.quota_source IS NOT NULL) free_used,
                        count(*) FILTER(WHERE c.status='reserved' AND c.quota_source IS NOT NULL) free_held,
                        count(*) charge_count
                 FROM generation_charges c LEFT JOIN studio_generations g ON g.id=c.generation_id
                 WHERE c.item_id=i.id OR g.item_id=i.id
               ) billing ON true
               WHERE i.run_id=ANY(?) AND i.retired_at IS NULL ORDER BY i.run_id,i.position,am.ordinal""", (run_ids,),
        ).fetchall():
            slots_by_run.setdefault(slot["run_id"], []).append(slot)
    result: list[dict[str, Any]] = []
    for run in runs:
        source = str(run["source"])
        key = str(run["external_run_id"])
        # The legacy UI entry still provides the Web recipe canvas snapshot.
        # Do not resurrect generations deleted by their owner.
        existing = by_web_key.get(key) if source == "web" else None
        if source == "web" and not existing and run["creation_mode"] != "canvas":
            continue
        if source not in ("web", "skill", "api"):
            continue
        work_id = str(run["work_id"] or "")
        slots = slots_by_run.get(run["id"], [])
        original_by_url = {
            str(item.get("imageUrl") or ""): item
            for item in (existing or {}).get("items", [])
            if isinstance(item, dict) and item.get("imageUrl")
        }
        completed: list[dict[str, Any]] = []
        output_slots: list[dict[str, Any]] = []
        seen_tasks = set()
        for slot in slots:
            url = str(slot["image_url"] or "")
            state = str(slot["status"])
            public_slot = {
                "id": str(slot["id"]),
                "position": int(slot["position"]),
                "status": state,
                "imageUrl": url if state == "success" else "",
                "errorCode": str(slot["error_code"] or ""),
            }
            if public_slot["id"] not in seen_tasks:
                output_slots.append(public_slot)
                seen_tasks.add(public_slot["id"])
            if state == "success" and url:
                img = dict(original_by_url.get(url, {}))
                img.update(public_slot)
                if slot["output_ordinal"] is not None:
                    img["id"] = f"{public_slot['id']}:media:{slot['output_ordinal']}"
                if work_id:
                    img["workId"] = work_id
                completed.append(img)
        if existing:
            entry = dict(existing)
            entry["items"] = completed
        else:
            safe_topic, masked = sanitize_prompt_for_client(
                str(run["original_request"] or ""), conn,
            )
            entry = {
                "id": str(run["id"]), "tabTitle": "Skill 手绘创作" if source == "skill" else "生成作品",
                "topic": safe_topic or "手绘创作",
                "mode": source, "modeLabel": "外部创作" if source != "web" else "生成",
                "kind": "multi" if int(run["expected_count"]) > 1 else "single",
                "recipeSummary": "", "prompt": safe_topic, "markdown": "",
                "items": completed, "engine": "upload" if source == "skill" else source,
                "taskId": "", "requestId": str(run["request_id"] or ""),
                "error": "", "recipeId": "", "creationSource": run["creation_mode"] if source == "web" else source,
                "promptMasked": bool(masked),
            }
        entry["runId"] = str(run["id"])
        entry["canvasId"] = run["canvas_id"] or ""
        billing_slots = {slot["id"]: slot for slot in slots}.values()
        entry["billing"] = {
            "amountCents": sum(int(slot["settled_cents"] or 0) for slot in billing_slots),
            "heldCents": sum(int(slot["held_cents"] or 0) for slot in billing_slots),
            "freeUsed": sum(int(slot["free_used"] or 0) for slot in billing_slots),
            "freeHeld": sum(int(slot["free_held"] or 0) for slot in billing_slots),
            "chargeCount": sum(int(slot["charge_count"] or 0) for slot in billing_slots),
        }
        entry["status"] = str(run["status"])
        entry["createdAt"] = format_short_time(run["created_at"])
        entry["createdAtISO"] = str(run["created_at"])
        entry["imageCount"] = len(completed)
        entry["outputSlots"] = output_slots
        # A work removed by moderation must not leave a stale workId cached
        # in the gateway snapshot; works.run_id is the only source of truth.
        entry["workId"] = work_id
        entry["source"] = source
        result.append(entry)
    return result


def get_studio_workspace(db: Database, user: dict[str, Any] | None, *, collection=None, history_cursor="", history_limit=40) -> dict[str, Any]:
    conn = db.get_conn()
    presets = [
        dict(r)
        for r in conn.execute(
            "SELECT id, title, blueprint, scenario_badge, scenario_desc, sort_order FROM studio_workflows WHERE is_official_preset = 1 AND enabled = 1 ORDER BY sort_order ASC"
        ).fetchall()
    ]
    if not user:
        return {"loggedIn": False, "workflows": [], "articles": [], "history": [], "pendingTasks": [], "uploads": [], "officialPresets": presets}

    uid = int(user["id"])
    wfs = []
    for r in conn.execute(
        "SELECT * FROM studio_workflows WHERE user_id = ? AND is_official_preset = 0 ORDER BY updated_at_ms DESC",
        (uid,),
    ).fetchall() if collection in (None,"workflows") else []:
        try:
            g = json.loads(r["graph_json"])
        except Exception:
            g = None
        wfs.append(
            {
                "id": r["id"],
                "title": r["title"],
                "blueprint": r["blueprint"],
                "updatedAtMs": int(r["updated_at_ms"]),
                "graph": g,
            }
        )

    arts = []
    for r in conn.execute("SELECT * FROM studio_articles WHERE user_id = ? AND COALESCE(deleted_at, '') = '' ORDER BY updated_at_ms DESC", (uid,)).fetchall() if collection is None else []:
        arts.append(
            {
                "id": r["id"],
                "articleTitle": r["article_title"],
                "markdown": r["markdown"],
                "cards": json.loads(r["cards_json"] or "[]"),
                "_illustrationsReady":r["illustrations_ready"],
                "style1": r["style1"],
                "layout": r["layout_code"],
                "status": r["status"],
                "runCount": int(r["run_count"]),
                "createdAtMs": int(r["created_at_ms"]),
                "updatedAtMs": int(r["updated_at_ms"]),
                "writeSeq": int(r["write_seq"]),
                "settings": r["settings_json"],
                "coverRatio": r["settings_json"].get("coverRatio", "2.35:1"),
                "inlineRatio": r["settings_json"].get("inlineRatio", "4:3"),
            }
        )

    from .studio_articles import hydrate_cards
    article_cards = hydrate_cards(conn, [article["id"] for article in arts])
    for article in arts:
        if article.pop("_illustrationsReady") or article_cards.get(article["id"]):
            article["cards"] = article_cards[article["id"]]
    hist = []
    pending_tasks = []
    history_filter, history_ids = _seed_filter("id", "generations")
    from .studio_paging import page_history_runs
    selected_runs, history_after = page_history_runs(conn, uid, cursor=history_cursor, limit=history_limit) if collection in (None,"history") else ([], "")
    selected_web_keys = [r["external_run_id"] for r in selected_runs if r["source"] == "web"]
    execution_rows = conn.execute(
        f"SELECT * FROM studio_generations WHERE user_id = ? AND COALESCE(deleted_at, '') = '' AND {history_filter} "
        "AND (run_id=ANY(?) OR batch_id=ANY(?) OR (batch_id='' AND id=ANY(?))) ORDER BY created_at DESC,id DESC",
        (uid, *history_ids, [r["id"] for r in selected_runs], selected_web_keys, selected_web_keys),
    ).fetchall() if selected_runs else []
    recipe_ids = list({r["recipe_id"] for r in execution_rows if r["recipe_id"]})
    recipe_subjects = {r["id"]: r["subject"] for r in conn.execute(
        "SELECT id,subject FROM studio_recipes WHERE user_id=? AND id=ANY(?)", (uid,recipe_ids),
    ).fetchall()} if recipe_ids else {}
    asset_codes = set()
    for row in execution_rows:
        asset_codes.update(str(row["recipe_summary"] or "").upper().replace("#", "").split())
        try:
            asset_codes.update(str(v.get("code") or "").upper().lstrip("#") for v in json.loads(row["system_append_json"] or "{}").get("systemAppend", []) if isinstance(v,dict))
        except (ValueError, TypeError, AttributeError):
            pass
    asset_prices = {str(r["code"]).upper(): r for r in conn.execute(
        "SELECT code,unlock_cost,source_type FROM catalog_assets WHERE UPPER(code)=ANY(?)", (list(asset_codes),),
    ).fetchall()} if asset_codes else {}
    work_by_external = {str(r["external_run_id"]): r["id"] for r in conn.execute(
        "SELECT gr.external_run_id,w.id FROM generation_runs gr JOIN works w ON w.run_id=gr.id "
        "WHERE gr.user_id=? AND gr.source='web' AND gr.external_run_id=ANY(?)",
        (uid,list({str(r["batch_id"] or r["id"]) for r in execution_rows})),
    ).fetchall()} if execution_rows else {}
    for r in execution_rows:
        r_keys = r.keys() if hasattr(r, "keys") else r
        vis_prompt, was_masked = get_generation_visible_prompt(r)

        # Check if generation used paid resources: if so, never return full prompt to client
        is_paid = False
        if ("cost_type" in r_keys and r["cost_type"] == "credits") or ("credits_spent" in r_keys and int(r["credits_spent"] or 0) > 0):
            is_paid = True
        else:
            codes_to_check = set()
            if "recipe_summary" in r_keys and r["recipe_summary"]:
                for c in str(r["recipe_summary"]).split():
                    c_clean = c.strip().upper().lstrip("#")
                    if c_clean:
                        codes_to_check.add(c_clean)
            if "system_append_json" in r_keys and r["system_append_json"]:
                try:
                    s_data = json.loads(r["system_append_json"])
                    for item in s_data.get("systemAppend", []):
                        c_clean = str(item.get("code") or "").strip().upper().lstrip("#")
                        if c_clean:
                            codes_to_check.add(c_clean)
                except Exception:
                    pass
            for c_clean in codes_to_check:
                ca = asset_prices.get(c_clean)
                if ca and (int(ca["unlock_cost"] or 0) > 0 or ca["source_type"] == "exclusive"):
                    is_paid = True
                    break

        if is_paid:
            vis_prompt = ""
            was_masked = True

        raw_items = json.loads(r["items_json"] or "[]")
        if raw_items and isinstance(raw_items[0], str):
            items = [{"id": f"{r['id']}_{idx}", "title": r["tab_title"] or "生成项", "imageUrl": u} for idx, u in enumerate(raw_items)]
        else:
            items = []
            for idx, it in enumerate(raw_items if isinstance(raw_items, list) else []):
                if isinstance(it, dict):
                    items.append({
                        "id": it.get("id") or f"{r['id']}_{idx}",
                        "title": it.get("title") or r["tab_title"] or "生成项",
                        "imageUrl": it.get("imageUrl") or "",
                        "ratio": it.get("ratio") or "3:4",
                    })
                elif isinstance(it, str):
                    items.append({"id": f"{r['id']}_{idx}", "title": r["tab_title"] or "生成项", "imageUrl": it, "ratio": "3:4"})

        snap = None
        creation_source = ""
        if r["system_append_json"]:
            try:
                s_data = json.loads(r["system_append_json"])
                snap = s_data.get("recipeSnapshot")
                candidate = str(s_data.get("creationSource") or "").strip().lower()
                if candidate in ("quick", "batch", "article", "canvas", "other"):
                    creation_source = candidate
            except Exception:
                pass

        user_topic = ""
        if "subject" in r_keys and r["subject"]:
            user_topic = str(r["subject"]).strip()
        elif "recipe_id" in r_keys and r["recipe_id"]:
            recipe_subject = recipe_subjects.get(r["recipe_id"])
            if recipe_subject:
                user_topic = str(recipe_subject).strip()
        if not user_topic:
            user_topic = "手绘创作"

        hist_entry = {
            "id": r["id"],
            "createdAt": format_short_time(r["created_at"]),
            "tabTitle": r["tab_title"] or user_topic,
            "topic": user_topic,
            "mode": r["mode"],
            "modeLabel": r["mode_label"],
            "kind": r["kind"],
            "recipeSummary": r["recipe_summary"],
            "prompt": vis_prompt,
            "markdown": r["markdown"],
            "items": items,
            "status": r["status"],
            "engine": r["engine"],
            "taskId": r["task_id"] or "",
            "requestId": r["request_id"] or "",
            "error": sanitize_client_error_msg(r["error_msg"], r["status"]),
            "recipeId": r["recipe_id"] if "recipe_id" in r_keys else "",
            "creationSource": creation_source,
            "batchId": str(r["batch_id"] or "") if "batch_id" in r_keys else "",
            "batchIndex": int(r["batch_index"] or 0) if "batch_index" in r_keys else 0,
            "batchTotal": int(r["batch_total"] or 1) if "batch_total" in r_keys else 1,
        }
        # Link the history item to the single work of its canonical run.
        # Its image slots do not have separate work IDs.
        logical_key = hist_entry["batchId"] or str(r["id"])
        canonical_work_id = work_by_external.get(logical_key)
        if canonical_work_id:
            hist_entry["workId"] = canonical_work_id
            for item in items:
                item["workId"] = canonical_work_id
        if snap:
            hist_entry["recipeSnapshot"] = snap
        if was_masked:
            hist_entry["promptMasked"] = True
        hist.append(hist_entry)
        if r["status"] in ("queued", "running"):
            pending_entry = {
                "genId": r["id"],
                "requestId": r["request_id"] or "",
                "clientRequestId": r["request_id"] or "",
                "taskId": r["task_id"] or "",
                "status": r["status"],
                "createdAt": r["created_at"],
                "mode": r["mode"],
                "kind": r["kind"],
                "reservationDate": r["reservation_date"] or "",
            }
            if was_masked:
                pending_entry["promptMasked"] = True
            pending_tasks.append(pending_entry)

    # Multiple parallel cloud requests are execution slots of ONE logical run.
    # Collapse them only after collecting their individual pending task records.
    batch_groups: dict[str, dict[str, Any]] = {}
    history_runs: list[dict[str, Any]] = []
    for entry in hist:
        bid = entry.get("batchId") or ""
        if not bid:
            history_runs.append(entry)
            continue
        if bid not in batch_groups:
            group = dict(entry)
            group["id"] = bid
            group["items"] = []
            group["_slots"] = []
            group["_requests"] = []
            group["kind"] = "multi" if group["batchTotal"] > 1 else entry["kind"]
            batch_groups[bid] = group
            history_runs.append(group)
        group = batch_groups[bid]
        group["_slots"].append((entry["batchIndex"], entry["items"]))
        group["_requests"].append((entry["batchIndex"], entry["requestId"]))
        if entry.get("workId") and not group.get("workId"):
            group["workId"] = entry["workId"]
        if entry.get("promptMasked"):
            group["promptMasked"] = True
            group["prompt"] = ""
        if entry["status"] == "success":
            group["status"] = "success"
    for group in batch_groups.values():
        seen_images: set[str] = set()
        for _, slot_items in sorted(group.pop("_slots"), key=lambda pair: pair[0]):
            for item in slot_items:
                url = str(item.get("imageUrl") or "").strip()
                if not url or url in seen_images:
                    continue
                seen_images.add(url)
                if group.get("workId"):
                    item["workId"] = group["workId"]
                group["items"].append(item)
        request_ids = sorted(group.pop("_requests"), key=lambda pair: pair[0])
        group["requestId"] = request_ids[0][1] if request_ids else ""
        group["imageCount"] = len(group["items"])
        if group.get("promptMasked"):
            group["prompt"] = ""
    hist = _canonical_studio_history(conn, history_runs, runs=selected_runs) if collection in (None,"history") else []

    uploads = [
        {
            "id": r["id"],
            "cat": r["cat"],
            "name_zh": r["name_zh"],
            "desc_zh": r["desc_zh"],
            "image": r["image_url"],
            "custom": True,
        }
        for r in (conn.execute("SELECT * FROM user_uploads WHERE user_id = ? AND deleted_at IS NULL ORDER BY created_at DESC", (uid,)).fetchall()
                  if collection in (None,"uploads") else [])
    ]

    if collection:
        result = {"loggedIn":True,collection:{"history":hist,"workflows":wfs,"uploads":uploads}[collection]}
        if collection == "history":
            result["nextCursor"] = history_after
        return result
    return {
        "loggedIn": True,
        "workflows": wfs,
        "articles": arts,
        "history": hist,
        "historyCursor": history_after,
        "pendingTasks": pending_tasks,
        "uploads": uploads,
        "officialPresets": presets,
    }


def save_user_studio_workflow(db: Database, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    uid = int(user["id"])
    wf_id = str(body.get("id") or f"wf_{int(time.time() * 1000)}")
    title = str(body.get("title") or "未命名工作流").strip()[:100]
    blueprint = str(body.get("blueprint") or "single")
    graph_json = json.dumps(body.get("graph") or {}, ensure_ascii=False)
    now_ms = int(body.get("updatedAtMs") or time.time() * 1000)
    now_iso = utc_now_iso()

    with db.transaction() as tx:
        tx.execute(
            """
            INSERT INTO studio_workflows (id, user_id, title, blueprint, scenario_badge, scenario_desc, graph_json, is_official_preset, enabled, sort_order, updated_at_ms, created_at)
            VALUES (?, ?, ?, ?, '', '', ?, 0, 1, 0, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                blueprint = excluded.blueprint,
                graph_json = excluded.graph_json,
                updated_at_ms = excluded.updated_at_ms
            WHERE studio_workflows.user_id = excluded.user_id
            """,
            (wf_id, uid, title, blueprint, graph_json, now_ms, now_iso),
        )
    return {"ok": True, "id": wf_id}


def delete_user_studio_workflow(db: Database, user: dict[str, Any], wf_id: str) -> dict[str, Any]:
    uid = int(user["id"])
    with db.transaction() as tx:
        tx.execute("DELETE FROM studio_workflows WHERE id = ? AND user_id = ? AND is_official_preset = 0", (wf_id, uid))
    return {"ok": True}


def sync_user_studio_articles(db: Database, user: dict[str, Any], articles: list[dict[str, Any]]) -> dict[str, Any]:
    from .studio_articles import save_articles
    return save_articles(db, user, articles)


def delete_user_studio_article(db: Database, user: dict[str, Any], article_id: str) -> dict[str, Any]:
    """Soft-delete an article owned by the user.

    Only the author can delete their own article. If the article does not
    exist (or is already deleted), returns 404. If owned by someone else, returns 403.
    """
    uid = int(user["id"])
    aid = str(article_id or "").strip()
    if not aid:
        raise ServiceError("文章编号不能为空", status=400, code="article_id_required")
    with db.transaction() as tx:
        row = tx.execute("SELECT user_id, deleted_at FROM studio_articles WHERE id = ?", (aid,)).fetchone()
        if not row or (row["deleted_at"] and str(row["deleted_at"]).strip()):
            raise ServiceError("文章不存在", status=404, code="article_not_found")
        if int(row["user_id"] or 0) != uid:
            raise ServiceError("无权删除其他账号的文章", status=403, code="article_forbidden")
        now_iso = utc_now_iso()
        tx.execute("UPDATE studio_articles SET deleted_at = ? WHERE id = ? AND user_id = ?", (now_iso, aid, uid))
    return {"ok": True, "id": aid, "deleted": True}


def list_user_studio_articles(db: Database, user: dict[str, Any]) -> dict[str, Any]:
    """The caller's own articles, and only ever their own.

    The rows are private working notes, so the user id in the session decides
    what comes back -- there is no path that reads someone else's list.
    """
    uid = int(user["id"])
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT id, article_title, status, run_count, created_at_ms, updated_at_ms
        FROM studio_articles
        WHERE user_id = ? AND COALESCE(deleted_at, '') = ''
        ORDER BY updated_at_ms DESC, id ASC
        LIMIT 200
        """,
        (uid,),
    ).fetchall()
    items = [
        {
            "id": r["id"],
            "articleTitle": r["article_title"],
            "status": r["status"],
            "runCount": int(r["run_count"] or 0),
            "createdAtMs": int(r["created_at_ms"] or 0),
            "updatedAtMs": int(r["updated_at_ms"] or 0),
        }
        for r in rows
    ]
    return {"ok": True, "items": items, "total": len(items)}


def record_user_studio_history(db: Database, user: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    if "visibility" in entry:
        raise ServiceError("当前暂不支持设置可见性", status=400, code="visibility_not_allowed")

    CODE_RE = re.compile(r"^(?:USR-)?[A-Z]{1,4}-[A-Z0-9]+$")

    for field_name in ("styles", "layouts"):
        if field_name in entry and entry[field_name] is not None:
            field_val = entry[field_name]
            if not isinstance(field_val, list):
                raise ServiceError(f"{field_name} 必须是列表", status=400, code="invalid_resource_shape")
            for item in field_val:
                if isinstance(item, dict):
                    code_val = str(item.get("code") or "").strip().upper().lstrip("#")
                    if not CODE_RE.match(code_val):
                        raise ServiceError(f"无效的资源编号: {code_val}", status=400, code="invalid_resource_code")
                elif isinstance(item, str):
                    code_val = item.strip().upper().lstrip("#")
                    if not CODE_RE.match(code_val):
                        raise ServiceError(f"无效的资源编号: {code_val}", status=400, code="invalid_resource_code")
                else:
                    raise ServiceError(f"{field_name} 项格式不正确", status=400, code="invalid_resource_shape")

    if "recipeSnapshot" in entry and entry["recipeSnapshot"] is not None:
        snap = entry["recipeSnapshot"]
        if not isinstance(snap, dict):
            raise ServiceError("recipeSnapshot 必须是对象", status=400, code="invalid_resource_shape")
        for k in ("style1", "style2", "layout"):
            if snap.get(k):
                c = str(snap[k]).strip().upper().lstrip("#")
                if not CODE_RE.match(c):
                    raise ServiceError(f"无效的资源编号: {c}", status=400, code="invalid_resource_code")

    uid = int(user["id"])
    creation_source = str(entry.get("creationSource") or "").strip().lower()
    if creation_source not in ("quick", "batch", "article", "canvas", "other"):
        creation_source = ""
    hid = str(entry.get("id") or f"hist_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}").strip()[:160]
    if not hid:
        raise ServiceError("历史记录编号不能为空", status=400, code="history_id_required")
    req_id = str(entry.get("requestId") or entry.get("request_id") or "").strip()
    now_iso = utc_now_iso()
    with db.transaction() as tx:
        existing = None
        if req_id:
            existing = tx.execute(
                "SELECT * FROM studio_generations WHERE user_id = ? AND request_id = ? AND request_id != '' ORDER BY created_at DESC LIMIT 1",
                (uid, req_id),
            ).fetchone()
        if not existing and hid:
            existing = tx.execute("SELECT * FROM studio_generations WHERE id = ?", (hid,)).fetchone()
        if existing and int(existing["user_id"] or 0) != uid:
            raise ServiceError("该历史记录编号属于其他账号，不能覆盖", status=409, code="history_conflict")

        user_p = str(entry.get("prompt") or "")
        scan_failed = False
        try:
            has_sec = check_text_has_secret(user_p, tx)
        except Exception:
            scan_failed = True
            has_sec = False
        if scan_failed:
            vis_p = None
            prompt_masked = 0
        elif has_sec:
            vis_p = ""
            prompt_masked = 1
        else:
            vis_p = user_p
            prompt_masked = 0
        values = (
            str(entry.get("tabTitle") or ""),
            str(entry.get("mode") or ""),
            str(entry.get("modeLabel") or ""),
            str(entry.get("kind") or "single"),
            str(entry.get("recipeSummary") or ""),
            user_p,
            vis_p,
            prompt_masked,
            str(entry.get("markdown") or ""),
            json.dumps(entry.get("items") or [], ensure_ascii=False),
        )
        fork_gen_id = str(entry.get("forkGenerationId") or entry.get("fork_generation_id") or "").strip()
        fork_item_id = str(entry.get("forkItemId") or entry.get("fork_item_id") or "").strip()
        clean_subj = str(entry.get("subject") or "").strip()[:140]
        if not clean_subj:
            items_list = entry.get("items") or []
            if isinstance(items_list, list) and items_list:
                first_item = items_list[0]
                if isinstance(first_item, dict):
                    clean_subj = str(
                        first_item.get("subject")
                        or (first_item.get("recipeSnapshot") or {}).get("subject")
                        or ""
                    ).strip()[:140]

        if fork_gen_id:
            target_gen = tx.execute("SELECT * FROM studio_generations WHERE id = ?", (fork_gen_id,)).fetchone()
            if not target_gen or not check_generation_social_accessible(target_gen, viewer=user, allow_own=True):
                fork_gen_id = ""
                fork_item_id = ""
            elif int(target_gen["user_id"]) == uid:
                fork_gen_id = ""
                fork_item_id = ""

        if existing:
            target_id = existing["id"]
            # A browser save may use the same id or request_id as a real cloud generation.
            # Only update user-editable presentation fields; never replace
            # ownership, engine, cost, task, status, or accounting columns.
            tx.execute(
                """
                UPDATE studio_generations
                SET tab_title = ?, mode = ?, mode_label = ?, kind = ?, recipe_summary = ?,
                    prompt = ?, visible_prompt = ?, prompt_masked = ?, markdown = ?, items_json = ?, deleted_at = '',
                    subject = CASE WHEN ? != '' THEN ? ELSE subject END,
                    fork_generation_id = CASE WHEN ? != '' THEN ? ELSE fork_generation_id END,
                    fork_item_id = CASE WHEN ? != '' THEN ? ELSE fork_item_id END
                WHERE id = ? AND user_id = ?
                """,
                (*values, clean_subj, clean_subj, fork_gen_id, fork_gen_id, fork_item_id, fork_item_id, target_id, uid),
            )
            # Public success must not be committed without its canonical works.
            # Projection errors roll back this transaction instead of silently hiding images.
            from .generation_works import project_generation_to_works
            project_generation_to_works(tx, target_id)
            return {"ok": True, "id": target_id}
        else:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                    prompt, visible_prompt, prompt_masked, markdown, items_json, system_append_json, engine, cost_type, credits_spent, status, created_at, request_id,
                    subject, fork_generation_id, fork_item_id, visibility
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sample', 'free', 0, 'success', ?, ?, ?, ?, ?, ?)
                """,
                (hid, uid, user["username"], *values, json.dumps({"creationSource": creation_source}), now_iso, req_id, clean_subj, fork_gen_id, fork_item_id,
                 "public"),
            )
            # Public success must not be committed without its canonical works.
            # Projection errors roll back this transaction instead of silently hiding images.
            from .generation_works import project_generation_to_works
            project_generation_to_works(tx, hid)
            return {"ok": True, "id": hid}


def delete_user_studio_history(db: Database, user: dict[str, Any], history_id: str) -> dict[str, Any]:
    """Soft-delete one complete logical Web run, never just one gateway slot.

    The execution/billing rows remain for refunds and audits. All successful
    sibling slots become invisible as a single transaction, and the canonical
    generated work is hidden. Accept UI batch IDs, V3 run IDs, and individual
    execution IDs without relying on legacy mapping tables.
    """
    uid = int(user["id"])
    key = str(history_id or "").strip()
    if not key:
        raise ServiceError("历史记录编号不能为空", status=400, code="history_id_required")
    with db.transaction() as tx:
        logical = tx.execute(
            """SELECT id,external_run_id,status FROM generation_runs
               WHERE user_id=? AND source='web' AND
                 (id=? OR external_run_id=?) LIMIT 1""",
            (uid, key, key),
        ).fetchone()
        if logical:
            external = str(logical["external_run_id"])
            rows = tx.execute(
                """SELECT id,status,deleted_at FROM studio_generations
                   WHERE user_id=? AND
                     (id=? OR (batch_id<>'' AND batch_id=?))""",
                (uid, external, external),
            ).fetchall()
        else:
            execution = tx.execute(
                "SELECT user_id,batch_id FROM studio_generations WHERE id=?", (key,),
            ).fetchone()
            if not execution:
                return {"ok": True, "id": key, "deleted": False}
            if int(execution["user_id"] or 0) != uid:
                raise ServiceError("无权删除其他账号的历史记录", status=403, code="history_forbidden")
            batch_id = str(execution["batch_id"] or "")
            rows = tx.execute(
                """SELECT id,status,deleted_at FROM studio_generations
                   WHERE user_id=? AND
                     (id=? OR (batch_id<>'' AND batch_id=?))""",
                (uid, key, batch_id),
            ).fetchall()
        if any(str(r["status"]) in ("queued", "running") for r in rows):
            raise ServiceError("生成任务仍在进行中，完成或失败后才能删除历史", status=409, code="history_active")
        active = [str(r["id"]) for r in rows if not r["deleted_at"]]
        if not active:
            return {"ok": True, "id": key, "deleted": False}
        now = utc_now_iso()
        for execution_id in active:
            tx.execute(
                """UPDATE studio_generations SET deleted_at=?
                   WHERE id=? AND user_id=? AND COALESCE(deleted_at,'')=''""",
                (now, execution_id, uid),
            )
        # Hide after all siblings have been updated; otherwise one remaining
        # slot could incorrectly republish the work during this operation.
        from .generation_works import sync_generation_visibility
        sync_generation_visibility(tx, active[0], "private", is_deleted=True)
    return {"ok": True, "id": key, "deleted": True, "executionCount": len(active)}


def delete_all_user_studio_history(db: Database, user: dict[str, Any]) -> dict[str, Any]:
    """Soft-delete all completed/refunded history rows owned by the user.

    In-flight rows stay visible so task recovery and accounting can finish;
    callers must use this explicit function rather than treating an empty id as
    a wildcard in ``delete_user_studio_history``.
    """
    uid = int(user["id"])
    now_iso = utc_now_iso()
    with db.transaction() as tx:
        gen_ids = [r[0] for r in tx.execute("SELECT id FROM studio_generations WHERE user_id = ? AND COALESCE(deleted_at, '') = '' AND status NOT IN ('queued', 'running')", (uid,)).fetchall()]
        cur = tx.execute(
            """
            UPDATE studio_generations
            SET deleted_at = ?
            WHERE user_id = ? AND COALESCE(deleted_at, '') = ''
              AND status NOT IN ('queued', 'running')
            """,
            (now_iso, uid),
        )
        deleted = int(cur.rowcount or 0)
        # Roll back the whole operation if a linked public work cannot be hidden.
        from .generation_works import sync_generation_visibility
        for gid in gen_ids:
            sync_generation_visibility(tx, str(gid), "private", is_deleted=True)
        deleted = int(cur.rowcount or 0)
    return {"ok": True, "deleted": deleted}


def get_user_studio_task(
    db: Database,
    user: dict[str, Any] | None,
    task_id: str = "",
    request_id: str = "",
) -> dict[str, Any] | None:
    """Resolve a task only inside the authenticated user's generation rows."""
    if not user:
        raise ServiceError("查询生图任务请先登录账号", status=401, code="login_required")
    uid = int(user["id"])
    tid = str(task_id or "").strip()
    rid = str(request_id or "").strip()
    if not tid and not rid:
        raise ServiceError("缺少任务编号或 requestId", status=400, code="task_id_required")
    conn = db.get_conn()
    if tid:
        row = conn.execute(
            "SELECT * FROM studio_generations WHERE user_id = ? AND (task_id = ? OR id = ?) ORDER BY created_at DESC LIMIT 1",
            (uid, tid, tid),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM studio_generations WHERE user_id = ? AND request_id = ? ORDER BY created_at DESC LIMIT 1",
            (uid, rid),
        ).fetchone()
    if not row:
        return None
    vis_prompt, was_masked = get_generation_visible_prompt(row)
    try:
        raw_items = json.loads(row["items_json"] or "[]")
    except Exception:
        raw_items = []
    clean_images: list[str] = []
    for it in (raw_items if isinstance(raw_items, list) else []):
        if isinstance(it, str):
            clean_images.append(it)
        elif isinstance(it, dict) and it.get("imageUrl"):
            clean_images.append(str(it["imageUrl"]))
    ret = {
        "genId": row["id"],
        "requestId": row["request_id"] or "",
        "clientRequestId": row["request_id"] or "",
        "taskId": row["task_id"] or "",
        "status": row["status"],
        "images": clean_images,
        "error": sanitize_client_error_msg(row["error_msg"], row["status"]),
        "reservationDate": row["reservation_date"] or "",
    }
    if was_masked:
        ret["promptMasked"] = True
    if row["system_append_json"]:
        try:
            s_data = json.loads(row["system_append_json"])
            if s_data.get("recipeSnapshot"):
                ret["recipeSnapshot"] = s_data["recipeSnapshot"]
        except Exception:
            pass
    return ret


def claim_cloud_generation_submission(db: Database, user: dict[str, Any] | None, gen_id: str) -> dict[str, Any]:
    """Atomically claim the gateway-submit edge of a reserved generation.

    The HTTP layer can call this after ``prepare_cloud_generation``. Exactly
    one retry may move a reservation from ``running`` to ``queued``; later
    retries receive ``claimed=False`` and must wait for the existing task.
    """
    if not user:
        raise ServiceError("提交生图任务请先登录账号", status=401, code="login_required")
    uid = int(user["id"])
    gid = str(gen_id or "").strip()
    if not gid:
        raise ServiceError("缺少生成记录编号", status=400, code="generation_id_required")
    with db.transaction() as tx:
        row = tx.execute("SELECT * FROM studio_generations WHERE id = ?", (gid,)).fetchone()
        if not row:
            raise ServiceError("生成记录不存在", status=404, code="generation_not_found")
        if int(row["user_id"] or 0) != uid:
            raise ServiceError("无权提交其他账号的生图任务", status=403, code="generation_forbidden")
        cur = tx.execute(
            "UPDATE studio_generations SET status = 'queued' WHERE id = ? AND user_id = ? AND status = 'running' AND COALESCE(task_id, '') = '' AND prompt_ready = 1",
            (gid, uid),
        )
        current = tx.execute("SELECT * FROM studio_generations WHERE id = ?", (gid,)).fetchone()
    return {
        "claimed": bool(cur.rowcount),
        "genId": gid,
        "status": current["status"] if current else row["status"],
        "taskId": current["task_id"] if current else row["task_id"],
        "requestId": current["request_id"] if current else row["request_id"],
    }


def _cloud_generation_result(
    conn: PgConnection,
    row: dict[str, Any],
    settings: dict[str, Any],
    *,
    idempotent: bool = False,
) -> dict[str, Any]:
    """Return the stable public shape used by first submit and retry paths."""
    uid = int(row["user_id"])
    wallet = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (uid,)).fetchone()
    vis_prompt, was_masked = get_generation_visible_prompt(row)
    row_keys = row.keys() if hasattr(row, "keys") else row
    is_paid = ("cost_type" in row_keys and row["cost_type"] == "credits") or ("credits_spent" in row_keys and int(row["credits_spent"] or 0) > 0)
    if not is_paid:
        codes_to_check = set()
        if "recipe_summary" in row_keys and row["recipe_summary"]:
            for c in str(row["recipe_summary"]).split():
                c_clean = c.strip().upper().lstrip("#")
                if c_clean:
                    codes_to_check.add(c_clean)
        if "system_append_json" in row_keys and row["system_append_json"]:
            try:
                s_data = json.loads(row["system_append_json"])
                for item in s_data.get("systemAppend", []):
                    c_clean = str(item.get("code") or "").strip().upper().lstrip("#")
                    if c_clean:
                        codes_to_check.add(c_clean)
            except Exception:
                pass
        for c_clean in codes_to_check:
            ca = conn.execute("SELECT unlock_cost, source_type FROM catalog_assets WHERE code = ? OR UPPER(code) = ?", (c_clean, c_clean)).fetchone()
            if ca and (int(ca["unlock_cost"] or 0) > 0 or ca["source_type"] == "exclusive"):
                is_paid = True
                break
    if is_paid:
        vis_prompt = ""
        was_masked = True
    res = {
        "genId": row["id"],
        "requestId": row["request_id"] or "",
        "clientRequestId": row["request_id"] or "",
        "idempotent": bool(idempotent),
        "status": row["status"],
        "taskId": row["task_id"] or "",
        "finalPrompt": vis_prompt,
        "costType": row["cost_type"],
        "creditsSpent": int(row["credits_spent"] or 0),
        "credits": int(wallet["balance"]) if wallet else 0,
        "freeQuotaRemaining": get_wallet_quota_state(conn,uid,settings)["freeQuotaRemaining"],
        "amountCents": int(row.get("amount_cents") or 0),
        "billingSpec": row.get("billing_snapshot"),
        "reservationDate": row["reservation_date"] or "",
        "model": resolve_gateway_model(settings),
    }
    if was_masked:
        res["promptMasked"] = True
    if "fork_generation_id" in row_keys and row["fork_generation_id"]:
        res["forkGenerationId"] = str(row["fork_generation_id"])
    if "fork_item_id" in row_keys and row["fork_item_id"]:
        res["forkItemId"] = str(row["fork_item_id"])
    return res


def consume_daily_usage(db: Database, user_id: int | str, scope: str, limit: int) -> bool:
    """Durably record and enforce daily resource usage per user.

    In a short transaction, reads the day's count, checks against ``limit``,
    and atomically increments the counter via upsert. Returns False when
    the usage would exceed ``limit``.
    """
    uid = int(user_id)
    clean_scope = str(scope or "").strip()
    today = local_today_str()
    with db.transaction() as tx:
        row = tx.execute(
            "SELECT count FROM daily_usage WHERE user_id = ? AND scope = ? AND usage_date = ?",
            (uid, clean_scope, today),
        ).fetchone()
        current = int(row["count"]) if row else 0
        if current >= limit:
            return False
        tx.execute(
            """
            INSERT INTO daily_usage (user_id, scope, usage_date, count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT (user_id, scope, usage_date)
            DO UPDATE SET count = daily_usage.count + 1
            """,
            (uid, clean_scope, today),
        )
        return True


def build_recipe_gateway_prompt(raw_prompt: str, injected_notes: list[str]) -> str:
    """Combine base prompt and injected notes cleanly with double newlines."""
    parts = [p.strip() for p in [raw_prompt] + list(injected_notes) if p and str(p).strip()]
    return "\n\n".join(parts)


def trim_composed_prompt(composed: str, max_budget: int) -> str:
    """Trim composed prompt within max_budget, preferring sentence end or newline."""
    if len(composed) <= max_budget:
        return composed
    candidate = composed[:max(0, max_budget)]
    last_idx = -1
    for i in range(len(candidate) - 1, -1, -1):
        if candidate[i] in ("。", "！", "？", ".", "!", "?", "\n"):
            last_idx = i + 1
            break
    if last_idx >= int(max_budget * 0.4):
        return candidate[:last_idx].strip()
    return candidate.strip()


def _compose_skill_prompt(
    style_code: str,
    layout_code: str,
    theme: str,
    *,
    style2_code: str = "",
    colors: list[str] | None = None,
    tones: list[str] | None = None,
    moods: list[str] | None = None,
    whitespace: str = "",
    ratio: str = "",
    mode: str = "",
) -> str:
    """Build an image prompt through the hand-drawn style Skill.

    Returns ``""`` when the Skill is unavailable or cannot produce a prompt, so
    the caller can fall back to the plain prompt instead of failing the request.
    """
    if not (style_code or layout_code or style2_code):
        return ""
    try:
        from . import skill_prompt
    except Exception:  # noqa: BLE001 - Skill module is optional
        return ""
    try:
        if not skill_prompt.skill_available():
            return ""
        composed = skill_prompt.compose_prompt(
            str(style_code or ""),
            str(layout_code or ""),
            "",
            str(theme or ""),
            style2_code=str(style2_code or ""),
            colors=colors,
            tones=tones,
            moods=moods,
            whitespace=str(whitespace or ""),
            ratio=str(ratio or ""),
            mode=str(mode or ""),
        )
    except Exception:  # noqa: BLE001 - never fail a paid generation on this
        logger.warning("Skill prompt composition failed; falling back to plain prompt", exc_info=True)
        return ""
    return str(composed.get("prompt") or "").strip()


def prepare_cloud_generation(
    db: Database,
    user: dict[str, Any] | None,
    body: dict[str, Any],
    *,
    gateway_protocol: str = "",
) -> dict[str, Any]:
    """Reserve one generation atomically and inject DB blackbox prompts.

    ``requestId``/``clientRequestId`` is scoped to the authenticated user. A
    retry returns the original reservation rather than charging a second time;
    callers should inspect ``idempotent`` and ``status`` before submitting to a
    gateway again. At most ``gateway.max_inflight_per_user`` queued/running
    rows may exist for one user (default 1).
    """
    if not user:
        raise ServiceError("调用云端真实大模型生图请先登录账号", status=401, code="login_required")
    if "visibility" in body:
        raise ServiceError("当前暂不支持设置可见性", status=400, code="visibility_not_allowed")

    uid = int(user["id"])
    uname = user["username"]

    from .studio_execution import apply_source_input
    apply_source_input(db, user, body)
    document_source = bool(body.get("canvasId") or body.get("articleId"))

    # A canvas batch sends independent gateway requests but represents one
    # logical public work. Validate the group boundary server-side.
    batch_id = str(body.get("batchId") or "").strip()
    if batch_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", batch_id):
        raise ServiceError("批次 ID 无效", status=400, code="invalid_batch_id")
    try:
        batch_index = int(body.get("batchIndex", 0))
        batch_total = int(body.get("batchTotal", 1))
    except (ValueError, TypeError):
        raise ServiceError("批次序号无效", status=400, code="invalid_batch_index")
    if batch_total < 1 or batch_total > 200 or batch_index < 0 or batch_index >= batch_total:
        raise ServiceError("批次序号超出范围", status=400, code="invalid_batch_index")
    if not batch_id and (batch_index != 0 or batch_total != 1):
        raise ServiceError("缺少批次 ID", status=400, code="invalid_batch_id")

    recipe_id = str(body.get("recipeId") or "").strip()
    r_colors: list[str] = []
    r_tones: list[str] = []
    r_moods: list[str] = []
    r_whitespace = ""
    r_ratio = "3:4"
    r_mode = "graphic-text"
    if document_source:
        r_colors=list(body.get("colors") or [])
        r_tones=list(body.get("tones") or [])
        r_moods=list(body.get("moods") or [])
        r_whitespace=str(body.get("whitespace") or "")
        r_ratio=str(body.get("ratio") or "3:4")
        r_mode=str(body.get("mode") or "graphic-text")
    if recipe_id:
        r_row = db.get_conn().execute(
            "SELECT * FROM studio_recipes WHERE id = ? AND user_id = ?",
            (recipe_id, uid),
        ).fetchone()
        if not r_row:
            raise ServiceError("配方不存在或无权访问", status=404, code="recipe_not_found")

        body["recipeId"] = recipe_id
        r_styles = json.loads(r_row["style_ids"] or "[]")
        body["style1"] = r_styles[0] if len(r_styles) > 0 else ""
        body["style2"] = r_styles[1] if len(r_styles) > 1 else ""
        body["layout"] = r_row["layout_id"] or ""
        body["ratio"] = r_row["ratio"] or "3:4"
        body["mode"] = r_row["mode"] or "graphic-text"
        r_refs = json.loads(r_row["references_json"] or "[]")
        body["refImages"] = r_refs
        body.pop("useCh001", None)
        body.pop("customRefImg", None)

        r_colors = json.loads(r_row["colors"] or "[]")
        r_tones = json.loads(r_row["tones"] or "[]")
        r_moods = json.loads(r_row["moods"] or "[]")
        r_whitespace = str(r_row["whitespace"] or "")
        r_ratio = str(r_row["ratio"] or "3:4")
        r_mode = str(r_row["mode"] or "graphic-text")

        r_prompt = str(r_row["prompt"] or "").strip()
        if r_prompt:
            body["prompt"] = r_prompt
            body["promptFromSkill"] = True
        else:
            body["prompt"] = str(r_row["subject"] or "").strip()
            body.pop("promptFromSkill", None)

    history_id = str(body.get("historyId") or body.get("generationId") or "").strip()
    if history_id and not recipe_id:
        h_row = db.get_conn().execute(
            "SELECT * FROM studio_generations WHERE id = ? AND user_id = ? AND COALESCE(deleted_at, '') = ''",
            (history_id, uid),
        ).fetchone()
        if not h_row:
            raise ServiceError("历史生成记录不存在或无权访问", status=404, code="history_not_found")
        h_keys = h_row.keys() if hasattr(h_row, "keys") else h_row
        if not body.get("prompt") and "subject" in h_keys and h_row["subject"]:
            body["prompt"] = str(h_row["subject"])
        if not body.get("style1") or not body.get("layout"):
            h_snap = None
            if "system_append_json" in h_keys and h_row["system_append_json"]:
                try:
                    s_data = json.loads(h_row["system_append_json"])
                    h_snap = s_data.get("recipeSnapshot")
                except Exception:
                    pass
            if isinstance(h_snap, dict):
                if not body.get("style1") and h_snap.get("style1"):
                    body["style1"] = str(h_snap["style1"])
                if not body.get("style2") and h_snap.get("style2"):
                    body["style2"] = str(h_snap["style2"])
                if not body.get("layout") and h_snap.get("layout"):
                    body["layout"] = str(h_snap["layout"])
            if not body.get("style1") or not body.get("layout"):
                summary_codes = [c.strip().upper().lstrip("#") for c in str(h_row["recipe_summary"] or "").split() if c.strip()]
                for sc in summary_codes:
                    if sc.startswith(("SC-", "IG-", "SB-", "IP-", "EC-", "LAY-", "USR-L")):
                        if not body.get("layout"):
                            body["layout"] = sc
                    else:
                        if not body.get("style1"):
                            body["style1"] = sc
                        elif not body.get("style2") and sc != body.get("style1"):
                            body["style2"] = sc
        if not body.get("ratio") and "tab_title" in h_keys and h_row["tab_title"] and re.match(r"^\d+:\d+$", str(h_row["tab_title"])):
            body["ratio"] = h_row["tab_title"]
        if not body.get("mode") and "mode" in h_keys and h_row["mode"]:
            body["mode"] = h_row["mode"]

    raw_prompt = str(body.get("prompt") or "").strip()
    style1 = str(body.get("style1") or "").strip().upper().lstrip("#")
    style2 = str(body.get("style2") or "").strip().upper().lstrip("#")
    layout = str(body.get("layout") or "").strip().upper().lstrip("#")

    # If codes were embedded in raw_prompt:
    if not style1 and not body.get("canvasId"):
        m_s = re.search(r"(?:【画风】|画风|Style|角色风格)[：:\s]*#?([A-Za-z0-9_-]+)", raw_prompt)
        if m_s:
            style1 = m_s.group(1).strip().upper().lstrip("#")
    if not style2 and not body.get("canvasId"):
        m_s2 = re.search(r"(?:【场景风格】|场景风格|Scene Style)[：:\s]*#?([A-Za-z0-9_-]+)", raw_prompt)
        if m_s2:
            style2 = m_s2.group(1).strip().upper().lstrip("#")
    if not layout and not body.get("canvasId"):
        m_l = re.search(r"(?:【图型】|图型|Layout)[：:\s]*#?([A-Za-z0-9_-]+)", raw_prompt)
        if m_l:
            layout = m_l.group(1).strip().upper().lstrip("#")

    user_subject = str(body.get("subject") or body.get("topic") or body.get("theme") or "").strip()
    if not user_subject:
        m_subj = re.search(r"【(?:核心画面与文案主题|文章标题或导语|主题)】[：:\s]*([^\n]+)", raw_prompt)
        if m_subj:
            user_subject = m_subj.group(1).strip()
        else:
            m_subj2 = re.search(r"(?:^|，|；|\n)主题[：:\s]*([^，；\n|]+)", raw_prompt)
            if m_subj2:
                user_subject = m_subj2.group(1).strip()
            else:
                m_subj3 = re.search(r"\[Subject & Copy\]:[ \t]*([^\n]+)", raw_prompt)
                if m_subj3:
                    user_subject = m_subj3.group(1).strip()
    if not user_subject:
        if raw_prompt and not re.search(r"#\s*[A-Z0-9_-]+", raw_prompt) and "【" not in raw_prompt:
            user_subject = raw_prompt.strip()
        else:
            user_subject = "手绘创作"
    request_id = str(body.get("requestId") or body.get("clientRequestId") or "").strip()
    if len(request_id) > 128:
        raise ServiceError("requestId 过长", status=400, code="invalid_request_id")
    today = local_today_str()
    now_iso = utc_now_iso()
    gen_id = f"gen_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    from_skill = bool(body.get("promptFromSkill"))
    injected_notes: list[str] = []

    with db.transaction() as tx:
        from .studio_execution import lock_generation_actor
        lock_generation_actor(tx,uid)
        settings = get_site_settings(tx)
        econ = settings.get("economy", {})
        gateway = settings.get("gateway", {})

        # Idempotency is checked before permissions/charging. Once a request
        # has been accepted, a retry must replay its reservation even if the
        # browser has since changed its selected paid asset.
        if request_id:
            existing = tx.execute(
                "SELECT * FROM studio_generations WHERE user_id = ? AND request_id = ? ORDER BY created_at DESC LIMIT 1",
                (uid, request_id),
            ).fetchone()
            if existing:
                res = _cloud_generation_result(tx, existing, settings, idempotent=True)
                orig_recipe_id = str(existing["recipe_id"] or "").strip()
                if orig_recipe_id:
                    res["recipeId"] = orig_recipe_id
                    has_snap = False
                    snap_raw = existing["system_append_json"] if "system_append_json" in existing.keys() else None
                    if snap_raw is not None:
                        try:
                            snap_data = json.loads(snap_raw)
                            has_snap = True
                        except Exception:
                            has_snap = False
                    if has_snap:
                        if isinstance(snap_data, dict):
                            res["systemAppend"] = snap_data.get("systemAppend") or snap_data.get("system_append") or []
                            if snap_data.get("promptTrimmed") or snap_data.get("prompt_trimmed"):
                                res["promptTrimmed"] = True
                        elif isinstance(snap_data, list):
                            res["systemAppend"] = snap_data
                    else:
                        codes = [c.strip().upper() for c in (existing["recipe_summary"] or "").split() if c.strip()]
                        sys_append = []
                        for code in codes:
                            ca = tx.execute(
                                "SELECT secret_blackbox_prompt FROM catalog_assets WHERE code = ? AND status = 'published'",
                                (code,),
                            ).fetchone()
                            if ca and (ca["secret_blackbox_prompt"] or "").strip():
                                sys_append.append({"type": "asset_instructions", "code": code})
                        res["systemAppend"] = sys_append
                return res

        max_inflight = max(0, int(gateway.get("max_inflight_per_user", 1)))
        if max_inflight:
            active = tx.execute(
                """
                SELECT COUNT(*) AS cnt FROM studio_generations
                WHERE user_id = ? AND COALESCE(deleted_at, '') = '' AND status IN ('queued', 'running')
                """,
                (uid,),
            ).fetchone()
            if active and int(active["cnt"]) >= max_inflight:
                raise ServiceError("已有生图任务正在进行，请等待完成后再提交", status=429, code="generation_in_progress")

        # ``forkOf`` must point at a live work.  Without this check any account
        # could name an arbitrary id, spend its free quota, and book a "fork"
        # against content it never saw — free to create and free to farm.
        fork_target = str(body.get("forkOf") or "").strip()
        if fork_target:
            target_row = tx.execute(
                "SELECT id, author_username FROM works WHERE id = ? AND status = 'published'",
                (fork_target,),
            ).fetchone()
            if not target_row:
                raise ServiceError("被复刻的作品不存在或已下架", status=400, code="fork_target_invalid")
            if str(target_row["author_username"]) == str(uname):
                # Self-forks are not reuse; drop the lineage silently rather than
                # erroring out of a normal "iterate on my own work" flow.
                fork_target = ""

        fork_gen_target = str(body.get("forkGenerationId") or body.get("fork_generation_id") or "").strip()
        fork_item_target = str(body.get("forkItemId") or body.get("fork_item_id") or "").strip()
        if fork_gen_target:
            target_gen = tx.execute(
                "SELECT * FROM studio_generations WHERE id = ?",
                (fork_gen_target,),
            ).fetchone()
            if not target_gen or not check_generation_social_accessible(target_gen, viewer=user, allow_own=True):
                raise ServiceError("复刻来源生图记录不存在或已不可访问", status=404, code="fork_source_not_found")
            if int(target_gen["user_id"]) == uid:
                fork_gen_target = ""
                fork_item_target = ""

        # 1. Verify unlock status and fetch DB blackbox secrets / pending definitions.
        system_append_list: list[dict[str, str]] = []
        injected_definitions: list[str] = []
        is_paid_resource = False
        for code in (style1, style2, layout):
            if not code:
                continue
            from . import resource_registry
            res = resource_registry.resolve(tx, code, viewer=user, purpose="generate")
            if not res:
                if body.get("canvasId"):
                    raise ServiceError("批次资源已不可用",status=403,code="asset_unavailable")
                continue
            if not res.get("canUse"):
                hidden_by = (res.get("access") or {}).get("hiddenBy")
                if hidden_by == "withdrawn":
                    raise ServiceError("该资源已下架，暂不能用于生成", status=403, code="asset_withdrawn")
                elif hidden_by == "locked":
                    raise ServiceError(f"尚未解锁付费编号 {code}《{res['name']}》，请先解锁后再调用", status=403, code="asset_locked")
                else:
                    raise ServiceError("该资源暂不能用于生成", status=403, code="asset_unavailable")

            ca = tx.execute("SELECT unlock_cost, source_type FROM catalog_assets WHERE code = ? OR UPPER(code) = ?", (code, code)).fetchone()
            if (ca and (int(ca["unlock_cost"] or 0) > 0 or ca["source_type"] == "exclusive")) or int(res.get("unlock_cost") or 0) > 0 or res.get("source_type") == "exclusive":
                is_paid_resource = True

            frozen=(body.get("_canvasResourceInputs") or {}).get(code)
            if frozen:
                res={**res,"_raw_definition":frozen["_raw_definition"],
                     "secret_blackbox_prompt":frozen["secret_blackbox_prompt"],
                     "name":frozen.get("name") or res.get("name") or code}
                is_paid_resource = is_paid_resource or frozen["private"]
            if int(res.get("unlock_cost") or 0)<=0 and res.get("status")=="published":
                tx.execute("INSERT INTO unlocks(user_id,author_username,target_type,target_id,cost,author_share,status,created_at) VALUES(?,?,'asset',?,0,0,'settled',?) ON CONFLICT(user_id,target_type,target_id) DO NOTHING",(uid,str(res.get("author_username") or ""),code,now_iso))
            inject = frozen["inject"] if frozen else (res.get("access") or {}).get("inject")
            if inject == "blackbox":
                secret = (res.get("secret_blackbox_prompt") or "").strip()
                if secret:
                    injected_notes.append(secret)
                    system_append_list.append({"type": "asset_instructions", "code": code})
            elif inject == "definition":
                raw_def = (res.get("_raw_definition") or "").strip()
                if raw_def:
                    injected_notes.append(raw_def)
                    system_append_list.append({"type": "asset_instructions", "code": code})
                    injected_definitions.append(raw_def)

            elif body.get("canvasId"):
                # Free public and the author's private resources normally rely
                # on the form's prompt. Canvas prompts use the frozen definition.
                from .skill_prompt import strip_bilingual_definition
                raw_def=strip_bilingual_definition(res.get("_raw_definition") or "")
                name=str(res.get("name") or code)
                if raw_def:
                    injected_notes.append(raw_def.replace("#"+code,name).replace(code,name))
                else:
                    injected_notes.append(f"{'图型' if code==layout else '画风'}：{name}")

        canvas_user_prompt=raw_prompt
        canvas_gateway_prompt=None
        if body.get("canvasId"):
            from .canvas_prompt import build_canvas_prompt
            canvas_gateway_prompt=build_canvas_prompt(raw_prompt,body,injected_notes)
        if document_source:
            parameters=[("画幅比例",r_ratio),("创作模式",r_mode),("配色","、".join(r_colors)),
                        ("影调","、".join(r_tones)),("氛围","、".join(r_moods)),("留白",r_whitespace)]
            canvas_user_prompt += "\n"+"\n".join(f"【{label}】：{value}" for label,value in parameters if value)
        # Length check before charging (X6)
        if recipe_id or document_source:
            recipe_full_prompt = canvas_gateway_prompt or build_recipe_gateway_prompt(canvas_user_prompt, injected_notes)
            if len(recipe_full_prompt) > 4000:
                if not raw_prompt.strip():
                    raise ServiceError("所选资源系统说明超过 4000 字上限，请精简所选资源", status=400, code="prompt_too_long")
                raise ServiceError("提示词加上系统说明后超过 4000 字上限，请精简提示词", status=400, code="prompt_too_long")

        # Community points are informational here. The generation quote holds
        # specification benefits and cash atomically under the actor lock.
        cost_type="cash"
        credits_spent=0
        cur_balance=int(tx.execute("SELECT balance FROM wallets WHERE user_id=?",(uid,)).fetchone()[0])

        # Check if client-supplied prompt contains blackbox secrets or injected definitions (G9, H6, §1a-2)
        client_scan_failed = False
        client_prompt_has_secret = False
        try:
            if raw_prompt and check_text_has_secret(raw_prompt, tx, extra_secrets=injected_definitions):
                client_prompt_has_secret = True
        except Exception:
            client_scan_failed = True

        # Initial prompt without skill (written in Transaction A)
        if recipe_id or document_source:
            initial_visible_prompt = raw_prompt
        else:
            cleaned_visible = raw_prompt
            initial_visible_prompt = cleaned_visible if from_skill else (
                f"立即生成图片：\n{cleaned_visible}\n\n请直接调用画图工具立即生成图片，不要输出任何询问文字、选项或确认反问。"
            )
        if client_scan_failed:
            initial_visible_prompt = None
            prompt_masked_init = 0
        elif client_prompt_has_secret:
            initial_visible_prompt = ""
            prompt_masked_init = 1
        else:
            prompt_masked_init = 0
        if body.get("canvasId") and is_paid_resource:
            initial_visible_prompt=""
            prompt_masked_init=1

        if recipe_id or document_source:
            initial_prompt = canvas_gateway_prompt or build_recipe_gateway_prompt(canvas_user_prompt, injected_notes)
        else:
            cleaned = raw_prompt
            if injected_notes:
                cleaned += "\n\n" + "\n".join(injected_notes)
            initial_prompt = cleaned if from_skill else (
                f"立即生成图片：\n{cleaned}\n\n请直接调用画图工具立即生成图片，不要输出任何询问文字、选项或确认反问。"
            )

        needs_compose = (not from_skill) and not body.get("canvasId") and bool(style1 or style2 or layout)
        prompt_ready = 0 if needs_compose else 1
        creation_source = str(body.get("creationSource") or "").strip().lower()
        if creation_source not in ("quick", "batch", "article", "canvas"):
            creation_source = "other"

        snap = body.get("recipeSnapshot")
        if not snap and (style1 or style2 or layout):
            snap = {"style1": style1, "style2": style2, "layout": layout}

        tx.execute(
            """
            INSERT INTO studio_generations (
                id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                prompt, visible_prompt, prompt_masked, system_append_json, markdown, items_json, engine, cost_type, credits_spent, task_id,
                status, error_msg, request_id, reservation_date, created_at, fork_work_id,
                prompt_ready, recipe_id, subject, visibility,
                fork_generation_id, fork_item_id
            ) VALUES (?, ?, ?, '云端生图', ?, '云端直出', 'single', ?, ?, ?, ?, ?, '', '[]', 'live', ?, ?, '', 'running', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gen_id,
                uid,
                uname,
                str(body.get("mode") or "graphic-text") if body.get("canvasId") else str(body.get("ratio") or "3:4"),
                f"{style1} {style2} {layout}".strip(),
                initial_prompt if recipe_id else initial_prompt[:4000],
                initial_visible_prompt if (initial_visible_prompt is None or recipe_id) else initial_visible_prompt[:4000],
                prompt_masked_init,
                json.dumps(
                    {
                        "systemAppend": system_append_list,
                        "promptTrimmed": False,
                        "recipeSnapshot": snap,
                        "creationSource": creation_source,
                        **({"gatewayProtocol": "openai"} if str(gateway_protocol or "").strip().lower() == "openai" else {}),
                    },
                    ensure_ascii=False,
                ),
                cost_type,
                credits_spent,
                request_id,
                today,
                now_iso,
                fork_target,
                prompt_ready,
                recipe_id,
                user_subject,
                "public",
                fork_gen_target,
                fork_item_target,
            ),
        )
        if batch_id:
            tx.execute(
                "UPDATE studio_generations SET batch_id=?,batch_index=?,batch_total=? WHERE id=?",
                (batch_id, batch_index, batch_total, gen_id),
            )
        # V3: reserve the logical run once, not once per gateway subrequest.
        # Concurrent model calls may have distinct requestId values, but share
        # their user's stable batchId and therefore one run / public work.
        from .generation_v3 import ensure_run
        try:
            canonical_run_id = ensure_run(
                tx, user_id=uid, source="web",
                external_run_id=batch_id or gen_id,
                expected_count=batch_total if batch_id else 1,
                request_id=batch_id or request_id,
            )
        except ValueError as exc:
            msg = str(exc).lower()
            if "size" in msg:
                raise ServiceError(
                    "当前系列批次张数已变更，请使用新批次重新发起生成",
                    status=409,
                    code="batch_size_mismatch",
                ) from exc
            raise ServiceError(
                "批次校验冲突，请开启新批次后再试",
                status=409,
                code="batch_conflict",
            ) from exc
        if batch_id:
            # Serialize remote-submission reservation against cancellation.
            # The cancellation endpoint locks the SAME run before writing a
            # cancelled slot, so a late client request cannot bypass it.
            tx.execute(
                "SELECT id FROM generation_runs WHERE id=? FOR UPDATE",
                (canonical_run_id,),
            ).fetchone()
            prior_slot = tx.execute(
                "SELECT status FROM generation_items WHERE run_id=? AND (ordinal=? OR (ordinal IS NULL AND position=?))",
                (canonical_run_id, batch_index,batch_index*1000),
            ).fetchone()
            if prior_slot and prior_slot["status"] == "cancelled":
                if body.get("retryCancelled") is not True:
                    raise ServiceError(
                        "该图片已被取消；如需重新生成，请明确选择重试",
                        status=409, code="generation_slot_cancelled",
                    )
        tx.execute(
            "UPDATE generation_runs SET original_request=? WHERE id=?",
            (user_subject, canonical_run_id),
        )

        if cost_type == "free_quota":
            tx.execute(
                """
                INSERT INTO studio_quota_reservations
                    (generation_id, user_id, reservation_date, units, status, created_at)
                VALUES (?, ?, ?, 1, 'reserved', ?)
                """,
                (gen_id, uid, today, now_iso),
            )
        from .economy import attach_charge
        attach_charge(tx,uid,gen_id,body)
        from .studio_execution import attach_attempt
        attach_attempt(tx, uid, canonical_run_id, gen_id, body)

    prompt_trimmed = False
    # Outside transaction: model call for freshly inserted rows
    if needs_compose:
        db.release_request_connection()
        composed = None
        try:
            if recipe_id or body.get("canvasId"):
                composed = _compose_skill_prompt(
                    style1 or style2,
                    layout,
                    raw_prompt,
                    style2_code=style2 if style1 else "",
                    colors=r_colors,
                    tones=r_tones,
                    moods=r_moods,
                    whitespace=r_whitespace,
                    ratio=r_ratio,
                    mode=r_mode,
                )
            else:
                composed = _compose_skill_prompt(style1 or style2, layout, raw_prompt)
        except Exception:
            logger.exception("Failed to compose skill prompt for generation %s", gen_id)
            composed = None

        if recipe_id or body.get("canvasId"):
            if composed:
                full_test = build_recipe_gateway_prompt(composed, injected_notes)
                if len(full_test) > 4000:
                    append_parts = [n.strip() for n in injected_notes if n and str(n).strip()]
                    append_text = "\n\n".join(append_parts)
                    separator_len = 2 if (append_text and composed) else 0
                    max_budget = 4000 - separator_len - len(append_text)
                    trimmed = trim_composed_prompt(composed, max_budget)
                    skill_prompt_text = build_recipe_gateway_prompt(trimmed, injected_notes)
                    skill_visible_prompt_text = trimmed
                    prompt_trimmed = True
                else:
                    skill_prompt_text = full_test
                    skill_visible_prompt_text = composed
            else:
                skill_prompt_text = None
                skill_visible_prompt_text = None
        else:
            if composed:
                skill_prompt_text = (composed + ("\n\n" + "\n".join(injected_notes) if injected_notes else ""))[:4000]
                skill_visible_prompt_text = composed[:4000]
            else:
                skill_prompt_text = None
                skill_visible_prompt_text = None

        with db.transaction() as tx:
            if client_scan_failed:
                final_vis_prompt = None
                final_masked = 0
            elif body.get("canvasId") and is_paid_resource or client_prompt_has_secret:
                final_vis_prompt = ""
                final_masked = 1
            elif skill_visible_prompt_text:
                try:
                    if check_text_has_secret(skill_visible_prompt_text, tx, extra_secrets=injected_definitions):
                        final_vis_prompt = ""
                        final_masked = 1
                    else:
                        final_vis_prompt = skill_visible_prompt_text
                        final_masked = 0
                except Exception:
                    final_vis_prompt = None
                    final_masked = 0
            else:
                final_vis_prompt = initial_visible_prompt
                final_masked = prompt_masked_init

            cur = tx.execute(
                """
                UPDATE studio_generations
                SET prompt = COALESCE(?, prompt),
                    visible_prompt = ?,
                    prompt_masked = ?,
                    system_append_json = ?,
                    prompt_ready = 1
                WHERE id = ? AND prompt_ready = 0
                """,
                (
                    skill_prompt_text,
                    final_vis_prompt,
                    final_masked,
                    json.dumps(
                        {
                            "systemAppend": system_append_list,
                            "promptTrimmed": bool(prompt_trimmed),
                            "recipeSnapshot": snap,
                            "creationSource": creation_source,
                            **({"gatewayProtocol": "openai"} if str(gateway_protocol or "").strip().lower() == "openai" else {}),
                        },
                        ensure_ascii=False,
                    ),
                    gen_id,
                ),
            )
            if cur.rowcount == 0:
                logger.warning("Transaction B: generation %s was not in prompt_ready=0 state (rowcount=0)", gen_id)

    # Keep the historical response keys while making request/retry state
    # explicit for the server and the canvas recovery client.
    # Re-read final row and finalPrompt directly from the database.
    current_row = db.get_conn().execute("SELECT * FROM studio_generations WHERE id = ?", (gen_id,)).fetchone()
    result = _cloud_generation_result(db.get_conn(), current_row, settings)
    result.update({
        "credits": cur_balance,
        "freeQuotaRemaining": result["freeQuotaRemaining"],
    })
    if recipe_id:
        result["recipeId"] = recipe_id
        result["systemAppend"] = system_append_list
        if prompt_trimmed:
            result["promptTrimmed"] = True
    return result


def refund_failed_cloud_generation(db: Database, gen_id: str, error_msg: str, *, poll_claim_token=None) -> None:
    now_iso = utc_now_iso()
    today = local_today_str()
    with db.transaction() as tx:
        from .studio_execution import lock_attempt
        row = lock_attempt(tx, gen_id, poll_claim_token=poll_claim_token)
        if not row or row["status"] in ("refunded", "success"):
            return
        uid = int(row["user_id"])
        tx.execute(
            "UPDATE studio_generations SET status = 'refunded', error_msg = ? WHERE id = ?",
            ((error_msg or "")[:300], gen_id),
        )
        from .economy import finish_charge
        finish_charge(tx,gen_id,success=False)
        if row["cost_type"] == "free_quota":
            reservation = tx.execute(
                "SELECT reservation_date, units, status FROM studio_quota_reservations WHERE generation_id = ?",
                (gen_id,),
            ).fetchone()
            reservation_date = str(
                (reservation["reservation_date"] if reservation else None)
                or row["reservation_date"]
                or str(row["created_at"] or "")[:10]
                or today
            )
            units = max(1, int(reservation["units"] if reservation else 1))
            if reservation and reservation["status"] == "reserved":
                tx.execute(
                    "UPDATE studio_quota_reservations SET status = 'released', released_at = ? WHERE generation_id = ? AND status = 'reserved'",
                    (now_iso, gen_id),
                )
            # Only decrement the wallet counter when it is still the same
            # business day. Across midnight, the old reservation is already
            # outside today's counter and must not reduce the new day's quota.
            if reservation_date == today:
                tx.execute(
                    "UPDATE wallets SET free_quota_used = GREATEST(0, free_quota_used - ?), updated_at = ? WHERE user_id = ? AND free_quota_date = ?",
                    (units, now_iso, uid, reservation_date),
                )
        elif int(row["credits_spent"] or 0) > 0:
            apply_wallet_delta(
                tx,
                uid,
                int(row["credits_spent"]),
                "studio_refund",
                f"云端生图异常自动退还积分 ({gen_id})",
                event_key=f"gen_refund_{gen_id}",
                ref_type="generation",
                ref_id=gen_id,
            )

        # The run remains the history identity even when every subrequest
        # fails. Do not create a public work for a fully failed run.
        logical_key = str(row["batch_id"] or "") or gen_id
        from .generation_v3 import _stable_id
        canonical_run_id = row["run_id"] or _stable_id("run", uid, "web", logical_key)
        exists = tx.execute(
            "SELECT 1 FROM generation_runs WHERE id=?", (canonical_run_id,),
        ).fetchone()
        from .studio_execution import is_current_attempt
        current_attempt = is_current_attempt(tx, row)
        if exists and current_attempt and row["item_id"]:
            tx.execute("UPDATE generation_items SET status='failed',media_id=NULL,error_code='gateway_failed',updated_at=? WHERE id=? AND status<>'success'",
                       (now_iso,row["item_id"]))
        elif exists and current_attempt:
            position = (
                int(row["batch_index"] or 0) * 1000
                if row["batch_id"] else 0
            )
            tx.execute(
                """
                INSERT INTO generation_items
                  (id,run_id,position,status,media_id,error_code,created_at,updated_at)
                VALUES (?, ?, ?, 'failed',NULL,'gateway_failed',?,?)
                ON CONFLICT(run_id,position) DO UPDATE SET
                    status='failed',media_id=NULL,error_code='gateway_failed',updated_at=excluded.updated_at
                WHERE generation_items.status <> 'success'
                """,
                (_stable_id("item", canonical_run_id, position),
                 canonical_run_id, position, now_iso, now_iso),
            )
        # V3: use ONE slot-driven state machine for success, failure and
        # cancellation. Gateway execution rows are billing facts, not another
        # authoritative logical-run state.
        if exists and current_attempt:
            from .generation_v3 import refresh_run_status
            refresh_run_status(tx, canonical_run_id)


def complete_cloud_generation(db: Database, gen_id: str, task_id: str, image_urls: list[str] | None = None, *, poll_claim_token=None) -> None:
    if image_urls is not None:
        image_urls = list(dict.fromkeys(str(url or "").strip() for url in image_urls if str(url or "").strip()))
    if image_urls is not None and not any(str(url or "").strip() for url in image_urls):
        # Gateway status "success" is not success for the user if every
        # image download/validation failed. Never consume quota and leave
        # a permanently empty public generation in its place.
        refund_failed_cloud_generation(db, gen_id, "生图任务未返回可保存的有效图片", poll_claim_token=poll_claim_token)
        return
    with db.transaction() as tx:
        from .studio_execution import lock_attempt
        generation = lock_attempt(tx, gen_id, poll_claim_token=poll_claim_token)
        if not generation or generation["status"] in ("refunded", "success"):
            return
        if image_urls is not None:
            from .economy import finish_charge
            finish_charge(tx,gen_id,success=True)
            tx.execute(
                "UPDATE studio_generations SET status = 'success', task_id = ?, items_json = ? WHERE id = ? AND status NOT IN ('refunded', 'success')",
                (task_id, json.dumps(image_urls, ensure_ascii=False), gen_id),
            )
            tx.execute(
                "UPDATE studio_quota_reservations SET status = 'consumed' WHERE generation_id = ? AND status = 'reserved'",
                (gen_id,),
            )
            # A fork is real work: it counts only once an actual image came back,
            # the run was not a sample, the run was not refunded first, and the
            # caller is not the parent's author.  The client cannot inflate this
            # by passing ``forkOf`` at publish time.
            already_refunded = bool(generation) and str(generation["status"] or "") == "refunded"
            if generation and generation["fork_work_id"] and generation["engine"] != "sample" and not already_refunded:
                real_images = [u for u in (image_urls or []) if str(u or "").strip()]
                if real_images:
                    parent = tx.execute(
                        "SELECT author_username FROM works WHERE id = ?", (generation["fork_work_id"],)
                    ).fetchone()
                    owner = tx.execute(
                        "SELECT username FROM users WHERE id = ?", (generation["user_id"],)
                    ).fetchone()
                    if parent and owner and str(owner["username"]) != str(parent["author_username"]):
                        from .curation import count_fork_if_new

                        count_fork_if_new(
                            tx,
                            str(generation["fork_work_id"]),
                            int(generation["user_id"]),
                            gen_id,
                            utc_now_iso(),
                        )
            if generation and generation["user_id"] is not None:
                for idx, media_url in enumerate(image_urls or []):
                    safe_url = str(media_url or "").strip()
                    if not safe_url:
                        continue
                    tx.execute(
                        """
                        INSERT INTO studio_generation_media
                            (id, generation_id, user_id, media_url, media_kind, storage_path, visibility, created_at)
                        VALUES (?, ?, ?, ?, 'generated', ?, 'private', ?) ON CONFLICT DO NOTHING
                        """,
                        (
                            f"gm_{gen_id}_{idx}",
                            gen_id,
                            int(generation["user_id"]),
                            safe_url,
                            safe_url.removeprefix("/generated/").split("?", 1)[0],
                            utc_now_iso(),
                        ),
                    )
            from .studio_execution import record_attempt_media, is_current_attempt
            if generation and not already_refunded:
                record_attempt_media(tx, generation, image_urls or [])
            if not is_current_attempt(tx, generation):
                return
            # Public success must not be committed without its canonical works.
            # Projection errors roll back this transaction instead of silently hiding images.
            from .generation_works import project_generation_to_works
            project_generation_to_works(tx, gen_id)
        else:
            tx.execute("UPDATE studio_generations SET task_id = ? WHERE id = ? AND status NOT IN ('refunded', 'success')", (task_id, gen_id))


def record_cloud_generation_task_id(db: Database, gen_id: str, task_id: str) -> None:
    """Record the client_task_id onto a pending studio generation before calling the gateway."""
    with db.transaction() as tx:
        tx.execute(
            "UPDATE studio_generations SET task_id = ? WHERE id = ? AND status NOT IN ('refunded', 'success')",
            (task_id, gen_id),
        )



def grant_studio_media_public(
    db: Database,
    user: dict[str, Any],
    media_url: str,
    target_type: str,
    target_id: str,
    generation_id: str | None = None,
) -> dict[str, Any]:
    """Grant one owned private media URL to one published content target.

    Publication code should call this only after validating the target's
    ownership/status. The grant is explicit and revocable; it is never inferred
    from a URL merely appearing in a draft.
    """
    uid = int(user["id"])
    url = str(media_url or "").strip().split("?", 1)[0]
    ttype = str(target_type or "").strip()
    tid = str(target_id or "").strip()
    if not url or not ttype or not tid:
        raise ServiceError("媒体授权参数不完整", status=400, code="media_grant_invalid")

    with db.transaction() as tx:
        media = tx.execute(
            "SELECT user_id, generation_id FROM studio_generation_media WHERE media_url = ? ORDER BY created_at DESC LIMIT 1",
            (url,),
        ).fetchone()
        owner_id = int(media["user_id"]) if media else None
        resolved_generation_id = generation_id or (media["generation_id"] if media else None)
        if owner_id is None and url.startswith("/uploads/"):
            upload = tx.execute(
                "SELECT user_id FROM user_uploads WHERE image_url = ? OR file_path = ? LIMIT 1",
                (url, url),
            ).fetchone()
            owner_id = int(upload["user_id"]) if upload else None
        if owner_id is None and resolved_generation_id:
            generation = tx.execute("SELECT user_id FROM studio_generations WHERE id = ?", (resolved_generation_id,)).fetchone()
            owner_id = int(generation["user_id"]) if generation and generation["user_id"] is not None else None
        if owner_id is None:
            raise ServiceError("找不到该私有媒体或其所有者", status=404, code="media_not_found")
        if owner_id != uid and user.get("role") not in ("admin", "operator", "reviewer"):
            raise ServiceError("无权公开其他账号的私有媒体", status=403, code="media_forbidden")

        grant_id = f"grant_{uuid.uuid4().hex}"
        now_iso = utc_now_iso()
        tx.execute(
            """
            INSERT INTO media_public_grants
                (id, media_url, owner_user_id, generation_id, target_type, target_id, granted_by_user_id, granted_at, revoked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(media_url, target_type, target_id) DO UPDATE SET
                owner_user_id = excluded.owner_user_id,
                generation_id = excluded.generation_id,
                granted_by_user_id = excluded.granted_by_user_id,
                granted_at = excluded.granted_at,
                revoked_at = NULL
            """,
            (grant_id, url, owner_id, resolved_generation_id, ttype, tid, uid, now_iso),
        )
    return {"ok": True, "mediaUrl": url, "targetType": ttype, "targetId": tid, "generationId": resolved_generation_id}


# ======================== SKILL-ADDON COMPATIBILITY (/studio/api/library) ========================

def build_skill_library_payload(db: Database, user: dict[str, Any]) -> dict[str, Any]:
    conn = db.get_conn()
    uid = int(user["id"])
    uname = user["username"]

    fav_codes = {
        r["target_id"]
        for r in conn.execute("SELECT target_id FROM collections WHERE user_id = ? AND bucket IN ('styles', 'layouts')", (uid,)).fetchall()
    }
    unlocked_codes = {
        r["target_id"]
        for r in conn.execute("SELECT target_id FROM unlocks WHERE user_id = ? AND target_type = 'asset' AND status = 'settled'", (uid,)).fetchall()
    }

    collected = []
    owned = []
    library_asset_filter, library_asset_ids = _seed_filter("code", "assets")
    official = []
    for r in conn.execute(
        f"SELECT * FROM catalog_assets WHERE status = 'published' AND {library_asset_filter}",
        library_asset_ids,
    ).fetchall():
        code = r["code"]
        if r["source_type"] == "exclusive":
            # Online-exclusive blackbox styles cannot be exported offline to local skill library
            continue
        if r["source_type"] == "official_override":
            continue
        if r["source_type"] == "official":
            if code in fav_codes:
                cost = int(r["unlock_cost"] or 0)
                is_unlocked = cost <= 0 or (code in unlocked_codes)
                official.append(
                    {
                        "id": f"official:{code}",
                        "ref": code,
                        "title": r["name"],
                        "name": r["name"],
                        "kind": r["kind"],
                        "version": "1.0.0",
                        "collected": True,
                        "unlocked": is_unlocked,
                        "source": "official",
                        "content_url": f"/studio/api/assets/{code}/content" if cost <= 0 else None,
                    }
                )
            continue
        is_mine = r["author_username"] == uname
        is_fav = code in fav_codes
        if not (is_mine or is_fav):
            continue
        is_unlocked = int(r["unlock_cost"] or 0) <= 0 or is_mine or (code in unlocked_codes)
        entry = {
            "id": f"asset:{code}",
            "ref": code,
            "title": r["name"],
            "name": r["name"],
            "kind": r["kind"],
            "version": "1.0.0",
            "collected": is_fav,
            "unlocked": is_unlocked,
            "source": "community",
            "author": {"username": r["author_username"], "name": r["author_name"]},
            "content_url": f"/studio/api/assets/{code}/content" if (is_unlocked and (int(r["unlock_cost"] or 0) <= 0 or is_mine)) else None,
        }
        if is_mine:
            owned.append(entry)
        else:
            collected.append(entry)

    # Also expose favorited official catalog items
    handled_official_refs = {item["ref"] for item in official}
    cat_file = CONTENT_DIR / "catalog.json"
    if cat_file.is_file():
        cat_data = json.loads(cat_file.read_text(encoding="utf-8"))
        for item in cat_data.get("resources", []):
            code = item.get("id")
            if code in fav_codes and code not in handled_official_refs and item.get("kind") in ("style", "layout"):
                handled_official_refs.add(code)
                official.append(
                    {
                        "id": f"official:{code}",
                        "ref": code,
                        "title": item.get("name") or code,
                        "name": item.get("name") or code,
                        "kind": item.get("kind"),
                        "version": "1.0.0",
                        "collected": True,
                        "unlocked": True,
                        "source": "official",
                        "content_url": f"/studio/api/assets/{code}/content",
                    }
                )

    # Also expose collected pending submission resources
    handled_codes = {r["ref"] for r in collected} | {r["ref"] for r in owned} | {r["ref"] for r in official}
    remaining_favs = fav_codes - handled_codes
    if remaining_favs:
        from . import resource_registry
        for fcode in sorted(remaining_favs):
            res = resource_registry.resolve(conn, fcode, viewer=user, purpose="view")
            if res and res.get("source") == "pending":
                collected.append(
                    {
                        "id": f"asset:{res['code']}",
                        "ref": res["code"],
                        "title": res["name"],
                        "name": res["name"],
                        "kind": res["kind"],
                        "version": "1.0.0",
                        "collected": True,
                        "unlocked": False,
                        "source": "pending",
                        "author": {"username": res.get("owner", {}).get("username", ""), "name": res.get("owner", {}).get("name", "")},
                        "content_url": None,
                    }
                )

    return {"collected": collected, "owned": owned, "official": official}


def build_skill_asset_content(db: Database, user: dict[str, Any], code: str) -> dict[str, Any]:
    clean_code = (code or "").strip().upper()
    if not is_demo_mode() and clean_code in seed_ids("assets"):
        raise ServiceError(f"未找到资源编号：{clean_code}", status=404, code="seed_content_hidden")
    conn = db.get_conn()
    from . import resource_registry
    res = resource_registry.resolve(conn, clean_code, viewer=user, purpose="view")
    if not res:
        raise ServiceError(f"未找到资源编号：{clean_code}", status=404)

    hidden_by = (res.get("access") or {}).get("hiddenBy")
    if hidden_by == "blackbox":
        raise ServiceError("官网在线独占黑盒资产仅支持云端调用，不支持导出明文定义", status=403)
    elif hidden_by == "paid":
        raise ServiceError("付费资产仅支持在线创作台调用，不支持导出明文定义", status=403)
    elif hidden_by == "locked":
        raise ServiceError("该共创资产尚未解锁", status=403)
    elif hidden_by == "pending":
        raise ServiceError("该资源尚未收录，暂不支持导出明文定义", status=403)
    elif hidden_by == "withdrawn":
        raise ServiceError("该资源已下架", status=403)

    if not (res.get("access") or {}).get("canRead"):
        raise ServiceError("暂无权查看此资源定义", status=403)

    license_name = (
        "Handraw Community Co-Creation License 1.0"
        if res.get("source") in ("community", "pending")
        else "Handraw Official Reference License 1.0"
    )
    resource: dict[str, Any] = {
        "kind": res["kind"],
        "name": f"{clean_code} {res['name']}",
        "prompt_zh": res["definition"] or clean_code,
        "prompt_en": f"Handraw {res['kind']} {clean_code}: {res['name']}",
        "license": license_name,
        "version": "1.0.0",
    }
    if res.get("author"):
        resource["author"] = {
            "username": res.get("author"),
            "name": res.get("authorName") or res.get("author"),
        }

    canonical = json.dumps(resource, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return {"resource": resource, "sha256": digest}


# ======================== DISCOURSE USER MIGRATION IMPORTER ========================

def import_discourse_users_batch(
    db: Database,
    actor: dict[str, Any] | None,
    raw_payload: str | list[dict[str, Any]],
    migration_credits: int | None = None,
) -> dict[str, Any]:
    """Import Discourse users from JSON list or CSV text additively (idempotent on username/email)."""
    records: list[dict[str, Any]] = []
    if isinstance(raw_payload, list):
        records = [r for r in raw_payload if isinstance(r, dict)]
    elif isinstance(raw_payload, str):
        stripped = raw_payload.strip()
        if not stripped:
            raise ServiceError("导入内容不能为空")
        if stripped.startswith("[") or stripped.startswith("{"):
            parsed = json.loads(stripped)
            records = parsed.get("users", []) if isinstance(parsed, dict) else parsed
        else:
            reader = csv.DictReader(io.StringIO(stripped))
            records = [dict(row) for row in reader]

    if not records:
        raise ServiceError("未解析到有效的 Discourse 用户记录")

    now_iso = utc_now_iso()
    imported = 0
    skipped = 0
    imported_usernames: list[str] = []
    skipped_no_email: list[str] = []
    invalid_usernames: list[str] = []
    conflicts: list[dict[str, Any]] = []
    staff_candidates: list[str] = []

    with db.transaction() as tx:
        settings = get_site_settings(tx)
        bonus = (
            int(migration_credits)
            if migration_credits is not None
            else int(settings.get("economy", {}).get("discourse_migration_credits", 50))
        )

        for rec in records:
            raw_uname = str(rec.get("username") or "").strip()
            cleaned_uname = re.sub(r"[^a-zA-Z0-9_\-]", "", raw_uname)
            if not raw_uname or cleaned_uname != raw_uname:
                invalid_usernames.append(raw_uname)
                skipped += 1
                continue
            if cleaned_uname.lower() in ("system", "discobot"):
                skipped += 1
                continue
            uname = cleaned_uname

            email = str(rec.get("email") or "").strip().lower()
            if not email:
                skipped_no_email.append(uname)
                skipped += 1
                continue

            exists_uname = tx.execute("SELECT id FROM users WHERE username = ?", (uname,)).fetchone()
            exists_email = tx.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if exists_uname or exists_email:
                if exists_uname and exists_email:
                    hit = "both"
                elif exists_uname:
                    hit = "username"
                else:
                    hit = "email"
                conflicts.append({"username": uname, "email": email, "hit": hit, "conflict": hit})
                skipped += 1
                continue

            dname = str(rec.get("name") or rec.get("display_name") or uname).strip()[:40]
            is_admin = str(rec.get("admin") or "").lower() in ("true", "1", "t", "yes") or rec.get("admin") is True
            is_mod = str(rec.get("moderator") or "").lower() in ("true", "1", "t", "yes") or rec.get("moderator") is True
            role = "user"
            if is_admin or is_mod:
                staff_candidates.append(uname)

            disc_hash = str(rec.get("password_hash") or "").strip()
            disc_salt = str(rec.get("salt") or "").strip()
            plain_pw = str(rec.get("password") or "").strip()

            if disc_hash and disc_salt and len(disc_hash) == 64:
                pw_hash = disc_hash.lower()
                pw_algo = "discourse_pbkdf2"
            elif plain_pw:
                pw_hash = hash_password(plain_pw)
                pw_algo = "pbkdf2_sha256"
                disc_salt = ""
            else:
                pw_hash = ""
                pw_algo = "reset_required"
                disc_salt = ""

            disc_id = int(rec["id"]) if str(rec.get("id") or "").isdigit() else None
            created_at = str(rec.get("created_at") or now_iso)
            api_key = ""

            cur = tx.execute(
                """
                INSERT INTO users (
                    username, display_name, email, password_hash, password_algo,
                    discourse_salt, discourse_user_id, role, status, bio,
                    invite_code, api_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', '原 Discourse 社区老用户迁移账号', ?, ?, ?) RETURNING id
                """,
                (uname, dname, email, pw_hash, pw_algo, disc_salt, disc_id, role, uname, api_key or None, created_at),
            )
            uid = int(cur.fetchone()[0])
            tx.execute(
                "INSERT INTO wallets (user_id, balance, free_quota_date, free_quota_used, checkin_date, locked, updated_at) VALUES (?, 0, '', 0, '', 0, ?)",
                (uid, now_iso),
            )
            if bonus > 0:
                apply_wallet_delta(
                    tx,
                    uid,
                    bonus,
                    "discourse_migration",
                    "原 Discourse 社区老用户无缝迁移激活礼包",
                    event_key=f"disc_mig_{uid}",
                )
            imported += 1
            imported_usernames.append(uname)

        record_audit_log(
            tx,
            actor,
            "users.import_discourse",
            "users",
            f"batch:{imported}",
            f"导入原 Discourse 注册用户 {imported} 人（跳过已存在 {skipped} 人），每人发放迁移礼金 +{bonus}✦",
            {"imported": imported, "skipped": skipped, "sample": imported_usernames[:10]},
        )

    return {
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "bonusPerUser": bonus,
        "usernames": imported_usernames,
        "skippedNoEmail": skipped_no_email,
        "invalidUsernames": invalid_usernames,
        "conflicts": conflicts,
        "staffCandidates": staff_candidates,
    }
