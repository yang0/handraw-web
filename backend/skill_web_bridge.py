"""Skill/Web v1: private resources, private Skill history and scoped social APIs.

Server-side contract for handraw-style/skills/handraw-cloud/scripts/handraw_cloud.py.
This module never publishes uploaded generations or private definitions.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import uuid
from typing import Any

from .db import utc_now_iso
from .services import ServiceError

from .skill_web_schema import SKILL_WEB_MIGRATIONS


def _limit(qs: dict[str, list[str]], default: int = 100) -> int:
    try:
        return max(1, min(200, int((qs.get("limit") or [str(default)])[0])))
    except (TypeError, ValueError):
        raise ServiceError("limit 参数无效", status=400, code="invalid_limit") from None


def _uuid(value: Any) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ServiceError("资源 ID 必须是 UUID", status=400, code="invalid_id") from None


def _user(handler: Any) -> dict[str, Any]:
    user = handler._current_user(required=True)
    if user.get("_auth_kind") == "token":
        from .user_library import check_token_rate_limit
        token_key = str(user.get("_token_id") or user.get("id"))
        if not check_token_rate_limit(token_key):
            raise ServiceError("客户端请求过于频繁", status=429, code="rate_limited")
    return user


def _one(qs: dict[str, list[str]], key: str, default: str = "") -> str:
    return str((qs.get(key) or [default])[0] or default)


def _resource(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "kind": row["kind"], "name": row["name"],
        "definition": json.loads(row["definition_json"]),
        "license": row["license"],
        "examples": json.loads(row["examples_json"]),
        "version": row["version"], "origin": json.loads(row["origin_json"]),
        "visibility": row["visibility"], "schemaVersion": int(row["schema_version"]),
        "revision": int(row["revision"]), "deletedAt": row["deleted_at"],
        "updatedAt": row["updated_at"],
    }


def put_resource(db: Any, user: dict[str, Any], rid: str, body: dict[str, Any]) -> dict[str, Any]:
    rid = _uuid(rid)
    uid = int(user["id"])
    if body.get("id") and _uuid(body["id"]) != rid:
        raise ServiceError("资源 ID 不一致", status=400, code="id_mismatch")
    if body.get("visibility", "private") != "private":
        raise ServiceError("个人资源同步只支持私有状态", status=403, code="private_only")
    if body.get("kind") not in ("style", "layout"):
        raise ServiceError("仅支持画风和图型", status=400, code="invalid_kind")
    name = body.get("name")
    definition = body.get("definition")
    license_text = body.get("license")
    examples = body.get("examples", [])
    origin = body.get("origin")
    if (not isinstance(name, str) or not name.strip() or len(name) > 120
            or not isinstance(license_text, str) or not license_text.strip() or len(license_text) > 2000):
        raise ServiceError("资源名称或许可无效", status=400, code="invalid_resource")
    if (not isinstance(definition, dict)
            or not all(isinstance(definition.get(lang), str)
                       and 0 < len(definition[lang].strip()) <= 16000 for lang in ("zh", "en"))):
        raise ServiceError("缺少有效中英文资源定义", status=400, code="invalid_definition")
    if not isinstance(examples, list) or len(examples) > 24 or not all(isinstance(v, str) and len(v) <= 1500 for v in examples):
        raise ServiceError("示例格式无效", status=400, code="invalid_examples")
    if origin is not None and not isinstance(origin, dict):
        raise ServiceError("来源格式无效", status=400, code="invalid_origin")
    version = str(body.get("version") or "1.0.0")
    if len(version) > 50:
        raise ServiceError("版本号过长", status=400, code="invalid_version")
    if body.get("schemaVersion", 1) != 1:
        raise ServiceError("不支持的资源结构版本", status=400, code="unsupported_schema")
    normalized = (body["kind"], name.strip(), json.dumps(definition, ensure_ascii=False, sort_keys=True),
                  license_text.strip(), json.dumps(examples, ensure_ascii=False),
                  version, json.dumps(origin, ensure_ascii=False, sort_keys=True))
    now = utc_now_iso()
    with db.transaction() as tx:
        foreign = tx.execute("SELECT user_id FROM skill_personal_resources WHERE id=?", (rid,)).fetchone()
        if foreign and int(foreign["user_id"]) != uid:
            raise ServiceError("资源不存在", status=404, code="not_found")
        row = tx.execute("SELECT * FROM skill_personal_resources WHERE id=? AND user_id=?", (rid, uid)).fetchone()
        if row and row["deleted_at"]:
            raise ServiceError("资源已删除，请先恢复", status=409, code="resource_deleted")
        if row:
            if body.get("baseRevision") is None:
                raise ServiceError("修改需携带 baseRevision", status=400, code="base_revision_required")
            if str(body["baseRevision"]) != str(row["revision"]):
                raise ServiceError("资源版本冲突", status=409, code="conflict",
                                   extra={"current": _resource(row)})
            old = (row["kind"], row["name"], row["definition_json"], row["license"],
                   row["examples_json"], row["version"], row["origin_json"])
            # Canonical JSON might have been stored by an older version: compare semantic values.
            if (row["kind"] == normalized[0] and row["name"] == normalized[1]
                    and json.loads(row["definition_json"]) == definition
                    and row["license"] == normalized[3] and json.loads(row["examples_json"]) == examples
                    and row["version"] == version and json.loads(row["origin_json"]) == origin):
                return {"ok": True, "resource": _resource(row), "unchanged": True}
            tx.execute("""UPDATE skill_personal_resources SET kind=?, name=?, definition_json=?,
                license=?, examples_json=?, version=?, origin_json=?, revision=revision+1,
                updated_at=? WHERE id=? AND user_id=?""",
                (*normalized, now, rid, uid))
        else:
            if body.get("baseRevision") not in (None, 0):
                raise ServiceError("新资源不能携带旧版 revision", status=409, code="conflict")
            tx.execute("""INSERT INTO skill_personal_resources
                (id,user_id,kind,name,definition_json,license,examples_json,version,
                 origin_json,visibility,schema_version,revision,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,'private',1,1,?,?)""",
                (rid, uid, *normalized, now, now))
        event = tx.execute("INSERT INTO skill_resource_changes(user_id,resource_id,created_at) VALUES(?,?,?)",
                           (uid, rid, now))
        tx.execute("UPDATE skill_personal_resources SET change_seq=? WHERE id=?", (event.lastrowid, rid))
        current = tx.execute("SELECT * FROM skill_personal_resources WHERE id=?", (rid,)).fetchone()
    return {"ok": True, "resource": _resource(current)}


def list_resources(db: Any, user: dict[str, Any], qs: dict[str, list[str]]) -> dict[str, Any]:
    uid = int(user["id"])
    limit = _limit(qs)
    try:
        since = int(_one(qs, "since", "0"))
        if since < 0:
            raise ValueError()
    except ValueError:
        raise ServiceError("同步游标无效", status=400, code="invalid_cursor") from None
    rows = db.get_conn().execute(
        "SELECT * FROM skill_personal_resources WHERE user_id=? AND change_seq>? ORDER BY change_seq ASC LIMIT ?",
        (uid, since, limit + 1)).fetchall()
    items = rows[:limit]
    return {"ok": True, "items": [_resource(row) for row in items],
            "hasMore": len(rows) > limit,
            "nextCursor": str(items[-1]["change_seq"]) if items else str(since)}


def delete_resource(db: Any, user: dict[str, Any], rid: str, body_revision: str) -> dict[str, Any]:
    rid = _uuid(rid)
    uid = int(user["id"])
    with db.transaction() as tx:
        row = tx.execute("SELECT * FROM skill_personal_resources WHERE id=? AND user_id=?", (rid,uid)).fetchone()
        if not row:
            raise ServiceError("资源不存在", status=404, code="not_found")
        if not body_revision or str(row["revision"]) != str(body_revision):
            raise ServiceError("资源版本冲突", status=409, code="conflict", extra={"current": _resource(row)})
        if not row["deleted_at"]:
            now = utc_now_iso()
            tx.execute("UPDATE skill_personal_resources SET deleted_at=?,updated_at=?,revision=revision+1 WHERE id=?",
                       (now, now, rid))
            event=tx.execute("INSERT INTO skill_resource_changes(user_id,resource_id,created_at) VALUES(?,?,?)",(uid,rid,now))
            tx.execute("UPDATE skill_personal_resources SET change_seq=? WHERE id=?", (event.lastrowid,rid))
        current=tx.execute("SELECT * FROM skill_personal_resources WHERE id=?", (rid,)).fetchone()
    return {"ok": True, "resource": _resource(current)}


def _history_payload(body: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], str]:
    rid = _uuid(body.get("externalRunId"))
    if body.get("originClient") != "skill" or body.get("visibility") != "public" or body.get("status") != "success":
        raise ServiceError("上传 Skill 作品必须明确声明 public，历史私有记录不自动公开", status=400, code="public_submission_required")
    original = body.get("originalRequest")
    images = body.get("images")
    if not isinstance(original, str) or not original.strip() or len(original) > 20000:
        raise ServiceError("原始创作指令无效", status=400, code="invalid_prompt")
    if not isinstance(images, list) or not (1 <= len(images) <= 12):
        raise ServiceError("图片数量需为 1–12", status=400, code="invalid_images")
    data: list[dict[str, Any]] = []
    for item in images:
        if not isinstance(item, dict) or not isinstance(item.get("sha256"), str):
            raise ServiceError("图片元数据无效", status=400, code="invalid_image")
        image_str = item.get("dataUrl")
        if not isinstance(image_str, str) or not image_str.startswith("data:image/"):
            raise ServiceError("只接受图片 data URL", status=400, code="invalid_image")
        # Validate before writing ANY image, including media hash and per-item size.
        try:
            raw = base64.b64decode(image_str.split(",", 1)[1], validate=True)
        except (ValueError, IndexError, binascii.Error):
            raise ServiceError("图片编码无效", status=400, code="invalid_image") from None
        if not raw or len(raw) > 15 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != item["sha256"].lower():
            raise ServiceError("图片大小或 SHA256 不匹配", status=400, code="image_checksum_mismatch")
        data.append({"sha256": item["sha256"].lower(), "dataUrl": image_str,
                     "name": str(item.get("name") or "")[:100], "bytes": len(raw)})
    request_id = str(body.get("requestId") or "")
    if not re.fullmatch(r"skill-history-[a-f0-9-]{36}", request_id):
        raise ServiceError("请求幂等标识无效", status=400, code="invalid_request_id")
    fingerprint = hashlib.sha256(json.dumps(
        {"id": rid, "original": original, "images": [item["sha256"] for item in data]},
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return rid, original, data, fingerprint


def _publish_skill_run_images(
    db: Any, user: dict[str, Any], run_id: str,
    original: str, saved: list[dict[str, Any]], external_id: str,
) -> list[str]:
    """The one canonical work for one explicitly uploaded Skill run."""
    from .services import publish_user_work
    from .server import validate_publish_media, _grant_published_media
    from .generation_v3 import record_public_work, work_images

    urls = [str(item["url"]) for item in saved]
    if not urls:
        return []
    existing = db.get_conn().execute(
        "SELECT id FROM works WHERE run_id=?", (run_id,),
    ).fetchone()
    if existing:
        work_id = str(existing["id"])
        if work_images(db.get_conn(), work_id) != urls:
            raise ServiceError(
                "当前生成任务的作品内容与上传图片不一致",
                status=409, code="work_images_conflict",
            )
        return [work_id]

    payload = validate_publish_media(db, user, {
        "title": "Skill 手绘创作",
        "prompt": original, "images": urls, "styles": [],
        "layout": "", "price": 0, "origin": "generation",
        "requestId": f"skill-gen-{external_id}",
    })
    if payload.get("images") != urls:
        raise ServiceError(
            "作品媒体归属验证失败", status=403, code="invalid_public_media",
        )
    receipt = publish_user_work(db, user, payload)
    work_id = str(receipt["workId"])
    _grant_published_media(
        db, user, payload, target_type="work", target_id=work_id,
    )
    for url in urls:
        grant = db.get_conn().execute(
            "SELECT 1 FROM media_public_grants "
            "WHERE media_url=? AND target_type='work' AND target_id=? "
            "AND revoked_at IS NULL LIMIT 1",
            (url.split("?", 1)[0], work_id),
        ).fetchone()
        if not grant:
            raise ServiceError(
                "作品图片授权未完成，请重试", status=503,
                code="media_grant_pending",
            )

    # A publish retry may return an existing work after a previous interrupted
    # transaction. The deterministic requestId above makes that safe.
    with db.transaction() as tx:
        record_public_work(
            tx, user_id=int(user["id"]), source="skill",
            external_run_id=external_id, work_id=work_id,
            ordered_images=[
                (i, item["url"], item["sha256"])
                for i, item in enumerate(saved)
            ],
            expected_count=len(saved),
            request_id=f"skill-history-{external_id}",
        )
    return [work_id]


def import_history(
    db: Any, user: dict[str, Any], body: dict[str, Any], image_store: Any,
) -> dict[str, Any]:
    """Upload and publish ONE multi-image work using only V3 run/media tables.

    Media is uploaded before being granted public access. Each successful
    upload slot is durably recorded, so a network failure can resume from the
    first missing item without duplicating the already stored files.
    """
    from .services import check_text_has_secret
    from .generation_v3 import (
        reserve_skill_run, record_skill_uploaded_item, uploaded_skill_images,
    )

    external_id, original, images, fingerprint = _history_payload(body)
    if check_text_has_secret(original, db.get_conn()):
        raise ServiceError(
            "提示词包含受保护内容，不能公开上传",
            status=400, code="public_prompt_protected",
        )
    uid = int(user["id"])
    request_id = str(body["requestId"])

    with db._write_lock:
        with db.transaction() as tx:
            try:
                run_id = reserve_skill_run(
                    tx, user_id=uid, external_run_id=external_id,
                    request_id=request_id, request_hash=fingerprint,
                    original_request=original, expected_count=len(images),
                )
            except ValueError as error:
                raise ServiceError(
                    str(error), status=409, code="idempotency_conflict",
                ) from error
            saved = uploaded_skill_images(tx, run_id)
            if len(saved) > len(images) or any(
                item["sha256"] != images[i]["sha256"]
                for i, item in enumerate(saved)
            ):
                raise ServiceError(
                    "已上传的图片与当前重试内容不一致",
                    status=409, code="upload_state_conflict",
                )
            prior_status = tx.execute(
                "SELECT status FROM generation_runs WHERE id=?", (run_id,),
            ).fetchone()["status"]
            used = tx.execute(
                "SELECT COALESCE(SUM(bytes),0) FROM user_uploads "
                "WHERE user_id=? AND cat='skill_history'",
                (uid,),
            ).fetchone()[0]
            remaining = sum(item["bytes"] for item in images[len(saved):])
            if int(used or 0) + remaining > 1024 * 1024 * 1024:
                raise ServiceError(
                    "Skill 云端作品存储已达到 1 GiB 上限",
                    status=413, code="skill_history_storage_quota_exceeded",
                )

        for position in range(len(saved), len(images)):
            item = images[position]
            receipt = image_store(
                db, user, item["dataUrl"],
                name_zh=f"Skill 创作作品 {position + 1}",
                cat="skill_history",
            )
            with db.transaction() as tx:
                record_skill_uploaded_item(
                    tx, run_id=run_id, user_id=uid,
                    position=position, url=receipt["url"],
                    sha256=item["sha256"],
                )
            saved.append({"url": receipt["url"], "sha256": item["sha256"]})

        works = _publish_skill_run_images(
            db, user, run_id, original, saved, external_id,
        )
        if len(works) != 1:
            raise ServiceError(
                "整批图片未能完成作品发布，请重试", status=503,
                code="publication_incomplete",
            )

    return {
        "ok": True, "id": run_id, "visibility": "public",
        "workId": works[0], "workIds": works,
        "imageCount": len(saved),
        "deduped": prior_status == "success",
    }


def list_history(
    db: Any, user: dict[str, Any], qs: dict[str, list[str]],
) -> dict[str, Any]:
    """Read one canonical record per logical run, from either Web or Skill."""
    uid = int(user["id"])
    limit = _limit(qs)
    try:
        offset = int(_one(qs, "cursor", "0"))
        if offset < 0 or offset > 1_000_000:
            raise ValueError()
    except ValueError:
        raise ServiceError(
            "游标无效", status=400, code="invalid_cursor",
        ) from None

    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT r.*, w.id AS work_id
        FROM generation_runs r
        LEFT JOIN works w ON w.run_id=r.id
        WHERE r.user_id=?
        ORDER BY r.created_at DESC,r.id DESC
        LIMIT ? OFFSET ?
        """,
        (uid, limit + 1, offset),
    ).fetchall()

    output: list[dict[str, Any]] = []
    for row in rows[:limit]:
        image_rows = conn.execute(
            """
            SELECT i.position, i.status, m.storage_key, m.sha256
            FROM generation_items i
            LEFT JOIN media_assets m ON m.id=i.media_id
            WHERE i.run_id=?
            ORDER BY i.position ASC
            """,
            (row["id"],),
        ).fetchall()
        media = [
            {"url": item["storage_key"], "sha256": item["sha256"]}
            for item in image_rows
            if item["status"] == "success" and item["storage_key"]
        ]
        wid = str(row["work_id"]) if row["work_id"] else ""
        output.append({
            "id": row["id"],
            "originClient": row["source"],
            "externalRunId": row["external_run_id"],
            "originalRequest": row["original_request"],
            "images": media,
            "imageCount": len(media),
            "status": row["status"],
            "visibility": "public" if wid else "private",
            "workIds": [wid] if wid else [],
            "publishedWorkId": wid or None,
            "workId": wid or None,
            "createdAt": row["created_at"],
        })
    return {
        "ok": True, "items": output,
        "hasMore": len(rows) > limit,
        "nextCursor": str(offset + limit) if len(rows) > limit else None,
    }

def notification_list(db: Any, user: dict[str, Any], qs: dict[str, list[str]]) -> dict[str, Any]:
    uid=int(user["id"])
    limit=_limit(qs,50)
    try:
        before=int(_one(qs,"before","9223372036854775807"))
    except ValueError:
        raise ServiceError("通知游标无效",status=400,code="invalid_cursor") from None
    rows=db.get_conn().execute(
        "SELECT id,kind,title,target_type,target_id,created_at,read_at FROM notifications "
        "WHERE user_id=? AND id<? ORDER BY id DESC LIMIT ?",(uid,before,limit+1)).fetchall()
    return {"ok":True,"items":[dict(x) for x in rows[:limit]],"hasMore":len(rows)>limit,
            "nextCursor":str(rows[limit-1]["id"]) if len(rows)>limit else None}


def collection_items(db: Any, user: dict[str, Any]) -> dict[str, Any]:
    from .services import build_skill_library_payload
    payload=build_skill_library_payload(db,user)
    items=[]
    for group in ("collected","owned","official"):
        for item in payload.get(group,[]):
            # A paid unlocked item may still be online-only. No offline export implied.
            items.append({**item,"section":group,"syncEligible":bool(item.get("content_url"))
                         and bool(item.get("unlocked"))})
    return {"ok":True,"items":items}


def download_resource(db: Any, user: dict[str, Any], resource_id: str) -> dict[str, Any]:
    if re.fullmatch(r"[a-fA-F0-9-]{36}",resource_id):
        row=db.get_conn().execute(
            "SELECT * FROM skill_personal_resources WHERE id=? AND user_id=? AND deleted_at IS NULL",
            (_uuid(resource_id),int(user["id"]))).fetchone()
        if not row:
            raise ServiceError("资源不存在",status=404,code="not_found")
        return {"ok":True,"resource":_resource(row)}
    from .services import build_skill_asset_content
    return {"ok":True,**build_skill_asset_content(db,user,resource_id)}



def _require_admin(user: dict[str,Any]) -> None:
    if user.get("role") != "admin":
        raise ServiceError("没有管理权限",status=403,code="admin_required")


def legacy_generation_audit(db: Any, user: dict[str,Any]) -> dict[str,Any]:
    """Read-only reconciliation of historical rows already marked public."""
    _require_admin(user)
    conn=db.get_conn()
    where="""g.status='success' AND g.visibility='public'
        AND COALESCE(g.deleted_at,'')='' AND g.engine!='demo'
        AND COALESCE(g.items_json,'') NOT IN ('','[]')"""
    eligible=conn.execute("SELECT COUNT(*) FROM studio_generations g WHERE "+where).fetchone()[0]
    missing=conn.execute(
        "SELECT COUNT(*) FROM studio_generations g WHERE "+where+
        " AND NOT EXISTS (SELECT 1 FROM generation_works gw WHERE gw.generation_id=g.id)"
    ).fetchone()[0]
    return {"ok":True,"eligibleLegacyPublic":eligible,"withoutMappedWork":missing,
            "note":"仅统计既有公开记录；私有历史未参与，也不会自动发布"}


def reconcile_legacy_generations(db: Any, user: dict[str,Any], body: dict[str,Any]) -> dict[str,Any]:
    """Explicit admin-only batch repair; never promote private histories."""
    _require_admin(user)
    if body.get("confirmed") is not True:
        raise ServiceError("必须明确确认修复旧公开作品",status=400,code="confirmation_required")
    try:
        batch=int(body.get("batchSize") or 50)
    except (TypeError,ValueError):
        raise ServiceError("batchSize 格式错误",status=400,code="invalid_batch_size") from None
    if not 1<=batch<=100:
        raise ServiceError("batchSize 必须介于 1–100",status=400,code="invalid_batch_size")
    cursor=body.get("cursor")
    if cursor is not None and (not isinstance(cursor,str) or len(cursor)>240):
        raise ServiceError("游标不正确",status=400,code="invalid_cursor")
    from .generation_works import backfill_historical_generations
    with db._write_lock:
        result=backfill_historical_generations(db.get_conn(),batch_size=batch,cursor=cursor)
    return {"ok":True,**result}

def _work_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(value)):
        raise ServiceError("作品编号无效",status=400,code="invalid_id")
    return value


def social_like(db: Any, user: dict[str, Any], work_id: str, body: dict[str,Any]) -> dict[str,Any]:
    from .services import toggle_user_like
    if type(body.get("liked")) is not bool:
        raise ServiceError("liked 必须明确是 true 或 false", status=400, code="invalid_like_action")
    return toggle_user_like(db,user,"work",_work_id(work_id),"set" if body["liked"] else "unset")


def social_comment(db: Any, user: dict[str, Any], work_id: str, body: dict[str, Any]) -> dict[str,Any]:
    from .resource_discussions import comment
    work_id=_work_id(work_id)
    text=body.get("text")
    request_id=body.get("requestId")
    if not isinstance(text,str) or not text.strip() or len(text)>3000:
        raise ServiceError("评论长度无效",status=400,code="invalid_comment")
    if not isinstance(request_id,str) or not re.fullmatch(r"skill-comment-[a-f0-9-]{36}",request_id):
        raise ServiceError("评论幂等标识无效",status=400,code="invalid_request_id")
    return comment(db,user,"work",work_id,text,request_id=request_id)


def comments(db: Any, user: dict[str,Any] | None, work_id: str, qs: dict[str,list[str]]) -> dict[str,Any]:
    from .forum_resources import resource_comments
    return resource_comments(db,user,"work",_work_id(work_id),_one(qs,"offset","0"),_one(qs,"limit","20"))


def handle_get(handler: Any, path: str, qs: dict[str,list[str]]) -> bool:
    if path == "/api/admin/skill-bridge/audit":
        handler._send_json(legacy_generation_audit(handler.db,_user(handler)))
    elif path == "/api/v1/me/resources":
        handler._send_json(list_resources(handler.db,_user(handler),qs))
    elif path == "/api/v1/me/collection-items":
        handler._send_json(collection_items(handler.db,_user(handler)))
    elif path == "/api/v1/me/generations":
        handler._send_json(list_history(handler.db,_user(handler),qs))
    elif path == "/api/v1/me/notifications":
        handler._send_json(notification_list(handler.db,_user(handler),qs))
    elif (m:=re.fullmatch(r"/api/v1/resources/([^/]+)/download",path)):
        handler._send_json(download_resource(handler.db,_user(handler),m[1]))
    elif (m:=re.fullmatch(r"/api/v1/works/([^/]+)/comments",path)):
        handler._send_json(comments(handler.db,handler._current_user(required=False),m[1],qs))
    else:
        return False
    return True


def handle_put(handler: Any, path: str, body: dict[str,Any]) -> bool:
    match=re.fullmatch(r"/api/v1/me/resources/([^/]+)",path)
    if not match:
        return False
    handler._send_json(put_resource(handler.db,_user(handler),match[1],body))
    return True


def handle_delete(handler: Any, path: str, qs: dict[str,list[str]]) -> bool:
    match=re.fullmatch(r"/api/v1/me/resources/([^/]+)",path)
    if not match:
        return False
    handler._send_json(delete_resource(handler.db,_user(handler),match[1],_one(qs,"baseRevision")))
    return True


def handle_post(handler: Any, path: str, body: dict[str,Any]) -> bool:
    if path == "/api/admin/skill-bridge/reconcile":
        handler._send_json(reconcile_legacy_generations(handler.db,_user(handler),body))
    elif path == "/api/v1/me/generations":
        # Skill deliberately uploads finished images as public works in one operation.
        from .server import save_data_url_upload
        handler._send_json(import_history(handler.db,_user(handler),body,save_data_url_upload))
    elif (m:=re.fullmatch(r"/api/v1/works/([^/]+)/likes",path)):
        handler._send_json(social_like(handler.db,_user(handler),m[1],body))
    elif (m:=re.fullmatch(r"/api/v1/works/([^/]+)/comments",path)):
        handler._send_json(social_comment(handler.db,_user(handler),m[1],body))
    else:
        return False
    return True
