"""Small workspace bootstrap and owner-scoped keyset document summaries."""

from __future__ import annotations

import base64
import json

from .services import ServiceError


def page_articles(db, user, *, cursor="", limit=50):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ServiceError("分页数量无效", status=400, code="invalid_limit")
    boundary = ""
    parameters = [user["id"]]
    if cursor:
        if len(cursor) > 512:
            raise ServiceError("文章分页位置无效", status=400, code="invalid_cursor")
        try:
            stamp, aid = json.loads(
                base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            )
            if type(stamp) is not int or not isinstance(aid, str) or len(aid) > 160:
                raise ValueError
        except (ValueError, TypeError, UnicodeDecodeError) as exc:
            raise ServiceError(
                "文章分页位置无效", status=400, code="invalid_cursor"
            ) from exc
        boundary = " AND (a.updated_at_ms<? OR (a.updated_at_ms=? AND a.id>?))"
        parameters.extend((stamp, stamp, aid))
    rows = (
        db.get_conn()
        .execute(
            """SELECT a.id,a.article_title,a.status,a.run_count,a.created_at_ms,a.updated_at_ms,
                  a.write_seq,a.settings_json,a.style1,a.layout_code,cover.storage_key AS cover_url
           FROM studio_articles a
           LEFT JOIN LATERAL (
             SELECT m.storage_key FROM article_illustrations i JOIN media_assets m ON m.id=i.selected_media_id
             WHERE i.article_id=a.id AND i.deleted_at IS NULL ORDER BY (i.role='cover') DESC,i.sort_order,i.id LIMIT 1
           ) cover ON true
           WHERE a.user_id=? AND a.deleted_at=''"""
            + boundary
            + " ORDER BY a.updated_at_ms DESC,a.id ASC LIMIT ?",
            (*parameters, limit + 1),
        )
        .fetchall()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    items = [
        {
            "id": r["id"],
            "articleTitle": r["article_title"],
            "status": r["status"],
            "runCount": r["run_count"],
            "createdAtMs": r["created_at_ms"],
            "updatedAtMs": r["updated_at_ms"],
            "writeSeq": r["write_seq"],
            "settings": r["settings_json"],
            "style1": r["style1"],
            "layout": r["layout_code"],
            "_summary": True,
            "coverRatio": r["settings_json"].get("coverRatio", "2.35:1"),
            "inlineRatio": r["settings_json"].get("inlineRatio", "4:3"),
            "cards": [{"imageUrl": r["cover_url"], "role": "cover"}]
            if r["cover_url"]
            else [],
        }
        for r in rows
    ]
    after = (
        base64.urlsafe_b64encode(
            json.dumps([rows[-1]["updated_at_ms"], rows[-1]["id"]]).encode()
        )
        .decode()
        .rstrip("=")
        if more
        else ""
    )
    return {"ok": True, "items": items, "nextCursor": after}


def bootstrap_workspace(db, user):
    conn = db.get_conn()
    presets = [
        dict(row)
        for row in conn.execute(
            "SELECT id,title,blueprint,scenario_badge,scenario_desc,sort_order FROM studio_workflows "
            "WHERE is_official_preset=1 AND enabled=1 ORDER BY sort_order"
        ).fetchall()
    ]
    if not user:
        return {
            "loggedIn": False,
            "articles": [],
            "workflows": [],
            "uploads": [],
            "history": [],
            "pendingTasks": [],
            "officialPresets": presets,
        }
    articles = page_articles(db, user)
    pending = [
        {
            "genId": r["id"],
            "taskId": r["task_id"],
            "requestId": r["request_id"],
            "status": r["status"],
            "createdAt": r["created_at"],
            "mode": r["mode"],
            "kind": r["kind"],
        }
        for r in conn.execute(
            "SELECT id,task_id,request_id,status,created_at,mode,kind FROM studio_generations WHERE user_id=? AND deleted_at='' "
            "AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 200",
            (user["id"],),
        ).fetchall()
    ]
    return {
        "loggedIn": True,
        "articles": articles["items"],
        "articleCursor": articles["nextCursor"],
        "pendingTasks": pending,
        "officialPresets": presets,
        "deferredCollections": True,
    }
