"""Forum lifecycle and account invitations; every entry uses the same policy."""

from __future__ import annotations

import re
import uuid


def access_sql(category="forum_topics.category", viewer=None, *, public_only=False):
    if not re.fullmatch(r"[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?", category):
        raise ValueError("Invalid category SQL reference")
    uid = int((viewer or {}).get("id") or 0)
    admin = bool(viewer and viewer.get("role") == "admin" and not public_only)
    permission = "TRUE" if admin else "fb.visibility='public'"
    if uid and not public_only and not admin:
        permission += f" OR EXISTS(SELECT 1 FROM forum_board_members fm WHERE fm.board_key=fb.key AND fm.user_id={uid} AND fm.revoked_at IS NULL)"
    return f"EXISTS(SELECT 1 FROM forum_boards fb WHERE fb.key={category} AND fb.state='open' AND ({permission}))"


def list_boards(conn, viewer=None):
    rows = conn.execute(
        f"SELECT b.* FROM forum_boards b WHERE {access_sql('b.key', viewer)} ORDER BY position,key"
    ).fetchall()
    return [
        {
            "key": r["key"],
            "id": r["key"],
            "label": r["label"],
            "shortLabel": r["label"],
            "desc": r["description"],
            "visibility": r["visibility"],
            "revision": r["revision"],
            "url": "/forum/?category=" + r["key"],
        }
        for r in rows
    ]


def require_board(conn, key, viewer=None, *, write=False):
    from .services import ServiceError

    row = conn.execute(
        "SELECT * FROM forum_boards WHERE key=?" + (" FOR SHARE" if write else ""),
        (key,),
    ).fetchone()
    allowed = (
        row
        and conn.execute(
            f"SELECT 1 FROM forum_boards b WHERE b.key=? AND {access_sql('b.key', viewer)}",
            (key,),
        ).fetchone()
    )
    if not allowed:
        raise ServiceError("论坛不存在或无访问权限", 404, "forum_unavailable")
    return dict(row)


def require_topic(conn, topic_id, viewer=None, *, write=False):
    from .services import ServiceError

    row = conn.execute(
        "SELECT category FROM forum_topics WHERE id=?", (topic_id,)
    ).fetchone()
    if not row:
        raise ServiceError("帖子不存在或不可见", 404, "not_found")
    return require_board(conn, row["category"], viewer, write=write)


def can_read_topic(conn, topic_id, viewer=None):
    return bool(
        conn.execute(
            f"SELECT 1 FROM forum_topics t WHERE t.id=? AND {access_sql('t.category', viewer)}",
            (topic_id,),
        ).fetchone()
    )


def _admin(user):
    from .services import ServiceError

    if not user or user.get("role") != "admin" or user.get("status", "active") != "active":
        raise ServiceError("只有超级管理员可以管理论坛", 403, "forbidden")


def admin_list(db, user):
    _admin(user)
    conn = db.get_conn()
    boards = [
        dict(r)
        for r in conn.execute(
            "SELECT b.*, (SELECT count(*) FROM forum_board_members m WHERE m.board_key=b.key AND m.revoked_at IS NULL) member_count,(SELECT count(*) FROM forum_topics t WHERE t.category=b.key) topic_count FROM forum_boards b ORDER BY position,key"
        ).fetchall()
    ]
    members = [
        dict(r)
        for r in conn.execute(
            "SELECT m.board_key,m.user_id,u.username,u.display_name,m.invited_at FROM forum_board_members m JOIN users u ON u.id=m.user_id WHERE m.revoked_at IS NULL ORDER BY u.username"
        ).fetchall()
    ]
    for board in boards:
        board["members"] = [m for m in members if m["board_key"] == board["key"]]
    # HTTP serializer expects JSON-native values.
    for row in boards:
        for key in ("created_at", "updated_at"):
            row[key] = str(row[key])
        for member in row["members"]:
            member["invited_at"] = str(member["invited_at"])
    return {"ok": True, "items": boards}


def save_board(db, user, body, key=None):
    from .services import ServiceError, record_audit_log
    from .runtime_policy import sanitize_plain_text

    _admin(user)
    label = sanitize_plain_text(str(body.get("label") or "").strip(), max_chars=80)
    if not label:
        raise ServiceError("请填写论坛名称")
    visibility = str(body.get("visibility") or "public")
    state = str(body.get("state") or "open")
    if visibility not in ("public", "private") or state not in ("open", "closed"):
        raise ServiceError("论坛状态或可见范围无效")
    description = sanitize_plain_text(
        str(body.get("description") or ""), max_chars=1000
    )
    with db.transaction() as tx:
        if key:
            old = tx.execute(
                "SELECT * FROM forum_boards WHERE key=? FOR UPDATE", (key,)
            ).fetchone()
            if not old:
                raise ServiceError("论坛不存在", 404)
            try:
                revision = int(body.get("revision") or 0)
            except (ValueError, TypeError):
                raise ServiceError("论坛版本无效，请刷新后重试")
            if revision != old["revision"]:
                raise ServiceError(
                    "论坛设置已更新，请刷新后重试", 409, "revision_conflict"
                )
            if (
                old["visibility"] == "private"
                and visibility == "public"
                and tx.execute(
                    "SELECT 1 FROM forum_topics WHERE category=? LIMIT 1", (key,)
                ).fetchone()
            ):
                raise ServiceError(
                    "已有私密内容的论坛不能直接改为公开，请新建公开论坛",
                    409,
                    "private_history",
                )
            tx.execute(
                "UPDATE forum_boards SET label=?,description=?,visibility=?,state=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE key=?",
                (label, description, visibility, state, key),
            )
            tx.execute(
                "UPDATE forum_topics SET category_label=? WHERE category=?",
                (label, key),
            )
        else:
            key = "board_" + uuid.uuid4().hex
            tx.execute(
                "INSERT INTO forum_boards(key,label,description,visibility,state,created_by) VALUES(?,?,?,?,?,?)",
                (key, label, description, visibility, state, user["id"]),
            )
        record_audit_log(
            tx,
            user,
            "forum_board_save",
            "forum_board",
            key,
            details={"label": label, "visibility": visibility, "state": state},
        )
    return {"ok": True, "key": key}


def change_members(db, user, key, body):
    from .services import ServiceError, record_audit_log

    _admin(user)
    usernames = body.get("usernames")
    if not isinstance(usernames, list) or not 1 <= len(usernames) <= 100:
        raise ServiceError("请填写1至100个受邀用户名")
    names = list(
        dict.fromkeys(
            str(n).strip().lstrip("@").lower() for n in usernames if str(n).strip()
        )
    )
    if not names:
        raise ServiceError("请填写受邀用户名")
    revoke = body.get("action") == "revoke"
    if body.get("action", "invite") not in ("invite", "revoke"):
        raise ServiceError("成员操作无效")
    with db.transaction() as tx:
        if not tx.execute(
            "SELECT key FROM forum_boards WHERE key=? FOR UPDATE", (key,)
        ).fetchone():
            raise ServiceError("论坛不存在", 404)
        rows = tx.execute(
            "SELECT id,username FROM users WHERE LOWER(username) IN ("
            + ",".join("?" for _ in names)
            + ") AND status='active'",
            names,
        ).fetchall()
        found = {r["username"].lower() for r in rows}
        if set(names) - found:
            raise ServiceError(
                "以下账号不存在或已停用：" + "、".join(sorted(set(names) - found))
            )
        for row in rows:
            if revoke:
                tx.execute(
                    "UPDATE forum_board_members SET revoked_at=CURRENT_TIMESTAMP WHERE board_key=? AND user_id=? AND revoked_at IS NULL",
                    (key, row["id"]),
                )
            else:
                tx.execute(
                    "INSERT INTO forum_board_members(board_key,user_id,invited_by) VALUES(?,?,?) ON CONFLICT(board_key,user_id) DO UPDATE SET revoked_at=NULL,invited_by=EXCLUDED.invited_by,invited_at=CURRENT_TIMESTAMP WHERE forum_board_members.revoked_at IS NOT NULL",
                    (key, row["id"], user["id"]),
                )
        record_audit_log(
            tx,
            user,
            "forum_members_revoke" if revoke else "forum_members_invite",
            "forum_board",
            key,
            details={"userIds": [r["id"] for r in rows]},
        )
    return {"ok": True}
