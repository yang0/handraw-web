"""Bounded, owner-scoped continuation for Studio documents and executions."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime

from .services import ServiceError


def read_cursor(cursor, kind, limit):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ServiceError("分页数量无效", status=400, code="invalid_limit")
    if not cursor:
        return None
    try:
        if not isinstance(cursor, str) or len(cursor) > 768:
            raise ValueError
        value = json.loads(
            base64.b64decode(
                cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
            )
        )
        if not isinstance(value, list) or len(value) != 3 or value[0] != kind:
            raise ValueError
        stamp, key = value[1:]
        if (
            not isinstance(stamp, str)
            or not 1 <= len(stamp) <= 96
            or not isinstance(key, str)
            or not 1 <= len(key) <= 200
        ):
            raise ValueError
        if kind == "canvases":
            datetime.fromisoformat(stamp)
        return stamp, key
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error) as exc:
        raise ServiceError(
            "分页位置无效，请重新载入", status=400, code="invalid_cursor"
        ) from exc


def next_cursor(kind, rows, limit, field):
    if len(rows) <= limit:
        return ""
    row = rows[limit - 1]
    stamp = row[field]
    if isinstance(stamp, datetime):
        stamp = stamp.isoformat()
    return (
        base64.urlsafe_b64encode(json.dumps([kind, stamp, row["id"]]).encode())
        .decode()
        .rstrip("=")
    )


def page_canvases(db, user, *, cursor="", limit=50):
    after = read_cursor(cursor, "canvases", limit)
    args = [user["id"]]
    boundary = ""
    if after:
        boundary = " AND (updated_at<? OR (updated_at=? AND id>?))"
        args.extend((after[0], after[0], after[1]))
    rows = (
        db.get_conn()
        .execute(
            "SELECT id,name,write_seq,updated_at FROM studio_canvases WHERE user_id=? AND deleted_at IS NULL"
            + boundary
            + " ORDER BY updated_at DESC,id ASC LIMIT ?",
            (*args, limit + 1),
        )
        .fetchall()
    )
    return {
        "ok": True,
        "items": [
            {
                "id": r["id"],
                "name": r["name"],
                "writeSeq": r["write_seq"],
                "updatedAt": r["updated_at"].isoformat(),
            }
            for r in rows[:limit]
        ],
        "nextCursor": next_cursor("canvases", rows, limit, "updated_at"),
    }


def page_history_runs(conn, user_id, *, cursor="", limit=40):
    from .services import _seed_filter

    after = read_cursor(cursor, "history", limit)
    exclusion, seed_args = _seed_filter("g.id", "generations")
    boundary = ""
    args = [user_id, *seed_args]
    if after:
        boundary = " AND (r.created_at,r.id)<(?,?)"
        args.extend(after)
    # Select whole runs before loading their attempts, so a large batch never
    # consumes a window of execution rows and hides older logical batches.
    rows = conn.execute(
        """SELECT r.*,w.id AS work_id FROM generation_runs r
           LEFT JOIN works w ON w.run_id=r.id WHERE r.user_id=? AND (
             r.source<>'web' OR EXISTS (
               SELECT 1 FROM studio_generations g WHERE g.user_id=r.user_id
               AND (g.run_id=r.id OR (g.batch_id<>'' AND g.batch_id=r.external_run_id)
                    OR (g.batch_id='' AND g.id=r.external_run_id))
               AND COALESCE(g.deleted_at,'')='' AND """
        + exclusion
        + """
             ) OR (r.creation_mode='canvas' AND NOT EXISTS (
               SELECT 1 FROM studio_generations g WHERE g.run_id=r.id
             ))
           )"""
        + boundary
        + " ORDER BY r.created_at DESC,r.id DESC LIMIT ?",
        (*args, limit + 1),
    ).fetchall()
    return rows[:limit], next_cursor("history", rows, limit, "created_at")
