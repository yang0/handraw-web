"""Skill/Web v1 API: private resources, imported generations and shared social actions.

The website is the authority for account ownership, resource revisions and
published work. Local Skill uploads never create a public work implicitly.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageFile

from .config import get_generated_dir
from .db import utc_now_iso
from .runtime_policy import decode_data_image_url
from .services import ServiceError

logger = logging.getLogger("handraw.skill_cloud")
MAX_RESOURCE_TEXT = 30000
MAX_REQUEST_TEXT = 60000
MAX_RUN_IMAGES = 12
MAX_TOTAL_PRIVATE_BYTES = 1024 * 1024 * 1024
UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
WORK_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def _user(handler: Any) -> dict[str, Any]:
    user = handler._current_user(required=True)
    if user.get("_auth_kind") == "token":
        from .user_library import check_token_rate_limit
        if not check_token_rate_limit(str(user.get("_token_id") or user["id"])):
            raise ServiceError("请求过于频繁", status=429, code="rate_limited")
    return user


def _uuid(value: Any) -> str:
    try:
        raw = str(value)
        if not UUID_RE.fullmatch(raw):
            raise ValueError()
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError, TypeError):
        raise ServiceError("ID 必须是标准 UUID", status=400, code="invalid_id") from None


def _query(qs: dict, key: str, default: str = "") -> str:
    val = qs.get(key)
    if isinstance(val, list):
        return str(val[0] if val else default)
    return str(val if val is not None else default)


def _limit(qs: dict, default: int = 100) -> int:
    try:
        return max(1, min(200, int(_query(qs, "limit", str(default)))))
    except ValueError:
        raise ServiceError("分页 limit 无效", status=400, code="invalid_limit") from None


def _json_value(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return fallback


def _seq(conn: Any) -> int:
    conn.execute("UPDATE skill_resource_change_counter SET next_seq=next_seq+1 WHERE id=1")
    return int(conn.execute("SELECT next_seq FROM skill_resource_change_counter WHERE id=1").fetchone()[0])


def _resource(row: Any, *, include_definition: bool = True) -> dict:
    item = {
        "id": row["id"], "kind": row["kind"], "name": row["name"],
        "license": row["license"], "examples": _json_value(row["examples_json"], []),
        "version": row["version"], "origin": _json_value(row["origin_json"], None),
        "visibility": "private", "schemaVersion": 1,
        "revision": int(row["revision"]), "changeSeq": int(row["change_seq"]),
        "updatedAt": row["updated_at"], "deletedAt": row["deleted_at"],
    }
    if include_definition and not row["deleted_at"]:
        item["definition"] = _json_value(row["definition_json"], {})
    return item


def _resource_input(body: dict) -> dict:
    if body.get("visibility", "private") != "private":
        raise ServiceError("个人资源同步只能是私有", status=400, code="private_only")
    kind = str(body.get("kind") or "")
    if kind not in ("style", "layout"):
        raise ServiceError("仅支持个人画风与图型", status=400, code="invalid_kind")
    name = str(body.get("name") or "").strip()
    if not 1 <= len(name) <= 120:
        raise ServiceError("资源名称长度应为 1–120", status=400, code="invalid_name")
    definition = body.get("definition")
    if not isinstance(definition, dict):
        raise ServiceError("缺少资源定义", status=400, code="invalid_definition")
    zh, en = definition.get("zh"), definition.get("en")
    if not all(isinstance(v, str) and 1 <= len(v.strip()) <= MAX_RESOURCE_TEXT for v in (zh, en)):
        raise ServiceError("需要有效中英文画风或图型定义", status=400, code="invalid_definition")
    license_text = str(body.get("license") or "").strip()
    if not 1 <= len(license_text) <= 1000:
        raise ServiceError("缺少授权说明", status=400, code="invalid_license")
    examples = body.get("examples", [])
    if not isinstance(examples, list) or len(examples) > 12 or any(
        not isinstance(x, str) or len(x) > 2000 for x in examples
    ):
        raise ServiceError("示例格式无效", status=400, code="invalid_examples")
    origin = body.get("origin")
    if origin is not None and (not isinstance(origin, dict) or len(json.dumps(origin, ensure_ascii=False)) > 5000):
        raise ServiceError("来源格式无效", status=400, code="invalid_origin")
    version = str(body.get("version") or "1.0.0")
    if not re.fullmatch(r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}(?:[-+][A-Za-z0-9.-]{1,40})?", version):
        raise ServiceError("版本格式无效", status=400, code="invalid_version")
    if body.get("schemaVersion", 1) != 1:
        raise ServiceError("资源 schemaVersion 不支持", status=400, code="invalid_schema_version")
    return {
        "kind": kind, "name": name, "definition_json": json.dumps({"zh": zh, "en": en}, ensure_ascii=False),
        "license": license_text, "examples_json": json.dumps(examples, ensure_ascii=False),
        "origin_json": json.dumps(origin, ensure_ascii=False), "version": version,
    }


def put_resource(db: Any, user: dict, resource_id: str, body: dict) -> dict:
    rid = _uuid(resource_id)
    if body.get("id") and _uuid(body["id"]) != rid:
        raise ServiceError("资源 ID 不一致", status=400, code="id_mismatch")
    fields = _resource_input(body)
    uid = int(user["id"])
    now = utc_now_iso()
    with db.transaction() as tx:
        row = tx.execute("SELECT * FROM skill_personal_resources WHERE id=?", (rid,)).fetchone()
        if row and int(row["user_id"]) != uid:
            raise ServiceError("资源不存在", status=404, code="not_found")
        if row:
            if row["deleted_at"]:
                raise ServiceError("资源已删除", status=409, code="deleted",
                                   extra={"current": _resource(row, include_definition=False)})
            try:
                base = int(body["baseRevision"])
            except (KeyError, ValueError, TypeError):
                raise ServiceError("更新必须提供 baseRevision", status=400, code="base_revision_required") from None
            if base != int(row["revision"]):
                raise ServiceError("资源版本冲突", status=409, code="conflict",
                                   extra={"current": _resource(row)})
            rev = base + 1
            seq = _seq(tx)
            tx.execute(
                """UPDATE skill_personal_resources SET kind=?,name=?,definition_json=?,
                license=?,examples_json=?,version=?,origin_json=?,revision=?,
                change_seq=?,updated_at=? WHERE id=? AND user_id=?""",
                (fields["kind"], fields["name"], fields["definition_json"],
                 fields["license"], fields["examples_json"], fields["version"],
                 fields["origin_json"], rev, seq, now, rid, uid),
            )
        else:
            if body.get("baseRevision") not in (None, 0):
                raise ServiceError("新建资源的版本错误", status=409, code="conflict")
            seq = _seq(tx)
            tx.execute(
                """INSERT INTO skill_personal_resources
                (id,user_id,kind,name,definition_json,license,examples_json,version,
                 origin_json,visibility,revision,change_seq,deleted_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,'private',1,?,NULL,?,?)""",
                (rid, uid, fields["kind"], fields["name"], fields["definition_json"],
                 fields["license"], fields["examples_json"], fields["version"],
                 fields["origin_json"], seq, now, now),
            )
        saved = tx.execute("SELECT * FROM skill_personal_resources WHERE id=? AND user_id=?",
                           (rid, uid)).fetchone()
    return {"ok": True, "resource": _resource(saved)}


def list_resources(db: Any, user: dict, qs: dict) -> dict:
    limit = _limit(qs)
    cursor_raw = _query(qs, "since", "")
    try:
        cursor = int(cursor_raw) if cursor_raw else 0
        if cursor < 0:
            raise ValueError()
    except ValueError:
        raise ServiceError("资源游标无效", status=400, code="invalid_cursor") from None
    has_since = bool(cursor_raw)
    rows = db.get_conn().execute(
        """SELECT * FROM skill_personal_resources
           WHERE user_id=? AND change_seq>? AND (? OR deleted_at IS NULL)
           ORDER BY change_seq,id LIMIT ?""",
        (int(user["id"]), cursor, int(has_since), limit + 1),
    ).fetchall()
    values = rows[:limit]
    return {"ok": True, "items": [_resource(row) for row in values],
            "hasMore": len(rows) > limit,
            "nextCursor": str(values[-1]["change_seq"]) if values else str(cursor)}


def delete_resource(db: Any, user: dict, rid: str, qs: dict) -> dict:
    rid = _uuid(rid)
    try:
        revision = int(_query(qs, "baseRevision"))
    except ValueError:
        raise ServiceError("删除必须传 baseRevision", status=400, code="base_revision_required") from None
    with db.transaction() as tx:
        row = tx.execute("SELECT * FROM skill_personal_resources WHERE id=? AND user_id=?",
                         (rid, int(user["id"]))).fetchone()
        if not row:
            raise ServiceError("资源不存在", status=404, code="not_found")
        if revision != int(row["revision"]):
            raise ServiceError("版本冲突", status=409, code="conflict",
                               extra={"current": _resource(row)})
        if row["deleted_at"]:
            return {"ok": True, "resource": _resource(row, include_definition=False)}
        now = utc_now_iso()
        tx.execute(
            """UPDATE skill_personal_resources SET deleted_at=?,revision=revision+1,
               change_seq=?,updated_at=? WHERE id=?""",
            (now, _seq(tx), now, rid),
        )
        item = tx.execute("SELECT * FROM skill_personal_resources WHERE id=?", (rid,)).fetchone()
    return {"ok": True, "resource": _resource(item, include_definition=False)}


def collection_items(db: Any, user: dict) -> dict:
    from .services import build_skill_library_payload
    data = build_skill_library_payload(db, user)
    result = []
    for section in ("collected", "owned", "official"):
        for item in data.get(section, []):
            eligible = bool(item.get("unlocked") and item.get("content_url"))
            result.append({**item, "section": section, "syncEligible": eligible})
    # Personal resources are visible only to their creator, not part of public
    # collections and do not grant ownership of third-party content.
    return {"ok": True, "items": result, "hasMore": False}


def download_resource(db: Any, user: dict, rid: str) -> dict:
    try:
        uid = _uuid(rid)
    except ServiceError:
        uid = None
    if uid:
        row = db.get_conn().execute(
            "SELECT * FROM skill_personal_resources WHERE id=? AND user_id=? AND deleted_at IS NULL",
            (uid, int(user["id"])),
        ).fetchone()
        if not row:
            raise ServiceError("资源不存在", status=404, code="not_found")
        record = _resource(row)
        return {"ok": True, "resource": record, "sha256": hashlib.sha256(
            json.dumps(record["definition"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
    # Legacy catalog licensing decisions remain in the existing resolver.
    from .services import build_skill_asset_content
    result = build_skill_asset_content(db, user, rid)
    return {"ok": True, **result}


def _validate_image(item: Any) -> tuple[bytes, str, str, str]:
    if not isinstance(item, dict):
        raise ServiceError("图片数据格式无效", status=400, code="invalid_image")
    try:
        raw, ext, mime = decode_data_image_url(str(item.get("dataUrl") or ""))
        with Image.open(io.BytesIO(raw)) as img:
            if img.width * img.height > 40_000_000:
                raise ValueError("图片像素超过限制")
            img.verify()
    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ServiceError("图片无效或过大", status=400, code="invalid_image") from None
    digest = hashlib.sha256(raw).hexdigest()
    if str(item.get("sha256") or "").lower() != digest:
        raise ServiceError("图片 SHA256 校验失败", status=400, code="sha256_mismatch")
    name = str(item.get("name") or "image" + ext)
    if len(name) > 120 or "/" in name or "\\" in name or any(ord(ch) < 32 for ch in name):
        raise ServiceError("图片名称无效", status=400, code="invalid_image_name")
    return raw, ext, mime, digest


def _generation_row(db: Any, row: Any) -> dict:
    media = db.get_conn().execute(
        "SELECT * FROM skill_generation_media WHERE run_id=? ORDER BY position", (row["id"],)
    ).fetchall()
    return {
        "id": row["id"], "externalRunId": row["external_run_id"],
        "originClient": "skill", "visibility": "private", "status": row["status"],
        "originalRequest": row["original_request"], "createdAt": row["created_at"],
        "images": [{"id": m["id"], "name": m["file_name"], "sha256": m["sha256"],
                    "url": m["media_url"], "bytes": m["bytes"]} for m in media],
    }


def import_generation(db: Any, user: dict, body: dict) -> dict:
    external = _uuid(body.get("externalRunId"))
    if (body.get("visibility") != "private" or body.get("originClient") != "skill"
            or body.get("status") != "success"):
        raise ServiceError("Skill 历史只能私有保存已完成的任务", status=400, code="invalid_generation")
    original = body.get("originalRequest")
    if not isinstance(original, str) or not 1 <= len(original.strip()) <= MAX_REQUEST_TEXT:
        raise ServiceError("原始指令无效", status=400, code="invalid_prompt")
    images = body.get("images")
    if not isinstance(images, list) or not 1 <= len(images) <= MAX_RUN_IMAGES:
        raise ServiceError("图片数量应为 1–12", status=400, code="invalid_images")
    verified = [_validate_image(item) for item in images]
    request_digest = hashlib.sha256(json.dumps({
        "externalRunId": external, "originalRequest": original,
        "images": [(str(i.get("name") or ""), v[3]) for i, v in zip(images, verified)],
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    uid = int(user["id"])
    existing = db.get_conn().execute(
        "SELECT * FROM skill_generation_runs WHERE user_id=? AND external_run_id=?",
        (uid, external),
    ).fetchone()
    if existing:
        if existing["request_hash"] != request_digest:
            raise ServiceError("历史 ID 的内容与已保存记录不一致", status=409, code="conflict")
        return {"ok": True, "id": existing["id"], "visibility": "private", "deduped": True}
    total_new = sum(len(x[0]) for x in verified)
    used = db.get_conn().execute(
        "SELECT COALESCE(SUM(bytes),0) FROM skill_generation_media WHERE user_id=?", (uid,)
    ).fetchone()[0]
    if int(used) + total_new > MAX_TOTAL_PRIVATE_BYTES:
        raise ServiceError("私有生图历史存储超过容量上限", status=413, code="quota_exceeded")
    from .config import get_generated_dir
    target_dir = get_generated_dir()
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    saved_paths: list[Path] = []
    records = []
    try:
        for idx, (item, (raw, ext, mime, digest)) in enumerate(zip(images, verified)):
            file_name = "skill_" + uuid.uuid4().hex + ext
            target = target_dir / file_name
            with target.open("xb") as fd:
                os.chmod(target, 0o600)
                fd.write(raw)
            saved_paths.append(target)
            records.append((str(uuid.uuid4()), run_id, uid, "/generated/" + file_name,
                            str(item.get("name") or "image" + ext), str(target),
                            mime, digest, len(raw), idx, utc_now_iso()))
        with db.transaction() as tx:
            prior = tx.execute(
                "SELECT * FROM skill_generation_runs WHERE user_id=? AND external_run_id=?",
                (uid, external),
            ).fetchone()
            if prior:
                if prior["request_hash"] != request_digest:
                    raise ServiceError("历史 ID 冲突", status=409, code="conflict")
                run_id = prior["id"]
                deduped = True
            else:
                tx.execute(
                    """INSERT INTO skill_generation_runs
                       (id,user_id,external_run_id,origin_client,status,original_request,
                        request_hash,created_at)
                       VALUES (?,?,?,'skill','success',?,?,?)""",
                    (run_id, uid, external, original, request_digest, utc_now_iso()),
                )
                tx.executemany(
                    """INSERT INTO skill_generation_media
                       (id,run_id,user_id,media_url,file_name,file_path,
                        content_type,sha256,bytes,position,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    records,
                )
                deduped = False
        if deduped:
            for p in saved_paths:
                p.unlink(missing_ok=True)
        return {"ok": True, "id": run_id, "visibility": "private", "deduped": deduped}
    except Exception:
        for p in saved_paths:
            p.unlink(missing_ok=True)
        raise


def list_generations(db: Any, user: dict, qs: dict) -> dict:
    # Use a simple stable pair cursor across both stores (no private media
    # bodies or original bytes in the response).
    limit = _limit(qs, default=50)
    cursor = _query(qs, "cursor", "")
    uid = int(user["id"])
    conn = db.get_conn()
    cursor_time, sep, cursor_id = cursor.partition("::")
    if cursor and (not sep or not cursor_time or not WORK_RE.fullmatch(cursor_id)
                   or len(cursor_time) > 48 or any(c not in "0123456789-:TZ+." for c in cursor_time)):
        raise ServiceError("历史分页游标无效", status=400, code="invalid_cursor")
    predicate = " AND (created_at<? OR (created_at=? AND id<?))" if cursor else ""
    params = ((uid, cursor_time, cursor_time, cursor_id,
               uid, cursor_time, cursor_time, cursor_id, limit + 1)
              if cursor else (uid, uid, limit + 1))
    rows = conn.execute(
        """SELECT 'skill' AS origin, id, created_at FROM skill_generation_runs WHERE user_id=?"""
        + predicate
        + """ UNION ALL SELECT 'web' AS origin, id, created_at FROM studio_generations
              WHERE user_id=? AND COALESCE(deleted_at,'')=''"""
        + predicate
        + " ORDER BY created_at DESC,id DESC LIMIT ?",
        params,
    ).fetchall()
    page = rows[:limit]
    result = []
    for row in page:
        if row["origin"] == "skill":
            data = conn.execute("SELECT * FROM skill_generation_runs WHERE id=? AND user_id=?",
                                (row["id"], uid)).fetchone()
            result.append(_generation_row(db, data))
        else:
            data = conn.execute("SELECT * FROM studio_generations WHERE id=? AND user_id=?",
                                (row["id"], uid)).fetchone()
            result.append({
                "id": data["id"], "originClient": "web",
                "visibility": data["visibility"] if "visibility" in data.keys() else "private",
                "status": data["status"], "createdAt": data["created_at"],
                "images": _json_value(data["items_json"], []),
            })
    return {
        "ok": True, "items": result, "hasMore": len(rows) > limit,
        "nextCursor": (page[-1]["created_at"] + "::" + page[-1]["id"]) if page else cursor,
    }


def social_like(db: Any, user: dict, wid: str, body: dict) -> dict:
    from .services import toggle_user_like
    if "liked" not in body or not isinstance(body["liked"], bool):
        raise ServiceError("liked 必须为布尔值", status=400, code="invalid_liked")
    return toggle_user_like(db, user, "work", wid, action="set" if body["liked"] else "unset")


def social_comment(db: Any, user: dict, wid: str, body: dict) -> dict:
    """Create one domain comment per requestId, including concurrent retries.

    A pending request is durable and never replayed blindly after a crash:
    consumers receive outcome_uncertain and must reconcile instead.
    """
    from .services import add_comment_to_work
    content = str(body.get("text") or "").strip()
    if not 1 <= len(content) <= 3000:
        raise ServiceError("评论长度应为 1–3000", status=400, code="invalid_comment")
    request_id = str(body.get("requestId") or "")
    if not request_id or len(request_id) > 120 or not re.fullmatch(r"[A-Za-z0-9_-]+", request_id):
        raise ServiceError("评论需要幂等 requestId", status=400, code="invalid_request_id")
    uid = int(user["id"])
    body_hash = hashlib.sha256((wid + "\n" + content).encode()).hexdigest()
    # Reservation has a database unique key, not just a per-process mutex.
    with db.transaction() as tx:
        row = tx.execute(
            "SELECT * FROM skill_comment_requests WHERE user_id=? AND request_id=?",
            (uid, request_id),
        ).fetchone()
        if row:
            if row["work_id"] != wid or row["body_hash"] != body_hash:
                raise ServiceError("评论幂等键已用于不同内容", status=409, code="conflict")
            if not row["reply_id"]:
                raise ServiceError("评论提交结果待核实，禁止重复发送", status=409,
                                   code="outcome_uncertain")
            return {"ok": True, "replyId": row["reply_id"], "deduped": True}
        tx.execute(
            """INSERT INTO skill_comment_requests
               (user_id,request_id,work_id,body_hash,reply_id,created_at)
               VALUES(?,?,?,?,?,?)""",
            (uid, request_id, wid, body_hash, "", utc_now_iso()),
        )
    try:
        result = add_comment_to_work(db, user, wid, content)
    except ServiceError:
        # Domain validation failed before the comment committed: release the
        # reservation so the user can correct it and retry.
        with db.transaction() as tx:
            tx.execute(
                "DELETE FROM skill_comment_requests WHERE user_id=? AND request_id=? AND reply_id=''",
                (uid, request_id),
            )
        raise
    except Exception:
        # A backend failure could have happened after the reply committed.
        # Keep the reservation to avoid duplicating an already-visible reply.
        logger.exception("Skill comment result uncertain (requestId suppressed)")
        raise ServiceError("评论提交结果待核实，请在网站确认", status=409,
                           code="outcome_uncertain") from None
    with db.transaction() as tx:
        tx.execute(
            "UPDATE skill_comment_requests SET reply_id=? WHERE user_id=? AND request_id=?",
            (result["replyId"], uid, request_id),
        )
    return result

def handle_get(handler: Any, path: str, qs: dict) -> bool:
    if path == "/api/v1/me/resources":
        handler._send_json(list_resources(handler.db, _user(handler), qs)); return True
    if path == "/api/v1/me/collection-items":
        handler._send_json(collection_items(handler.db, _user(handler))); return True
    m = re.fullmatch(r"/api/v1/resources/([^/]+)/download", path)
    if m:
        handler._send_json(download_resource(handler.db, _user(handler), m.group(1))); return True
    if path == "/api/v1/me/generations":
        handler._send_json(list_generations(handler.db, _user(handler), qs)); return True
    if path == "/api/v1/me/notifications":
        from .features import list_notifications
        user = _user(handler)
        try:
            before = max(0, int(_query(qs, "before", "0")))
        except ValueError:
            raise ServiceError("通知游标无效", status=400, code="invalid_cursor") from None
        handler._send_json(list_notifications(handler.db, user, before)); return True
    m = re.fullmatch(r"/api/v1/works/([^/]+)/comments", path)
    if m:
        from .works_feed import get_work_by_id
        wid = m.group(1)
        if not WORK_RE.fullmatch(wid):
            raise ServiceError("作品 ID 无效", status=400, code="invalid_work_id")
        work = get_work_by_id(handler.db, wid, current_user=None)
        if not work:
            raise ServiceError("作品不存在", status=404, code="work_not_found")
        handler._send_json({"ok": True, "id": wid, "comments": work.get("comments", [])})
        return True
    return False


def handle_put(handler: Any, path: str, body: dict) -> bool:
    m = re.fullmatch(r"/api/v1/me/resources/([^/]+)", path)
    if not m:
        return False
    handler._send_json(put_resource(handler.db, _user(handler), m.group(1), body))
    return True


def handle_delete(handler: Any, path: str, qs: dict) -> bool:
    m = re.fullmatch(r"/api/v1/me/resources/([^/]+)", path)
    if not m:
        return False
    handler._send_json(delete_resource(handler.db, _user(handler), m.group(1), qs))
    return True


def handle_post(handler: Any, path: str, body: dict) -> bool:
    if path == "/api/v1/me/generations":
        handler._send_json(import_generation(handler.db, _user(handler), body)); return True
    m = re.fullmatch(r"/api/v1/works/([^/]+)/(likes|comments)", path)
    if m:
        wid, action = m.groups()
        if not WORK_RE.fullmatch(wid):
            raise ServiceError("作品 ID 无效", status=400, code="invalid_work_id")
        user = _user(handler)
        result = (social_like(handler.db, user, wid, body) if action == "likes" else
                  social_comment(handler.db, user, wid, body))
        handler._send_json(result)
        return True
    return False
