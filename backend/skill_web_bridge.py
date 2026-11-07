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

SKILL_WEB_MIGRATIONS = [
    (94, "094_skill_personal_resources", """
        CREATE TABLE IF NOT EXISTS skill_personal_resources (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL CHECK(kind IN ('style','layout')),
            name TEXT NOT NULL,
            definition_json TEXT NOT NULL,
            license TEXT NOT NULL,
            examples_json TEXT NOT NULL DEFAULT '[]',
            version TEXT NOT NULL DEFAULT '1.0.0',
            origin_json TEXT NOT NULL DEFAULT 'null',
            visibility TEXT NOT NULL DEFAULT 'private',
            schema_version INTEGER NOT NULL DEFAULT 1,
            revision INTEGER NOT NULL DEFAULT 1,
            change_seq INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_skill_resources_user_seq
            ON skill_personal_resources(user_id,change_seq);
        CREATE TABLE IF NOT EXISTS skill_resource_changes (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            resource_id TEXT NOT NULL REFERENCES skill_personal_resources(id),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_skill_change_user_seq ON skill_resource_changes(user_id,seq);
    """),
    (95, "095_skill_private_generations_and_comment_idempotency", """
        CREATE TABLE IF NOT EXISTS skill_generation_runs (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            external_run_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            original_request TEXT NOT NULL,
            images_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'success',
            visibility TEXT NOT NULL DEFAULT 'private',
            created_at TEXT NOT NULL,
            UNIQUE(user_id,external_run_id),
            UNIQUE(user_id,request_id)
        );
        CREATE INDEX IF NOT EXISTS idx_skill_runs_user_created
            ON skill_generation_runs(user_id,created_at DESC,id DESC);
        CREATE TABLE IF NOT EXISTS skill_comment_receipts (
            user_id INTEGER NOT NULL REFERENCES users(id),
            request_id TEXT NOT NULL,
            work_id TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(user_id,request_id)
        );
    """),
    (96, "096_skill_explicit_history_publications", """
        CREATE TABLE IF NOT EXISTS skill_history_publications (
            user_id INTEGER NOT NULL REFERENCES users(id),
            source TEXT NOT NULL CHECK(source IN ('skill','web')),
            history_id TEXT NOT NULL,
            work_id TEXT NOT NULL REFERENCES works(id),
            created_at TEXT NOT NULL,
            PRIMARY KEY(user_id,source,history_id)
        );
        CREATE INDEX IF NOT EXISTS idx_skill_history_work ON skill_history_publications(work_id);
    """),
]


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
    return handler._current_user(required=True)


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
    if body.get("originClient") != "skill" or body.get("visibility") != "private" or body.get("status") != "success":
        raise ServiceError("仅允许导入明确私有的 Skill 成功生成历史", status=400, code="private_history_only")
    original = body.get("originalRequest")
    images = body.get("images")
    if not isinstance(original, str) or not original.strip() or len(original) > 50000:
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
                     "name": str(item.get("name") or "")[:100]})
    request_id = str(body.get("requestId") or "")
    if not re.fullmatch(r"skill-history-[a-f0-9-]{36}", request_id):
        raise ServiceError("请求幂等标识无效", status=400, code="invalid_request_id")
    fingerprint = hashlib.sha256(json.dumps(
        {"id": rid, "original": original, "images": [item["sha256"] for item in data]},
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return rid, original, data, fingerprint


def import_history(db: Any, user: dict[str, Any], body: dict[str, Any], image_store: Any) -> dict[str, Any]:
    """Store private media incrementally and resume interrupted uploads by run ID.

    A partially uploaded run is not visible in history and is never promoted to
    a public work. Retrying the same request reuses committed image references.
    """
    rid, original, images, fingerprint = _history_payload(body)
    uid = int(user["id"])
    now = utc_now_iso()
    with db._write_lock:
        old = db.get_conn().execute(
            "SELECT * FROM skill_generation_runs WHERE user_id=? AND (external_run_id=? OR request_id=?)",
            (uid, rid, body["requestId"])).fetchone()
        if old:
            if old["external_run_id"] != rid or old["request_hash"] != fingerprint:
                raise ServiceError("重复请求内容不一致", status=409, code="idempotency_conflict")
            if old["status"] == "success":
                return {"ok": True, "id": old["id"], "visibility": "private", "deduped": True}
            new_id = old["id"]
            saved = json.loads(old["images_json"] or "[]")
            if len(saved) > len(images) or any(
                saved[idx]["sha256"] != item["sha256"] for idx, item in enumerate(saved)
            ):
                raise ServiceError("云端上传进度与图片不一致", status=409, code="upload_state_conflict")
        else:
            new_id = "skillgen_" + uuid.uuid4().hex
            saved = []
            with db.transaction() as tx:
                tx.execute("""INSERT INTO skill_generation_runs
                    (id,user_id,external_run_id,request_id,request_hash,original_request,images_json,
                     status,visibility,created_at) VALUES(?,?,?,?,?,?,?,'uploading','private',?)""",
                    (new_id, uid, rid, body["requestId"], fingerprint, original, "[]", now))
        for index in range(len(saved), len(images)):
            item = images[index]
            result = image_store(db, user, item["dataUrl"],
                                 name_zh=f"Skill 创作历史 {index + 1}", cat="skill_history")
            saved.append({"url": result["url"], "sha256": item["sha256"]})
            with db.transaction() as tx:
                tx.execute("UPDATE skill_generation_runs SET images_json=? WHERE id=? AND user_id=?",
                           (json.dumps(saved, ensure_ascii=False), new_id, uid))
        with db.transaction() as tx:
            tx.execute("UPDATE skill_generation_runs SET status='success' WHERE id=? AND user_id=?",
                       (new_id, uid))
    return {"ok": True, "id": new_id, "visibility": "private", "deduped": False}

def list_history(db: Any, user: dict[str, Any], qs: dict[str, list[str]]) -> dict[str, Any]:
    uid = int(user["id"])
    limit = _limit(qs)
    try:
        offset = int(_one(qs,"cursor","0"))
        if offset < 0 or offset > 1_000_000:
            raise ValueError()
    except ValueError:
        raise ServiceError("游标无效", status=400, code="invalid_cursor") from None
    conn = db.get_conn()
    # Both website and Skill histories are private owner-scoped reads.
    rows = conn.execute("""
        SELECT id, created_at, status, 'skill' AS origin, external_run_id, original_request,
               images_json, visibility FROM skill_generation_runs WHERE user_id=? AND status='success'
        UNION ALL
        SELECT id, created_at, status, 'web' AS origin, '' AS external_run_id, prompt,
               items_json, visibility FROM studio_generations
        WHERE user_id=? AND COALESCE(deleted_at,'')=''
        ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?
    """, (uid,uid,limit+1,offset)).fetchall()
    result = []
    for row in rows[:limit]:
        try:
            media=json.loads(row["images_json"] or "[]")
        except (ValueError,TypeError):
            media=[]
        result.append({"id":row["id"],"originClient":row["origin"],"externalRunId":row["external_run_id"],
                       "originalRequest":row["original_request"],"images":media,
                       "status":row["status"],"visibility":row["visibility"],
                       "canPublish":row["status"]=="success" and row["visibility"]=="private",
                       "createdAt":row["created_at"]})
    return {"ok": True,"items":result,"hasMore":len(rows)>limit,
            "nextCursor":str(offset+limit) if len(rows)>limit else None}



def publish_history(db: Any, user: dict[str, Any], history_id: str, body: dict[str,Any]) -> dict[str,Any]:
    """Create a public work ONLY after an explicit confirmation from the owner."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", history_id):
        raise ServiceError("历史 ID 无效", status=400, code="invalid_id")
    title = body.get("title")
    prompt = body.get("prompt")
    if (not isinstance(title,str) or not title.strip() or len(title)>140
            or not isinstance(prompt,str) or not prompt.strip() or len(prompt)>20000
            or body.get("confirmed") is not True):
        raise ServiceError("必须确认公开的标题、提示词和图片",status=400,code="publication_confirmation_required")
    uid=int(user["id"])
    with db._write_lock:
        conn=db.get_conn()
        row=conn.execute(
            "SELECT id,status,visibility,images_json FROM skill_generation_runs WHERE id=? AND user_id=?",
            (history_id,uid)).fetchone()
        source="skill"
        if not row:
            row=conn.execute(
                "SELECT id,status,visibility,items_json AS images_json FROM studio_generations "
                "WHERE id=? AND user_id=? AND COALESCE(deleted_at,'')=''",
                (history_id,uid)).fetchone()
            source="web"
        if not row:
            raise ServiceError("历史记录不存在",status=404,code="not_found")
        previous=conn.execute(
            "SELECT work_id FROM skill_history_publications WHERE user_id=? AND source=? AND history_id=?",
            (uid,source,history_id)).fetchone()
        if previous:
            return {"ok":True,"workId":previous["work_id"],"alreadyPublished":True}
        if row["status"]!="success" or row["visibility"]!="private":
            raise ServiceError("只能发布未公开的成功创作历史",status=409,code="not_private_history")
        try:
            originals=json.loads(row["images_json"] or "[]")
        except (ValueError,TypeError):
            originals=[]
        urls=[]
        for item in originals:
            if isinstance(item,str):
                url=item
            elif isinstance(item,dict):
                url=str(item.get("url") or item.get("imageUrl") or item.get("image") or "")
            else:
                continue
            if url and url not in urls:
                urls.append(url)
        raw_indices=body.get("indices")
        if raw_indices is not None:
            if (not isinstance(raw_indices,list) or not raw_indices
                    or len(raw_indices)>9 or any(type(i) is not int or i<0 or i>=len(urls) for i in raw_indices)
                    or len(set(raw_indices)) != len(raw_indices)):
                raise ServiceError("图片选择无效",status=400,code="invalid_image_selection")
            urls=[urls[i] for i in raw_indices]
        if not (1<=len(urls)<=9):
            raise ServiceError("请选择 1–9 张图片发布",status=400,code="invalid_images")
        from .server import validate_publish_media, _grant_published_media
        from .services import publish_user_work
        payload=validate_publish_media(db,user,{
            "title":title.strip(),"prompt":prompt,"images":urls,
            "styles":[],"layout":"","price":0,
            "requestId":"history-pub-"+history_id,
        })
        if len(payload.get("images") or []) != len(urls):
            raise ServiceError("有部分图片不可发布",status=403,code="media_not_publishable")
        result=publish_user_work(db,user,payload)
        _grant_published_media(db,user,payload,target_type="topic",target_id=str(result.get("topicId") or ""))
        wid=str(result["workId"])
        with db.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO skill_history_publications "
                       "(user_id,source,history_id,work_id,created_at) VALUES(?,?,?,?,?)",
                       (uid,source,history_id,wid,utc_now_iso()))
        return {"ok":True,"workId":wid,"url":result.get("url"),"alreadyPublished":False}

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


def _work_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(value)):
        raise ServiceError("作品编号无效",status=400,code="invalid_id")
    return value


def social_like(db: Any, user: dict[str, Any], work_id: str, body: dict[str,Any]) -> dict[str,Any]:
    from .services import toggle_user_like
    return toggle_user_like(db,user,"work",_work_id(work_id),"set" if body.get("liked") is True else "unset")


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
    if path == "/api/v1/me/resources":
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
    if path == "/api/v1/me/generations":
        # Import only when explicitly requested; never auto-publish to works.
        from .server import save_data_url_upload
        handler._send_json(import_history(handler.db,_user(handler),body,save_data_url_upload))
    elif (m:=re.fullmatch(r"/api/v1/me/generations/([^/]+)/publish",path)):
        handler._send_json(publish_history(handler.db,_user(handler),m[1],body))
    elif (m:=re.fullmatch(r"/api/v1/works/([^/]+)/likes",path)):
        handler._send_json(social_like(handler.db,_user(handler),m[1],body))
    elif (m:=re.fullmatch(r"/api/v1/works/([^/]+)/comments",path)):
        handler._send_json(social_comment(handler.db,_user(handler),m[1],body))
    else:
        return False
    return True
