"""Studio 2.0 project drafts: single writer, owner-scoped CAS and replay-safe patches.

Issue #103 / RFC #102. This is NOT a generation, workflow-template or public
work table. Current Web execution remains on the V3 run/item ledger.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


STUDIO_PROJECT_MIGRATIONS = [
    (101, "101_studio_project_drafts", """
        CREATE TABLE IF NOT EXISTS studio_projects (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL CHECK(kind IN ('image', 'series', 'article')),
            title TEXT NOT NULL DEFAULT '',
            authority TEXT NOT NULL CHECK(authority IN ('spec', 'graph', 'article')),
            revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
            draft_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_studio_projects_owner_updated
          ON studio_projects(user_id,updated_at DESC,id DESC);
        CREATE TABLE IF NOT EXISTS studio_project_requests (
            user_id INTEGER NOT NULL REFERENCES users(id),
            project_id TEXT NOT NULL REFERENCES studio_projects(id),
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id,project_id,idempotency_key)
        );
    """),
]

_ID = re.compile(r"^[A-Za-z0-9_-]{4,100}$")
_KINDS = {"image", "series", "article"}
_AUTHORITIES = {"spec", "graph", "article"}
_ALLOWED_DRAFT_KEYS = {"creationSpec", "plan", "graph", "article", "activeView", "editorLayout"}
_BAD_JSON_KEYS = {"apiKey", "accessToken", "authorization", "secret_blackbox_prompt",
                  "secretBlackboxPrompt", "finalPrompt", "base64", "b64_json"}
_MAX_DRAFT_BYTES = 512 * 1024


def _fail(message: str, status: int = 400, code: str = "invalid_project",
          **extra: Any) -> None:
    from .services import ServiceError
    raise ServiceError(message, status=status, code=code, extra=extra or None)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _id(value: Any, field: str = "projectId") -> str:
    value = str(value or "")
    if not _ID.fullmatch(value):
        _fail(f"{field} 格式无效", code="invalid_project_id")
    return value


def _key(value: Any) -> str:
    key = str(value or "").strip()
    if not 8 <= len(key) <= 128 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", key):
        _fail("幂等请求键无效", code="idempotency_key_required")
    return key


def _canonical(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, OverflowError, RecursionError):
        _fail("项目草稿包含无法序列化的内容", code="invalid_project_json")


def _validate_draft(draft: Any, tx: Any, user_id: int) -> str:
    if not isinstance(draft, dict) or set(draft) - _ALLOWED_DRAFT_KEYS:
        _fail("项目草稿字段无效", code="invalid_project_draft")
    seen_media: set[str] = set()

    def walk(value: Any, depth: int = 0) -> None:
        if depth > 35:
            _fail("项目草稿嵌套过深", code="invalid_project_draft")
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or key in _BAD_JSON_KEYS:
                    _fail("草稿包含不可存储的私密字段", code="invalid_project_draft")
                if key in ("mediaId", "sourceMediaId") and child:
                    if not isinstance(child, str) or len(child) > 128:
                        _fail("媒体引用无效", code="invalid_project_media")
                    seen_media.add(child)
                walk(child, depth + 1)
        elif isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
        elif isinstance(value, str):
            if value.lstrip().lower().startswith(("data:image/", "data:application/octet-stream;")):
                _fail("请先上传本地参考图片，再保存项目到云端", code="project_media_upload_required")
            if len(value) > 200000:
                _fail("草稿文本过长", code="project_draft_too_large")

    walk(draft)
    encoded = _canonical(draft)
    if len(encoded.encode("utf-8")) > _MAX_DRAFT_BYTES:
        _fail("项目草稿超过 512 KiB 限制", status=413, code="project_draft_too_large")
    # Browser-selected IDs and AI-proposed resources are not capabilities.
    # Verify catalog existence, type, entitlement and media owner in the same
    # transaction that will commit the Project revision (no extra upload table).
    from .studio_resources import check_media_owner, validate_draft_refs
    for media_id in seen_media:
        check_media_owner(media_id, tx, user_id)
    validate_draft_refs(draft, tx, {"id": user_id})
    return encoded


def _row_to_project(row: Any, *, include_draft: bool = True) -> dict[str, Any]:
    data = {
        "id": str(row["id"]),
        "kind": str(row["kind"]),
        "title": str(row["title"]),
        "authority": str(row["authority"]),
        "revision": int(row["revision"]),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }
    if include_draft:
        data["draft"] = json.loads(row["draft_json"])
    return data


def _project_row(tx: Any, user_id: int, project_id: str, *, lock: bool = False) -> Any:
    query = "SELECT * FROM studio_projects WHERE id=? AND user_id=?"
    if lock and getattr(tx, "dialect", "") == "postgresql":
        query += " FOR UPDATE"
    row = tx.execute(query, (project_id, user_id)).fetchone()
    if not row:
        # Same response for someone else's project and a nonexistent ID.
        _fail("项目不存在", status=404, code="project_not_found")
    return row


def _request_hash(operation: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256((operation + ":" + _canonical(payload)).encode("utf-8")).hexdigest()


def _replay(tx: Any, uid: int, project_id: str, key: str, request_hash: str) -> dict[str, Any] | None:
    row = tx.execute(
        """SELECT request_hash,response_json FROM studio_project_requests
           WHERE user_id=? AND project_id=? AND idempotency_key=?""",
        (uid, project_id, key),
    ).fetchone()
    if not row:
        return None
    if str(row["request_hash"]) != request_hash:
        _fail("同一个幂等键不能用于不同内容", status=409, code="idempotency_key_reused")
    response = json.loads(row["response_json"])
    response["idempotentReplay"] = True
    return response


def _record(tx: Any, uid: int, project_id: str, key: str,
            request_hash: str, response: dict[str, Any]) -> None:
    tx.execute(
        """INSERT INTO studio_project_requests
           (user_id,project_id,idempotency_key,request_hash,response_json,created_at)
           VALUES (?,?,?,?,?,?)""",
        (uid, project_id, key, request_hash, _canonical(response), _now()),
    )


def create_project(db: Any, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    uid = int(user["id"])
    project_id = _id(body.get("projectId") or body.get("id"))
    key = _key(body.get("idempotencyKey"))
    kind = str(body.get("kind") or "")
    authority = str(body.get("authority") or "")
    title = str(body.get("title") or "").strip()[:140] or "未命名创作"
    if kind not in _KINDS or authority not in _AUTHORITIES:
        _fail("项目任务类型或编辑权威无效", code="invalid_project_kind")
    if kind == "image" and authority == "article":
        _fail("单图项目不能使用文章编辑权威", code="invalid_project_authority")
    draft = body.get("draft")
    if draft is None:
        draft = {}
    request_payload = {"projectId": project_id, "kind": kind, "authority": authority,
                       "title": title, "draft": draft}
    digest = _request_hash("create", request_payload)
    with db.transaction() as tx:
        exists = tx.execute("SELECT user_id FROM studio_projects WHERE id=?",
                            (project_id,)).fetchone()
        if exists:
            if int(exists["user_id"]) != uid:
                _fail("项目已存在", status=409, code="project_exists")
            prior = _replay(tx, uid, project_id, key, digest)
            if prior:
                return prior
            _fail("项目编号已存在，请重新生成项目编号", status=409, code="project_exists")
        draft_json = _validate_draft(draft, tx, uid)
        now = _now()
        tx.execute(
            """INSERT INTO studio_projects
               (id,user_id,kind,title,authority,revision,draft_json,created_at,updated_at)
               VALUES (?,?,?,?,?,1,?,?,?)""",
            (project_id, uid, kind, title, authority, draft_json, now, now),
        )
        result = {"ok": True, "projectId": project_id, "revision": 1,
                  "saveState": "synced", "updatedAt": now}
        _record(tx, uid, project_id, key, digest, result)
        return result


def get_project(db: Any, user: dict[str, Any], project_id: str) -> dict[str, Any]:
    uid = int(user["id"])
    row = _project_row(db.get_conn(), uid, _id(project_id))
    return {"ok": True, "project": _row_to_project(row)}


def _project_page_cursor(raw: str) -> tuple[str, str]:
    if not isinstance(raw, str) or not 0 < len(raw) <= 300:
        _fail("项目分页游标无效", code="invalid_project_cursor")
    try:
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        parts = json.loads(decoded.decode("utf-8"))
        if not isinstance(parts, list) or len(parts) != 2:
            raise ValueError("invalid cursor")
        stamp, ident = parts
        if (not isinstance(stamp, str) or len(stamp) > 48
                or not re.fullmatch(r"[0-9]{4}-[0-9TZ:.-]+", stamp)):
            raise ValueError("invalid timestamp")
        return stamp, _id(ident)
    except (ValueError, UnicodeError, TypeError, OverflowError, binascii.Error):
        _fail("项目分页游标无效", code="invalid_project_cursor")


def _cursor_for(row: Any) -> str:
    raw = _canonical([str(row["updated_at"]), str(row["id"])]).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def list_projects(db: Any, user: dict[str, Any], *,
                  query: str = "", cursor: str = "", limit: int = 40) -> dict[str, Any]:
    uid = int(user["id"])
    if not isinstance(query, str) or len(query) > 120:
        _fail("项目搜索关键词过长", code="invalid_project_query")
    if type(limit) is not int or not 1 <= limit <= 100:
        _fail("项目列表每页数量无效", code="invalid_project_limit")
    sql = """SELECT id,kind,title,authority,revision,created_at,updated_at
             FROM studio_projects WHERE user_id=?"""
    args: list[Any] = [uid]
    if query.strip():
        # Escape SQL wildcard characters so search means literal text; the
        # owner predicate is never removed, even on arbitrary cursor input.
        literal = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql += " AND title LIKE ? ESCAPE '\\'"
        args.append("%" + literal + "%")
    if cursor:
        stamp, item_id = _project_page_cursor(cursor)
        sql += " AND (updated_at < ? OR (updated_at = ? AND id < ?))"
        args.extend([stamp, stamp, item_id])
    sql += " ORDER BY updated_at DESC,id DESC LIMIT ?"
    args.append(limit + 1)
    rows = db.get_conn().execute(sql, tuple(args)).fetchall()
    has_more = len(rows) > limit
    page = rows[:limit]
    return {
        "ok": True,
        "projects": [_row_to_project(row, include_draft=False) for row in page],
        "hasMore": has_more,
        "nextCursor": _cursor_for(page[-1]) if has_more and page else "",
    }


def _pointer_tokens(path: Any) -> list[str]:
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 200:
        _fail("项目修改路径无效", code="invalid_project_patch")
    parts = path[1:].split("/")
    if not parts or len(parts) > 12 or any(part == "" for part in parts):
        _fail("项目修改路径无效", code="invalid_project_patch")
    result = [part.replace("~1", "/").replace("~0", "~") for part in parts]
    if any(x in {"__proto__", "constructor", "prototype"} for x in result):
        _fail("项目修改路径无效", code="invalid_project_patch")
    return result



# Node-scoped edits are deliberately narrower than Canvas-authority Graph writes.
# In particular, no client may target edges, node identities, status or run
# snapshots by a "simple editor" patch. The owner-scoped Project CAS covers
# concurrent tabs, while this validator covers topology and field authority.
_SIMPLE_NODE_FIELDS = {
    "text_input": {"text"},
    "skill_params": {"style1", "style2", "fusion", "layout", "colors", "tones",
                     "moods", "customMood", "whitespace", "audience",
                     "businessScene", "sc021Type", "sc022Name", "sc022Pinyin",
                     "resourceRefs"},
    "output_control": {"ratio", "ratioSource", "mode", "count"},
}


def _patch_graph_node(draft: dict[str, Any], tokens: list[str],
                      item: dict[str, Any]) -> None:
    if len(tokens) != 5 or tokens[0:2] != ["graph", "nodesById"] or tokens[3] != "data":
        _fail("简洁编辑只能修改指定节点参数", code="invalid_graph_node_patch")
    if item["op"] != "set" or "value" not in item:
        _fail("简洁编辑不允许删除节点参数", code="invalid_graph_node_patch")
    graph = draft.get("graph")
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    edges = graph.get("edges", []) if isinstance(graph, dict) else []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        _fail("画布图形格式无效", code="invalid_graph_node_patch")
    ident, field = tokens[2], tokens[4]
    if len(ident) > 100 or not ident:
        _fail("节点编号无效", code="invalid_graph_node_patch")
    matched = [node for node in nodes if isinstance(node, dict) and node.get("id") == ident]
    if len(matched) != 1:
        _fail("目标节点不存在或有歧义", code="invalid_graph_node_patch")
    node = matched[0]
    kind = node.get("type")
    if field not in _SIMPLE_NODE_FIELDS.get(kind, set()):
        _fail("此字段必须在画布编辑", status=409, code="graph_field_read_only")
    controls = [n for n in nodes if isinstance(n, dict) and n.get("type") == "output_control"]
    skills = [n for n in nodes if isinstance(n, dict) and n.get("type") == "skill_params"]
    texts = [n for n in nodes if isinstance(n, dict) and n.get("type") == "text_input"]
    known = {"skill_params", "text_input", "asset", "output_control",
             "output_display", "loop", "article_plan"}
    if (not controls or len(skills) != 1 or len(texts) != 1 or
            any(not isinstance(n, dict) or n.get("type") not in known for n in nodes)):
        _fail("复杂图形不可用简洁编辑覆盖", status=409, code="graph_field_read_only")
    ids = [n.get("id") for n in nodes]
    if len(set(ids)) != len(ids) or any(
        not isinstance(e, dict) or e.get("from") not in ids or e.get("to") not in ids
        for e in edges
    ):
        _fail("图形连接不完整", status=409, code="graph_field_read_only")
    inbound = lambda ctrl: {e["from"] for e in edges if e.get("to") == ctrl.get("id")}
    shared = all(skills[0]["id"] in inbound(c) and texts[0]["id"] in inbound(c)
                 for c in controls)
    if not shared or (len(controls) > 1 and
                      (kind == "output_control" or kind == "skill_params" and field not in
                       {"style1", "style2", "fusion", "resourceRefs"})):
        _fail("多分支仅可编辑安全映射的公共字段", status=409,
              code="graph_field_read_only")
    if kind == "skill_params" and node != skills[0] or (
        kind == "text_input" and node != texts[0]
    ) or (kind == "output_control" and
          (len(controls) != 1 or node != controls[0])):
        _fail("只能修改项目中唯一的公共参数节点", status=409,
              code="graph_field_read_only")
    locked = (node.get("data") or {}).get("lockedFields", [])
    field_lock = {"style1": "style", "style2": "secondaryStyle",
                  "layout": "layout", "ratio": "ratio", "text": "subject"}.get(field, field)
    if isinstance(locked, list) and field_lock in locked:
        _fail("该参数已锁定", status=409, code="graph_field_read_only")
    if not isinstance(node.get("data"), dict):
        node["data"] = {}
    node["data"][field] = deepcopy(item["value"])
    graph["revision"] = max(0, int(graph.get("revision", 0) or 0)) + 1


def _apply_patch(project: dict[str, Any], patch: Any) -> dict[str, Any]:
    patches = patch if isinstance(patch, list) else [patch]
    if not patches or len(patches) > 32:
        _fail("一次修改不能超过 32 个字段", code="invalid_project_patch")
    updated = deepcopy(project)
    for item in patches:
        if not isinstance(item, dict) or item.get("op") not in ("set", "remove"):
            _fail("仅支持 set/remove 字段修改", code="invalid_project_patch")
        tokens = _pointer_tokens(item.get("path"))
        if tokens[0] == "title":
            if len(tokens) != 1 or item["op"] != "set":
                _fail("项目名称修改无效", code="invalid_project_patch")
            updated["title"] = str(item.get("value") or "").strip()[:140] or "未命名创作"
            continue
        if tokens[0] == "authority":
            if len(tokens) != 1 or item["op"] != "set" or item.get("value") not in _AUTHORITIES:
                _fail("项目编辑权威无效", code="invalid_project_authority")
            updated["authority"] = item["value"]
            continue
        if tokens[0] not in _ALLOWED_DRAFT_KEYS:
            _fail("不允许修改此项目字段", code="invalid_project_patch")
        draft = updated["draft"]
        # At every revision, only the execution authority is writable:
        # derived Graphs cannot overwrite Spec/Plan, and vice versa.
        root = tokens[0]
        authority = updated["authority"]
        writable = {
            "spec": {"creationSpec", "plan", "activeView", "editorLayout"},
            "graph": {"graph", "activeView", "editorLayout"},
            "article": {"article", "creationSpec", "plan", "activeView", "editorLayout"},
        }
        if root not in writable[authority]:
            _fail("当前视图不能覆盖另一编辑权威的数据", status=409,
                  code="editor_authority_conflict")
        if root == "graph" and len(tokens) > 1 and tokens[1] == "nodesById":
            _patch_graph_node(draft, tokens, item)
            continue
        node = draft
        for segment in tokens[:-1]:
            if not isinstance(node, dict):
                _fail("不能在非对象上修改字段", code="invalid_project_patch")
            if segment not in node:
                if item["op"] == "remove":
                    node = None
                    break
                node[segment] = {}
            node = node[segment]
        if node is None:
            continue
        if not isinstance(node, dict):
            _fail("不能在非对象上修改字段", code="invalid_project_patch")
        last = tokens[-1]
        if item["op"] == "remove":
            node.pop(last, None)
        else:
            if "value" not in item:
                _fail("字段修改缺少 value", code="invalid_project_patch")
            node[last] = deepcopy(item["value"])
    # A view switch changes activeView/editorLayout, never authority. Once a
    # user edits Graph, an unchecked return to Spec would expose a second
    # writable source; explicit future migration must validate reversibility.
    if project["authority"] == "graph" and updated["authority"] == "spec":
        _fail("Graph 项目不能直接切回 Spec 写入权威", status=409,
              code="editor_authority_conflict")
    if updated["authority"] == "graph" and not isinstance(updated["draft"].get("graph"), dict):
        _fail("Graph 写入权威要求存在图形", code="invalid_project_draft")
    if updated["kind"] == "image" and updated["authority"] == "article":
        _fail("单图项目不能使用文章编辑权威", code="invalid_project_authority")
    return updated


def patch_project(db: Any, user: dict[str, Any], project_id: str,
                  body: dict[str, Any]) -> dict[str, Any]:
    uid, project_id = int(user["id"]), _id(project_id)
    base = body.get("baseRevision")
    if type(base) is not int or base < 1:
        _fail("必须提供有效的 baseRevision", code="base_revision_required")
    key = _key(body.get("idempotencyKey"))
    patch = body.get("patch")
    digest = _request_hash("patch", {"baseRevision": base, "patch": patch})
    with db.transaction() as tx:
        row = _project_row(tx, uid, project_id, lock=True)
        previous = _replay(tx, uid, project_id, key, digest)
        if previous:
            return previous
        current = int(row["revision"])
        if base != current:
            _fail("项目在其他标签或设备已更新，请比较差异并另存副本",
                  status=409, code="project_revision_conflict", currentRevision=current)
        before = _row_to_project(row)
        next_state = _apply_patch(before, patch)
        draft_json = _validate_draft(next_state["draft"], tx, uid)
        unchanged = (
            next_state["authority"] == before["authority"]
            and next_state["title"] == before["title"]
            and draft_json == _canonical(before["draft"])
        )
        version = current if unchanged else current + 1
        stamp = str(row["updated_at"]) if unchanged else _now()
        if not unchanged:
            tx.execute(
                """UPDATE studio_projects SET authority=?, title=?, revision=?,
                   draft_json=?, updated_at=? WHERE id=? AND user_id=? AND revision=?""",
                (next_state["authority"], next_state["title"], version,
                 draft_json, stamp, project_id, uid, current),
            )
        response = {"ok": True, "projectId": project_id, "revision": version,
                    "saveState": "synced", "updatedAt": stamp, "unchanged": unchanged}
        _record(tx, uid, project_id, key, digest, response)
        return response


def copy_project(db: Any, user: dict[str, Any], project_id: str,
                 body: dict[str, Any]) -> dict[str, Any]:
    """Conflict recovery: preserve the server's version and create a new ID."""
    uid = int(user["id"])
    project_id = _id(project_id)
    source = _project_row(db.get_conn(), uid, project_id)
    new_id = _id(body.get("newProjectId"), "newProjectId")
    if new_id == project_id:
        _fail("副本必须使用新项目编号", code="invalid_project_id")
    snapshot = body.get("localDraft", json.loads(source["draft_json"]))
    return create_project(db, user, {
        "projectId": new_id,
        "kind": source["kind"],
        "authority": body.get("authority") or source["authority"],
        "title": str(body.get("title") or source["title"])[:140] + " (副本)",
        "draft": snapshot,
        "idempotencyKey": body.get("idempotencyKey"),
    })
