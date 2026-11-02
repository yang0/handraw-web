"""Core domain services for Handraw Web 2.0 (Auth, Boot, Economy, Catalog, Works, Forum, Studio, Skill-Addon)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import threading
import time
import uuid
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend.services")

from .config import CONTENT_DIR, SESSION_COOKIE_NAME, SESSION_TTL_SECONDS
from .db import Database, local_today_str, utc_now_iso
from .seed import DEFAULT_SITE_SETTINGS, DEMO_DEFAULT_PASSWORD, is_demo_mode, is_seed_username, seed_ids
from .runtime_policy import sanitize_media_url
from .work_schema import deduplicate_generation_history
from .security import (
    generate_api_key,
    generate_session_token,
    hash_password,
    parse_cookie_header,
    verify_password,
)


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


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
    {"key": "showcase", "label": "🎨 晒作品", "shortLabel": "晒作品版", "desc": "发布作品即进入本版，作品、画风与图型自动关联，可回复讨论"},
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


def get_site_settings(conn: sqlite3.Connection) -> dict[str, Any]:
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
    tx: sqlite3.Connection,
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
    tx: sqlite3.Connection,
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
    now = utc_now_iso()
    w = tx.execute("SELECT balance, locked FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
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
    tx.execute(
        """
        INSERT INTO ledgers (user_id, delta, balance_after, kind, event_key, reason, ref_type, ref_id, actor_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, int(delta), new_balance, kind, event_key, reason, ref_type, str(ref_id), actor_id, now),
    )
    return new_balance, True


def get_wallet_quota_state(conn: sqlite3.Connection, user_id: int, settings: dict[str, Any]) -> dict[str, Any]:
    today = local_today_str()
    econ = settings.get("economy", {})
    max_q = max(0, int(econ.get("daily_free_quota", 3)))
    w = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
    if not w:
        return {"balance": 0, "freeQuotaMax": max_q, "freeQuotaRemaining": max_q, "dailyCheckedIn": False, "locked": False}
    used = int(w["free_quota_used"]) if w["free_quota_date"] == today else 0
    checked_in = bool(w["checkin_date"] == today)
    return {
        "balance": int(w["balance"]),
        "freeQuotaMax": max_q,
        "freeQuotaRemaining": max(0, max_q - used),
        "dailyCheckedIn": checked_in,
        "locked": bool(w["locked"]),
    }


def _count_user_published_items(conn: sqlite3.Connection, username: str) -> int:
    work_filter, work_ids = _seed_filter("id", "works")
    asset_filter, asset_ids = _seed_filter("code", "assets")
    w_cnt = int(
        conn.execute(
            f"SELECT COUNT(*) FROM works WHERE author_username = ? AND status = 'published' AND images_json IS NOT NULL AND TRIM(images_json) NOT IN ('', '[]', 'null') AND json_valid(images_json) = 1 AND {work_filter}",
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
            # To prevent SQLite write lock contention on frequent read queries (e.g. Skill sync),
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
        row = conn.execute(
            """
            SELECT u.*
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, now_ts),
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

    row = conn.execute(
        """
        SELECT u.*
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ? AND s.expires_at > ?
        """,
        (sess_token, now_ts),
    ).fetchone()
    if not row or row["status"] != "active":
        return None
    result = dict(row)
    result["_session_token"] = sess_token
    result["_auth_kind"] = "session"
    result["_token_scopes"] = ["*"]
    return result


def create_session_for_user(tx: sqlite3.Connection, user_id: int, user_agent: str = "", ip_addr: str = "") -> str:
    token = generate_session_token()
    now_iso = utc_now_iso()
    exp = int(time.time()) + SESSION_TTL_SECONDS
    tx.execute(
        "INSERT INTO sessions (token, user_id, user_agent, ip_addr, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (token, user_id, (user_agent or "")[:200], (ip_addr or "")[:64], exp, now_iso),
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
    if len(password or "") < 6:
        raise ServiceError("登录密码长度至少 6 位")

    clean_email = (email or f"{uname}@handraw-style.com").strip().lower()
    dname = (display_name or uname).strip()[:40]
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
                role, status, bio, invite_code, invited_by, api_key, created_at, last_login_at
            ) VALUES (?, ?, ?, ?, 'pbkdf2_sha256', 'user', 'active', 'Handraw 新锐社区创作者', ?, ?, ?, ?, ?)
            """,
            (uname, dname, clean_email, pw_hash, uname, inviter_row["username"] if inviter_row else "", api_key or None, now_iso, now_iso),
        )
        uid = int(cur.lastrowid)
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
    with db.transaction() as tx:
        tx.execute("DELETE FROM sessions WHERE token = ?", (token,))


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
    """Self-service personal account profile & password management for logged-in users."""
    uid = int(user["id"])
    with db.transaction() as tx:
        row = tx.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if not row:
            raise ServiceError("账号不存在", status=404)

        dname = str(body.get("displayName") if body.get("displayName") is not None else row["display_name"]).strip()[:40]
        if not dname:
            raise ServiceError("显示昵称不能为空")
        email = str(body.get("email") if body.get("email") is not None else (row["email"] or "")).strip().lower()[:120]
        bio = str(body.get("bio") if body.get("bio") is not None else (row["bio"] or "")).strip()[:300]

        if email and email != (row["email"] or "").lower():
            dup = tx.execute("SELECT id FROM users WHERE LOWER(email) = ? AND id != ?", (email, uid)).fetchone()
            if dup:
                raise ServiceError("该邮箱已被其他账号绑定")

        pw_hash = row["password_hash"]
        pw_algo = row["password_algo"]
        disc_salt = row["discourse_salt"]
        new_pw = str(body.get("newPassword") or "")
        if new_pw:
            if len(new_pw) < 6:
                raise ServiceError("新登录密码长度至少 6 位")
            cur_pw = str(body.get("currentPassword") or "")
            if not verify_password(cur_pw, row["password_hash"], password_algo=row["password_algo"], discourse_salt=row["discourse_salt"]):
                raise ServiceError("当前旧密码验证不正确", status=403)
            pw_hash = hash_password(new_pw)
            pw_algo = "pbkdf2_sha256"
            disc_salt = ""

        api_key = generate_api_key() if body.get("regenerateApiKey") else row["api_key"]
        tx.execute(
            """
            UPDATE users SET display_name = ?, email = ?, bio = ?, password_hash = ?, password_algo = ?, discourse_salt = ?, api_key = ?
            WHERE id = ?
            """,
            (dname, email, bio, pw_hash, pw_algo, disc_salt, api_key, uid),
        )
        # Keep denormalized author_name fresh on user's works/topics/assets
        if dname != row["display_name"]:
            tx.execute("UPDATE works SET author_name = ? WHERE author_username = ?", (dname, row["username"]))
            tx.execute("UPDATE forum_topics SET author_name = ? WHERE author_username = ?", (dname, row["username"]))
            tx.execute("UPDATE catalog_assets SET author_name = ? WHERE author_username = ? AND source_type = 'community'", (dname, row["username"]))

        updated = dict(tx.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())
    return {"ok": True, "boot": build_boot_payload(db, updated)}


# ======================== BOOT PAYLOAD & STRICT SERVER GATES ========================

def _serialize_catalog_asset(row: sqlite3.Row, unlocked_set: set[str], current_user: dict[str, Any] | None) -> dict[str, Any]:
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
        public_def = f"[LOCKED_ASSET::{code}] 付费共创资产（需 {cost} 积分解锁后查看完整定义词与创作台挂载权限）"
    else:
        public_def = row["definition"] or row["description"] or ""

    try:
        stamps = json.loads(row["stamp_counts_json"] or "{}")
    except Exception:
        stamps = {}

    return {
        "id": code,
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


def get_secrets_cache(conn: sqlite3.Connection | None = None, force: bool = False) -> tuple[str, list[str], set[str]]:
    global _SECRETS_CACHE
    now = time.time()
    secrets: list[str] = []
    if conn is not None:
        try:
            rows = conn.execute(
                "SELECT DISTINCT secret_blackbox_prompt FROM catalog_assets WHERE secret_blackbox_prompt IS NOT NULL AND TRIM(secret_blackbox_prompt) <> ''"
            ).fetchall()
            secrets = [str(r[0]).strip() for r in rows if r[0] and str(r[0]).strip()]
        except Exception as exc:
            raise SecretsScanError(f"Failed to query catalog secrets: {exc}") from exc
    else:
        try:
            from .config import get_db_path
            target = get_db_path()
            if not Path(target).exists():
                raise SecretsScanError(f"Database path not found: {target}")
            one_shot = sqlite3.connect(str(target), timeout=5.0)
            try:
                rows = one_shot.execute(
                    "SELECT DISTINCT secret_blackbox_prompt FROM catalog_assets WHERE secret_blackbox_prompt IS NOT NULL AND TRIM(secret_blackbox_prompt) <> ''"
                ).fetchall()
                secrets = [str(r[0]).strip() for r in rows if r[0] and str(r[0]).strip()]
            finally:
                one_shot.close()
        except Exception as exc:
            raise SecretsScanError(f"Failed to query catalog secrets from db path: {exc}") from exc

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
    conn: sqlite3.Connection | None = None,
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
    conn: sqlite3.Connection | None = None,
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


def get_valid_catalog_codes(conn: sqlite3.Connection | None = None) -> dict[str, set[str]]:
    """Return dictionary of real catalog codes {styles, layouts, colors, tones, all} (J2, J3)."""
    static = _get_static_catalog_codes()
    styles = set(static["styles"])
    layouts = set(static["layouts"])
    colors = set(static["colors"])
    tones = set(static["tones"])

    rows: list[Any] = []
    if conn is not None:
        try:
            rows = conn.execute("SELECT code, kind FROM catalog_assets").fetchall()
        except Exception:
            rows = []
    else:
        try:
            from .config import get_db_path

            target = get_db_path()
            if target and Path(target).is_file():
                one_shot = sqlite3.connect(str(target), timeout=5.0)
                try:
                    rows = one_shot.execute("SELECT code, kind FROM catalog_assets").fetchall()
                finally:
                    one_shot.close()
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


def mask_recipe_data(data: Any, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Rebuild masked recipe from typed fields only; drop all free-text fields and non-dict shapes (H1, J1-J3)."""
    if not isinstance(data, dict):
        return {"prompt": "", "promptMasked": True}
    catalog_codes = get_valid_catalog_codes(conn=conn)
    return _rebuild_recipe_dict(data, catalog_codes=catalog_codes)


def get_generation_visible_prompt(row: sqlite3.Row | dict[str, Any] | None) -> tuple[str, bool]:
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


def get_work_client_prompt(row: sqlite3.Row | dict[str, Any] | None, is_admin_route: bool = False) -> tuple[str, bool]:
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
    row: sqlite3.Row | dict[str, Any] | None,
    is_admin_route: bool = False,
    conn: sqlite3.Connection | None = None,
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


def sanitize_prompt_for_client(prompt: str, conn: sqlite3.Connection | None = None) -> tuple[str, bool]:
    """Compatibility adapter: returns ('', True) if text contains secret, else (prompt, False)."""
    if not prompt or not isinstance(prompt, str):
        return "", False
    try:
        if check_text_has_secret(prompt, conn):
            return "", True
    except Exception:
        return "", True
    return prompt, False


def _resolve_generation_visible_prompt(row: sqlite3.Row | dict[str, Any], conn: sqlite3.Connection | None = None) -> tuple[str, bool]:
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
        logger.warning("run_blackbox_backfill aborted: failed to query catalog secrets (fail-closed, G1)")
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
                has_errors = True
                continue

        if gen_updates:
            try:
                with db.transaction() as tx:
                    tx.executemany(
                        "UPDATE studio_generations SET visible_prompt = ?, prompt_masked = ? WHERE id = ? AND prompt = ?",
                        gen_updates,
                    )
                counts["generations"] += len(gen_updates)
            except Exception:
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
                has_errors = True
                continue

        if work_updates:
            try:
                with db.transaction() as tx:
                    tx.executemany("UPDATE works SET prompt_has_secret = ? WHERE id = ? AND prompt = ?", work_updates)
                counts["works"] += len(work_updates)
            except Exception:
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
                has_errors = True
                continue

        if topic_updates:
            try:
                with db.transaction() as tx:
                    tx.executemany("UPDATE forum_topics SET recipe_has_secret = ? WHERE id = ? AND recipe_json = ?", topic_updates)
                counts["topics"] += len(topic_updates)
            except Exception:
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
            logger.warning("Failed to persist blackbox_secrets_hash to site_settings")
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
    row: sqlite3.Row,
    comments_by_work: dict[str, list[dict[str, Any]]],
    unlocked_set: set[str],
    current_user: dict[str, Any] | None,
    conn: sqlite3.Connection | None = None,
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
    }


def _serialize_topic(
    row: sqlite3.Row,
    replies_by_topic: dict[str, list[dict[str, Any]]],
    unlocked_set: set[str],
    current_user: dict[str, Any] | None,
    conn: sqlite3.Connection | None = None,
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


def compute_public_asset_counts_and_creators(conn: sqlite3.Connection) -> tuple[dict[str, int], int, int, list[dict[str, Any]]]:
    """Compute exact counts per style/layout and creator honor summaries WITHOUT exposing any work images or prompts."""
    asset_counts: dict[str, int] = {}
    creator_stats: dict[str, dict[str, Any]] = {}

    users_map = {
        r["username"]: {"display_name": r["display_name"], "honor_override": r["honor_override"]}
        for r in conn.execute("SELECT username, display_name, honor_override FROM users WHERE status = 'active'").fetchall()
    }

    def ensure_rec(uname: str, aname: str) -> dict[str, Any]:
        rec = creator_stats.get(uname)
        if not rec:
            uinfo = users_map.get(uname, {})
            clean_name = uinfo.get("display_name") or aname or uname
            rec = {
                "username": uname,
                "authorName": clean_name,
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
        f"SELECT author_username, author_name, styles_json, layout_code, cheers, likes, favorites, forks, is_new_release, published_at_ms FROM works WHERE status = 'published' AND images_json IS NOT NULL AND TRIM(images_json) NOT IN ('', '[]', 'null') AND json_valid(images_json) = 1 AND {work_filter}",
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
            LEFT JOIN studio_generations g ON (c.bucket = 'generations' AND g.id = c.target_id)
            WHERE c.user_id = ?
              AND (
                (c.bucket IN ('styles', 'layouts') AND {collection_filter})
                OR (c.bucket = 'works' AND {collection_work_filter})
                OR (c.bucket = 'topics' AND {collection_topic_filter})
                OR (
                    c.bucket = 'generations'
                    AND g.id IS NOT NULL
                    AND g.status = 'success'
                    AND COALESCE(g.deleted_at, '') = ''
                    AND g.engine != 'demo'
                    AND (g.user_id = ? OR g.visibility = 'public')
                    AND (g.items_json IS NOT NULL AND g.items_json != '' AND g.items_json != '[]')
                )
              )
            ORDER BY c.rowid DESC
            """,
            (uid, *collection_ids, *collection_work_ids, *collection_topic_ids, uid),
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
            LEFT JOIN studio_generations g ON (i.target_type = 'like_generation' AND g.id = i.target_id)
            WHERE i.user_id = ?
              AND (
                (i.target_type IN ('like_style', 'like_layout') AND {interaction_asset_filter})
                OR (i.target_type IN ('like_work', 'like_topic') AND ({interaction_work_filter} OR {interaction_topic_filter}))
                OR (
                    i.target_type = 'like_generation'
                    AND g.id IS NOT NULL
                    AND g.status = 'success'
                    AND COALESCE(g.deleted_at, '') = ''
                    AND g.engine != 'demo'
                    AND (g.user_id = ? OR g.visibility = 'public')
                    AND (g.items_json IS NOT NULL AND g.items_json != '' AND g.items_json != '[]')
                )
                OR i.target_type NOT IN ('like_style', 'like_layout', 'like_work', 'like_topic', 'like_generation')
              )
            """,
            (uid, *interaction_asset_ids, *interaction_work_ids, *interaction_topic_ids, uid),
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
    for r in cat_rows:
        ser = _serialize_catalog_asset(r, unlocked_set, current_user)
        if r["source_type"] == "exclusive":
            exclusive_resources.append(ser)
        elif r["source_type"] == "community":
            community_resources.append(ser)
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
                    "definition": None,
                    "unlockCost": 0,
                    "author": sr["owner_username"],
                    "authorName": sr["owner_username"],
                    "isMine": False,
                    "canUse": True,
                    "access": {
                        "canRead": False,
                        "canUse": True,
                        "hiddenBy": "pending",
                    },
                })

    # Forum topics & replies (publicly visible, paid lockedBody masked unless unlocked!)
    replies_by_topic: dict[str, list[dict[str, Any]]] = {}
    reply_filter, reply_ids = _seed_filter("id", "forum_replies")
    reply_topic_filter, reply_topic_ids = _seed_filter("topic_id", "topics")
    for rp in conn.execute(
        f"SELECT * FROM forum_replies WHERE status = 'published' AND {reply_filter} AND {reply_topic_filter} ORDER BY rowid ASC",
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
        f"SELECT * FROM forum_topics WHERE status = 'published' AND {topic_filter} AND {topic_vis_filter} ORDER BY pinned DESC, published_at_ms DESC",
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
        f"SELECT * FROM work_comments WHERE status = 'published' AND {comment_filter} AND {comment_work_filter} ORDER BY rowid ASC",
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
    work_filter, work_ids = _seed_filter("id", "works")
    work_rows = conn.execute(
        f"SELECT * FROM works WHERE status = 'published' AND images_json IS NOT NULL AND TRIM(images_json) NOT IN ('', '[]', 'null') AND json_valid(images_json) = 1 AND {work_filter} ORDER BY featured DESC, published_at_ms DESC",
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
        f"SELECT * FROM asset_comments WHERE status = 'published' AND {asset_comment_filter} AND {asset_comment_asset_filter} ORDER BY rowid ASC",
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
            "avatarUrl": "/assets/user-avatar.webp",
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

    payload = {
        "version": 4,
        "serverBacked": True,
        "demoMode": is_demo_mode(),
        "loggedIn": bool(current_user),
        "user": user_payload,
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
        "topics": topics_out,
        "forumBoards": FORUM_BOARDS,
        "forumModerators": forum_moderators,
        "exclusiveResources": exclusive_resources,
        "communityResources": community_resources,
        "officialOverrides": official_overrides,
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
    if current_user:
        payload['user']['reviewAccess']=review_access(db,current_user)
    return payload


def perform_daily_checkin(db: Database, user: dict[str, Any]) -> dict[str, Any]:
    uid = int(user["id"])
    today = local_today_str()
    now = utc_now_iso()
    with db.transaction() as tx:
        settings = get_site_settings(tx)
        bonus = int(settings.get("economy", {}).get("daily_checkin_credits", 5))
        w = tx.execute("SELECT checkin_date FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        if w and w["checkin_date"] == today:
            raise ServiceError("今日已完成打卡签到，明天再来吧！")
        tx.execute(
            "UPDATE wallets SET checkin_date = ?, free_quota_date = ?, free_quota_used = 0, updated_at = ? WHERE user_id = ?",
            (today, today, now, uid),
        )
        new_bal, _ = apply_wallet_delta(
            tx, uid, bonus, "checkin", f"每日社区创作打卡奖励 ({today})", event_key=f"checkin_{uid}_{today}"
        )
        q_state = get_wallet_quota_state(tx, uid, settings)
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
    amt = int(amount or 0)
    if amt not in (50, 100, 200, 500):
        raise ServiceError("无效的充值档位")
    uid = int(user["id"])
    with db.transaction() as tx:
        new_bal, _ = apply_wallet_delta(
            tx,
            uid,
            amt,
            "recharge",
            f"在线充值积分加油包 (+{amt} 积分)",
        )
    return {"ok": True, "added": amt, "credits": new_bal}


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
    row: sqlite3.Row | dict[str, Any] | None,
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


def attach_generation_social_counts(
    conn: sqlite3.Connection,
    items: list[dict[str, Any]],
    viewer: dict[str, Any] | None = None,
) -> None:
    if not items:
        return
    gen_ids = [str(it["id"]).strip() for it in items if it.get("id")]
    if not gen_ids:
        return
    ph = ",".join("?" for _ in gen_ids)

    likes_map: dict[str, int] = {}
    for r in conn.execute(
        f"SELECT target_id, COUNT(*) AS cnt FROM interactions WHERE target_type = 'like_generation' AND target_id IN ({ph}) GROUP BY target_id",
        gen_ids,
    ).fetchall():
        likes_map[str(r["target_id"])] = int(r["cnt"])

    favs_map: dict[str, int] = {}
    for r in conn.execute(
        f"SELECT target_id, COUNT(*) AS cnt FROM collections WHERE bucket = 'generations' AND target_id IN ({ph}) GROUP BY target_id",
        gen_ids,
    ).fetchall():
        favs_map[str(r["target_id"])] = int(r["cnt"])

    viewer_likes: set[str] = set()
    viewer_favs: set[str] = set()
    if viewer and viewer.get("id"):
        vuid = int(viewer["id"])
        for r in conn.execute(
            f"SELECT target_id FROM interactions WHERE user_id = ? AND target_type = 'like_generation' AND target_id IN ({ph})",
            (vuid, *gen_ids),
        ).fetchall():
            viewer_likes.add(str(r["target_id"]))
        for r in conn.execute(
            f"SELECT target_id FROM collections WHERE user_id = ? AND bucket = 'generations' AND target_id IN ({ph})",
            (vuid, *gen_ids),
        ).fetchall():
            viewer_favs.add(str(r["target_id"]))

    for it in items:
        gid = str(it.get("id") or "").strip()
        it["likes"] = likes_map.get(gid, 0)
        it["favorites"] = favs_map.get(gid, 0)
        it["liked"] = gid in viewer_likes if viewer else False
        it["favorited"] = gid in viewer_favs if viewer else False


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

    if bucket == "generations":
        g_row = db.get_conn().execute(
            "SELECT * FROM studio_generations WHERE id = ?", (tid,)
        ).fetchone()
        if not check_generation_social_accessible(g_row, viewer=user, allow_own=True):
            raise ServiceError("生图记录不存在或不可见", status=404, code="not_found")

    with db.transaction() as tx:
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

        rewarded = 0
        if existing and not should_collect:
            tx.execute("DELETE FROM collections WHERE user_id = ? AND bucket = ? AND target_id = ?", (uid, bucket, tid))
            collected = False
            if bucket == "works":
                tx.execute("UPDATE works SET favorites = MAX(0, favorites - 1) WHERE id = ?", (tid,))
            elif bucket == "topics":
                tx.execute("UPDATE forum_topics SET favorites = MAX(0, favorites - 1) WHERE id = ?", (tid,))
        elif not existing and should_collect:
            if bucket in ("styles", "layouts") and resource_entry and not resource_entry.get("canCollect"):
                raise ServiceError("该资源暂不支持收藏", status=403)
            tx.execute(
                "INSERT INTO collections (user_id, bucket, target_id, created_at) VALUES (?, ?, ?, ?)",
                (uid, bucket, tid, now),
            )
            collected = True
            if bucket == "works":
                tx.execute("UPDATE works SET favorites = favorites + 1 WHERE id = ?", (tid,))
            elif bucket == "topics":
                tx.execute("UPDATE forum_topics SET favorites = favorites + 1 WHERE id = ?", (tid,))

            if bucket != "generations":
                u_row = tx.execute("SELECT first_collect_rewarded FROM users WHERE id = ?", (uid,)).fetchone()
                if u_row and not int(u_row["first_collect_rewarded"]):
                    settings = get_site_settings(tx)
                    bonus = int(settings.get("economy", {}).get("first_collect_credits", 2))
                    tx.execute("UPDATE users SET first_collect_rewarded = 1 WHERE id = ?", (uid,))
                    if bonus > 0:
                        apply_wallet_delta(
                            tx,
                            uid,
                            bonus,
                            "first_collect",
                            f"首次使用云端收藏夹激励（{title_label or tid}）",
                            event_key=f"first_collect_{uid}",
                        )
                        rewarded = bonus
        else:
            collected = bool(existing)

        if bucket == "works":
            norm_type = "work"
            new_favorites = int(tx.execute("SELECT favorites FROM works WHERE id = ?", (tid,)).fetchone()["favorites"])
        elif bucket == "topics":
            norm_type = "topic"
            new_favorites = int(tx.execute("SELECT favorites FROM forum_topics WHERE id = ?", (tid,)).fetchone()["favorites"])
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

        bal = int(tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()["balance"])
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
        norm_type = "generation"
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
        if norm_type == "work":
            w_row = tx.execute("SELECT id, title, author_name, likes FROM works WHERE id = ?", (tid,)).fetchone()
            if not w_row:
                raise ServiceError("作品不存在", status=404)
            title_lbl = w_row["title"]
        elif norm_type == "topic":
            t_row = tx.execute("SELECT id, title, author_name, likes FROM forum_topics WHERE id = ?", (tid,)).fetchone()
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

        rewarded = 0
        if existing and not should_like:
            tx.execute(
                "DELETE FROM interactions WHERE user_id = ? AND target_type = ? AND target_id = ? AND stamp_label = ''",
                (uid, itype, tid),
            )
            liked = False
            if norm_type == "work":
                tx.execute("UPDATE works SET likes = MAX(0, likes - 1) WHERE id = ?", (tid,))
            elif norm_type == "topic":
                tx.execute("UPDATE forum_topics SET likes = MAX(0, likes - 1) WHERE id = ?", (tid,))
        elif not existing and should_like:
            tx.execute(
                "INSERT OR IGNORE INTO interactions (user_id, target_type, target_id, stamp_label, created_at) VALUES (?, ?, ?, '', ?)",
                (uid, itype, tid, now),
            )
            liked = True
            if norm_type == "work":
                tx.execute("UPDATE works SET likes = likes + 1 WHERE id = ?", (tid,))
            elif norm_type == "topic":
                tx.execute("UPDATE forum_topics SET likes = likes + 1 WHERE id = ?", (tid,))

            if norm_type != "generation":
                u_row = tx.execute("SELECT first_cheer_rewarded FROM users WHERE id = ?", (uid,)).fetchone()
                if u_row and not int(u_row["first_cheer_rewarded"]):
                    settings = get_site_settings(tx)
                    bonus = int(settings.get("economy", {}).get("first_cheer_credits", 2))
                    tx.execute("UPDATE users SET first_cheer_rewarded = 1 WHERE id = ?", (uid,))
                    if bonus > 0:
                        apply_wallet_delta(
                            tx,
                            uid,
                            bonus,
                            "first_cheer",
                            f"友善社区互动：首次点赞《{title_lbl[:20]}》",
                            event_key=f"first_cheer_{uid}",
                        )
                        rewarded = bonus
        else:
            liked = bool(existing)

        if norm_type == "work":
            new_likes = int(tx.execute("SELECT likes FROM works WHERE id = ?", (tid,)).fetchone()["likes"])
        elif norm_type == "topic":
            new_likes = int(tx.execute("SELECT likes FROM forum_topics WHERE id = ?", (tid,)).fetchone()["likes"])
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

        bal = int(tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()["balance"])

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
    tid = (target_id or "").strip()
    stamp = (stamp_label or "").strip()[:20]
    uid = int(user["id"])
    now = utc_now_iso()

    with db.transaction() as tx:
        is_official_asset = False
        if target_type == "work":
            target = tx.execute("SELECT id, title, author_name, cheers, stamp_counts_json FROM works WHERE id = ?", (tid,)).fetchone()
        else:
            clean_code = tid.strip().upper().lstrip("#")
            from . import resource_registry
            cat_res = resource_registry.resolve(tx, clean_code, viewer=user, purpose="stamp")
            if not cat_res:
                raise ServiceError("未找到目标内容", status=404)
            if not cat_res.get("canStamp", True):
                raise ServiceError("该资源暂不支持盖章", status=403)
            tid = cat_res["code"]
            target = tx.execute("SELECT code AS id, name AS title, author_name, cheers, stamp_counts_json FROM catalog_assets WHERE code = ? OR UPPER(code) = ?", (tid, clean_code)).fetchone()
            if not target:
                is_official_asset = True
                c_row = tx.execute("SELECT COUNT(*) AS cnt FROM interactions WHERE target_type = 'asset' AND (target_id = ? OR UPPER(target_id) = ?) AND stamp_label = ''", (clean_code, clean_code)).fetchone()
                target = {
                    "id": clean_code,
                    "title": cat_res.get("name") or clean_code,
                    "author_name": cat_res.get("author_name") or cat_res.get("author") or "官方资源",
                    "cheers": int(c_row["cnt"] if c_row else 0),
                    "stamp_counts_json": "{}",
                }

        if not target:
            raise ServiceError("未找到目标内容", status=404)

        existing = tx.execute(
            "SELECT 1 FROM interactions WHERE user_id = ? AND target_type = ? AND (target_id = ? OR UPPER(target_id) = ?) AND stamp_label = ?",
            (uid, target_type, tid, tid, stamp),
        ).fetchone()

        rewarded = 0
        if existing and not stamp:
            tx.execute(
                "DELETE FROM interactions WHERE user_id = ? AND target_type = ? AND (target_id = ? OR UPPER(target_id) = ?) AND stamp_label = ''",
                (uid, target_type, tid, tid),
            )
            new_cheers = max(0, int(target["cheers"]) - 1)
            if target_type == "work":
                tx.execute("UPDATE works SET cheers = ? WHERE id = ?", (new_cheers, tid))
            elif not is_official_asset:
                tx.execute("UPDATE catalog_assets SET cheers = ? WHERE code = ?", (new_cheers, tid))
            cheered = False
        elif existing and stamp:
            cheered = True
            new_cheers = int(target["cheers"])
        else:
            tx.execute(
                "INSERT OR IGNORE INTO interactions (user_id, target_type, target_id, stamp_label, created_at) VALUES (?, ?, ?, ?, ?)",
                (uid, target_type, tid, stamp, now),
            )
            tx.execute(
                "INSERT OR IGNORE INTO interactions (user_id, target_type, target_id, stamp_label, created_at) VALUES (?, ?, ?, '', ?)",
                (uid, target_type, tid, now),
            )
            new_cheers = int(target["cheers"]) + 1
            if not is_official_asset:
                stamps_dict = json.loads(target["stamp_counts_json"] or "{}")
                if stamp:
                    prev = int(stamps_dict.get(stamp, 0))
                    stamps_dict[stamp] = prev + 1
                if target_type == "work":
                    tx.execute(
                        "UPDATE works SET cheers = ?, stamp_counts_json = ? WHERE id = ?",
                        (new_cheers, json.dumps(stamps_dict, ensure_ascii=False), tid),
                    )
                else:
                    tx.execute(
                        "UPDATE catalog_assets SET cheers = ?, stamp_counts_json = ? WHERE code = ?",
                        (new_cheers, json.dumps(stamps_dict, ensure_ascii=False), tid),
                    )
            cheered = True

            u_row = tx.execute("SELECT first_cheer_rewarded FROM users WHERE id = ?", (uid,)).fetchone()
            if u_row and not int(u_row["first_cheer_rewarded"]):
                settings = get_site_settings(tx)
                bonus = int(settings.get("economy", {}).get("first_cheer_credits", 2))
                tx.execute("UPDATE users SET first_cheer_rewarded = 1 WHERE id = ?", (uid,))
                if bonus > 0:
                    apply_wallet_delta(
                        tx,
                        uid,
                        bonus,
                        "first_cheer",
                        f"友善社区互动：首次送上鼓励支持 @{target['author_name']}",
                        event_key=f"first_cheer_{uid}",
                    )
                    rewarded = bonus

        bal = int(tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()["balance"])
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
                    bal_row = tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()
                    cur_bal = int(bal_row["balance"]) if bal_row else 0
                    return {
                        "ok": True,
                        "credits": cur_bal,
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
                (payee_name, payee_name),
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

        already_liked = tx.execute(
            "SELECT 1 FROM interactions WHERE user_id = ? AND target_type = ? AND target_id = ? AND stamp_label = ''",
            (uid, itype, tid),
        ).fetchone()
        if not already_liked:
            tx.execute(
                "INSERT OR IGNORE INTO interactions (user_id, target_type, target_id, stamp_label, created_at) VALUES (?, ?, ?, '', ?)",
                (uid, itype, tid, now_ts),
            )
            if raw_type == "work":
                tx.execute("UPDATE works SET likes = likes + 1 WHERE id = ?", (tid,))
            elif raw_type == "topic":
                tx.execute("UPDATE forum_topics SET likes = likes + 1 WHERE id = ?", (tid,))

        # Also maintain generic interaction record for cheers
        tx.execute(
            "INSERT OR IGNORE INTO interactions (user_id, target_type, target_id, stamp_label, created_at) VALUES (?, ?, ?, '', ?)",
            (uid, raw_type, tid, now_ts),
        )

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

        settings = get_site_settings(tx)
        share_ratio = float(settings.get("economy", {}).get("author_share_ratio", 0.80))

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
            cost = int(t_row["price"] or 0)
            title = t_row["title"]
            author_uname = t_row["author_username"]
            author_name = t_row["author_name"]
            unlocked_content = t_row["locked_body"]
        elif a_row:
            resolved_type = "asset"
            tid = a_row["code"]
            cost = int(a_row["unlock_cost"] or 0)
            title = f"{a_row['code']} {a_row['name']}"
            author_uname = a_row["author_username"] if a_row["source_type"] == "community" else ""
            author_name = a_row["author_name"] if a_row["source_type"] == "community" else ""
            unlocked_content = a_row["definition"] if a_row["source_type"] != "exclusive" else ""
        else:
            raise ServiceError("未找到待解锁内容", status=404)

        existing = tx.execute(
            "SELECT status FROM unlocks WHERE user_id = ? AND target_type = ? AND target_id = ?",
            (uid, resolved_type, tid),
        ).fetchone()
        if existing and existing["status"] == "settled":
            bal = int(tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()["balance"])
            res = {"ok": True, "alreadyUnlocked": True, "credits": bal, "unlockedContent": unlocked_content, "targetType": resolved_type, "targetId": tid}
            if was_masked:
                res["promptMasked"] = True
            return res

        if cost <= 0 or author_uname == user["username"]:
            bal = int(tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()["balance"])
            res = {"ok": True, "alreadyUnlocked": True, "credits": bal, "unlockedContent": unlocked_content, "targetType": resolved_type, "targetId": tid}
            if was_masked:
                res["promptMasked"] = True
            return res

        author_share = max(1, round(cost * share_ratio)) if author_uname else 0
        new_bal, _ = apply_wallet_delta(
            tx,
            uid,
            -cost,
            "unlock_spend",
            f"解锁{f' @{author_name} 的' if author_name else ''}「{title}」" + ("（80% 积分实时分账原作者）" if author_uname else ""),
            event_key=f"unlock_{uid}_{resolved_type}_{tid}",
            ref_type=resolved_type,
            ref_id=tid,
        )

        if author_uname and author_share > 0:
            arow = tx.execute("SELECT id FROM users WHERE username = ?", (author_uname,)).fetchone()
            if arow and int(arow["id"]) != uid:
                apply_wallet_delta(
                    tx,
                    int(arow["id"]),
                    author_share,
                    "unlock_royalty",
                    f"作品/资产「{title}」被 @{user['display_name']} 解锁分成 (80%)",
                    event_key=f"royalty_{arow['id']}_{uid}_{resolved_type}_{tid}",
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

def publish_user_work(db, user, body):
    # Works publish immediately (D-02).  Double review stays for styles and
    # layouts, which feed the shared catalogue.
    from .curation import publish_work_direct
    return publish_work_direct(db, user, body)



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
    raw = str(title or "").strip()
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

    if price > 0:
        if "hw-paywall-divider" not in raw_body:
            raise ServiceError("付费帖子缺少付费分界线", status=400)
        divider_match = re.search(
            r"<div[^>]*class=[\"'][^\"']*hw-paywall-divider[^\"']*[\"'][^>]*>.*?</div>\s*</div>|<(?:div|hr)[^>]*class=[\"'][^\"']*hw-paywall-divider[^\"']*[\"'][^>]*>(?:.*?</div>)?|<[^>]*hw-paywall-divider[^>]*>",
            raw_body,
            flags=re.DOTALL,
        )
        if divider_match:
            after_part = raw_body[divider_match.end():]
        else:
            parts = raw_body.split("hw-paywall-divider", 1)
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

    images = body.get("images") or []
    recipe = body.get("recipe")
    if isinstance(shared_card, dict):
        if not recipe or not isinstance(recipe, dict):
            recipe = {"sharedCard": shared_card}
        else:
            recipe["sharedCard"] = shared_card

    uid = int(user["id"])
    now_iso = utc_now_iso()
    now_ms = int(time.time() * 1000)
    tid = f"topic_{now_ms}_{uuid.uuid4().hex[:4]}"

    incoming_summary = str(body.get("summary") or "").strip()
    if incoming_summary:
        summary = incoming_summary[:60000]
    elif price > 0 and len(raw_body) > 60:
        clean_text = re.sub(r"<[^>]+>", " ", raw_body).strip()
        summary = (clean_text[:120] if len(clean_text) > 120 else clean_text) + "……（以下为核心实战干货，需付费解锁查看）"
    else:
        summary = raw_body
    locked_body = (str(body.get("lockedBody") or raw_body)).strip()[:60000] if price > 0 else ""

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

        if not work_id:
            work_id = str(body.get("workId") or "").strip()[:64]
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
                status, published_at_ms, created_label, created_at, updated_at
            ) VALUES (?, ?, ?, 0, 0, ?, ?, ?, 0, 0, 0, ?, ?, ?, 0, '', ?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, '刚刚', ?, ?)
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
    from .resource_discussions import find_topic_source, comment
    if not direct:
        source=find_topic_source(db,topic_id)
        if source and source['origin']!='submission':
            return comment(db,user,source['kind'],source['target_id'],text)
    clean = (text or "").strip()[:3000]
    if not clean:
        raise ServiceError("请输入回复内容")
    uid = int(user["id"])
    today = local_today_str()
    now_iso = utc_now_iso()
    rid = f"rep_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}"

    with db.transaction() as tx:
        tp = tx.execute("SELECT id, title FROM forum_topics WHERE id = ? AND status = 'published'", (topic_id,)).fetchone()
        if not tp:
            raise ServiceError("帖子不存在或已下架", status=404)

        settings = get_site_settings(tx)
        econ = settings.get("economy", {})
        reply_reward = int(econ.get("reply_publish_credits", 2))
        daily_cap = int(econ.get("reply_daily_cap", 5))

        tx.execute(
            """
            INSERT INTO forum_replies (
                id, topic_id, author_username, author_name, text, mounted_style, mounted_layout,
                likes, accepted, status, time_label, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 'published', '刚刚', ?)
            """,
            (
                rid,
                topic_id,
                user["username"],
                user["display_name"],
                clean,
                (mounted_style or "").strip().upper().lstrip("#"),
                (mounted_layout or "").strip().upper().lstrip("#"),
                now_iso,
            ),
        )

        today_rewarded_cnt = int(
            tx.execute(
                "SELECT COUNT(*) FROM ledgers WHERE user_id = ? AND kind = 'publish_reply' AND created_at LIKE ?",
                (uid, f"{today}%"),
            ).fetchone()[0]
        )
        rewarded = 0
        if reply_reward > 0 and today_rewarded_cnt < daily_cap:
            new_bal, _ = apply_wallet_delta(
                tx,
                uid,
                reply_reward,
                "publish_reply",
                f"参与帖子《{tp['title'][:18]}…》深度回复激励",
                event_key=f"pub_reply_{rid}",
                ref_type="reply",
                ref_id=rid,
            )
            rewarded = reply_reward
        else:
            new_bal = int(tx.execute("SELECT balance FROM wallets WHERE user_id = ?", (uid,)).fetchone()["balance"])

    return {"ok": True, "replyId": rid, "rewarded": rewarded, "credits": new_bal}


def accept_forum_bounty_reply(db: Database, user: dict[str, Any], topic_id: str, reply_id: str) -> dict[str, Any]:
    now_iso = utc_now_iso()
    with db.transaction() as tx:
        tp = tx.execute("SELECT * FROM forum_topics WHERE id = ?", (topic_id,)).fetchone()
        if not tp:
            raise ServiceError("帖子不存在", status=404)
        is_staff = user.get("role") in ("admin", "reviewer")
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
    row: sqlite3.Row | dict[str, Any],
    conn: sqlite3.Connection | None = None,
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
    with db.transaction() as tx:
        deduplicate_generation_history(tx)
    conn = db.get_conn()
    if history_id:
        row = conn.execute(
            "SELECT * FROM studio_generations WHERE id = ? AND COALESCE(deleted_at, '') = ''",
            (history_id,),
        ).fetchone()
        if not row:
            return None
        res = serialize_public_generation_history(row, conn)
        attach_generation_social_counts(conn, [res], viewer=None)
        return res
    history_filter, history_ids = _seed_filter("id", "generations")
    rows = conn.execute(
        f"SELECT * FROM studio_generations WHERE COALESCE(deleted_at, '') = '' AND {history_filter} ORDER BY created_at DESC LIMIT ?",
        (*history_ids, max(1, min(100, limit))),
    ).fetchall()
    items = [serialize_public_generation_history(r, conn) for r in rows]
    attach_generation_social_counts(conn, items, viewer=None)
    return items


def get_user_public_generations(
    db: Database,
    username: str,
    *,
    cursor: str = "",
    limit: int = 24,
    viewer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Retrieve public generation history for a creator with stable cursor pagination."""
    conn = db.get_conn()
    u_clean = str(username or "").strip()
    u_row = conn.execute("SELECT id, username FROM users WHERE username = ?", (u_clean,)).fetchone()
    if not u_row:
        raise ServiceError("创作者不存在", status=404, code="user_not_found")
    uid = int(u_row["id"])

    with db.transaction() as tx:
        deduplicate_generation_history(tx, user_id=uid)

    conn = db.get_conn()
    safe_limit = max(1, min(60, int(limit)))

    cursor_created_at = None
    cursor_id = None
    if cursor:
        cur_str = str(cursor).strip()
        try:
            import base64
            decoded = base64.urlsafe_b64decode(cur_str.encode("ascii")).decode("utf-8")
            parts = decoded.split("|", 1)
            if len(parts) == 2:
                cursor_created_at, cursor_id = parts
        except Exception:
            parts = cur_str.split("|", 1)
            if len(parts) == 2:
                cursor_created_at, cursor_id = parts

    params: list[Any] = [uid]
    cursor_clause = ""
    if cursor_created_at and cursor_id:
        cursor_clause = " AND (created_at < ? OR (created_at = ? AND id < ?))"
        params.extend([cursor_created_at, cursor_created_at, cursor_id])

    params.append(safe_limit + 1)

    sql = f"""
        SELECT * FROM studio_generations
        WHERE user_id = ?
          AND status = 'success'
          AND COALESCE(deleted_at, '') = ''
          AND engine != 'demo'
          AND visibility = 'public'
          AND (items_json IS NOT NULL AND items_json != '' AND items_json != '[]')
          {cursor_clause}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
    """
    rows = conn.execute(sql, tuple(params)).fetchall()

    has_more = len(rows) > safe_limit
    result_rows = rows[:safe_limit]

    items: list[dict[str, Any]] = []
    for r in result_rows:
        serialized = serialize_public_generation_history(r, conn)
        if serialized.get("images"):
            items.append(serialized)

    attach_generation_social_counts(conn, items, viewer=viewer)

    next_cursor = None
    if has_more and result_rows:
        last = result_rows[-1]
        import base64
        next_cursor = base64.urlsafe_b64encode(f"{last['created_at']}|{last['id']}".encode("utf-8")).decode("ascii")

    total_row = conn.execute(
        """
        SELECT COUNT(1) FROM studio_generations
        WHERE user_id = ?
          AND status = 'success'
          AND COALESCE(deleted_at, '') = ''
          AND engine != 'demo'
          AND visibility = 'public'
          AND (items_json IS NOT NULL AND items_json != '' AND items_json != '[]')
        """,
        (uid,),
    ).fetchone()
    total_count = int(total_row[0]) if total_row else len(items)

    return {
        "ok": True,
        "generations": items,
        "nextCursor": next_cursor,
        "hasMore": bool(has_more),
        "total": total_count,
    }


def get_user_public_generation_by_id(
    db: Database,
    username: str,
    generation_id: str,
    *,
    viewer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Retrieve a single public generation item for a creator by id."""
    conn = db.get_conn()
    u_clean = str(username or "").strip()
    u_row = conn.execute("SELECT id, username FROM users WHERE username = ?", (u_clean,)).fetchone()
    if not u_row:
        raise ServiceError("创作者不存在", status=404, code="user_not_found")
    uid = int(u_row["id"])

    with db.transaction() as tx:
        deduplicate_generation_history(tx, user_id=uid)

    conn = db.get_conn()
    gen_id = str(generation_id or "").strip()
    row = conn.execute(
        """
        SELECT * FROM studio_generations
        WHERE id = ?
          AND user_id = ?
        """,
        (gen_id, uid),
    ).fetchone()

    is_owner = bool(viewer and int(viewer.get("id") or 0) == uid)
    if not check_generation_social_accessible(row, viewer=viewer, allow_own=is_owner):
        raise ServiceError("生图记录不存在或不可见", status=404, code="not_found")

    serialized = serialize_public_generation_history(row, conn)
    if not serialized.get("images"):
        raise ServiceError("生图记录不存在或无结果图片", status=404, code="not_found")

    attach_generation_social_counts(conn, [serialized], viewer=viewer)

    return {
        "ok": True,
        "generation": serialized,
    }


def get_user_collected_generations(
    db: Database,
    user: dict[str, Any],
    limit: int = 60,
) -> dict[str, Any]:
    uid = int(user["id"])
    conn = db.get_conn()
    safe_limit = max(1, min(100, int(limit)))

    rows = conn.execute(
        """
        SELECT g.*
        FROM collections c
        JOIN studio_generations g ON g.id = c.target_id
        WHERE c.user_id = ?
          AND c.bucket = 'generations'
          AND g.status = 'success'
          AND COALESCE(g.deleted_at, '') = ''
          AND g.engine != 'demo'
          AND (g.user_id = ? OR g.visibility = 'public')
          AND (g.items_json IS NOT NULL AND g.items_json != '' AND g.items_json != '[]')
        ORDER BY c.created_at DESC
        LIMIT ?
        """,
        (uid, uid, safe_limit),
    ).fetchall()

    items = []
    for r in rows:
        ser = serialize_public_generation_history(r, conn)
        if ser.get("images"):
            items.append(ser)

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


def get_studio_workspace(db: Database, user: dict[str, Any] | None) -> dict[str, Any]:
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
    ).fetchall():
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
    for r in conn.execute("SELECT * FROM studio_articles WHERE user_id = ? ORDER BY updated_at_ms DESC", (uid,)).fetchall():
        arts.append(
            {
                "id": r["id"],
                "articleTitle": r["article_title"],
                "markdown": r["markdown"],
                "cards": json.loads(r["cards_json"] or "[]"),
                "style1": r["style1"],
                "layout": r["layout_code"],
                "status": r["status"],
                "runCount": int(r["run_count"]),
                "createdAtMs": int(r["created_at_ms"]),
                "updatedAtMs": int(r["updated_at_ms"]),
            }
        )

    hist = []
    pending_tasks = []
    history_filter, history_ids = _seed_filter("id", "generations")
    for r in conn.execute(
        f"SELECT * FROM studio_generations WHERE user_id = ? AND COALESCE(deleted_at, '') = '' AND {history_filter} ORDER BY created_at DESC LIMIT 40",
        (uid, *history_ids),
    ).fetchall():
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
                ca = conn.execute("SELECT unlock_cost, source_type FROM catalog_assets WHERE code = ? OR UPPER(code) = ?", (c_clean, c_clean)).fetchone()
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
        if r["system_append_json"]:
            try:
                s_data = json.loads(r["system_append_json"])
                snap = s_data.get("recipeSnapshot")
            except Exception:
                pass

        user_topic = ""
        if "subject" in r_keys and r["subject"]:
            user_topic = str(r["subject"]).strip()
        elif "recipe_id" in r_keys and r["recipe_id"]:
            rcp = conn.execute("SELECT subject FROM studio_recipes WHERE id = ?", (r["recipe_id"],)).fetchone()
            if rcp and rcp["subject"]:
                user_topic = str(rcp["subject"]).strip()
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
        }
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

    uploads = [
        {
            "id": r["id"],
            "cat": r["cat"],
            "name_zh": r["name_zh"],
            "desc_zh": r["desc_zh"],
            "image": r["image_url"],
            "custom": True,
        }
        for r in conn.execute("SELECT * FROM user_uploads WHERE user_id = ? AND deleted_at IS NULL ORDER BY created_at DESC", (uid,)).fetchall()
    ]

    return {
        "loggedIn": True,
        "workflows": wfs,
        "articles": arts,
        "history": hist,
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
    uid = int(user["id"])
    now_ms = int(time.time() * 1000)
    with db.transaction() as tx:
        for art in (articles or [])[:50]:
            if not isinstance(art, dict) or not art.get("id"):
                continue
            aid = str(art["id"])
            # Skip static read-only seed articles unless modified
            tx.execute(
                """
                INSERT INTO studio_articles (id, user_id, article_title, markdown, cards_json, style1, layout_code, status, run_count, created_at_ms, updated_at_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    article_title = excluded.article_title,
                    markdown = excluded.markdown,
                    cards_json = excluded.cards_json,
                    style1 = excluded.style1,
                    layout_code = excluded.layout_code,
                    status = excluded.status,
                    run_count = excluded.run_count,
                    updated_at_ms = excluded.updated_at_ms
                WHERE studio_articles.user_id = excluded.user_id
                """,
                (
                    aid,
                    uid,
                    str(art.get("articleTitle") or "未命名文章")[:140],
                    str(art.get("markdown") or ""),
                    json.dumps(art.get("cards") or [], ensure_ascii=False),
                    str(art.get("style1") or ""),
                    str(art.get("layout") or ""),
                    str(art.get("status") or "ready"),
                    int(art.get("runCount") or 0),
                    int(art.get("createdAtMs") or now_ms),
                    int(art.get("updatedAtMs") or now_ms),
                ),
            )
    return {"ok": True}


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
                    fork_generation_id = CASE WHEN ? != '' THEN ? ELSE fork_generation_id END,
                    fork_item_id = CASE WHEN ? != '' THEN ? ELSE fork_item_id END
                WHERE id = ? AND user_id = ?
                """,
                (*values, fork_gen_id, fork_gen_id, fork_item_id, fork_item_id, target_id, uid),
            )
            return {"ok": True, "id": target_id}
        else:
            tx.execute(
                """
                INSERT INTO studio_generations (
                    id, user_id, username, tab_title, mode, mode_label, kind, recipe_summary,
                    prompt, visible_prompt, prompt_masked, markdown, items_json, engine, cost_type, credits_spent, status, created_at, request_id,
                    fork_generation_id, fork_item_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sample', 'free', 0, 'success', ?, ?, ?, ?)
                """,
                (hid, uid, user["username"], *values, now_iso, req_id, fork_gen_id, fork_item_id),
            )
            return {"ok": True, "id": hid}


def delete_user_studio_history(db: Database, user: dict[str, Any], history_id: str) -> dict[str, Any]:
    """Hide one cloud history row owned by the current user.

    This is a soft delete so a generation's task, quota reservation, and
    accounting trail cannot be erased by a history UI action.
    """
    uid = int(user["id"])
    hid = str(history_id or "").strip()
    if not hid:
        raise ServiceError("历史记录编号不能为空", status=400, code="history_id_required")
    with db.transaction() as tx:
        row = tx.execute("SELECT user_id, status, deleted_at FROM studio_generations WHERE id = ?", (hid,)).fetchone()
        if not row:
            return {"ok": True, "id": hid, "deleted": False}
        if int(row["user_id"] or 0) != uid:
            raise ServiceError("无权删除其他账号的历史记录", status=403, code="history_forbidden")
        if row["status"] in ("queued", "running"):
            raise ServiceError("生成任务仍在进行中，完成或失败后才能删除历史", status=409, code="history_active")
        if row["deleted_at"]:
            return {"ok": True, "id": hid, "deleted": False}
        tx.execute("UPDATE studio_generations SET deleted_at = ? WHERE id = ? AND user_id = ?", (utc_now_iso(), hid, uid))
    return {"ok": True, "id": hid, "deleted": True}


def delete_all_user_studio_history(db: Database, user: dict[str, Any]) -> dict[str, Any]:
    """Soft-delete all completed/refunded history rows owned by the user.

    In-flight rows stay visible so task recovery and accounting can finish;
    callers must use this explicit function rather than treating an empty id as
    a wildcard in ``delete_user_studio_history``.
    """
    uid = int(user["id"])
    now_iso = utc_now_iso()
    with db.transaction() as tx:
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
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    settings: dict[str, Any],
    *,
    idempotent: bool = False,
) -> dict[str, Any]:
    """Return the stable public shape used by first submit and retry paths."""
    uid = int(row["user_id"])
    today = local_today_str()
    wallet = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (uid,)).fetchone()
    max_free = max(0, int(settings.get("economy", {}).get("daily_free_quota", 3)))
    used = int(wallet["free_quota_used"]) if (wallet and wallet["free_quota_date"] == today) else 0
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
        "freeQuotaRemaining": max(0, max_free - used),
        "reservationDate": row["reservation_date"] or "",
        "model": str(settings.get("gateway", {}).get("model", "gpt-image-2")),
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
        return ""
    return str(composed.get("prompt") or "").strip()


def prepare_cloud_generation(db: Database, user: dict[str, Any] | None, body: dict[str, Any]) -> dict[str, Any]:
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
    is_staff = user.get("role") in ("admin", "reviewer")

    recipe_id = str(body.get("recipeId") or "").strip()
    r_colors: list[str] = []
    r_tones: list[str] = []
    r_moods: list[str] = []
    r_whitespace = ""
    r_ratio = "3:4"
    r_mode = "graphic-text"
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
    if not style1:
        m_s = re.search(r"(?:【画风】|画风|Style|角色风格)[：:\s]*#?([A-Za-z0-9_-]+)", raw_prompt)
        if m_s:
            style1 = m_s.group(1).strip().upper().lstrip("#")
    if not style2:
        m_s2 = re.search(r"(?:【场景风格】|场景风格|Scene Style)[：:\s]*#?([A-Za-z0-9_-]+)", raw_prompt)
        if m_s2:
            style2 = m_s2.group(1).strip().upper().lstrip("#")
    if not layout:
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
        settings = get_site_settings(tx)
        econ = settings.get("economy", {})
        gateway = settings.get("gateway", {})
        max_free = max(0, int(econ.get("daily_free_quota", 3)))
        per_img_cost = max(0, int(econ.get("studio_credit_per_image", 2)))

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

            inject = (res.get("access") or {}).get("inject")
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

        # Length check before charging (X6)
        if recipe_id:
            recipe_full_prompt = build_recipe_gateway_prompt(raw_prompt, injected_notes)
            if len(recipe_full_prompt) > 4000:
                if not raw_prompt.strip():
                    raise ServiceError("所选资源系统说明超过 4000 字上限，请精简所选资源", status=400, code="prompt_too_long")
                raise ServiceError("提示词加上系统说明后超过 4000 字上限，请精简提示词", status=400, code="prompt_too_long")

        # 2. Enforce daily free quota -> automatic credit fallback.
        w = tx.execute("SELECT * FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        used = int(w["free_quota_used"]) if (w and w["free_quota_date"] == today) else 0
        if used < max_free:
            tx.execute(
                "UPDATE wallets SET free_quota_date = ?, free_quota_used = ?, updated_at = ? WHERE user_id = ?",
                (today, used + 1, now_iso, uid),
            )
            cost_type = "free_quota"
            credits_spent = 0
            cur_balance = int(w["balance"]) if w else 0
            free_remaining = max(0, max_free - (used + 1))
        else:
            cost_type = "credits"
            credits_spent = per_img_cost
            cur_balance, _ = apply_wallet_delta(
                tx,
                uid,
                -per_img_cost,
                "studio_gen",
                f"在线创作台云端直出生图消耗 ({style1 or layout or '自由创作'})",
                event_key=f"gen_spend_{gen_id}",
                ref_type="generation",
                ref_id=gen_id,
            )
            free_remaining = 0
            is_paid_resource = True

        # Check if client-supplied prompt contains blackbox secrets or injected definitions (G9, H6, §1a-2)
        client_scan_failed = False
        client_prompt_has_secret = False
        try:
            if raw_prompt and check_text_has_secret(raw_prompt, tx, extra_secrets=injected_definitions):
                client_prompt_has_secret = True
        except Exception:
            client_scan_failed = True

        # Initial prompt without skill (written in Transaction A)
        if recipe_id:
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

        if recipe_id:
            initial_prompt = build_recipe_gateway_prompt(raw_prompt, injected_notes)
        else:
            cleaned = raw_prompt
            if injected_notes:
                cleaned += "\n\n" + "\n".join(injected_notes)
            initial_prompt = cleaned if from_skill else (
                f"立即生成图片：\n{cleaned}\n\n请直接调用画图工具立即生成图片，不要输出任何询问文字、选项或确认反问。"
            )

        needs_compose = (not from_skill) and bool(style1 or style2 or layout)
        prompt_ready = 0 if needs_compose else 1

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
            ) VALUES (?, ?, ?, '云端生图', ?, '云端直出', 'single', ?, ?, ?, ?, ?, '', '[]', 'live', ?, ?, '', 'running', '', ?, ?, ?, ?, ?, ?, ?, 'public', ?, ?)
            """,
            (
                gen_id,
                uid,
                uname,
                str(body.get("ratio") or "3:4"),
                f"{style1} {style2} {layout}".strip(),
                initial_prompt if recipe_id else initial_prompt[:4000],
                initial_visible_prompt if (initial_visible_prompt is None or recipe_id) else initial_visible_prompt[:4000],
                prompt_masked_init,
                json.dumps({"systemAppend": system_append_list, "promptTrimmed": False, "recipeSnapshot": snap}, ensure_ascii=False),
                cost_type,
                credits_spent,
                request_id,
                today,
                now_iso,
                fork_target,
                prompt_ready,
                recipe_id,
                user_subject,
                fork_gen_target,
                fork_item_target,
            ),
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
        inserted = tx.execute("SELECT * FROM studio_generations WHERE id = ?", (gen_id,)).fetchone()

    prompt_trimmed = False
    # Outside transaction: model call for freshly inserted rows
    if needs_compose:
        composed = None
        try:
            if recipe_id:
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

        if recipe_id:
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
            elif client_prompt_has_secret:
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
        "freeQuotaRemaining": free_remaining,
    })
    if recipe_id:
        result["recipeId"] = recipe_id
        result["systemAppend"] = system_append_list
        if prompt_trimmed:
            result["promptTrimmed"] = True
    return result


def refund_failed_cloud_generation(db: Database, gen_id: str, error_msg: str) -> None:
    now_iso = utc_now_iso()
    today = local_today_str()
    with db.transaction() as tx:
        row = tx.execute("SELECT * FROM studio_generations WHERE id = ?", (gen_id,)).fetchone()
        if not row or row["status"] in ("refunded", "success"):
            return
        uid = int(row["user_id"])
        tx.execute(
            "UPDATE studio_generations SET status = 'refunded', error_msg = ? WHERE id = ?",
            ((error_msg or "")[:300], gen_id),
        )
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
                    "UPDATE wallets SET free_quota_used = MAX(0, free_quota_used - ?), updated_at = ? WHERE user_id = ? AND free_quota_date = ?",
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


def complete_cloud_generation(db: Database, gen_id: str, task_id: str, image_urls: list[str] | None = None) -> None:
    with db.transaction() as tx:
        generation = tx.execute(
            "SELECT user_id, fork_work_id, engine, status FROM studio_generations WHERE id = ?", (gen_id,)
        ).fetchone()
        if image_urls is not None:
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
                        INSERT OR IGNORE INTO studio_generation_media
                            (id, generation_id, user_id, media_url, media_kind, storage_path, visibility, created_at)
                        VALUES (?, ?, ?, ?, 'generated', ?, 'private', ?)
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
        else:
            tx.execute("UPDATE studio_generations SET task_id = ? WHERE id = ? AND status NOT IN ('refunded', 'success')", (task_id, gen_id))


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
    for r in conn.execute(
        f"SELECT * FROM catalog_assets WHERE status = 'published' AND {library_asset_filter}",
        library_asset_ids,
    ).fetchall():
        code = r["code"]
        if r["source_type"] == "exclusive":
            # Online-exclusive blackbox styles cannot be exported offline to local skill library
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
            "content_url": f"/studio/api/assets/{code}/content" if is_unlocked else None,
        }
        if is_mine:
            owned.append(entry)
        else:
            collected.append(entry)

    # Also expose favorited official catalog items
    official = []
    cat_file = CONTENT_DIR / "catalog.json"
    if cat_file.is_file():
        cat_data = json.loads(cat_file.read_text(encoding="utf-8"))
        for item in cat_data.get("resources", []):
            code = item.get("id")
            if code in fav_codes and item.get("kind") in ("style", "layout"):
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
        "prompt_zh": res["definition"] or res.get("description") or clean_code,
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', '原 Discourse 社区老用户迁移账号', ?, ?, ?)
                """,
                (uname, dname, email, pw_hash, pw_algo, disc_salt, disc_id, role, uname, api_key or None, created_at),
            )
            uid = int(cur.lastrowid)
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
