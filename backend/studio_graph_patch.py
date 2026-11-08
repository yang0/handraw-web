"""Studio 2.0 #126: review-first, owner-authorized, reversible GraphPatch.

Only Project.draft.graph is mutable. Reviews are durable one-use records, not
untrusted client-signed patches. Preview never writes Graph, Run, Item, Work,
Artifact or gateway ledger. Apply/revert use owner + CAS in one transaction.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .services import ServiceError, get_site_settings
from .studio_projects import (_canonical, _id, _now, _project_row,
                              _row_to_project, _validate_draft)
from .studio_resources import check_media_owner, check_resource_ref

_NODE_TYPES = {"text_input", "skill_params", "asset", "output_control", "output_display",
               "bridge", "loop", "fission", "article_plan"}
_EDITABLE_TYPES = {"text_input", "skill_params", "asset", "output_control", "bridge"}
_FIELDS = {
    "text_input": {"text"},
    "skill_params": {"style1", "style2", "layout", "fusion", "colors", "tones",
                     "audience", "businessScene", "moods", "resourceRefs"},
    "asset": {"items"},
    "output_control": {"ratio", "count", "mode"},
    "bridge": {"ratios"},
}
_LOCK_ALIAS = {"text": "subject", "style1": "style", "style2": "secondaryStyle"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,99}$")
_RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9", "2.35:1"}
_PRESETS = {"seasons", "platforms", "style_compare"}
_OPS = {"addNode", "removeNode", "setNodeData", "addEdge", "removeEdge"}
_MAX_OPS = 80
_TTL_SECONDS = 1800


def _error(code: str, message: str, status: int = 422, **extra: Any) -> None:
    raise ServiceError(message, code=code, status=status, extra=extra or None)


def _owner(user: dict[str, Any]) -> int:
    if user.get("_auth_kind") == "token":
        _error("graphpatch_login_required", "AI 画布编辑必须使用网站登录态", 403)
    return int(user["id"])


def _id_valid(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def _version(graph: dict[str, Any]) -> int:
    val = graph.get("revision", 0)
    if type(val) is not int or val < 0:
        _error("graphpatch_invalid_graph", "Graph revision 必须为非负整数")
    return val


def _graph(project: dict[str, Any]) -> dict[str, Any]:
    if project["authority"] != "graph":
        _error("graphpatch_authority", "请先在画布中保存为 Graph 项目", 409)
    graph = project["draft"].get("graph")
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) \
            or not isinstance(graph.get("edges"), list):
        _error("graphpatch_invalid_graph", "项目缺少合法 Graph")
    return graph


def _check_graph(graph: dict[str, Any]) -> None:
    nodes, edges = graph["nodes"], graph["edges"]
    if len(nodes) > 600 or len(edges) > 2000:
        _error("graphpatch_too_large", "Graph 超过当前安全编辑上限")
    ids = set()
    types = {}
    for n in nodes:
        if not isinstance(n, dict) or not _id_valid(n.get("id")) or \
                n.get("type") not in _NODE_TYPES or not isinstance(n.get("data", {}), dict):
            _error("graphpatch_invalid_node", "Graph 节点身份或类型无效")
        if n["id"] in ids:
            _error("graphpatch_duplicate_node", "Graph 存在重复节点")
        ids.add(n["id"])
        types[n["id"]] = n["type"]
    edge_ids, adjacent = set(), {ident: [] for ident in ids}
    for e in edges:
        if not isinstance(e, dict) or not _id_valid(e.get("id")) or \
                e["id"] in edge_ids or e.get("from") not in ids or \
                e.get("to") not in ids or e["from"] == e["to"]:
            _error("graphpatch_invalid_edge", "Graph 连线缺失、重复或自连接")
        if types[e["to"]] in {"text_input", "skill_params", "fission"}:
            _error("graphpatch_invalid_edge", "输入/风格节点不能作为连线目标")
        if types[e["to"]] == "output_display" and \
                types[e["from"]] not in {"output_control", "article_plan"}:
            _error("graphpatch_invalid_edge", "成图展示只能由生成或文章方案驱动")
        edge_ids.add(e["id"])
        adjacent[e["from"]].append(e["to"])
    # Iterative Kahn topological order: handles large Graphs without recursion.
    indegree = {i: 0 for i in ids}
    for targets in adjacent.values():
        for target in targets:
            indegree[target] += 1
    queue = [i for i, count in indegree.items() if count == 0]
    seen = 0
    while queue:
        v = queue.pop()
        seen += 1
        for dst in adjacent[v]:
            indegree[dst] -= 1
            if indegree[dst] == 0:
                queue.append(dst)
    if seen != len(ids):
        _error("graphpatch_cycle", "GraphPatch 会产生循环依赖，未修改项目")


def _authorized_ref(tx: Any, user: dict[str, Any], raw: Any, kind: str) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or not _ID.fullmatch(raw):
        _error("graphpatch_invalid_resource", "资源编号非法")
    # resolve uses the actual viewer's canUse entitlement, not the front-end
    # list or values supplied by an LLM.
    from .resource_registry import resolve
    row = resolve(tx, raw, viewer=user, purpose="generate")
    if not row or row.get("kind") != kind:
        _error("graphpatch_resource_not_found", "资源不存在或已失效")
    if not row.get("canUse") or not row.get("access", {}).get("canUse"):
        _error("graphpatch_resource_forbidden", "该画风/图型未授权", 403)
    source = str(row.get("source") or "official")
    metadata = row.get("_raw_row") or {}
    ver = metadata.get("revision") or metadata.get("version")
    if ver is None:
        from .studio_resources import _catalog
        ver = _catalog()[0] if source == "official" and not metadata else "current"
    ref = {"id": raw, "type": kind, "source": source, "version": ver}
    check_resource_ref(ref, kind, tx, user)
    return ref


def _clean_data(node_type: str, field: str, value: Any, tx: Any,
                user: dict[str, Any]) -> Any:
    if field not in _FIELDS.get(node_type, set()):
        _error("graphpatch_protected_field", "不能修改运行状态、成果或受保护节点字段", 403)
    if field in {"style1", "style2", "layout"}:
        return _authorized_ref(tx, user, value, "layout" if field == "layout" else "style")
    if field == "resourceRefs":
        _error("graphpatch_protected_field", "资源引用由服务端派生，不能直接写入", 403)
    if field == "items":
        if not isinstance(value, list) or len(value) > 12:
            _error("graphpatch_invalid_media", "图片参数数量无效")
        sanitized = []
        for item in value:
            if not isinstance(item, dict) or set(item) - {"mediaId", "role"}:
                _error("graphpatch_invalid_media", "图片必须通过 MediaRef 引用")
            check_media_owner(item.get("mediaId"), tx, int(user["id"]))
            role = item.get("role", "other")
            if role not in {"character", "scene", "object", "composition", "result", "other"}:
                _error("graphpatch_invalid_media", "媒体用途无效")
            sanitized.append({"mediaId": item["mediaId"], "role": role})
        return sanitized
    if field in {"colors", "tones"}:
        if not isinstance(value, list) or len(value) > 20:
            _error("graphpatch_invalid_resource", "多选资源必须是有效列表")
        kind = "color" if field == "colors" else "tone"
        for ref in value:
            check_resource_ref(ref, kind, tx, user)
        return deepcopy(value)
    if field == "moods":
        if not isinstance(value, list) or len(value) > 10 or \
                any(not isinstance(s, str) or len(s) > 60 for s in value):
            _error("graphpatch_invalid_field", "情绪标签无效")
        return deepcopy(value)
    if field == "fusion":
        if type(value) is not bool:
            _error("graphpatch_invalid_field", "融合参数必须为布尔值")
        return value
    if field == "count":
        if type(value) is not int or not 1 <= value <= 200:
            _error("graphpatch_invalid_count", "生成数量只允许 1–200")
        return value
    if field == "ratio":
        if not isinstance(value, str) or value not in _RATIOS:
            _error("graphpatch_invalid_ratio", "画幅比例不在允许范围内")
        return value
    if field == "ratios":
        if not isinstance(value, list) or not 1 <= len(value) <= 6 or \
                any(not isinstance(r, str) or r not in _RATIOS for r in value):
            _error("graphpatch_invalid_ratio", "多平台画幅无效")
        return deepcopy(value)
    if field == "mode":
        if not isinstance(value, str) or value not in {"graphic-text", "series", "article-illust", "photo"}:
            _error("graphpatch_invalid_mode", "生成模式无效")
        return value
    if not isinstance(value, str) or len(value) > (2000 if field == "text" else 200):
        _error("graphpatch_invalid_field", "文本字段不合法或过长")
    return value


def _assign(node: dict[str, Any], field: str, value: Any, tx: Any,
            user: dict[str, Any]) -> None:
    cleaned = _clean_data(node["type"], field, value, tx, user)
    data = node.setdefault("data", {})
    if field in ("style1", "style2", "layout"):
        aliases = {"style1": "style", "style2": "secondaryStyle", "layout": "layout"}
        key = aliases[field]
        refs = data.setdefault("resourceRefs", {})
        if not isinstance(refs, dict):
            _error("graphpatch_invalid_resource", "已有资源元数据无效")
        refs[key] = cleaned
        data[field] = cleaned["id"] if cleaned else ""
    else:
        data[field] = cleaned


def _lock(node: dict[str, Any], field: str) -> bool:
    locks = node.get("data", {}).get("lockedFields", [])
    return isinstance(locks, list) and (field in locks or _LOCK_ALIAS.get(field, field) in locks)


def _protected_result(node: dict[str, Any]) -> bool:
    if node["type"] in {"output_display", "article_plan"}:
        return True
    data = node.get("data") or {}
    return any(k in data for k in ("runId", "requestId", "studio2RunSnapshot",
                                  "items", "artifactId", "mediaId",
                                  "generationId", "runSnapshot")) or            data.get("status") in {"running", "generating", "success", "partial"}


def _candidate(graph: dict[str, Any], operations: Any, tx: Any,
               user: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]],
                                               list[dict[str, str]]]:
    if not isinstance(operations, list) or not 1 <= len(operations) <= _MAX_OPS:
        _error("graphpatch_invalid_ops", "GraphPatch 操作数量无效")
    next_graph = deepcopy(graph)
    nodes = next_graph["nodes"]
    edges = next_graph["edges"]
    diffs = []
    conflicts = []
    for seq, op in enumerate(operations):
        if not isinstance(op, dict) or op.get("op") not in _OPS:
            _error("graphpatch_invalid_ops", "不支持的 GraphPatch 操作")
        kind = op["op"]
        if kind == "addNode":
            if set(op) != {"op", "node"} or not isinstance(op["node"], dict):
                _error("graphpatch_invalid_ops", "新节点结构无效")
            src = op["node"]
            if set(src) - {"id", "type", "title", "x", "y", "w", "h", "data"} or \
                    not _id_valid(src.get("id")) or src.get("type") not in _EDITABLE_TYPES or \
                    not isinstance(src.get("data", {}), dict):
                _error("graphpatch_invalid_node", "新增节点不能包含运行结果或非法字段")
            if any(n["id"] == src["id"] for n in nodes):
                _error("graphpatch_duplicate_node", "新增节点编号已存在")
            node = {"id": src["id"], "type": src["type"],
                    "title": str(src.get("title") or src["type"])[:64], "data": {},
                    "x": src.get("x", 0), "y": src.get("y", 0)}
            for pos_key in ("x", "y"):
                val = node[pos_key]
                if type(val) not in (int, float) or not math.isfinite(val) or abs(val) > 100000:
                    _error("graphpatch_invalid_node", "新增节点坐标无效")
            for dim in ("w", "h"):
                if dim in src:
                    val = src[dim]
                    if type(val) not in (int, float) or not math.isfinite(val) \
                            or not 100 <= val <= 2000:
                        _error("graphpatch_invalid_node", "新增节点尺寸无效")
                    node[dim] = val
            for key, value in src.get("data", {}).items():
                _assign(node, key, value, tx, user)
            nodes.append(node)
            diffs.append({"index": seq, "op": kind, "path": "nodes/" + node["id"],
                          "before": None, "after": {"type": node["type"],
                          "title": node["title"]}})
        elif kind == "removeNode":
            if set(op) != {"op", "id"} or not _id_valid(op["id"]):
                _error("graphpatch_invalid_ops", "删除节点操作无效")
            target = next((n for n in nodes if n["id"] == op["id"]), None)
            if not target:
                _error("graphpatch_node_missing", "要删除的节点不存在")
            if target["type"] not in _EDITABLE_TYPES or _protected_result(target):
                _error("graphpatch_protected_node", "不能删除已有成果、运行或文章节点", 403)
            if target.get("data", {}).get("lockedFields"):
                conflicts.append({"nodeId": op["id"], "field": "*", "code": "locked_node"})
            if any(e["from"] == op["id"] or e["to"] == op["id"] for e in edges):
                _error("graphpatch_connected_node", "删除节点前必须显式删除所连接的连线")
            if not conflicts:
                nodes.remove(target)
            diffs.append({"index": seq, "op": kind, "path": "nodes/" + op["id"],
                          "before": {"type": target["type"], "title": target.get("title")},
                          "after": None})
        elif kind == "setNodeData":
            if set(op) != {"op", "id", "field", "value"} or not _id_valid(op["id"]):
                _error("graphpatch_invalid_ops", "修改节点参数操作无效")
            target = next((n for n in nodes if n["id"] == op["id"]), None)
            if not target:
                _error("graphpatch_node_missing", "修改目标节点不存在")
            if target["type"] not in _EDITABLE_TYPES or _protected_result(target):
                _error("graphpatch_protected_node", "不能修改已有运行或媒体结果", 403)
            field = op["field"]
            if not isinstance(field, str) or field not in _FIELDS[target["type"]] or \
                    field == "resourceRefs":
                _error("graphpatch_protected_field", "字段不允许由 GraphPatch 修改", 403)
            old = deepcopy(target.get("data", {}).get(field))
            if _lock(target, field):
                conflicts.append({"nodeId": target["id"], "field": field,
                                  "code": "locked_field"})
                # Still validate proposed resources/media so preview cannot
                # be abused as an authorization or probing oracle.
                _clean_data(target["type"], field, op["value"], tx, user)
            else:
                _assign(target, field, op["value"], tx, user)
            diffs.append({"index": seq, "op": kind,
                          "path": "nodes/" + target["id"] + "/data/" + field,
                          "before": old,
                          "after": deepcopy(target["data"].get(field)) if not _lock(target, field)
                          else "[已锁定 · 未应用]"})
        elif kind == "addEdge":
            if set(op) != {"op", "edge"} or not isinstance(op["edge"], dict) or \
                    set(op["edge"]) != {"id", "from", "to"} or \
                    not all(_id_valid(op["edge"][k]) for k in ("id", "from", "to")):
                _error("graphpatch_invalid_edge", "新增连线格式无效")
            if any(e["id"] == op["edge"]["id"] for e in edges):
                _error("graphpatch_duplicate_edge", "新增连线编号已存在")
            edges.append(deepcopy(op["edge"]))
            diffs.append({"index": seq, "op": kind, "path": "edges/" + op["edge"]["id"],
                          "before": None, "after": deepcopy(op["edge"])})
        elif kind == "removeEdge":
            if set(op) != {"op", "id"} or not _id_valid(op["id"]):
                _error("graphpatch_invalid_edge", "删除连线格式无效")
            edge = next((e for e in edges if e["id"] == op["id"]), None)
            if not edge:
                _error("graphpatch_edge_missing", "要删除的连线不存在")
            if any(n["id"] in (edge["from"], edge["to"]) and _protected_result(n)
                   for n in nodes):
                _error("graphpatch_protected_edge", "不允许重写已有运行结果的关系", 403)
            edges.remove(edge)
            diffs.append({"index": seq, "op": kind, "path": "edges/" + op["id"],
                          "before": deepcopy(edge), "after": None})
    _check_graph(next_graph)
    next_graph["revision"] = _version(graph) + 1
    return next_graph, diffs, conflicts


def _impact(before: dict[str, Any], after: dict[str, Any], db: Any) -> dict[str, Any]:
    def count(graph: dict[str, Any]) -> int:
        total = 0
        for n in graph["nodes"]:
            if n["type"] == "output_control":
                val = n.get("data", {}).get("count", 1)
                total += max(1, min(200, int(val) if type(val) is int else 1))
        return total
    more = max(0, count(after) - count(before))
    settings = get_site_settings(db.get_conn())
    unit = int(settings.get("economy", {}).get("studio_credit_per_image", 2))
    return {"additionalPotentialImages": more,
            "estimatedAdditionalCredits": more * unit,
            "creditPerImage": unit, "chargedNow": False,
            "generationStarted": False, "estimateOnly": True}


def _preset(graph: dict[str, Any], preset: str, selected: list[str],
            body: dict[str, Any], tx: Any, user: dict[str, Any]) -> list[dict[str, Any]]:
    if preset not in _PRESETS:
        _error("graphpatch_invalid_preset", "画布操作不受支持")
    nodes = graph["nodes"]
    pick = next((n for n in nodes if n["id"] in selected), None)
    subject = next((n for n in nodes if n["type"] == "text_input"), None)
    style = next((n for n in nodes if n["type"] == "skill_params"), None)
    base_control = next((n for n in nodes if n["type"] == "output_control"), None)
    if not subject or not base_control:
        _error("graphpatch_missing_source", "请先创建含文本与生成设置的画布")
    ident = "gp" + uuid.uuid4().hex[:12]
    position_x = float((pick or base_control).get("x", 300)) + 430
    position_y = float((pick or base_control).get("y", 200))
    ops: list[dict[str, Any]] = []
    def add(t: str, suffix: str, x: float, y: float,
            data: dict[str, Any], title: str) -> str:
        nid = ident + suffix
        ops.append({"op": "addNode", "node": {"id": nid, "type": t,
                    "title": title, "x": x, "y": y, "data": data}})
        return nid
    def edge(src: str, dst: str, suffix: str) -> None:
        ops.append({"op": "addEdge",
                    "edge": {"id": ident + "e" + suffix, "from": src, "to": dst}})
    ratio = base_control.get("data", {}).get("ratio", "3:4")
    if not isinstance(ratio, str) or ratio not in _RATIOS:
        ratio = "3:4"
    if preset == "seasons":
        origin = pick if pick and pick["type"] == "text_input" else subject
        theme = str(origin.get("data", {}).get("text") or "保留原主题")[:380]
        for i, season in enumerate(("春", "夏", "秋", "冬")):
            y = position_y + 250 * i
            txt = add("text_input", "t" + str(i), position_x, y,
                      {"text": theme + " · " + season + "季氛围与构图"}, season + "季主题")
            control = add("output_control", "c" + str(i), position_x + 420, y,
                          {"mode": "graphic-text", "ratio": ratio, "count": 1},
                          season + "季生成")
            edge(txt, control, "t" + str(i))
            if style:
                edge(style["id"], control, "s" + str(i))
            if pick and pick["type"] == "output_display":
                edge(pick["id"], control, "r" + str(i))
    elif preset == "platforms":
        for i, (title, aspect) in enumerate((("公众号头图", "2.35:1"),
                    ("小红书", "3:4"), ("抖音竖版", "9:16"))):
            control = add("output_control", "p" + str(i),
                          position_x + i * 430, position_y + i * 250,
                          {"mode": "graphic-text", "ratio": aspect, "count": 1},
                          title)
            edge(subject["id"], control, "t" + str(i))
            if style:
                edge(style["id"], control, "s" + str(i))
    else:
        styles = body.get("styleIds")
        if not isinstance(styles, list) or len(styles) != 2 or styles[0] == styles[1]:
            _error("graphpatch_styles_required", "请明确选择两个不同的已授权画风")
        for i, style_id in enumerate(styles):
            _authorized_ref(tx, user, style_id, "style")
            st = add("skill_params", "s" + str(i),
                     position_x, position_y + i * 350,
                     {"style1": style_id}, "横评画风 " + str(i + 1))
            control = add("output_control", "x" + str(i),
                          position_x + 450, position_y + i * 350,
                          {"mode": "graphic-text", "ratio": ratio, "count": 1},
                          "横评生成 " + str(i + 1))
            edge(st, control, "s" + str(i))
            edge(subject["id"], control, "t" + str(i))
    return ops


def _ai_operations(db: Any, user: dict[str, Any], graph: dict[str, Any],
                   instruction: str, selected: list[str]) -> list[dict[str, Any]]:
    # The model sees only identities/types and a user-submitted instruction.
    # No raw text, preview URLs, private media, resource definitions, run IDs,
    # prompt recipes, or local image data leave the server in this request.
    from .ai_client import chat
    from .batch_plan_routes import parse_batch_plan_response
    from .studio_ai_plan import _user_catalog
    catalog = _user_catalog(db, user, instruction)
    # Only identities and display names for resources the actual user may use.
    # Never serialize private prompt bodies, resource definitions or images.
    approved = {
        kind: [{"id": row["id"], "name": row["name"]}
               for row in catalog[kind]]
        for kind in ("style", "layout")
    }
    abstract = {"instruction": instruction, "selectedIds": selected,
                "authorizedResources": approved,
                "nodes": [{"id": n["id"], "type": n["type"]}
                          for n in graph["nodes"][:300]],
                "edges": [{"id": e["id"], "from": e["from"], "to": e["to"]}
                          for e in graph["edges"][:1000]],
                "allowedOperations": sorted(_OPS),
                "allowedNewTypes": sorted(_EDITABLE_TYPES),
                "allowedFields": {k: sorted(v - {"resourceRefs"}) for k, v in _FIELDS.items()},
                "instructionForModel": ("返回单个 JSON 对象，仅含 operations 数组。"
                    "每条操作为 addNode(node)、removeNode(id)、setNodeData(id,field,value)、"
                    "addEdge(edge:{id,from,to}) 或 removeEdge(id)。"
                    "新增 ID 必须唯一，由英文字母/数字/下划线组成；"
                    "新画风与图型 ID 必须取自 authorizedResources，不得编造编号；"
                    "不要编辑 output_display/article_plan 的既有结果。"
                    "不得创建引用私有图片 URL、资源秘方、状态字段或运行记录。"
                    "只能提出供用户确认的变更，不触发生成。")}
    answer, meta = chat([
        {"role": "system", "content": "你是 GraphPatch 严格结构编辑器，只返回 JSON。"
                                      "现有图的任何文本/私有媒体均不可猜测。"},
        {"role": "user", "content": json.dumps(abstract, ensure_ascii=False)}
    ], json_mode=True, temperature=0.15, timeout=45)
    if not meta.get("ok") or not answer:
        _error("graphpatch_ai_unavailable", "AI 未返回有效画布方案，图形未变化", 502)
    try:
        obj = parse_batch_plan_response(answer)
    except (TypeError, ValueError):
        _error("graphpatch_ai_invalid_json", "AI 返回了非 JSON 的 GraphPatch", 502)
    if not isinstance(obj, dict) or set(obj) != {"operations"}:
        _error("graphpatch_ai_schema", "AI GraphPatch 不符合结构化协议")
    return obj["operations"]


def _selected(graph: dict[str, Any], value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 80 or \
            any(not isinstance(v, str) for v in value):
        _error("graphpatch_invalid_selection", "选中子图格式无效")
    allowed = {n["id"] for n in graph["nodes"]}
    if any(v not in allowed for v in value):
        _error("graphpatch_invalid_selection", "所选节点不属于当前项目")
    return list(dict.fromkeys(value))


def _scope(operations: Any, graph: dict[str, Any], selected: list[str],
           scope: Any) -> str:
    """Constrain existing-node mutations to the explicitly selected subgraph."""
    if scope not in ("project", "selection"):
        _error("graphpatch_invalid_scope", "GraphPatch 作用域必须是项目或选中子图", 400)
    if scope == "project":
        return scope
    if not selected:
        _error("graphpatch_selection_required", "请先选择子图节点，或改用整个项目作用域", 400)
    existing = {n["id"] for n in graph["nodes"]}
    new_ids = {o.get("node", {}).get("id") for o in operations
               if isinstance(o, dict) and o.get("op") == "addNode"
               and isinstance(o.get("node"), dict)}
    edge_by_id = {e["id"]: e for e in graph["edges"]}
    for op in operations:
        if not isinstance(op, dict):
            _error("graphpatch_invalid_ops", "补丁操作无效")
        kind = op.get("op")
        if kind in {"removeNode", "setNodeData"} and op.get("id") not in selected:
            _error("graphpatch_scope_forbidden", "此操作超出所选节点范围", 403)
        if kind == "removeEdge":
            e = edge_by_id.get(op.get("id"))
            if e and e["from"] not in selected and e["to"] not in selected:
                _error("graphpatch_scope_forbidden", "不能删除所选子图外的连线", 403)
        if kind == "addEdge":
            e = op.get("edge")
            if isinstance(e, dict) and not (
                e.get("from") in selected or e.get("to") in selected or
                e.get("from") in new_ids or e.get("to") in new_ids
            ):
                _error("graphpatch_scope_forbidden", "连线修改超出所选子图范围", 403)
    return scope


def preview(db: Any, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    uid = _owner(user)
    if not isinstance(body, dict):
        _error("graphpatch_invalid_request", "预览参数格式无效", 400)
    project_id = _id(body.get("projectId"))
    base = body.get("baseRevision")
    graph_revision = body.get("graphRevision")
    if type(base) is not int or base < 1 or type(graph_revision) is not int or graph_revision < 0:
        _error("graphpatch_revision_required", "必须指定项目和图形基线版本", 400)
    mode = body.get("mode")
    generated_ops = None
    if mode == "ai":
        instruction = body.get("instruction")
        if not isinstance(instruction, str) or not 2 <= len(instruction.strip()) <= 800:
            _error("graphpatch_invalid_instruction", "请输入 2–800 字的修改说明", 400)
        # Do not hold any transaction/writer lock across a 45-second model
        # request. Read owner-scoped context, call the LLM, then re-check
        # the identical CAS baseline under the exclusive commit transaction.
        initial = _project_row(db.get_conn(), uid, project_id)
        if int(initial["revision"]) != base:
            _error("project_revision_conflict", "项目已变化，请刷新后重新规划", 409)
        source_graph = _graph(_row_to_project(initial))
        if _version(source_graph) != graph_revision:
            _error("graphpatch_revision_conflict", "Graph 版本已变化", 409)
        _check_graph(source_graph)
        selected = _selected(source_graph, body.get("selectedIds"))
        from .services import consume_daily_usage
        if not consume_daily_usage(db, uid, "studio_graphpatch_ai", limit=30):
            _error("graphpatch_ai_rate_limit", "今日画布 AI 规划次数已达到上限", 429)
        generated_ops = _ai_operations(db, user, source_graph,
                                       instruction.strip(), selected)
    with db.transaction() as tx:
        row = _project_row(tx, uid, project_id, lock=True)
        if int(row["revision"]) != base:
            _error("project_revision_conflict", "项目已被其他设备更新，请重新载入", 409,
                   currentRevision=int(row["revision"]))
        graph = _graph(_row_to_project(row))
        if _version(graph) != graph_revision:
            _error("graphpatch_revision_conflict", "Graph 版本已变化，请重新预览", 409)
        _check_graph(graph)
        selected = _selected(graph, body.get("selectedIds"))
        scope = body.get("scope", "project")
        if mode == "preset":
            ops = _preset(graph, body.get("preset"), selected, body, tx, user)
        elif mode == "ai":
            ops = generated_ops
        elif mode == "operations":
            ops = body.get("operations")
        else:
            _error("graphpatch_invalid_mode", "请选择 AI 或预置的结构化操作", 400)
        scope = _scope(ops, graph, selected, scope)
        after, diffs, conflicts = _candidate(graph, ops, tx, user)
        next_draft = deepcopy(json.loads(row["draft_json"]))
        next_draft["graph"] = after
        # Validate in the transaction even for preview; no database mutation
        # of the Project and no permission bypass via a generated ID.
        _validate_draft(next_draft, tx, uid)
        impact = _impact(graph, after, db)
        preview_data = {"operations": len(ops), "diffs": diffs,
                        "scope": scope, "selectedIds": selected,
                        "summary": {"nodesAdded": sum(o["op"] == "addNode" for o in ops),
                                    "nodesRemoved": sum(o["op"] == "removeNode" for o in ops),
                                    "fieldsChanged": sum(o["op"] == "setNodeData" for o in ops),
                                    "edgesAdded": sum(o["op"] == "addEdge" for o in ops),
                                    "edgesRemoved": sum(o["op"] == "removeEdge" for o in ops)},
                        "costImpact": impact, "conflicts": conflicts}
        review_id = "gpr" + uuid.uuid4().hex
        tx.execute("""INSERT INTO studio_graphpatch_reviews
            (id,user_id,project_id,base_revision,graph_revision,before_graph_json,
             operations_json,preview_json,status,created_at)
            VALUES (?,?,?,?,?,?,?,?, 'pending',?)""",
            (review_id, uid, project_id, base, graph_revision,
             _canonical(graph), _canonical(ops), _canonical(preview_data), _now()))
        # Prevent unbounded stale review records for this account/project.
        tx.execute("""DELETE FROM studio_graphpatch_reviews
            WHERE user_id=? AND project_id=? AND status='pending' AND id<>?
            AND created_at < ?""",
            (uid, project_id, review_id,
             datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()-86400,
                                    timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")))
    return {"ok": True, "schemaVersion": 1, "phase": "review",
            "reviewId": review_id, "projectId": project_id,
            "baseRevision": base, "graphRevision": graph_revision,
            "canApply": not conflicts, **preview_data,
            "generated": "preset" if mode == "preset" else mode,
            "execution": {"generationStarted": False, "chargedNow": False}}


def _review(tx: Any, user_id: int, raw: Any) -> Any:
    if not isinstance(raw, str) or not re.fullmatch(r"gpr[0-9a-f]{32}", raw):
        _error("graphpatch_review_missing", "审阅记录不存在", 404)
    row = tx.execute("SELECT * FROM studio_graphpatch_reviews WHERE id=? AND user_id=?",
                     (raw, user_id)).fetchone()
    if not row:
        _error("graphpatch_review_missing", "审阅记录不存在", 404)
    created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
    if (datetime.now(timezone.utc) - created).total_seconds() > _TTL_SECONDS \
            and row["status"] == "pending":
        _error("graphpatch_review_expired", "预览已过期，请重新生成", 409)
    return row


def apply(db: Any, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    uid = _owner(user)
    if not isinstance(body, dict) or body.get("confirmed") is not True:
        _error("graphpatch_confirmation_required", "必须先预览并明确确认应用", 409)
    with db.transaction() as tx:
        review = _review(tx, uid, body.get("reviewId"))
        if review["status"] == "applied":
            return json.loads(review["response_json"])
        if review["status"] != "pending":
            _error("graphpatch_review_closed", "该补丁已经撤销或关闭", 409)
        row = _project_row(tx, uid, review["project_id"], lock=True)
        if int(row["revision"]) != int(review["base_revision"]):
            _error("project_revision_conflict", "项目已被其他标签修改，不能应用旧补丁", 409)
        before = _graph(_row_to_project(row))
        if _version(before) != int(review["graph_revision"]) or \
                _canonical(before) != review["before_graph_json"]:
            _error("graphpatch_revision_conflict", "画布已修改，请重新预览", 409)
        ops = json.loads(review["operations_json"])
        reviewed_context = json.loads(review["preview_json"])
        _scope(ops, before, reviewed_context.get("selectedIds", []),
               reviewed_context.get("scope", "project"))
        next_graph, _, conflicts = _candidate(before, ops, tx, user)
        if conflicts:
            _error("graphpatch_locked_field", "存在锁定节点/字段，必须先解决冲突", 409,
                   conflicts=conflicts)
        draft = json.loads(row["draft_json"])
        draft["graph"] = next_graph
        draft_json = _validate_draft(draft, tx, uid)
        new_rev = int(row["revision"]) + 1
        stamp = _now()
        result = {"ok": True, "phase": "applied", "reviewId": review["id"],
                  "projectId": review["project_id"], "projectRevision": new_rev,
                  "graphRevision": next_graph["revision"], "graph": next_graph,
                  "canUndo": True, "generationStarted": False,
                  "chargedNow": False}
        updated = tx.execute("""UPDATE studio_projects SET draft_json=?,revision=?,
            updated_at=? WHERE id=? AND user_id=? AND revision=?""",
            (draft_json, new_rev, stamp, row["id"], uid, row["revision"]))
        if updated.rowcount != 1:
            _error("project_revision_conflict", "项目在确认时发生并发修改", 409)
        tx.execute("""UPDATE studio_graphpatch_reviews
            SET status='applied',applied_revision=?,response_json=? WHERE id=? AND user_id=?""",
            (new_rev, _canonical(result), review["id"], uid))
        return result


def undo(db: Any, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    uid = _owner(user)
    if not isinstance(body, dict) or body.get("confirmed") is not True:
        _error("graphpatch_confirmation_required", "撤销必须由用户明确触发", 409)
    with db.transaction() as tx:
        review = _review(tx, uid, body.get("reviewId"))
        if review["status"] == "reverted":
            return {"ok": True, "phase": "reverted", "reviewId": review["id"],
                    "alreadyReverted": True, "chargedNow": False}
        if review["status"] != "applied":
            _error("graphpatch_undo_unavailable", "补丁尚未应用，无法撤销", 409)
        project = _project_row(tx, uid, review["project_id"], lock=True)
        if int(project["revision"]) != int(review["applied_revision"]):
            _error("graphpatch_undo_conflict", "已有其他项目修改，不能覆盖；请先处理版本冲突",
                   409, currentRevision=int(project["revision"]))
        prior = json.loads(review["before_graph_json"])
        current_graph = _graph(_row_to_project(project))
        # Graph revision is monotonic: a rollback is a fresh CAS write,
        # never resurrecting an old revision that later stale AI could target.
        prior["revision"] = _version(current_graph) + 1
        draft = json.loads(project["draft_json"])
        draft["graph"] = prior
        draft_json = _validate_draft(draft, tx, uid)
        next_rev = int(project["revision"]) + 1
        updated = tx.execute("""UPDATE studio_projects SET draft_json=?,revision=?,
            updated_at=? WHERE id=? AND user_id=? AND revision=?""",
            (draft_json, next_rev, _now(), project["id"], uid, project["revision"]))
        if updated.rowcount != 1:
            _error("graphpatch_undo_conflict", "项目已被其他设备修改", 409)
        tx.execute("""UPDATE studio_graphpatch_reviews SET status='reverted'
                      WHERE id=? AND user_id=?""", (review["id"], uid))
        return {"ok": True, "phase": "reverted", "reviewId": review["id"],
                "projectId": review["project_id"], "projectRevision": next_rev,
                "graphRevision": prior["revision"], "graph": prior,
                "chargedNow": False, "generationStarted": False}


def list_styles(db: Any, user: dict[str, Any]) -> dict[str, Any]:
    """Only public/authorized identities and display names, never recipes."""
    _owner(user)
    from .studio_ai_plan import _user_catalog
    authorized = _user_catalog(db, user)
    return {"ok": True, "styles": [
        {"id": s["id"], "name": s["name"]} for s in authorized["style"]
    ]}
