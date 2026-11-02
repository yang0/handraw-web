"""Direct Messaging (DM) Phase 1A backend module for Handraw Web 2.0.

Provides:
- Schema migration (070_direct_messages)
- Conversation & message lifecycle with read cursors
- Anti-replay via clientMessageId
- Rate limiting (10/min, 100/day, 10 new contacts/day)
- Block & abuse report integration
- Standalone unread counts endpoint (/api/messages/unread)
- Strict participant-only access (no admin bypass)
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlparse

if TYPE_CHECKING:
    from .db import Database


def _service_error(message: str, status: int = 400, code: str = "bad_request") -> Exception:
    from .services import ServiceError
    return ServiceError(message, status=status, code=code)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Migration block 070+
DM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dm_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_low_id INTEGER NOT NULL,
    user_high_id INTEGER NOT NULL,
    last_message_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_low_id, user_high_id),
    FOREIGN KEY (user_low_id) REFERENCES users(id),
    FOREIGN KEY (user_high_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_dm_conv_low_high ON dm_conversations(user_low_id, user_high_id);
CREATE INDEX IF NOT EXISTS idx_dm_conv_updated ON dm_conversations(updated_at DESC);

CREATE TABLE IF NOT EXISTS dm_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    sender_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    client_message_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(sender_id, client_message_id),
    FOREIGN KEY (conversation_id) REFERENCES dm_conversations(id),
    FOREIGN KEY (sender_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_dm_messages_conv_id ON dm_messages(conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_dm_messages_sender_time ON dm_messages(sender_id, created_at DESC);

CREATE TABLE IF NOT EXISTS dm_members (
    conversation_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    last_read_message_id INTEGER NOT NULL DEFAULT 0,
    read_at TEXT,
    PRIMARY KEY (conversation_id, user_id),
    FOREIGN KEY (conversation_id) REFERENCES dm_conversations(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_dm_members_user ON dm_members(user_id);

CREATE TABLE IF NOT EXISTS dm_blocks (
    user_id INTEGER NOT NULL,
    blocked_user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, blocked_user_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (blocked_user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_dm_blocks_user ON dm_blocks(user_id);
CREATE INDEX IF NOT EXISTS idx_dm_blocks_blocked ON dm_blocks(blocked_user_id);

CREATE TABLE IF NOT EXISTS dm_contact_history (
    sender_id INTEGER NOT NULL,
    recipient_id INTEGER NOT NULL,
    first_contact_date TEXT NOT NULL,
    first_contact_at TEXT NOT NULL,
    PRIMARY KEY (sender_id, recipient_id),
    FOREIGN KEY (sender_id) REFERENCES users(id),
    FOREIGN KEY (recipient_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_dm_contact_hist_date ON dm_contact_history(sender_id, first_contact_date);
"""

DM_MIGRATIONS: list[tuple[int, str, str]] = [
    (70, "070_direct_messages", DM_SCHEMA_SQL),
]


def _require_active_user(user: dict[str, Any] | None) -> dict[str, Any]:
    if not user:
        raise _service_error("请先登录账号后再执行私信操作", status=401, code="login_required")
    if user.get("status") != "active":
        raise _service_error("当前账号状态异常或已被停用，无法使用私信", status=403, code="account_suspended")
    return user


def _validate_dm_body(body: Any) -> str:
    text = str(body or "").strip()
    non_ws_count = len(re.sub(r"\s+", "", text))
    if non_ws_count < 1 or non_ws_count > 2000:
        raise _service_error("私信正文需为 1–2000 个非空白字符", status=400, code="invalid_body_length")
    # Disallow raw HTML elements
    if "<" in text and re.search(r"<\s*/?[a-zA-Z][^>]*>", text):
        raise _service_error("首版私信暂不支持 HTML 内容", status=400, code="html_not_allowed")
    # Disallow image/media markdown syntax
    if re.search(r"!\[.*?\]\(.*?\)", text):
        raise _service_error("首版私信暂不支持图片或附件", status=400, code="media_not_allowed")
    return text


def is_user_blocked(conn: Any, user_a_id: int, user_b_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM dm_blocks WHERE (user_id = ? AND blocked_user_id = ?) OR (user_id = ? AND blocked_user_id = ?)",
        (user_a_id, user_b_id, user_b_id, user_a_id),
    ).fetchone()
    return row is not None


def _check_dm_rate_limits(conn: Any, sender_id: int, recipient_id: int, now_dt: datetime) -> None:
    now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    today_str = now_dt.strftime("%Y-%m-%d")
    today_start = f"{today_str}T00:00:00Z"
    one_min_ago = (now_dt - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. 10 messages / minute
    cnt_min = conn.execute(
        "SELECT COUNT(*) FROM dm_messages WHERE sender_id = ? AND created_at >= ?",
        (sender_id, one_min_ago),
    ).fetchone()[0]
    if cnt_min >= 10:
        raise _service_error("私信发送过于频繁，每分钟最多发送 10 条，请稍后再试", status=429, code="rate_limited_minute")

    # 2. 100 messages / day
    cnt_day = conn.execute(
        "SELECT COUNT(*) FROM dm_messages WHERE sender_id = ? AND created_at >= ?",
        (sender_id, today_str),
    ).fetchone()[0]
    if cnt_day >= 100:
        raise _service_error("今日私信发送条数已达上限（100 条）", status=429, code="rate_limited_daily")

    # 3. 10 new contacts / day
    contact_row = conn.execute(
        "SELECT first_contact_date FROM dm_contact_history WHERE sender_id = ? AND recipient_id = ?",
        (sender_id, recipient_id),
    ).fetchone()
    if not contact_row:
        cnt_contacts = conn.execute(
            "SELECT COUNT(*) FROM dm_contact_history WHERE sender_id = ? AND first_contact_date = ?",
            (sender_id, today_str),
        ).fetchone()[0]
        if cnt_contacts >= 10:
            raise _service_error("今日新联系人数已达上限（10 人）", status=429, code="rate_limited_contacts")


def send_direct_message(db: Database, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    cur_user = _require_active_user(user)
    sender_id = int(cur_user["id"])

    # Resolve recipient
    recip_raw = body.get("recipientId") or body.get("userId") or body.get("toUserId")
    recip_uname = body.get("recipientUsername") or body.get("toUsername") or body.get("username")

    conn = db.get_conn()
    recip_row = None
    if recip_raw is not None and str(recip_raw).strip():
        recip_str = str(recip_raw).strip()
        if recip_str.isdigit():
            recip_row = conn.execute("SELECT id, username, display_name, status FROM users WHERE id = ?", (int(recip_str),)).fetchone()
        else:
            recip_row = conn.execute("SELECT id, username, display_name, status FROM users WHERE lower(username) = lower(?)", (recip_str,)).fetchone()
    elif recip_uname:
        recip_row = conn.execute("SELECT id, username, display_name, status FROM users WHERE lower(username) = lower(?)", (str(recip_uname).strip(),)).fetchone()

    if not recip_row:
        raise _service_error("收信人不存在", status=404, code="recipient_not_found")
    if recip_row["status"] != "active":
        raise _service_error("收信人账号已被停用，无法发送私信", status=403, code="recipient_suspended")

    recipient_id = int(recip_row["id"])
    if recipient_id == sender_id:
        raise _service_error("不能给自己发送私信", status=400, code="cannot_message_self")

    # Anti-replay: client_message_id uniqueness check
    client_msg_id = str(body.get("clientMessageId") or "").strip()
    if not client_msg_id:
        client_msg_id = f"cm_{uuid.uuid4().hex}"

    existing_msg = conn.execute(
        "SELECT * FROM dm_messages WHERE sender_id = ? AND client_message_id = ?",
        (sender_id, client_msg_id),
    ).fetchone()
    if existing_msg:
        # Idempotent return without duplicate write
        conv_id = existing_msg["conversation_id"]
        peer_member = conn.execute(
            "SELECT last_read_message_id FROM dm_members WHERE conversation_id = ? AND user_id = ?",
            (conv_id, recipient_id),
        ).fetchone()
        peer_read = int(peer_member["last_read_message_id"] or 0) if peer_member else 0
        return {
            "ok": True,
            "conversationId": conv_id,
            "message": {
                "id": existing_msg["id"],
                "conversationId": conv_id,
                "senderId": sender_id,
                "body": existing_msg["body"],
                "clientMessageId": existing_msg["client_message_id"],
                "createdAt": existing_msg["created_at"],
                "isSelf": True,
                "isRead": bool(existing_msg["id"] <= peer_read),
            },
            "replayed": True,
        }

    # Check block relationship
    if is_user_blocked(conn, sender_id, recipient_id):
        raise _service_error("无法发送私信：已拉黑对方或已被对方拉黑", status=403, code="dm_blocked")

    # Validate message text
    clean_body = _validate_dm_body(body.get("body"))

    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    today_str = now_dt.strftime("%Y-%m-%d")

    # Check persistent rate limits
    _check_dm_rate_limits(conn, sender_id, recipient_id, now_dt)

    u_low, u_high = (sender_id, recipient_id) if sender_id < recipient_id else (recipient_id, sender_id)

    with db.transaction() as tx:
        conv = tx.execute(
            "SELECT id FROM dm_conversations WHERE user_low_id = ? AND user_high_id = ?",
            (u_low, u_high),
        ).fetchone()
        if not conv:
            tx.execute(
                "INSERT INTO dm_conversations (user_low_id, user_high_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (u_low, u_high, now_iso, now_iso),
            )
            conv_id = int(tx.execute("SELECT last_insert_rowid()").fetchone()[0])
            tx.execute(
                "INSERT INTO dm_members (conversation_id, user_id, last_read_message_id, read_at) VALUES (?, ?, 0, NULL), (?, ?, 0, NULL)",
                (conv_id, u_low, conv_id, u_high),
            )
        else:
            conv_id = int(conv["id"])

        tx.execute(
            "INSERT INTO dm_messages (conversation_id, sender_id, body, client_message_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (conv_id, sender_id, clean_body, client_msg_id, now_iso),
        )
        msg_id = int(tx.execute("SELECT last_insert_rowid()").fetchone()[0])

        tx.execute(
            "UPDATE dm_conversations SET last_message_id = ?, updated_at = ? WHERE id = ?",
            (msg_id, now_iso, conv_id),
        )

        # Advance sender's read cursor to own message
        tx.execute(
            "UPDATE dm_members SET last_read_message_id = MAX(last_read_message_id, ?), read_at = ? WHERE conversation_id = ? AND user_id = ?",
            (msg_id, now_iso, conv_id, sender_id),
        )

        # Durably record contact history for new contact rate limit
        tx.execute(
            "INSERT OR IGNORE INTO dm_contact_history (sender_id, recipient_id, first_contact_date, first_contact_at) VALUES (?, ?, ?, ?)",
            (sender_id, recipient_id, today_str, now_iso),
        )

    return {
        "ok": True,
        "conversationId": conv_id,
        "message": {
            "id": msg_id,
            "conversationId": conv_id,
            "senderId": sender_id,
            "body": clean_body,
            "clientMessageId": client_msg_id,
            "createdAt": now_iso,
            "isSelf": True,
            "isRead": False,
        },
        "replayed": False,
    }


def list_dm_conversations(db: Database, user: dict[str, Any], qs: dict[str, list[str]]) -> dict[str, Any]:
    cur_user = _require_active_user(user)
    uid = int(cur_user["id"])
    conn = db.get_conn()

    limit_val = 30
    if "limit" in qs:
        try:
            limit_val = max(1, min(100, int(qs["limit"][0])))
        except (ValueError, TypeError):
            pass

    cursor_val = (qs.get("cursor") or [""])[0].strip()

    params: list[Any] = [uid, uid]
    cursor_clause = ""
    if cursor_val:
        cursor_clause = "AND c.updated_at < ?"
        params.append(cursor_val)

    params.append(limit_val + 1)

    sql = f"""
    SELECT c.id, c.user_low_id, c.user_high_id, c.last_message_id, c.updated_at, c.created_at,
           m.last_read_message_id,
           lm.body AS last_msg_body, lm.sender_id AS last_msg_sender_id, lm.created_at AS last_msg_time
    FROM dm_conversations c
    JOIN dm_members m ON m.conversation_id = c.id AND m.user_id = ?
    LEFT JOIN dm_messages lm ON lm.id = c.last_message_id
    WHERE (c.user_low_id = ? OR c.user_high_id = ?) {cursor_clause}
    ORDER BY c.updated_at DESC, c.id DESC
    LIMIT ?
    """
    rows = conn.execute(sql, [uid, *params]).fetchall()

    has_more = len(rows) > limit_val
    visible_rows = rows[:limit_val]

    conversations = []
    for r in visible_rows:
        cid = int(r["id"])
        peer_id = int(r["user_high_id"]) if uid == int(r["user_low_id"]) else int(r["user_low_id"])
        peer_user = conn.execute("SELECT id, username, display_name FROM users WHERE id = ?", (peer_id,)).fetchone()
        peer_name = peer_user["display_name"] if peer_user else f"用户_{peer_id}"
        peer_uname = peer_user["username"] if peer_user else f"user_{peer_id}"

        # Unread count in this conversation for current user
        unread_cnt = conn.execute(
            "SELECT COUNT(*) FROM dm_messages WHERE conversation_id = ? AND sender_id != ? AND id > ?",
            (cid, uid, int(r["last_read_message_id"] or 0)),
        ).fetchone()[0]

        blocked = is_user_blocked(conn, uid, peer_id)

        last_msg = None
        if r["last_message_id"]:
            last_msg = {
                "id": int(r["last_message_id"]),
                "senderId": int(r["last_msg_sender_id"] or 0),
                "body": str(r["last_msg_body"] or "")[:120],
                "createdAt": str(r["last_msg_time"] or r["updated_at"]),
            }

        conversations.append({
            "id": cid,
            "peer": {
                "id": peer_id,
                "username": peer_uname,
                "displayName": peer_name,
                "avatarUrl": "/assets/user-avatar.webp",
            },
            "lastMessage": last_msg,
            "unreadCount": int(unread_cnt),
            "updatedAt": str(r["updated_at"]),
            "isBlocked": blocked,
        })

    next_cursor = visible_rows[-1]["updated_at"] if (has_more and visible_rows) else None

    return {
        "ok": True,
        "conversations": conversations,
        "nextCursor": next_cursor,
    }


def list_dm_messages(db: Database, user: dict[str, Any], conversation_id: int, qs: dict[str, list[str]]) -> dict[str, Any]:
    cur_user = _require_active_user(user)
    uid = int(cur_user["id"])
    conn = db.get_conn()

    conv = conn.execute("SELECT * FROM dm_conversations WHERE id = ?", (conversation_id,)).fetchone()
    if not conv:
        raise _service_error("私信会话不存在", status=404, code="conversation_not_found")

    # Strict participant check: Admin does NOT have bypass permission to view other users' DMs
    if uid != int(conv["user_low_id"]) and uid != int(conv["user_high_id"]):
        raise _service_error("无权查看该私信会话", status=403, code="dm_access_denied")

    peer_id = int(conv["user_high_id"]) if uid == int(conv["user_low_id"]) else int(conv["user_low_id"])
    peer_user = conn.execute("SELECT id, username, display_name FROM users WHERE id = ?", (peer_id,)).fetchone()
    peer_name = peer_user["display_name"] if peer_user else f"用户_{peer_id}"
    peer_uname = peer_user["username"] if peer_user else f"user_{peer_id}"

    peer_member = conn.execute(
        "SELECT last_read_message_id FROM dm_members WHERE conversation_id = ? AND user_id = ?",
        (conversation_id, peer_id),
    ).fetchone()
    peer_read_id = int(peer_member["last_read_message_id"] or 0) if peer_member else 0

    my_member = conn.execute(
        "SELECT last_read_message_id FROM dm_members WHERE conversation_id = ? AND user_id = ?",
        (conversation_id, uid),
    ).fetchone()
    my_read_id = int(my_member["last_read_message_id"] or 0) if my_member else 0

    before_raw = (qs.get("before") or [""])[0].strip()
    after_raw = (qs.get("after") or [""])[0].strip()

    if before_raw and after_raw:
        raise _service_error("before 与 after 参数互斥，不能同时提供", status=400, code="mutually_exclusive_params")

    limit_val = 30
    if "limit" in qs:
        try:
            limit_val = max(1, min(100, int(qs["limit"][0])))
        except (ValueError, TypeError):
            pass

    if before_raw:
        try:
            before_id = int(before_raw)
        except ValueError as exc:
            raise _service_error("before 参数需为整数消息 ID", status=400) from exc
        rows = conn.execute(
            "SELECT * FROM dm_messages WHERE conversation_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
            (conversation_id, before_id, limit_val + 1),
        ).fetchall()
        has_more = len(rows) > limit_val
        msg_rows = list(reversed(rows[:limit_val]))
    elif after_raw:
        try:
            after_id = int(after_raw)
        except ValueError as exc:
            raise _service_error("after 参数需为整数消息 ID", status=400) from exc
        rows = conn.execute(
            "SELECT * FROM dm_messages WHERE conversation_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
            (conversation_id, after_id, limit_val + 1),
        ).fetchall()
        has_more = len(rows) > limit_val
        msg_rows = rows[:limit_val]
    else:
        rows = conn.execute(
            "SELECT * FROM dm_messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit_val + 1),
        ).fetchall()
        has_more = len(rows) > limit_val
        msg_rows = list(reversed(rows[:limit_val]))

    messages = []
    for r in msg_rows:
        is_self = (int(r["sender_id"]) == uid)
        mid = int(r["id"])
        is_read = (mid <= peer_read_id) if is_self else (mid <= my_read_id)
        messages.append({
            "id": mid,
            "conversationId": conversation_id,
            "senderId": int(r["sender_id"]),
            "body": r["body"],
            "clientMessageId": r["client_message_id"],
            "createdAt": r["created_at"],
            "isSelf": is_self,
            "isRead": is_read,
        })

    next_before = msg_rows[0]["id"] if (has_more and msg_rows and not after_raw) else None
    next_after = msg_rows[-1]["id"] if (has_more and msg_rows and after_raw) else None

    return {
        "ok": True,
        "conversation": {
            "id": conversation_id,
            "peer": {
                "id": peer_id,
                "username": peer_uname,
                "displayName": peer_name,
                "avatarUrl": "/assets/user-avatar.webp",
            },
            "isBlocked": is_user_blocked(conn, uid, peer_id),
            "myLastReadMessageId": my_read_id,
            "peerLastReadMessageId": peer_read_id,
        },
        "messages": messages,
        "hasMore": has_more,
        "nextBefore": next_before,
        "nextAfter": next_after,
    }


def mark_dm_read(db: Database, user: dict[str, Any], conversation_id: int, body: dict[str, Any]) -> dict[str, Any]:
    cur_user = _require_active_user(user)
    uid = int(cur_user["id"])
    conn = db.get_conn()

    conv = conn.execute("SELECT * FROM dm_conversations WHERE id = ?", (conversation_id,)).fetchone()
    if not conv:
        raise _service_error("私信会话不存在", status=404, code="conversation_not_found")
    if uid != int(conv["user_low_id"]) and uid != int(conv["user_high_id"]):
        raise _service_error("无权标记该私信会话已读", status=403, code="dm_access_denied")

    raw_msg_id = body.get("messageId")
    if raw_msg_id is None:
        raise _service_error("缺少已读消息 ID（messageId）", status=400, code="missing_message_id")
    try:
        msg_id = int(raw_msg_id)
    except (ValueError, TypeError) as exc:
        raise _service_error("已读消息 ID 无效", status=400) from exc

    # Cannot exceed the actual existing messages in this conversation
    target_msg = conn.execute(
        "SELECT id FROM dm_messages WHERE conversation_id = ? AND id = ?",
        (conversation_id, msg_id),
    ).fetchone()
    if not target_msg:
        raise _service_error("指定的消息在该会话中不存在", status=400, code="message_not_in_conversation")

    now_iso = utc_now_iso()
    with db.transaction() as tx:
        # Read cursor monotonically advances: only update if message_id > current last_read_message_id
        tx.execute(
            """
            UPDATE dm_members
            SET last_read_message_id = MAX(last_read_message_id, ?),
                read_at = CASE WHEN ? > last_read_message_id THEN ? ELSE read_at END
            WHERE conversation_id = ? AND user_id = ?
            """,
            (msg_id, msg_id, now_iso, conversation_id, uid),
        )
        updated_cursor = tx.execute(
            "SELECT last_read_message_id FROM dm_members WHERE conversation_id = ? AND user_id = ?",
            (conversation_id, uid),
        ).fetchone()

    return {
        "ok": True,
        "conversationId": conversation_id,
        "lastReadMessageId": int(updated_cursor["last_read_message_id"] or msg_id),
    }


def block_user(db: Database, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    cur_user = _require_active_user(user)
    uid = int(cur_user["id"])
    conn = db.get_conn()

    target_raw = body.get("userId") or body.get("targetUserId") or body.get("blockedUserId") or body.get("username")
    if not target_raw:
        raise _service_error("缺少拉黑目标用户 ID 或用户名", status=400)

    target_str = str(target_raw).strip()
    if target_str.isdigit():
        target_user = conn.execute("SELECT id, username FROM users WHERE id = ?", (int(target_str),)).fetchone()
    else:
        target_user = conn.execute("SELECT id, username FROM users WHERE lower(username) = lower(?)", (target_str,)).fetchone()

    if not target_user:
        raise _service_error("拉黑目标用户不存在", status=404)
    target_id = int(target_user["id"])
    if target_id == uid:
        raise _service_error("不能拉黑自己", status=400)

    now_iso = utc_now_iso()
    with db.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO dm_blocks (user_id, blocked_user_id, created_at) VALUES (?, ?, ?)",
            (uid, target_id, now_iso),
        )

    return {"ok": True, "blocked": True, "userId": target_id, "username": target_user["username"]}


def unblock_user(db: Database, user: dict[str, Any], target_raw: str) -> dict[str, Any]:
    cur_user = _require_active_user(user)
    uid = int(cur_user["id"])
    conn = db.get_conn()

    target_str = str(target_raw or "").strip()
    if target_str.isdigit():
        target_user = conn.execute("SELECT id, username FROM users WHERE id = ?", (int(target_str),)).fetchone()
    else:
        target_user = conn.execute("SELECT id, username FROM users WHERE lower(username) = lower(?)", (target_str,)).fetchone()

    if not target_user:
        raise _service_error("目标用户不存在", status=404)
    target_id = int(target_user["id"])

    with db.transaction() as tx:
        tx.execute(
            "DELETE FROM dm_blocks WHERE user_id = ? AND blocked_user_id = ?",
            (uid, target_id),
        )

    return {"ok": True, "unblocked": True, "userId": target_id, "username": target_user["username"]}


def get_messages_unread_summary(db: Database, user: dict[str, Any] | None) -> dict[str, Any]:
    if not user:
        return {"ok": True, "notifications": 0, "direct": 0, "broadcasts": 0, "total": 0}

    uid = int(user["id"])
    conn = db.get_conn()

    # Unread notifications
    n_count = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL",
        (uid,),
    ).fetchone()[0]

    # Unread direct messages
    dm_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM dm_messages m
        JOIN dm_members mem ON mem.conversation_id = m.conversation_id AND mem.user_id = ?
        WHERE m.sender_id != ? AND m.id > mem.last_read_message_id
        """,
        (uid, uid),
    ).fetchone()[0]

    # Broadcasts: reserved for Phase B, constant 0
    broadcasts_count = 0
    total = int(n_count) + int(dm_count) + broadcasts_count

    return {
        "ok": True,
        "notifications": int(n_count),
        "direct": int(dm_count),
        "broadcasts": broadcasts_count,
        "total": total,
    }


def handle_dm_report_target(tx: Any, uid: int, target_id: str, detail: str) -> tuple[str, str]:
    """Helper invoked by services.py:submit_abuse_report for target_type='dm_message'."""
    row = tx.execute("SELECT id, body, sender_id, conversation_id FROM dm_messages WHERE id = ?", (target_id,)).fetchone()
    if not row:
        raise _service_error("举报的私信不存在", status=404)
    conv = tx.execute("SELECT user_low_id, user_high_id FROM dm_conversations WHERE id = ?", (row["conversation_id"],)).fetchone()
    if not conv or (uid != int(conv["user_low_id"]) and uid != int(conv["user_high_id"])):
        raise _service_error("只能举报自己收到的或参与的私信消息", status=403)
    sender = tx.execute("SELECT username, display_name FROM users WHERE id = ?", (row["sender_id"],)).fetchone()
    sender_name = sender["display_name"] if sender else f"user_{row['sender_id']}"
    target_title = f"私信 @{sender_name}：{(row['body'] or '')[:40]}"
    context = f"[被举报私信内容] {row['body']}"
    clean_detail = f"{detail}\n{context}" if detail else context
    return target_title, clean_detail


# HTTP dispatch hooks
def handle_dm_get(handler: Any, req_path: str, qs: dict[str, list[str]]) -> bool:
    if req_path == "/api/messages/unread":
        user = handler._current_user(required=False)
        handler._send_json(get_messages_unread_summary(handler.db, user))
        return True

    if req_path == "/api/dm/conversations":
        user = handler._current_user(required=True)
        handler._send_json(list_dm_conversations(handler.db, user, qs))
        return True

    m_msgs = re.fullmatch(r"^/api/dm/conversations/(\d+)/messages$", req_path)
    if m_msgs:
        user = handler._current_user(required=True)
        conv_id = int(m_msgs.group(1))
        handler._send_json(list_dm_messages(handler.db, user, conv_id, qs))
        return True

    return False


def handle_dm_post(handler: Any, req_path: str, body: dict[str, Any]) -> bool:
    if req_path == "/api/dm/messages":
        user = handler._current_user(required=True)
        handler._send_json(send_direct_message(handler.db, user, body), status=200)
        return True

    m_read = re.fullmatch(r"^/api/dm/conversations/(\d+)/read$", req_path)
    if m_read:
        user = handler._current_user(required=True)
        conv_id = int(m_read.group(1))
        handler._send_json(mark_dm_read(handler.db, user, conv_id, body))
        return True

    if req_path == "/api/dm/blocks":
        user = handler._current_user(required=True)
        handler._send_json(block_user(handler.db, user, body))
        return True

    return False


def handle_dm_delete(handler: Any, req_path: str, qs: dict[str, list[str]]) -> bool:
    m_block = re.fullmatch(r"^/api/dm/blocks/([^/]+)$", req_path)
    if m_block:
        user = handler._current_user(required=True)
        target_raw = unquote(m_block.group(1))
        handler._send_json(unblock_user(handler.db, user, target_raw))
        return True

    return False
