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
import urllib.parse

from . import forum_resources
from . import services as S
from .resource_discussions import resolve_resource
from .skill_prompt import strip_bilingual_definition


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


def _resolve_ref_to_topic_id(db: Any, ref: str, user: dict[str, Any] | None = None) -> str | None:
    # Route handlers pass Database; utility callers/tests also pass an open
    # PostgreSQL connection. Both use the same read-only resolution path.
    conn = db.get_conn() if hasattr(db, "get_conn") else db
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
                sub = conn.execute(
                    "SELECT status FROM curation_submissions WHERE topic_id = ?", (ref,)
                ).fetchone()
                if sub and sub["status"] in ("pending", "changes_requested", "approved"):
                    res = True
                else:
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
    else:
        # Fallback 1: check forum_topics.work_id directly
        t_by_w = conn.execute(
            "SELECT id, status FROM forum_topics WHERE work_id = ?", (ref_work,)
        ).fetchone()
        if t_by_w and _is_topic_visible(conn, t_by_w, user):
            return str(t_by_w["id"])

        # Fallback 2: if published work exists, auto-prebuild topic
        w_cur = conn.execute(
            "SELECT * FROM works WHERE id = ? AND status = 'published'", (ref_work,)
        ).fetchone()
        if w_cur:
            from .resource_discussions import ensure_topic
            with db.transaction() as tx:
                tid = ensure_topic(tx, "work", ref_work, dict(w_cur), initial_origin="submission", listed_at_ms=None)
            return tid

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
        if not res:
            sub = conn.execute(
                "SELECT status FROM curation_submissions WHERE topic_id = ?", (m_asset["topic_id"],)
            ).fetchone()
            if sub and sub["status"] in ("pending", "changes_requested", "approved"):
                res = True
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
    topic_id = _resolve_ref_to_topic_id(handler.db, ref, user)
    if not topic_id:
        code = ""
        kind = None
        ref_clean = ref.strip()
        ref_lower = ref_clean.lower()
        if ref_lower.startswith("style-"):
            cand = ref_clean[6:].strip().upper().lstrip("#")
            if resolve_resource(conn, "style", cand, viewer=user, include_pending=True):
                code = cand
                kind = "style"
        elif ref_lower.startswith("layout-"):
            cand = ref_clean[7:].strip().upper().lstrip("#")
            if resolve_resource(conn, "layout", cand, viewer=user, include_pending=True):
                code = cand
                kind = "layout"
        else:
            cand = ref_clean.upper().lstrip("#")
            if resolve_resource(conn, "style", cand, viewer=user, include_pending=True):
                code = cand
                kind = "style"
            elif resolve_resource(conn, "layout", cand, viewer=user, include_pending=True):
                code = cand
                kind = "layout"

        if kind and code:
            res = resolve_resource(conn, kind, code, viewer=user, include_pending=True)
            if res:
                from .resource_discussions import ensure_topic
                with handler.db.transaction() as tx:
                    topic_id = ensure_topic(tx, kind, code, res)

        if not topic_id:
            from .config import DEMO_DIR
            forum_html = DEMO_DIR / "forum.html"
            data = forum_html.read_bytes() if forum_html.is_file() else b"Not Found"
            handler.send_response(404)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.send_header("Cache-Control", "no-cache")
            handler._cors_headers()
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return True

    location = f"/forum/?view=topic&id={topic_id}"
    extra = {}
    if qs and qs.get("focus"):
        focus_vals = qs.get("focus") or []
        if focus_vals and focus_vals[0] == "comment":
            extra["focus"] = "comment"
    if qs and qs.get("panel"):
        panel_vals = qs.get("panel") or []
        if panel_vals and panel_vals[0] == "report":
            extra["panel"] = "report"
    if qs and qs.get("tab"):
        tab_vals = qs.get("tab") or []
        if tab_vals and tab_vals[0] == "comments":
            extra["focus"] = "comment"
        elif tab_vals and tab_vals[0] == "report":
            extra["panel"] = "report"
    if extra:
        location += "&" + urllib.parse.urlencode(extra)

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
    topic_dict = S._serialize_topic(t_row, {}, unlocked_set, user, conn=conn)
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
        if w_row["run_id"] and (not work_res.get("styles") or not work_res.get("layout")):
            from .generation_works import recover_generation_work_assets
            recovered_styles, recovered_layout = recover_generation_work_assets(conn, w_row)
            if not work_res.get("styles"):
                work_res["styles"] = recovered_styles
            if not work_res.get("layout"):
                work_res["layout"] = recovered_layout
        if w_row["run_id"]:
            from .generation_v3 import work_images
            work_res["images"] = work_images(conn, m_target)
            from .generation_works import generation_image_assets
            work_res["imageAssets"] = generation_image_assets(conn, w_row, work_res["images"])
            if w_row["cover_media_id"]:
                cover = conn.execute(
                    "SELECT storage_key FROM media_assets WHERE id=?",
                    (w_row["cover_media_id"],),
                ).fetchone()
                work_res["coverUrl"] = str(cover["storage_key"]) if cover else ""
        w_likes = int(w_row["likes"] or 0)
        w_favorites = int(w_row["favorites"] or 0)
        w_forks = int(w_row["forks"] or 0)
        work_res["likes"] = w_likes
        work_res["favorites"] = w_favorites
        work_res["forks"] = w_forks

        # A generated work contains all its media; never create a separate
        # related-work rail for images from the same run.
        work_res["batchWorks"] = []

        mount = {
            "kind": "work",
            "work": work_res,
        }
        topic_dict["likes"] = w_likes
        topic_dict["favorites"] = w_favorites
        topic_dict["tips"] = int(w_row["tips"] or 0)
        topic_dict["workId"] = m_target
    elif mapping["kind"] in ("style", "layout"):
        m_kind = str(mapping["kind"])
        code = str(mapping["target_id"]).strip().upper().lstrip("#")
        raw = resolve_resource(conn, m_kind, code, viewer=user, include_pending=True)
        if not raw:
            sub = conn.execute(
                "SELECT status FROM curation_submissions WHERE topic_id = ?", (topic_id,)
            ).fetchone()
            if sub and sub["status"] in ("pending", "changes_requested", "approved"):
                mount = {"kind": "discussion"}
            else:
                raise S.ServiceError("关联资源不存在或不可见", status=404)
        else:
            if "code" in raw:
                asset_res = forum_resources._asset_resource(raw, unlocked_set, user)
            else:
                asset_res = forum_resources._static_resource(raw, m_kind)

            res_likes, res_favorites = _get_asset_social_metrics(conn, code)

            image = asset_res.get("image") or ""
            examples = []
            sub_row = conn.execute(
                "SELECT id, current_revision FROM curation_submissions WHERE kind = ? AND UPPER(target_id) = ? ORDER BY id DESC LIMIT 1",
                (m_kind, code),
            ).fetchone()
            if sub_row:
                v_row = conn.execute(
                    "SELECT payload_json FROM curation_versions WHERE submission_id = ? AND revision = ?",
                    (sub_row["id"], sub_row["current_revision"]),
                ).fetchone()
                if v_row:
                    try:
                        p_data = json.loads(v_row["payload_json"] or "{}")
                        from .curation import cover_of, examples_of
                        c = cover_of(p_data)
                        if c:
                            image = c
                        examples = examples_of(p_data) or []
                    except Exception:
                        pass

            a_row = conn.execute(
                "SELECT cheers, tips, stamp_counts_json, author_username, author_name, source_type FROM catalog_assets WHERE code = ? OR UPPER(code) = ?",
                (code, code),
            ).fetchone()
            if a_row:
                res_cheers = int(a_row["cheers"] or 0)
                res_tips = int(a_row["tips"] or 0)
                stamp_counts_raw = json.loads(a_row["stamp_counts_json"] or "{}")
                source_type = a_row["source_type"] or asset_res.get("sourceType") or ""
                author_username = a_row["author_username"] or asset_res.get("author") or ""
                author_name = a_row["author_name"] or asset_res.get("authorName") or ""
                if source_type in ("official", "exclusive"):
                    tip_row = conn.execute(
                        "SELECT COALESCE(SUM(delta), 0) AS total FROM ledgers WHERE ref_type = 'asset' AND (ref_id = ? OR UPPER(ref_id) = ?) AND kind = 'tip_official_in'",
                        (code, code),
                    ).fetchone()
                    if tip_row:
                        res_tips = max(res_tips, int(tip_row["total"] or 0))
            else:
                total_cheers_row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM interactions WHERE target_type = 'asset' AND (target_id = ? OR UPPER(target_id) = ?) AND stamp_label = ''",
                    (code, code),
                ).fetchone()
                res_cheers = int(total_cheers_row["cnt"] if total_cheers_row else 0)
                tip_row = conn.execute(
                    "SELECT COALESCE(SUM(delta), 0) AS total FROM ledgers WHERE ref_type = 'asset' AND (ref_id = ? OR UPPER(ref_id) = ?) AND kind = 'tip_official_in'",
                    (code, code),
                ).fetchone()
                res_tips = int(tip_row["total"] if tip_row else 0)
                stamp_rows = conn.execute(
                    "SELECT stamp_label, COUNT(*) AS cnt FROM interactions WHERE target_type = 'asset' AND (target_id = ? OR UPPER(target_id) = ?) AND stamp_label <> '' GROUP BY stamp_label",
                    (code, code),
                ).fetchall()
                stamp_counts_raw = {r["stamp_label"]: int(r["cnt"]) for r in stamp_rows}
                source_type = asset_res.get("sourceType") or raw.get("source_type") or "official"
                author_username = asset_res.get("author") or ""
                author_name = asset_res.get("authorName") or ""

            stamp_counts = {
                "超实用配方": int(stamp_counts_raw.get("超实用配方", 0)),
                "审美在线": int(stamp_counts_raw.get("审美在线", 0)),
            }

            mount = {
                "kind": m_kind,
                "resource": {
                    "code": code,
                    "name": asset_res.get("name") or asset_res.get("title") or code,
                    "image": image,
                    "examples": examples,
                    "description": asset_res.get("description") or "",
                    "definition": (
                        ""
                        if (forum_resources._FILTER_BLACKBOX in (asset_res.get("definition") or "") or (asset_res.get("definition") or "").startswith("[LOCKED_ASSET::"))
                        else (
                            strip_bilingual_definition(asset_res.get("definition") or "")
                            if m_kind == "layout"
                            else (asset_res.get("definition") or "")
                        )
                    ),
                    "unlocked": bool(asset_res.get("unlocked")),
                    "unlockCost": int(asset_res.get("unlockCost") or 0),
                    "sourceType": source_type,
                    "status": asset_res.get("status") or raw.get("status") or "published",
                    "pending": bool(asset_res.get("pending") or raw.get("pending")),
                    "author": author_username,
                    "authorName": author_name,
                    "useUrl": f"/studio/?{m_kind}={code}",
                    "likes": res_likes,
                    "favorites": res_favorites,
                    "cheers": res_cheers,
                    "stampCounts": stamp_counts,
                    "tips": res_tips,
                },
            }
            topic_dict["likes"] = res_likes
            topic_dict["favorites"] = res_favorites
    else:
        mount = {"kind": "discussion"}

    # Viewer state (liked, favorited, stamps per mount kind)
    viewer_stamps: list[str] = []
    if user:
        uid = int(user["id"])
        if mapping and mapping["kind"] in ("style", "layout"):
            m_code = str(mapping["target_id"]).strip().upper().lstrip("#")
            v_rows = conn.execute(
                "SELECT stamp_label FROM interactions WHERE user_id = ? AND target_type = 'asset' AND (target_id = ? OR UPPER(target_id) = ?)",
                (uid, m_code, m_code),
            ).fetchall()
            viewer_stamps = [r["stamp_label"] for r in v_rows]
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

    if mount.get("resource"):
        mount["resource"]["viewerStamps"] = viewer_stamps

    handler._send_json({
        "ok": True,
        "topic": topic_dict,
        "mount": mount,
        "viewer": {
            "liked": liked,
            "favorited": favorited,
            "stamps": viewer_stamps,
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
        res = resolve_resource(conn, mapping["kind"], mapping["target_id"],
                               viewer=user, include_pending=True)
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
            "text": S.sanitize_plain_text(r["text"] or ""),
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
