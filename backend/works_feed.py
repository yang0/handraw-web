"""Works feed service: public work admission, keyset & frozen-session pagination, and media dimensions."""
from __future__ import annotations

import base64
import json
import logging
import sqlite3
import time
from typing import Any
import uuid

from .db import Database
from .media_dims import image_size
from .ranking import WORK_POPULAR_EXPR, normalize_sort
from .services import (
    _seed_filter,
    _serialize_work,
)

logger = logging.getLogger("handraw.works_feed")

# In-memory store for frozen popular browsing sessions.
# session_id -> (ordered_ids: list[str], created_at_ts: float)
_FEED_POPULAR_SESSIONS: dict[str, tuple[list[str], float]] = {}
_SESSION_TTL_SECONDS = 1800.0  # 30 minutes


def _clean_expired_sessions() -> None:
    now = time.time()
    expired = [
        sid
        for sid, val in _FEED_POPULAR_SESSIONS.items()
        if len(val) >= 2 and (now - val[1]) > _SESSION_TTL_SECONDS
    ]
    for sid in expired:
        _FEED_POPULAR_SESSIONS.pop(sid, None)


def encode_cursor(data: dict[str, Any]) -> str:
    """Encode dictionary into URL-safe base64 string."""
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor_str: str | None) -> dict[str, Any] | None:
    """Decode URL-safe base64 cursor string into dict."""
    if not cursor_str or not isinstance(cursor_str, str):
        return None
    s = cursor_str.strip()
    if not s:
        return None
    padding = "=" * ((4 - len(s) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(s + padding)
        val = json.loads(raw.decode("utf-8"))
        return val if isinstance(val, dict) else None
    except Exception:
        return None


def _get_unlocked_set(conn: sqlite3.Connection, user: dict[str, Any] | None) -> set[str]:
    if not user:
        return set()
    uid = user.get("id")
    if not uid:
        return set()
    unlock_filter, unlock_ids = _seed_filter("target_id", "works")
    rows = conn.execute(
        f"SELECT target_id FROM unlocks WHERE user_id = ? AND status = 'settled' AND target_type = 'work' AND {unlock_filter}",
        (uid, *unlock_ids),
    ).fetchall()
    unlocked = {r["target_id"] for r in rows if r["target_id"]}
    uname = user.get("username")
    if uname:
        own_filter, own_ids = _seed_filter("id", "works")
        for r in conn.execute(
            f"SELECT id FROM works WHERE author_username = ? AND {own_filter}",
            (uname, *own_ids),
        ).fetchall():
            unlocked.add(r["id"])
    return unlocked


def _ratio_to_dims(ratio: str | None) -> tuple[int, int, float]:
    r = str(ratio or "3:4").strip()
    lookup = {
        "3:4": (900, 1200, 0.75),
        "4:3": (1200, 900, 1.3333),
        "1:1": (1024, 1024, 1.0),
        "16:9": (1280, 720, 1.7778),
        "9:16": (720, 1280, 0.5625),
        "2:3": (800, 1200, 0.6667),
        "3:2": (1200, 800, 1.5),
    }
    if r in lookup:
        return lookup[r]
    parts = r.split(":")
    if len(parts) == 2:
        try:
            w_part, h_part = float(parts[0]), float(parts[1])
            if w_part > 0 and h_part > 0:
                return int(w_part * 300), int(h_part * 300), round(w_part / h_part, 4)
        except ValueError:
            pass
    return (900, 1200, 0.75)


def enrich_dimensions(item: dict[str, Any]) -> None:
    """Enrich work item with pixel dimensions and aspect ratio for masonry / waterfall layout."""
    raw_images = item.get("images") or []
    dims_list: list[dict[str, Any]] = []
    cover_w, cover_h, cover_ar = None, None, None

    for i, u in enumerate(raw_images):
        url_str = u if isinstance(u, str) else (u.get("url") if isinstance(u, dict) else "")
        w, h, ar = None, None, None
        if url_str:
            sz = image_size(url_str)
            if sz:
                w, h = sz
                ar = round(w / h, 4) if h > 0 else 1.0
        if w is None or h is None:
            w, h, ar = _ratio_to_dims(item.get("ratio"))
        dims_list.append({"url": url_str, "width": w, "height": h, "aspectRatio": ar})
        if i == 0:
            cover_w, cover_h, cover_ar = w, h, ar

    if cover_w is None or cover_h is None:
        cover_w, cover_h, cover_ar = _ratio_to_dims(item.get("ratio"))

    item["coverWidth"] = cover_w
    item["coverHeight"] = cover_h
    item["aspectRatio"] = cover_ar
    item["imageDimensions"] = dims_list


def is_valid_work_row(row: sqlite3.Row | dict[str, Any]) -> bool:
    """Check if work row has valid published status and non-empty image list."""
    if row["status"] != "published":
        return False
    imgs_raw = row["images_json"] if "images_json" in row.keys() else row.get("images_json")
    if not imgs_raw:
        return False
    try:
        parsed = json.loads(imgs_raw)
        if not isinstance(parsed, list) or len(parsed) == 0:
            return False
        return any(
            (isinstance(img, str) and img.strip())
            or (isinstance(img, dict) and str(img.get("url") or "").strip())
            for img in parsed
        )
    except Exception:
        return False


def get_works_feed(
    db: Database,
    params: dict[str, Any],
    current_user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Retrieve paginated public works feed with filters, stable keyset/frozen ordering, and dimensions."""
    _clean_expired_sessions()
    conn = db.get_conn()

    # Parse limit (default 24, clamped 1..100)
    try:
        limit = max(1, min(100, int(params.get("limit") or 24)))
    except (ValueError, TypeError):
        limit = 24

    sort_mode = normalize_sort(params.get("sort"))
    cursor_str = str(params.get("cursor") or "").strip()
    fmt = str(params.get("format") or "all").strip().lower()
    access = str(params.get("access") or "all").strip().lower()
    asset = str(params.get("asset") or "").strip().upper()
    author = str(params.get("author") or "").strip()
    q = str(params.get("q") or params.get("query") or "").strip().lower()
    ids_param = str(params.get("ids") or "").strip()
    is_search = bool(q)

    # Base admission filter: published, seed exclusion, non-empty images, valid JSON
    seed_clause, seed_params = _seed_filter("w.id", "works")
    base_clauses = [
        "w.status = 'published'",
        seed_clause,
        "w.images_json IS NOT NULL",
        "TRIM(w.images_json) NOT IN ('', '[]', 'null')",
        "json_valid(w.images_json) = 1",
    ]
    base_params: list[Any] = list(seed_params)

    # Optional explicit IDs filter (comma-separated)
    if ids_param:
        id_list = [i.strip() for i in ids_param.split(",") if i.strip()]
        if id_list:
            placeholders = ", ".join("?" for _ in id_list)
            base_clauses.append(f"w.id IN ({placeholders})")
            base_params.extend(id_list)

    # Access filter (free / paid)
    if access == "free":
        base_clauses.append("w.price <= 0")
    elif access == "paid":
        base_clauses.append("w.price > 0")

    # Author filter
    if author:
        base_clauses.append("w.author_username = ? COLLATE NOCASE")
        base_params.append(author)

    # Asset code filter (styles or layout)
    if asset:
        base_clauses.append("(w.layout_code = ? OR w.styles_json LIKE ?)")
        base_params.extend([asset, f"%{asset}%"])

    # Search keyword filter
    if q:
        kw = f"%{q}%"
        base_clauses.append(
            "(w.title LIKE ? OR w.subject LIKE ? OR w.notes LIKE ? OR w.author_username LIKE ? OR w.author_name LIKE ? OR w.prompt LIKE ? OR w.styles_json LIKE ? OR w.layout_code LIKE ?)"
        )
        base_params.extend([kw, kw, kw, kw, kw, kw, kw, kw, kw])

    # Scenario matching rule filter
    scenario_param = str(params.get("scenario") or "").strip().lower()
    if scenario_param:
        from .home_scenarios import get_scenario_match_clause_by_key
        sc_clause, sc_params = get_scenario_match_clause_by_key(conn, scenario_param, table_alias="w")
        base_clauses.append(f"({sc_clause})")
        base_params.extend(sc_params)

    where_sql = " AND ".join(base_clauses)
    # V3 stores all images in one canonical work. Feed rows are already the
    # gallery unit; do not join generation mappings or run expensive window
    # rankings to collapse several per-image works.
    cte_sql = f"""
        WITH ranked_works AS (
            SELECT w.*,
                   'work_' || w.id AS batch_id,
                   1 AS batch_rank,
                   1 AS batch_total
            FROM works w
            WHERE {where_sql}
        )
    """

    candidate_filter = "1 = 1"


    # Compute format counts across the current filter scope (before format slicing)
    counts_sql = f"""
        {cte_sql}
        SELECT
            COUNT(*) AS all_cnt,
            SUM(CASE WHEN json_valid(images_json) = 1 AND json_array_length(images_json) = 1 THEN 1 ELSE 0 END) AS single_cnt,
            SUM(CASE WHEN json_valid(images_json) = 1 AND json_array_length(images_json) > 1 THEN 1 ELSE 0 END) AS multi_cnt
        FROM ranked_works
        WHERE {candidate_filter}
    """
    cnt_row = conn.execute(counts_sql, base_params).fetchone()
    total_all = int((cnt_row and cnt_row["all_cnt"]) or 0)
    total_single = int((cnt_row and cnt_row["single_cnt"]) or 0)
    total_multi = int((cnt_row and cnt_row["multi_cnt"]) or 0)
    counts = {
        "all": total_all,
        "single": total_single,
        "multi": total_multi,
    }

    # Format-specific clause
    if fmt == "single":
        fmt_clause = "json_valid(images_json) = 1 AND json_array_length(images_json) = 1"
    elif fmt == "multi":
        fmt_clause = "json_valid(images_json) = 1 AND json_array_length(images_json) > 1"
    else:
        fmt_clause = "1 = 1"

    total_filtered = (
        total_single if fmt == "single" else (total_multi if fmt == "multi" else total_all)
    )

    # Comments by work (for serialization)
    comment_filter, comment_ids = _seed_filter("id", "work_comments")
    comments_by_work: dict[str, list[dict[str, Any]]] = {}
    for cm in conn.execute(
        f"SELECT * FROM work_comments WHERE status = 'published' AND {comment_filter} ORDER BY created_at ASC, id ASC",
        comment_ids,
    ).fetchall():
        comments_by_work.setdefault(cm["work_id"], []).append(
            {
                "id": cm["id"],
                "user": cm["author_username"],
                "name": cm["author_name"],
                "text": cm["text"],
                "time": cm["time_label"] or cm["created_at"],
            }
        )

    # Also read comments from forum_replies via curation_resource_topics
    reply_filter, reply_ids = _seed_filter("fr.id", "forum_replies")
    for fr in conn.execute(
        f"""
        SELECT crt.target_id AS work_id, fr.id, fr.author_username, fr.author_name, fr.text, fr.time_label, fr.created_at
        FROM forum_replies fr
        JOIN curation_resource_topics crt ON crt.topic_id = fr.topic_id AND crt.kind = 'work'
        WHERE fr.status = 'published' AND {reply_filter}
        ORDER BY fr.created_at ASC, fr.id ASC
        """,
        reply_ids,
    ).fetchall():
        work_list = comments_by_work.setdefault(fr["work_id"], [])
        if not any(c["id"] == fr["id"] for c in work_list):
            work_list.append(
                {
                    "id": fr["id"],
                    "user": fr["author_username"],
                    "name": fr["author_name"],
                    "text": fr["text"],
                    "time": fr["time_label"] or fr["created_at"],
                }
            )

    unlocked_set = _get_unlocked_set(conn, current_user)

    # User like & collection target sets for fast lookup
    liked_ids: set[str] = set()
    collected_ids: set[str] = set()
    if current_user:
        uid = int(current_user["id"])
        liked_rows = conn.execute(
            "SELECT target_id FROM interactions WHERE user_id = ? AND target_type = 'work'",
            (uid,),
        ).fetchall()
        liked_ids = {r["target_id"] for r in liked_rows}
        col_rows = conn.execute(
            "SELECT target_id FROM collections WHERE user_id = ? AND bucket = 'works'",
            (uid,),
        ).fetchall()
        collected_ids = {r["target_id"] for r in col_rows}

    # -------------------------------------------------------------
    # Sort Mode 1: "popular" -> Frozen session pagination
    # -------------------------------------------------------------
    if sort_mode == "popular":
        cursor_data = decode_cursor(cursor_str)
        if cursor_data and "s" in cursor_data and "o" in cursor_data:
            session_id = str(cursor_data["s"])
            offset = max(0, int(cursor_data.get("o") or 0))
        else:
            session_id = str(params.get("session_id") or uuid.uuid4().hex[:16])
            offset = 0

        # Retrieve or initialize frozen session
        cur_uid = current_user["id"] if current_user else None
        cur_filter = (fmt, access, asset, author, q)

        if offset > 0 and session_id not in _FEED_POPULAR_SESSIONS:
            return {
                "ok": True,
                "items": [],
                "nextCursor": None,
                "hasMore": False,
                "total": 0,
                "counts": counts,
                "sessionId": session_id,
                "sessionExpired": True,
                "needsRefresh": True,
            }

        sess_data = _FEED_POPULAR_SESSIONS.get(session_id)
        if sess_data:
            ordered_ids = sess_data[0]
            if len(sess_data) >= 4:
                _, _, sess_uid, sess_filter = sess_data
                if sess_uid != cur_uid or sess_filter != cur_filter:
                    if offset > 0:
                        return {
                            "ok": True,
                            "items": [],
                            "nextCursor": None,
                            "hasMore": False,
                            "total": 0,
                            "counts": counts,
                            "sessionId": session_id,
                            "sessionExpired": True,
                            "needsRefresh": True,
                        }
                    else:
                        sess_data = None

        if not sess_data:
            pop_sql = f"""
                {cte_sql}
                SELECT id
                FROM ranked_works
                WHERE {candidate_filter} AND {fmt_clause}
                ORDER BY {WORK_POPULAR_EXPR} DESC, published_at_ms DESC, id DESC
            """
            id_rows = conn.execute(pop_sql, base_params).fetchall()
            ordered_ids = [r["id"] for r in id_rows]
            _FEED_POPULAR_SESSIONS[session_id] = (ordered_ids, time.time(), cur_uid, cur_filter)

        total_session_items = len(ordered_ids)
        page_ids = ordered_ids[offset : offset + limit]
        next_offset = offset + len(page_ids)
        has_more = next_offset < total_session_items
        next_cursor = encode_cursor({"s": session_id, "o": next_offset}) if has_more else None

        if page_ids:
            ph = ", ".join("?" for _ in page_ids)
            work_rows = conn.execute(
                f"""
                {cte_sql}
                SELECT * FROM ranked_works WHERE id IN ({ph})
                """,
                (*base_params, *page_ids),
            ).fetchall()
            row_map = {r["id"]: r for r in work_rows}
            items = []
            for pid in page_ids:
                row = row_map.get(pid)
                if row and is_valid_work_row(row):
                    w_dict = _serialize_work(row, comments_by_work, unlocked_set, current_user, conn=conn)
                    w_dict["liked"] = w_dict["id"] in liked_ids
                    w_dict["collected"] = w_dict["id"] in collected_ids
                    w_dict["batchId"] = row["batch_id"]
                    w_dict["batchTotal"] = int(row["batch_total"])
                    w_dict["batchIndex"] = int(row["batch_rank"])
                    enrich_dimensions(w_dict)
                    items.append(w_dict)
        else:
            items = []

        return {
            "ok": True,
            "items": items,
            "nextCursor": next_cursor,
            "hasMore": has_more,
            "total": total_session_items,
            "counts": counts,
            "sessionId": session_id,
        }

    # -------------------------------------------------------------
    # Sort Mode 2: "newest" (default) -> Stable keyset cursor pagination
    # -------------------------------------------------------------
    query_clauses = [candidate_filter, fmt_clause]
    query_params = list(base_params)

    cursor_data = decode_cursor(cursor_str)
    if cursor_data and "ms" in cursor_data and "id" in cursor_data:
        try:
            last_ms = int(cursor_data["ms"])
            last_id = str(cursor_data["id"])
            query_clauses.append("(published_at_ms < ? OR (published_at_ms = ? AND id < ?))")
            query_params.extend([last_ms, last_ms, last_id])
        except (ValueError, TypeError):
            pass

    fetch_limit = limit + 1
    query_params.append(fetch_limit)
    newest_sql = f"""
        {cte_sql}
        SELECT *
        FROM ranked_works
        WHERE {" AND ".join(query_clauses)}
        ORDER BY published_at_ms DESC, id DESC
        LIMIT ?
    """
    rows = conn.execute(newest_sql, query_params).fetchall()

    if len(rows) > limit:
        has_more = True
        return_rows = rows[:limit]
        last_row = return_rows[-1]
        next_cursor = encode_cursor({"ms": int(last_row["published_at_ms"]), "id": str(last_row["id"])})
    else:
        has_more = False
        return_rows = rows
        next_cursor = None

    items = []
    for row in return_rows:
        if is_valid_work_row(row):
            w_dict = _serialize_work(row, comments_by_work, unlocked_set, current_user, conn=conn)
            w_dict["liked"] = w_dict["id"] in liked_ids
            w_dict["collected"] = w_dict["id"] in collected_ids
            w_dict["batchId"] = row["batch_id"]
            w_dict["batchTotal"] = int(row["batch_total"])
            w_dict["batchIndex"] = int(row["batch_rank"])
            enrich_dimensions(w_dict)
            items.append(w_dict)

    return {
        "ok": True,
        "items": items,
        "nextCursor": next_cursor,
        "hasMore": has_more,
        "total": total_filtered,
        "counts": counts,
    }


def get_work_by_id(
    db: Database,
    work_id: str,
    current_user: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Retrieve single published work by ID with dimensions."""
    conn = db.get_conn()
    wid = str(work_id or "").strip()
    if not wid:
        return None

    seed_clause, seed_params = _seed_filter("id", "works")
    row = conn.execute(
        f"SELECT * FROM works WHERE id = ? AND status = 'published' AND {seed_clause}",
        (wid, *seed_params),
    ).fetchone()
    if not row or not is_valid_work_row(row):
        return None

    unlocked_set = _get_unlocked_set(conn, current_user)
    comment_filter, comment_ids = _seed_filter("id", "work_comments")
    comments = [
        {
            "id": cm["id"],
            "user": cm["author_username"],
            "name": cm["author_name"],
            "text": cm["text"],
            "time": cm["time_label"] or cm["created_at"],
        }
        for cm in conn.execute(
            f"SELECT * FROM work_comments WHERE work_id = ? AND status = 'published' AND {comment_filter} ORDER BY created_at ASC, id ASC",
            (wid, *comment_ids),
        ).fetchall()
    ]
    reply_filter, reply_ids = _seed_filter("fr.id", "forum_replies")
    for fr in conn.execute(
        f"""
        SELECT fr.id, fr.author_username, fr.author_name, fr.text, fr.time_label, fr.created_at
        FROM forum_replies fr
        JOIN curation_resource_topics crt ON crt.topic_id = fr.topic_id AND crt.kind = 'work'
        WHERE crt.target_id = ? AND fr.status = 'published' AND {reply_filter}
        ORDER BY fr.created_at ASC, fr.id ASC
        """,
        (wid, *reply_ids),
    ).fetchall():
        if not any(c["id"] == fr["id"] for c in comments):
            comments.append(
                {
                    "id": fr["id"],
                    "user": fr["author_username"],
                    "name": fr["author_name"],
                    "text": fr["text"],
                    "time": fr["time_label"] or fr["created_at"],
                }
            )

    w_dict = _serialize_work(row, {wid: comments}, unlocked_set, current_user, conn=conn)
    if row["run_id"]:
        # A generated work's ordered canonical media is authoritative; the
        # works.images_json value is only a transactionally maintained feed
        # thumbnail cache, never the source for the full detail response.
        from .generation_v3 import work_images
        w_dict["images"] = work_images(conn, wid)
    # V3: one work already represents the whole generation. There are no
    # sibling per-image works to look up or fold.
    run = conn.execute(
        "SELECT external_run_id FROM generation_runs WHERE id=?",
        (row["run_id"],),
    ).fetchone() if row["run_id"] else None
    w_dict["batchId"] = str(run["external_run_id"]) if run else f"work_{wid}"
    w_dict["batchTotal"] = 1
    w_dict["batchIndex"] = 1

    if current_user:
        uid = int(current_user["id"])
        liked = conn.execute(
            "SELECT 1 FROM interactions WHERE user_id = ? AND target_type = 'work' AND target_id = ?",
            (uid, wid),
        ).fetchone()
        w_dict["liked"] = bool(liked)
        collected = conn.execute(
            "SELECT 1 FROM collections WHERE user_id = ? AND bucket = 'works' AND target_id = ?",
            (uid, wid),
        ).fetchone()
        w_dict["collected"] = bool(collected)
    else:
        w_dict["liked"] = False
        w_dict["collected"] = False

    enrich_dimensions(w_dict)
    return w_dict
