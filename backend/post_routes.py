"""Post and unified topic routes for Phase 1a.

Endpoints:
    GET /api/posts/by-ref/{kind}/{id}
    GET /api/posts/{topicId}
    GET /api/posts/{topicId}/replies?cursor=&limit=20
    GET /t/{ref}
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any

from . import forum_resources
from . import services as S
from .resource_discussions import resolve_resource


def _is_topic_visible(conn: Any, t_row: Any, user: dict[str, Any] | None = None) -> bool:
    if not t_row:
        return False
    is_staff = bool(user and user.get("role") in ("admin", "operator", "reviewer"))
    if not is_staff and t_row["status"] != "published":
        return False
    # Seed filter check
    tf, tp = S._seed_filter("id", "topics")
    t_valid = conn.execute(
        f"SELECT 1 FROM forum_topics WHERE id = ? AND {tf}", (t_row["id"], *tp)
    ).fetchone()
    if not t_valid:
        return False
    return True


def _resolve_ref_to_topic_id(conn: Any, ref: str, user: dict[str, Any] | None = None) -> str | None:
    ref = ref.strip()
    if not ref:
        return None

    # 1. Direct topic ID in forum_topics
    t_row = conn.execute(
        "SELECT id, status FROM forum_topics WHERE id = ?", (ref,)
    ).fetchone()
    if t_row and _is_topic_visible(conn, t_row, user):
        m = conn.execute(
            "SELECT kind, target_id FROM curation_resource_topics WHERE topic_id = ?",
            (ref,),
        ).fetchone()
        if m:
            m_target = m["target_id"].upper().lstrip("#") if m["kind"] in ("style", "layout") else m["target_id"]
            res = resolve_resource(conn, m["kind"], m_target)
            if not res:
                return None
            if m["kind"] == "work":
                wf, wp = S._seed_filter("id", "works")
                w_valid = conn.execute(
                    f"SELECT 1 FROM works WHERE id = ? AND {wf}", (m_target, *wp)
                ).fetchone()
                if not w_valid:
                    return None
        return str(t_row["id"])

    # 2. Semantic prefix or direct work ID
    ref_work = ref[5:] if ref.lower().startswith("work-") else ref
    m_work = conn.execute(
        "SELECT topic_id, target_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?",
        (ref_work,),
    ).fetchone()
    if m_work:
        res = resolve_resource(conn, "work", ref_work)
        wf, wp = S._seed_filter("id", "works")
        w_valid = conn.execute(
            f"SELECT 1 FROM works WHERE id = ? AND {wf}", (ref_work, *wp)
        ).fetchone()
        if res and w_valid:
            t = conn.execute(
                "SELECT id, status FROM forum_topics WHERE id = ?", (m_work["topic_id"],)
            ).fetchone()
            if t and _is_topic_visible(conn, t, user):
                return str(m_work["topic_id"])

    # 3. Semantic prefix or direct style/layout code
    if ref.lower().startswith("style-"):
        kinds = ("style",)
        code = ref[6:].strip().upper().lstrip("#")
    elif ref.lower().startswith("layout-"):
        kinds = ("layout",)
        code = ref[7:].strip().upper().lstrip("#")
    else:
        kinds = ("style", "layout")
        code = ref.strip().upper().lstrip("#")

    placeholders = ",".join("?" for _ in kinds)
    m_asset = conn.execute(
        f"SELECT topic_id, kind, target_id FROM curation_resource_topics WHERE kind IN ({placeholders}) AND UPPER(target_id) = ?",
        (*kinds, code),
    ).fetchone()
    if m_asset:
        res = resolve_resource(conn, m_asset["kind"], m_asset["target_id"])
        if res:
            t = conn.execute(
                "SELECT id, status FROM forum_topics WHERE id = ?", (m_asset["topic_id"],)
            ).fetchone()
            if t and _is_topic_visible(conn, t, user):
                return str(m_asset["topic_id"])

    return None


def _handle_t_redirect(handler: Any, ref: str, qs: dict[str, list[str]] | None = None) -> bool:
    conn = handler.db.get_conn()
    user = handler._current_user(required=False)
    topic_id = _resolve_ref_to_topic_id(conn, ref, user)
    if not topic_id:
        handler.send_error(404, "Not found")
        return True
    location = f"/forum/?view=topic&id={topic_id}"
    if qs and qs.get("focus"):
        focus_vals = qs.get("focus") or []
        if focus_vals and focus_vals[0] == "comment":
            location += "&focus=comment"
    handler.send_response(302)
    handler.send_header("Location", location)
    handler._cors_headers()
    handler.end_headers()
    return True


def _handle_by_ref(handler: Any, kind: str, target_id: str) -> bool:
    target = target_id.upper().lstrip("#") if kind in ("style", "layout") else target_id
    conn = handler.db.get_conn()
    user = handler._current_user(required=False)
    res = resolve_resource(conn, kind, target)
    if not res:
        raise S.ServiceError("资源不存在", status=404)

    if kind in ("style", "layout"):
        mapping = conn.execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind = ? AND UPPER(target_id) = ?",
            (kind, target),
        ).fetchone()
    else:
        mapping = conn.execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind = ? AND target_id = ?",
            (kind, target),
        ).fetchone()

    if not mapping:
        raise S.ServiceError("帖子不存在", status=404)

    tid = str(mapping["topic_id"])
    t_row = conn.execute("SELECT id, status FROM forum_topics WHERE id = ?", (tid,)).fetchone()
    if not t_row or not _is_topic_visible(conn, t_row, user):
        raise S.ServiceError("帖子不可见", status=404)

    handler._send_json({"ok": True, "topicId": tid})
    return True


def _get_asset_social_metrics(conn: Any, code: str) -> tuple[int, int]:
    clean = (code or "").strip().upper().lstrip("#")
    if not clean:
        return 0, 0
    if S.is_demo_mode():
        seed_filter, seed_params = S._seed_filter("asset_code", "assets")
        row = conn.execute(
            f"SELECT base_likes, base_favorites FROM asset_social_seeds WHERE asset_code = ? AND {seed_filter}",
            (clean, *seed_params),
        ).fetchone()
        if row:
            base_likes = int(row["base_likes"])
            base_favorites = int(row["base_favorites"])
        else:
            base_likes, base_favorites = 0, 0
    else:
        base_likes = 0
        base_favorites = 0

    live_filter, live_params = S._seed_filter("target_id", "assets")
    like_row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM interactions WHERE target_type IN ('like_style', 'like_layout') AND target_id = ? AND {live_filter}",
        (clean, *live_params),
    ).fetchone()
    live_likes = int(like_row["cnt"]) if like_row else 0

    fav_row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM collections WHERE bucket IN ('styles', 'layouts') AND target_id = ? AND {live_filter}",
        (clean, *live_params),
    ).fetchone()
    live_favorites = int(fav_row["cnt"]) if fav_row else 0

    return max(0, base_likes + live_likes), max(0, base_favorites + live_favorites)


def _handle_detail(handler: Any, topic_id: str) -> bool:
    conn = handler.db.get_conn()
    user = handler._current_user(required=False)

    t_row = conn.execute("SELECT * FROM forum_topics WHERE id = ?", (topic_id,)).fetchone()
    if not t_row or not _is_topic_visible(conn, t_row, user):
        raise S.ServiceError("帖子不存在或不可见", status=404)

    mapping = conn.execute(
        "SELECT * FROM curation_resource_topics WHERE topic_id = ?", (topic_id,)
    ).fetchone()

    unlocked_set = forum_resources._unlocked(handler.db, user)

    # Reuse services._serialize_topic for canonical topic serialization
    topic_dict = S._serialize_topic(t_row, {}, unlocked_set, user)
    topic_dict["status"] = t_row["status"]
    if "status_source" in t_row.keys():
        topic_dict["status_source"] = t_row["status_source"]
    if "status_actor_role" in t_row.keys():
        topic_dict["status_actor_role"] = t_row["status_actor_role"]

    if not mapping:
        mount: dict[str, Any] = {"kind": "discussion"}
    elif mapping["kind"] == "work":
        m_target = str(mapping["target_id"])
        w_dict = resolve_resource(conn, "work", m_target)
        if not w_dict:
            raise S.ServiceError("作品不存在或不可见", status=404)
        w_row = conn.execute("SELECT * FROM works WHERE id = ?", (m_target,)).fetchone()
        work_res = forum_resources._work_resource(w_row, unlocked_set, user)
        w_likes = int(w_row["likes"] or 0)
        w_favorites = int(w_row["favorites"] or 0)
        w_forks = int(w_row["forks"] or 0)
        work_res["likes"] = w_likes
        work_res["favorites"] = w_favorites
        work_res["forks"] = w_forks
        mount = {
            "kind": "work",
            "work": work_res,
        }
        topic_dict["likes"] = w_likes
        topic_dict["favorites"] = w_favorites
        topic_dict["workId"] = m_target
    elif mapping["kind"] in ("style", "layout"):
        m_kind = str(mapping["kind"])
        code = str(mapping["target_id"]).strip().upper().lstrip("#")
        raw = resolve_resource(conn, m_kind, code)
        if not raw:
            raise S.ServiceError("关联资源不存在或不可见", status=404)

        if "code" in raw:
            asset_res = forum_resources._asset_resource(raw, unlocked_set, user)
        else:
            asset_res = forum_resources._static_resource(raw, m_kind)

        res_likes, res_favorites = _get_asset_social_metrics(conn, code)
        mount = {
            "kind": m_kind,
            "resource": {
                "code": code,
                "name": asset_res.get("name") or asset_res.get("title") or code,
                "image": asset_res.get("image") or "",
                "description": asset_res.get("description") or "",
                "definition": asset_res.get("definition") or "",
                "unlocked": bool(asset_res.get("unlocked")),
                "unlockCost": int(asset_res.get("unlockCost") or 0),
                "useUrl": f"/studio/?{m_kind}={code}",
                "likes": res_likes,
                "favorites": res_favorites,
            },
        }
        topic_dict["likes"] = res_likes
        topic_dict["favorites"] = res_favorites
    else:
        mount = {"kind": "discussion"}

    # Viewer state (liked and favorited per mount kind)
    if user:
        uid = int(user["id"])
        if mapping and mapping["kind"] == "work":
            wid = str(mapping["target_id"])
            liked = bool(
                conn.execute(
                    "SELECT 1 FROM interactions WHERE user_id = ? AND target_type = 'like_work' AND target_id = ? AND stamp_label = ''",
                    (uid, wid),
                ).fetchone()
            )
            favorited = bool(
                conn.execute(
                    "SELECT 1 FROM collections WHERE user_id = ? AND bucket = 'works' AND target_id = ?",
                    (uid, wid),
                ).fetchone()
            )
        elif mapping and mapping["kind"] == "style":
            code = str(mapping["target_id"]).strip().upper().lstrip("#")
            liked = bool(
                conn.execute(
                    "SELECT 1 FROM interactions WHERE user_id = ? AND target_type = 'like_style' AND (target_id = ? OR UPPER(target_id) = ?) AND stamp_label = ''",
                    (uid, code, code),
                ).fetchone()
            )
            favorited = bool(
                conn.execute(
                    "SELECT 1 FROM collections WHERE user_id = ? AND bucket = 'styles' AND (target_id = ? OR UPPER(target_id) = ?)",
                    (uid, code, code),
                ).fetchone()
            )
        elif mapping and mapping["kind"] == "layout":
            code = str(mapping["target_id"]).strip().upper().lstrip("#")
            liked = bool(
                conn.execute(
                    "SELECT 1 FROM interactions WHERE user_id = ? AND target_type = 'like_layout' AND (target_id = ? OR UPPER(target_id) = ?) AND stamp_label = ''",
                    (uid, code, code),
                ).fetchone()
            )
            favorited = bool(
                conn.execute(
                    "SELECT 1 FROM collections WHERE user_id = ? AND bucket = 'layouts' AND (target_id = ? OR UPPER(target_id) = ?)",
                    (uid, code, code),
                ).fetchone()
            )
        else:
            liked = bool(
                conn.execute(
                    "SELECT 1 FROM interactions WHERE user_id = ? AND target_type = 'like_topic' AND target_id = ? AND stamp_label = ''",
                    (uid, topic_id),
                ).fetchone()
            )
            favorited = bool(
                conn.execute(
                    "SELECT 1 FROM collections WHERE user_id = ? AND bucket = 'topics' AND target_id = ?",
                    (uid, topic_id),
                ).fetchone()
            )
    else:
        liked = False
        favorited = False

    handler._send_json({
        "ok": True,
        "topic": topic_dict,
        "mount": mount,
        "viewer": {
            "liked": liked,
            "favorited": favorited,
        },
    })
    return True


def _handle_replies(handler: Any, topic_id: str, qs: dict[str, list[str]]) -> bool:
    conn = handler.db.get_conn()
    user = handler._current_user(required=False)

    t_row = conn.execute("SELECT * FROM forum_topics WHERE id = ?", (topic_id,)).fetchone()
    if not t_row or not _is_topic_visible(conn, t_row, user):
        raise S.ServiceError("帖子不存在或已下架", status=404)

    mapping = conn.execute(
        "SELECT * FROM curation_resource_topics WHERE topic_id = ?", (topic_id,)
    ).fetchone()
    if mapping:
        res = resolve_resource(conn, mapping["kind"], mapping["target_id"])
        if not res:
            raise S.ServiceError("关联资源不存在或不可见", status=404)

    limit_raw = qs.get("limit", ["20"])[0]
    try:
        limit = max(1, min(50, int(limit_raw)))
    except (ValueError, TypeError):
        limit = 20

    cursor = (qs.get("cursor", [""])[0] or "").strip()

    c_time: str | None = None
    c_id: str | None = None
    if cursor:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            raw_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
            c_data = json.loads(raw_bytes.decode("utf-8"))
            if not isinstance(c_data, dict):
                raise ValueError("Cursor payload must be a JSON object")
            if c_data.get("topicId") != topic_id:
                raise ValueError("topicId in cursor does not match route")
            c_time = c_data.get("created_at")
            c_id = c_data.get("id")
            c_tid = c_data.get("topicId")
            if not isinstance(c_time, str) or not isinstance(c_id, str) or not isinstance(c_tid, str):
                raise ValueError("Cursor fields must be strings")
            if not c_time.strip() or not c_id.strip() or not c_tid.strip():
                raise ValueError("Cursor fields must be non-empty")
            if not re.fullmatch(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", c_time):
                raise ValueError("created_at must match YYYY-MM-DDTHH:MM:SSZ")
        except Exception:
            raise S.ServiceError("invalid_cursor", status=400)

    sf, sp = S._seed_filter("id", "forum_replies")
    where_parts = [
        "topic_id = ?",
        "status = 'published'",
        sf,
    ]
    params: list[Any] = [topic_id, *sp]

    if c_time and c_id:
        where_parts.append("(created_at > ? OR (created_at = ? AND id > ?))")
        params.extend([c_time, c_time, c_id])

    where_sql = " AND ".join(where_parts)
    sql = f"SELECT * FROM forum_replies WHERE {where_sql} ORDER BY created_at ASC, id ASC LIMIT ?"
    params.append(limit + 1)

    rows = conn.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items = []
    for r in page_rows:
        items.append({
            "id": r["id"],
            "topicId": r["topic_id"],
            "author": r["author_username"],
            "authorName": r["author_name"],
            "text": r["text"],
            "mountedStyle": r["mounted_style"] or "",
            "mountedLayout": r["mounted_layout"] or "",
            "likes": int(r["likes"] or 0),
            "accepted": bool(r["accepted"]),
            "time": r["time_label"] or S.format_short_time(r["created_at"]),
            "createdAt": r["created_at"],
        })

    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        payload = {
            "created_at": last["created_at"],
            "id": last["id"],
            "topicId": topic_id,
        }
        next_cursor = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")

    handler._send_json({
        "ok": True,
        "items": items,
        "nextCursor": next_cursor,
    })
    return True


def handle_get(handler: Any, path: str, qs: dict[str, list[str]]) -> bool:
    # 1. /t/{ref} redirect
    if path == "/t" or path == "/t/":
        handler.send_error(404, "Not found")
        return True
    if path.startswith("/t/"):
        ref = path[3:].strip()
        return _handle_t_redirect(handler, ref, qs)

    # 2. /api/posts/...
    if not path.startswith("/api/posts/"):
        return False

    sub = path[len("/api/posts/"):]
    # Check by-ref: by-ref/(work|style|layout)/([^/]+)
    m_by_ref = re.fullmatch(r"by-ref/(work|style|layout)/([^/]+)", sub, re.IGNORECASE)
    if m_by_ref:
        kind = m_by_ref.group(1).lower()
        target_id = m_by_ref.group(2)
        return _handle_by_ref(handler, kind, target_id)

    # Check replies: ([^/]+)/replies
    m_replies = re.fullmatch(r"([^/]+)/replies", sub)
    if m_replies:
        topic_id = m_replies.group(1)
        return _handle_replies(handler, topic_id, qs)

    # Check detail: ([^/]+)
    m_detail = re.fullmatch(r"([^/]+)", sub)
    if m_detail:
        topic_id = m_detail.group(1)
        return _handle_detail(handler, topic_id)

    return False
