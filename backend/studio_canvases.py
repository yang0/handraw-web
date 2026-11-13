"""Independent parameter canvases and bounded, deterministic batch expansion."""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
import re
import uuid

_PARAMETERS = {
    "prompt",
    "style1",
    "style2",
    "layout",
    "ratio",
    "refImages",
    "colors",
    "tones",
    "moods",
    "whitespace",
    "mode",
}
_RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9", "2.35:1", "3:2", "2:3"}
MAX_OUTPUTS = 200
_NODE_TYPES = {"parameter", "parameters", "combine", "output"}
_DEFAULTS = {
    "style1": "",
    "style2": "",
    "layout": "",
    "ratio": "3:4",
    "refImages": [],
    "colors": [],
    "tones": [],
    "moods": [],
    "whitespace": "",
    "mode": "graphic-text",
}


def _error(message, *, status=400, code="invalid_canvas"):
    from .services import ServiceError

    return ServiceError(message, status=status, code=code)


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def validate_canvas_document(graph):
    """A saved draft may be incomplete, but its structure must remain bounded."""
    if (
        not isinstance(graph, dict)
        or not isinstance(graph.get("nodes"), list)
        or not isinstance(graph.get("edges"), list)
    ):
        raise _error("画布需要节点和连线")
    try:
        size = len(_canonical(graph).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise _error("画布数据格式无效") from exc
    if size > 1_000_000 or len(graph["nodes"]) > 200 or len(graph["edges"]) > 400:
        raise _error("画布大小超限")
    ids = set()
    for node in graph["nodes"]:
        if not isinstance(node, dict) or node.get("type") not in _NODE_TYPES:
            raise _error("参数画布只支持参数、组合和输出节点")
        key = node.get("id")
        if not isinstance(key, str) or not key or len(key) > 160 or key in ids:
            raise _error("节点编号缺失或重复")
        ids.add(key)
        for axis in ("x", "y"):
            if axis in node and (
                type(node[axis]) not in (int, float)
                or not math.isfinite(node[axis])
                or not -50000 <= node[axis] <= 50000
            ):
                raise _error("画布节点位置无效")
    for edge in graph["edges"]:
        if (
            not isinstance(edge, dict)
            or edge.get("from") not in ids
            or edge.get("to") not in ids
        ):
            raise _error("连线指向不存在的节点")


def compile_canvas(graph):
    """Each parameter value is atomic: fusion styles and reference sets stay together."""
    validate_canvas_document(graph)
    if not 1 <= len(graph["nodes"]) <= 200 or len(graph["edges"]) > 400:
        raise _error("画布节点或连线数量无效")
    nodes = {}
    for node in graph["nodes"]:
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("id"), str)
            or not node["id"]
            or node["id"] in nodes
        ):
            raise _error("节点编号缺失或重复")
        if node.get("type") not in _NODE_TYPES:
            raise _error("参数画布只支持参数、组合和输出节点")
        nodes[node["id"]] = node
    incoming = {key: [] for key in nodes}
    edges = set()
    for edge in graph["edges"]:
        if (
            not isinstance(edge, dict)
            or edge.get("from") not in nodes
            or edge.get("to") not in nodes
        ):
            raise _error("连线指向不存在的节点")
        key = (edge["from"], edge["to"])
        if key in edges:
            raise _error("画布包含重复连线")
        edges.add(key)
        if nodes[key[0]]["type"] == "output":
            raise _error("输出节点是终点，不能继续连接其他节点")
        incoming[key[1]].append(key[0])
    active, cache = set(), {}

    def merge(rows):
        result = {}
        for row in rows:
            for key, value in row.items():
                if key in result:
                    raise _error(f"参数 {key} 被多次赋值，请将候选放在同一参数节点中")
                result[key] = value
        return result

    def candidates(parameter, values):
        if (
            not isinstance(parameter, str)
            or parameter not in _PARAMETERS
            or not isinstance(values, list)
            or not 1 <= len(values) <= MAX_OUTPUTS
        ):
            raise _error("参数名称或候选列表无效")
        rows = []
        for value in values:
            if parameter == "style1" and isinstance(value, dict):
                if (
                    set(value) - {"style1", "style2"}
                    or not value.get("style1")
                    or not all(isinstance(v, str) for v in value.values())
                ):
                    raise _error("融合画风需要主画风和可选副画风")
                row = dict(value)
            else:
                row = {parameter: value}
            if parameter == "refImages" and (
                not isinstance(value, list)
                or len(value) > 6
                or not all(isinstance(v, str) for v in value)
            ):
                raise _error("每个参考图候选必须是最多六张图片组成的一组")
            if parameter in ("colors", "tones", "moods") and (
                not isinstance(value, list)
                or not all(isinstance(v, str) for v in value)
            ):
                raise _error("配色、影调和氛围候选必须为字符串数组")
            if parameter in ("colors", "tones", "moods") and (
                len(value) > 10 or any(len(v) > 128 for v in value)
            ):
                raise _error("单套配色、影调或氛围方案过大")
            if parameter not in (
                "refImages",
                "colors",
                "tones",
                "moods",
                "style1",
            ) and not isinstance(value, str):
                raise _error("参数候选必须为字符串")
            if parameter == "style1" and not isinstance(value, (str, dict)):
                raise _error("画风候选格式无效")
            if parameter == "prompt" and (not value.strip() or len(value) > 4000):
                raise _error("主题不能为空且不能超过 4000 字符")
            if parameter == "ratio" and value not in _RATIOS:
                raise _error("图片比例无效")
            if parameter == "mode" and value not in ("graphic-text", "image-only", "poster"):
                raise _error("请选择纯图、图文或海报模式")
            if parameter == "whitespace" and len(value) > 256:
                raise _error("留白说明过长")
            rows.append(row)
        return rows

    def combine(sources, mode, repeat):
        if mode not in ("cartesian", "zip"):
            raise _error("请选择全组合或按行搭配")
        lengths = [len(source) for source in sources]
        if mode == "zip":
            count = max(lengths)
            if any(size not in (1, count) for size in lengths):
                raise _error("按行搭配的长度必须相同，固定单值可复用")
            groups = (
                [source[0 if len(source) == 1 else i] for source in sources]
                for i in range(count)
            )
        else:
            count = 1
            for size in lengths:
                count *= size
            groups = itertools.product(*sources)
        if type(repeat) is not int or repeat < 1 or repeat > MAX_OUTPUTS:
            raise _error("重复张数必须为 1–200 的整数")
        if count * repeat > MAX_OUTPUTS:
            raise _error("组合超过 200 张，请拆分批次", code="canvas_output_limit")
        rows = [
            copy.deepcopy(merge(group)) for group in groups for _ in range(repeat)
        ]
        return rows

    def expand(key):
        if key in active:
            raise _error("画布存在环路")
        if key in cache:
            return cache[key]
        active.add(key)
        node = nodes[key]
        kind = node["type"]
        if kind in ("parameter", "parameters"):
            if incoming[key]:
                raise _error("参数节点不能接收输入")
            if kind == "parameter":
                rows = candidates(node.get("parameter"), node.get("values"))
            else:
                fields = node.get("fields")
                if not isinstance(fields, dict) or not fields:
                    raise _error("出图参数至少需要一个字段")
                # JSONB can reorder keys. Keep the preview order stable after a save.
                order = node.get("fieldOrder")
                if order is None:
                    order = sorted(fields, key=lambda field: (field != "prompt", field))
                elif (
                    not isinstance(order, list)
                    or len(order) != len(fields)
                    or not all(isinstance(field, str) for field in order)
                    or set(order) != set(fields)
                ):
                    raise _error("出图参数顺序无效")
                sources = [candidates(field, fields[field]) for field in order]
                rows = combine(sources, node.get("mode", "cartesian"), 1)
        else:
            sources = [expand(source) for source in incoming[key]]
            if not sources:
                raise _error("组合或输出节点尚未连接参数")
            rows = combine(
                sources,
                node.get("mode", "cartesian"),
                node.get("repeat", 1) if kind == "output" else 1,
            )
        active.remove(key)
        cache[key] = rows
        return rows

    for key in nodes:
        expand(key)
    outputs = [node for node in graph["nodes"] if node["type"] == "output"]
    if not outputs:
        raise _error("画布需要至少一个输出节点")
    rows = []
    for output in outputs:
        for spec in cache[output["id"]]:
            if not str(spec.get("prompt") or "").strip():
                raise _error("输出组合缺少主题")
            ordinal = len(rows)
            effective = {**copy.deepcopy(_DEFAULTS), **spec}
            for field in ("style1", "style2", "layout"):
                effective[field] = str(effective[field]).strip().upper().lstrip("#")
            rows.append(
                {"ordinal": ordinal, "outputNodeId": output["id"], "spec": effective}
            )
            if len(rows) > MAX_OUTPUTS:
                raise _error(
                    "总输出超过 200 张，请拆分批次", code="canvas_output_limit"
                )
    return rows


def save_canvas(db, user, body):
    if body.get("articleId") or body.get("formId") or body.get("recipeId"):
        raise _error("参数画布不关联文章或其他表单")
    graph = body.get("graph")
    validate_canvas_document(graph)
    cid = str(body.get("id") or "canvas_" + uuid.uuid4().hex)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", cid):
        raise _error("画布编号无效")
    with db.transaction() as tx:
        tx.execute("SELECT pg_advisory_xact_lock(hashtextextended(?,209))", (cid,))
        row = tx.execute(
            "SELECT * FROM studio_canvases WHERE id=? FOR UPDATE", (cid,)
        ).fetchone()
        if row and (row["user_id"] != user["id"] or row["deleted_at"]):
            raise _error("画布不存在", status=404, code="canvas_not_found")
        base = body.get("baseWriteSeq", 0)
        name = str(body.get("name") or "参数组合画布")[:100]
        if type(base) is not int:
            raise _error("画布保存序号无效")
        if row and row["name"] == name and row["graph_json"] == graph:
            return {"ok": True, "id": row["id"], "writeSeq": row["write_seq"]}
        if base != (row["write_seq"] if row else 0):
            raise _error("画布已在其他窗口修改", status=409, code="canvas_conflict")
        result = tx.execute(
            "INSERT INTO studio_canvases(id,user_id,name,graph_json) VALUES(?,?,?,?::jsonb) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name,graph_json=excluded.graph_json,"
            "write_seq=studio_canvases.write_seq+1,updated_at=now() RETURNING id,write_seq",
            (cid, user["id"], name, _canonical(graph)),
        ).fetchone()
    return {"ok": True, "id": result["id"], "writeSeq": result["write_seq"]}


def get_canvas(db, user, cid):
    row = (
        db.get_conn()
        .execute(
            "SELECT * FROM studio_canvases WHERE id=? AND user_id=? AND deleted_at IS NULL",
            (cid, user["id"]),
        )
        .fetchone()
    )
    if not row:
        raise _error("画布不存在", status=404, code="canvas_not_found")
    return {
        "ok": True,
        "canvas": {
            "id": row["id"],
            "name": row["name"],
            "graph": row["graph_json"],
            "writeSeq": row["write_seq"],
        },
    }


def quote_count(quote, count):
    free = min(count, quote["freeRemaining"])
    total = (count - free) * quote["unitPrice"]
    return {
        **quote,
        "count": count,
        "freeUsed": free,
        "paidCount": count - free,
        "total": total,
        "affordable": quote["balance"] >= total,
    }


def preview_canvas(db, user, cid, *, _include_resources=False):
    canvas = get_canvas(db, user, cid)["canvas"]
    items = compile_canvas(canvas["graph"])
    from . import resource_registry
    from .recipe_routes import validate_recipe_media

    assets, references = {}, set()
    for item in items:
        spec = item["spec"]
        for key in ("style1", "style2", "layout"):
            code = str(spec.get(key) or "").upper()
            if not code or code in assets:
                continue
            resource = resource_registry.resolve(
                db.get_conn(), code, viewer=user, purpose="generate"
            )
            if not resource or not resource.get("canUse"):
                raise _error(
                    "组合包含不可使用的资源", status=403, code="asset_unavailable"
                )
            if resource.get("kind") != ("layout" if key == "layout" else "style"):
                raise _error("画风和图型编号类型不匹配", code="asset_kind_mismatch")
            inject = (resource.get("access") or {}).get("inject")
            definition = resource.get("_raw_definition") or ""
            if not definition and resource.get("source_type") == "official":
                definition = (resource_registry.static_catalog().get(code) or {}).get("definition") or ""
            assets[code] = {
                "inject": inject,
                "name": resource.get("name") or code,
                "_raw_definition": definition,
                "secret_blackbox_prompt": resource.get("secret_blackbox_prompt") or "",
                "private": inject == "blackbox"
                or int(resource.get("unlock_cost") or 0) > 0
                or resource.get("source_type") == "exclusive",
            }
        refs = spec.get("refImages") or []
        ref_key = tuple(refs)
        if ref_key not in references:
            clean = validate_recipe_media(db, int(user["id"]), refs)
            if clean != refs:
                raise _error("参考图格式无效", code="invalid_references")
            for ref in refs:
                if ref.startswith("/images/") and ".." not in ref.split("/"):
                    continue
                owned = (
                    db.get_conn()
                    .execute(
                        "SELECT 1 FROM user_uploads WHERE user_id=? AND image_url=? AND deleted_at IS NULL "
                        "UNION ALL SELECT 1 FROM studio_generation_media WHERE user_id=? AND media_url=? "
                        "UNION ALL SELECT 1 FROM media_assets WHERE owner_user_id=? AND storage_key=? LIMIT 1",
                        (user["id"], ref, user["id"], ref, user["id"], ref),
                    )
                    .fetchone()
                )
                if not owned:
                    raise _error(
                        "参考图不可用，请从个人素材中重新选择",
                        status=403,
                        code="foreign_media",
                    )
            references.add(ref_key)
    from .services import get_site_settings, get_wallet_quota_state

    settings = get_site_settings(db.get_conn())
    wallet = get_wallet_quota_state(db.get_conn(), user["id"], settings)
    quote = quote_count(
        {
            "unitPrice": max(
                0, int(settings.get("economy", {}).get("studio_credit_per_image", 2))
            ),
            "freeRemaining": wallet["freeQuotaRemaining"],
            "balance": wallet["balance"],
        },
        len(items),
    )
    digest = hashlib.sha256(
        _canonical(
            {
                "items": items,
                "resources": assets,
                "unitPrice": quote["unitPrice"],
                "freeRemaining": quote["freeRemaining"],
            }
        ).encode()
    ).hexdigest()
    result = {
        "ok": True,
        "items": items,
        "count": len(items),
        "planHash": digest,
        "writeSeq": canvas["writeSeq"],
        "quote": quote,
    }
    if _include_resources:
        result["_resources"] = assets
    return result


def submit_canvas(db, user, cid, body):
    key = str(body.get("requestId") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", key):
        raise _error("提交需要稳定的 requestId")
    previous = (
        db.get_conn()
        .execute(
            "SELECT * FROM generation_runs WHERE user_id=? AND source='web' AND external_run_id=?",
            (user["id"], key),
        )
        .fetchone()
    )
    if previous:
        plan = previous["plan_json"]
        selected = body.get("ordinals", list(range(plan.get("previewCount", 0))))
        if (
            previous["canvas_id"] != cid
            or not plan
            or body.get("planHash") != plan.get("planHash")
            or not isinstance(selected, list)
            or any(type(n) is not int for n in selected)
            or len(set(selected)) != len(selected)
            or sorted(selected) != plan.get("selectedOrdinals")
        ):
            raise _error(
                "请求编号已用于另一份组合清单",
                status=409,
                code="canvas_request_conflict",
            )
        return _run_response(previous["id"], key, plan["items"])
    preview = preview_canvas(db, user, cid, _include_resources=True)
    if body.get("planHash") != preview["planHash"]:
        raise _error(
            "组合清单已变化，请重新预览", status=409, code="canvas_plan_changed"
        )
    selected = body.get("ordinals", [item["ordinal"] for item in preview["items"]])
    if (
        not isinstance(selected, list)
        or not selected
        or any(type(n) is not int for n in selected)
        or len(set(selected)) != len(selected)
        or not set(selected) <= set(range(preview["count"]))
    ):
        raise _error("选择的组合无效")
    items = [item for item in preview["items"] if item["ordinal"] in selected]
    quote = quote_count(preview["quote"], len(items))
    max_credits = body.get("maxCredits", quote["total"])
    if (
        type(max_credits) is not int
        or max_credits < quote["total"]
        or not quote["affordable"]
    ):
        raise _error(
            "本次预计积分不足，请减少张数或重新确认费用",
            status=409,
            code="canvas_budget_required",
        )
    from .generation_v3 import ensure_run, _stable_id
    from .db import utc_now_iso

    plan = {
        "canvasId": cid,
        "planHash": preview["planHash"],
        "items": items,
        "previewCount": preview["count"],
        "selectedOrdinals": sorted(selected),
        "resourceInputs": preview["_resources"],
        "unitPrice": quote["unitPrice"],
        "maxCredits": max_credits,
    }
    with db.transaction() as tx:
        rid = ensure_run(
            tx,
            user_id=user["id"],
            source="web",
            external_run_id=key,
            expected_count=len(items),
            request_id=key,
        )
        run = tx.execute(
            "SELECT * FROM generation_runs WHERE id=? FOR UPDATE", (rid,)
        ).fetchone()
        if (
            run["plan_json"]
            and run["plan_json"] != plan
            or run["canvas_id"]
            and run["canvas_id"] != cid
            or run["creation_mode"] not in ("other", "canvas")
        ):
            raise _error(
                "请求编号已用于另一份组合清单",
                status=409,
                code="canvas_request_conflict",
            )
        tx.execute(
            "UPDATE generation_runs SET creation_mode='canvas',canvas_id=?,plan_json=?::jsonb WHERE id=?",
            (cid, _canonical(plan), rid),
        )
        for index, item in enumerate(items):
            tx.execute(
                "INSERT INTO generation_items(id,run_id,position,ordinal,status,spec_json,created_at,updated_at) "
                "VALUES(?,?,?,?,'pending',?::jsonb,?,?) ON CONFLICT(run_id,position) DO NOTHING",
                (
                    _stable_id("item", rid, index),
                    rid,
                    index,
                    index,
                    _canonical(item["spec"]),
                    utc_now_iso(),
                    utc_now_iso(),
                ),
            )
    return _run_response(rid, key, items)


def _run_response(rid, key, items):
    from .generation_v3 import _stable_id

    return {
        "ok": True,
        "runId": rid,
        "batchId": key,
        "count": len(items),
        "items": [
            {
                "itemId": _stable_id("item", rid, index),
                "batchIndex": index,
                "spec": item["spec"],
            }
            for index, item in enumerate(items)
        ],
    }
