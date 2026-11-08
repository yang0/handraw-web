"""Studio #125: one authorized AI planning protocol for image / series / article.

Planning never writes a Project, Run, Item, Work or media. Only a reviewed
CreationSpecPatch / PlanPatch may be applied by the current editor, with CAS.
The model sees full *authorized* catalog metadata, not protected definitions.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from .ai_client import chat
from .batch_plan_routes import parse_batch_plan_response
from .db import Database
from .resource_registry import resolve, static_catalog
from .services import ServiceError, consume_daily_usage
from .studio_projects import get_project
from .studio_resources import _catalog

log = logging.getLogger(__name__)

KINDS = {"image", "series", "article"}
RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9", "2.35:1"}
RESOURCE_ID = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,99}$")
VALID_IMAGE_TYPES = {"process", "concept", "comparison", "infographic", "scene", "mood"}
MODEL_KEYS = {"styleId", "layoutId", "ratio", "reasons", "slots"}
SLOT_KEYS = {"subject", "layoutId", "ratio", "reason", "afterBlockIdx", "role", "imageType", "purpose"}
REASON_KEYS = {"style", "layout", "ratio"}


def fail(code: str, message: str, status: int = 422) -> None:
    raise ServiceError(message, status=status, code=code)


def _user_catalog(db: Database, user: dict[str, Any], subject: str = ""
                  ) -> dict[str, list[dict[str, Any]]]:
    """Enumerate every accessible style/layout, not the first N or a fixed family.

    SQL discovers identities ONLY. resolve() enforces status, entitlement,
    owner and visibility. Never pass raw DB rows or hidden prompts to AI.
    """
    conn = db.get_conn()
    codes = set(static_catalog())
    for query in (
        "SELECT code FROM catalog_assets WHERE kind IN ('style','layout')",
        "SELECT target_id AS code FROM curation_submissions WHERE kind IN ('style','layout')",
        "SELECT code FROM user_resources WHERE kind IN ('style','layout') AND deleted_at IS NULL",
    ):
        try:
            codes.update(str(r["code"]).strip().upper() for r in conn.execute(query).fetchall() if r["code"])
        except Exception as exc:
            # user_resources is an optional future table; any *other* SQL
            # failure must surface, not silently erase resources.
            if "user_resources" not in query:
                raise
            log.debug("optional_user_resources_not_available type=%s", type(exc).__name__)
    result: dict[str, list[dict[str, Any]]] = {"style": [], "layout": []}
    for code in sorted(codes):
        if not RESOURCE_ID.fullmatch(code):
            continue
        resource = resolve(conn, code, viewer=user, purpose="generate")
        if (not resource or resource.get("kind") not in result or
                not resource.get("canUse") or
                not resource.get("access", {}).get("canUse")):
            continue
        can_read = bool(resource.get("access", {}).get("canRead"))
        meta = {"id": code, "name": str(resource.get("name") or code)[:100],
                "purpose": str(resource.get("description") or "")[:200] if can_read else "",
                "source": str(resource.get("source") or "official"),
                "type": resource["kind"]}
        result[resource["kind"]].append(meta)
    # Relevance decides the order in which the entire approved catalog is
    # presented to the model; it never filters out lower-ranking options.
    terms = str(subject or "").casefold().strip()
    tokens = {terms[i:i+2] for i in range(len(terms)-1)} or set(terms)
    def score(item: dict[str, Any]) -> tuple[int, int, str]:
        haystack = (item["id"]+" "+item["name"]+" "+item["purpose"]).casefold()
        grams = {haystack[i:i+2] for i in range(len(haystack)-1)}
        return (-int(bool(terms) and terms in haystack), -len(tokens & grams), item["id"])
    for group in result.values():
        group.sort(key=score)
    return result


def _ref(db: Database, user: dict[str, Any], code: str, kind: str,
         authorized: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    code = str(code or "").strip().upper()
    allowed = {x["id"] for x in authorized[kind]}
    if code not in allowed:
        conn = db.get_conn()
        found = resolve(conn, code, viewer=user, purpose="generate") if RESOURCE_ID.fullmatch(code) else None
        if found and found.get("kind") == kind and not found.get("canUse"):
            fail("ai_resource_forbidden", "AI 推荐了未获授权的资源，请重新规划", 403)
        fail("ai_resource_not_found", "AI 推荐了不存在或无效的画风/图型，未应用方案")
    row = resolve(db.get_conn(), code, viewer=user, purpose="generate")
    if not row or row.get("kind") != kind or not row.get("canUse"):
        fail("ai_resource_forbidden", "AI 推荐的资源已失去使用授权", 403)
    source = str(row.get("source") or "official")
    raw = row.get("_raw_row") or {}
    version = raw.get("revision") or raw.get("version")
    if version is None:
        version = _catalog()[0] if source == "official" and not raw else "current"
    return {"id": code, "type": kind, "source": source, "version": version}


def _upstream(meta: dict[str, Any]) -> None:
    reason = str(meta.get("reason") or "empty")
    log.warning("studio_ai_plan_error category=upstream reason=%s", reason[:35])
    if reason == "http_502":
        fail("ai_upstream_502", "AI 上游返回 HTTP 502，请检查网关后重试", 502)
    if reason == "invalid_json":
        fail("ai_invalid_json", "AI 网关返回的内容不是有效 JSON", 502)
    if reason == "no_key":
        fail("ai_not_configured", "尚未配置 AI 规划服务", 503)
    if reason == "timeout":
        fail("ai_timeout", "AI 规划请求超时，原方案未修改", 504)
    if reason == "http_403" or reason == "http_401":
        fail("ai_upstream_forbidden", "AI 网关拒绝了请求，请检查配置权限", 502)
    fail("ai_unavailable", "AI 规划服务暂不可用，原方案未修改", 503)


def _revision(db: Database, user: dict[str, Any], project_id: str,
              base_revision: int) -> None:
    if not project_id:
        return
    project = get_project(db, user, project_id)["project"]
    if project.get("revision") != base_revision:
        fail("ai_revision_conflict", "项目已被其他编辑更新，旧规划不能应用", 409)


def _valid_reason(obj: Any, name: str, required: bool = True) -> str:
    if not isinstance(obj, str) or (required and not obj.strip()) or len(obj) > 240:
        fail("ai_schema_invalid", "AI 未给出有效的" + name + "推荐理由")
    return obj.strip()[:240]


def _blocks(body: dict[str, Any]) -> list[dict[str, Any]]:
    raw = body.get("blocks")
    if not isinstance(raw, list) or not raw or len(raw) > 200:
        fail("ai_schema_invalid", "文章必须包含有效且有限的正文段落")
    clean = []
    seen = set()
    for block in raw:
        if not isinstance(block, dict) or type(block.get("idx")) is not int:
            fail("ai_schema_invalid", "正文段落编号无效")
        idx = block["idx"]
        if idx < 0 or idx in seen:
            fail("ai_schema_invalid", "正文段落编号重复或无效")
        seen.add(idx)
        clean.append({"idx": idx, "kind": str(block.get("kind") or "p")[:20],
                      "text": str(block.get("text") or "")[:300],
                      "anchorId": str(block.get("anchorId") or "block-" + str(idx))[:128]})
    if not any(b["kind"] in {"p", "h2", "h3", "ul", "blockquote"} and b["text"] for b in clean):
        fail("ai_cannot_recommend", "正文缺少足够的可配图内容，请先补充正文")
    return clean


def execute_ai_plan(db: Database, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    if user.get("_auth_kind") == "token":
        fail("token_disallowed", "请使用网站登录状态执行 AI 规划", 403)
    if not isinstance(body, dict) or body.get("kind") not in KINDS:
        fail("ai_schema_invalid", "规划入口必须是 image、series 或 article", 400)
    kind = body["kind"]
    subject = str(body.get("subject") or body.get("title") or "").strip()
    if not subject or len(subject) > 1000:
        fail("missing_subject", "请输入不超过 1000 字的创作主题", 400)
    base_revision = body.get("baseRevision")
    if type(base_revision) is not int or base_revision < 0:
        fail("ai_revision_required", "AI 规划请求缺少有效 baseRevision", 400)
    project_id = str(body.get("projectId") or "").strip()
    _revision(db, user, project_id, base_revision)
    count = body.get("count", 1 if kind == "image" else 6)
    if type(count) is not int or count < 1 or count > (7 if kind == "article" else 20):
        fail("ai_schema_invalid", "规划张数必须在允许范围内", 400)
    if kind == "image" and count != 1:
        fail("ai_schema_invalid", "单图规划只能包含一个输出", 400)
    existing_slots = body.get("currentSlots") or []
    if not isinstance(existing_slots, list) or len(existing_slots) > 200:
        fail("ai_schema_invalid", "当前槽位列表无效", 400)
    # Only structural IDs and lock names are accepted. No private assets,
    # prompt snapshots, preview URLs, credentials or protected definitions.
    current_slots = []
    for slot in existing_slots:
        if not isinstance(slot, dict):
            fail("ai_schema_invalid", "已有槽位格式无效", 400)
        sid = str(slot.get("slotId") or "").strip()
        if sid and not re.fullmatch(r"[\w:-]{1,128}", sid):
            fail("ai_schema_invalid", "已有 slotId 格式无效", 400)
        current_slots.append({"slotId": sid})
    current = body.get("current") or {}
    if not isinstance(current, dict):
        fail("ai_schema_invalid", "已有配方格式无效", 400)
    # Never include current private image metadata in the model request.
    selected = {k: str(current.get(k) or "")[:100] for k in ("styleId", "layoutId", "ratio")}
    locks = body.get("lockedFields") or []
    if not isinstance(locks, list) or any(not isinstance(k, str) for k in locks):
        fail("ai_schema_invalid", "锁定字段列表无效", 400)
    blocks = _blocks(body) if kind == "article" else []
    # Remote planning does not own the article text; it only receives
    # limited paragraph summaries and returns original stable anchors.
    authorized = _user_catalog(db, user, subject)
    if not authorized["style"] or not authorized["layout"]:
        fail("ai_catalog_empty", "当前没有可用于 AI 规划的已授权画风和图型")
    if not consume_daily_usage(db, user["id"], "studio_ai_plan", limit=50):
        fail("rate_limited", "今日 AI 规划次数已达上限", 429)
    prompt = {
        "kind": kind, "theme": subject, "count": count,
        "allowedStyles": authorized["style"], "allowedLayouts": authorized["layout"],
        "allowedRatios": sorted(RATIOS),
        "current": selected, "lockedFields": locks,
        "articleBlocks": blocks,
        "instruction": (
            "只返回 JSON 对象，精确字段 styleId, layoutId, ratio, reasons, slots。"
            "reasons 为 style/layout/ratio 三个具体理由，各不超过 240 字。"
            "styleId/layoutId 必须从全部授权目录中根据语义选择，不得编造。"
            "ratio 必须来自 allowedRatios。"
            "image: slots=[]；series: slots 含 count 条，每条有 subject,layoutId,ratio,reason；"
            "article: slots 含 count 条，第一条 role=cover 且 afterBlockIdx=-1，"
            "其余 role=illustration 且 afterBlockIdx 必须为真实正文块号，不能重复。"
            "文章条目亦包含 subject,layoutId,ratio,reason。"
            "严格尊重用户锁定和人工修改，AI 仅提出建议，不启动生图。"
        )
    }
    response, meta = chat([
        {"role": "system", "content": "你是严格受资源授权约束的 Handraw 创作方案规划师。"
                                      "只输出 JSON，不含提示词定义、私有素材和可执行脚本。"},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}
    ], json_mode=True, temperature=0.45, timeout=45)
    if not meta.get("ok") or not response:
        _upstream(meta)
    try:
        raw = parse_batch_plan_response(response)
    except (ValueError, TypeError):
        fail("ai_invalid_json", "AI 返回的 JSON 无法解析，未修改任何内容", 502)
    if not isinstance(raw, dict) or set(raw) - MODEL_KEYS or not {
            "styleId", "layoutId", "ratio", "reasons", "slots"} <= set(raw):
        fail("ai_schema_invalid", "AI 返回结构不符合统一方案契约")
    reasons = raw["reasons"]
    if not isinstance(reasons, dict) or set(reasons) != REASON_KEYS:
        fail("ai_schema_invalid", "AI 未提供画风、图型与画幅的字段级理由")
    reasons = {key: _valid_reason(reasons[key], key) for key in REASON_KEYS}
    style = _ref(db, user, raw["styleId"], "style", authorized)
    layout = _ref(db, user, raw["layoutId"], "layout", authorized)
    ratio = raw["ratio"]
    if not isinstance(ratio, str) or ratio not in RATIOS:
        fail("ai_schema_invalid", "AI 推荐了不合法的画幅比例")
    raw_slots = raw["slots"]
    if not isinstance(raw_slots, list) or len(raw_slots) != (0 if kind == "image" else count):
        fail("ai_cannot_recommend", "AI 未返回完整且可用的规划槽位")
    by_index = {b["idx"]: b for b in blocks}
    seen_anchor = set()
    slots = []
    for order, entry in enumerate(raw_slots):
        if not isinstance(entry, dict) or set(entry) - SLOT_KEYS:
            fail("ai_schema_invalid", "AI 返回的槽位字段无效")
        title = entry.get("subject")
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            fail("ai_cannot_recommend", "AI 未能给每张图规划有效主题")
        reason = _valid_reason(entry.get("reason"), "图卡")
        slot_layout = _ref(db, user, entry.get("layoutId"), "layout", authorized)
        slot_ratio = entry.get("ratio")
        if not isinstance(slot_ratio, str) or slot_ratio not in RATIOS:
            fail("ai_schema_invalid", "图卡画幅不在合法范围内")
        slot_id = current_slots[order]["slotId"] if order < len(current_slots) else ""
        slot_id = slot_id or "ai-slot-" + uuid.uuid4().hex[:20]
        result = {"slotId": slot_id, "order": order, "subject": title.strip(),
                  "overrides": {"layout": slot_layout, "ratio": slot_ratio},
                  "reasons": {"subject": reason, "layout": reason, "ratio": reason}}
        if kind == "article":
            is_cover = order == 0
            after = entry.get("afterBlockIdx")
            if type(after) is not int or (is_cover and after != -1) or (
                    not is_cover and after not in by_index):
                fail("ai_anchor_invalid", "文章规划引用了非法段落锚点")
            aid = "cover" if is_cover else by_index[after]["anchorId"]
            if aid in seen_anchor:
                fail("ai_anchor_invalid", "文章插图的锚点重复")
            seen_anchor.add(aid)
            result.update({"anchorId": aid, "afterBlockIdx": after,
                           "anchorText": "" if is_cover else by_index[after]["text"][:24],
                           "role": "cover" if is_cover else "illustration",
                           "purpose": str(entry.get("purpose") or "")[:40],
                           "imageType": str(entry.get("imageType") or "scene")})
            if result["imageType"] not in VALID_IMAGE_TYPES:
                fail("ai_schema_invalid", "文章配图类型无效")
        slots.append(result)
    # Do not force any model value over a user lock; the client must show the
    # difference. Preserve identity and caller's revision for CAS review.
    _revision(db, user, project_id, base_revision)
    return {
        "ok": True, "schemaVersion": 1, "kind": kind, "source": "model",
        "phase": "review", "baseRevision": base_revision,
        "creationSpecPatch": {
            "baseRevision": base_revision,
            "changes": {"style": style, "layout": layout, "ratio": ratio},
            "reasons": reasons,
            "candidates": {
                "style": [
                    next(x for x in authorized["style"] if x["id"] == style["id"]),
                    *[x for x in authorized["style"] if x["id"] != style["id"]][:4]
                ],
                "layout": [
                    next(x for x in authorized["layout"] if x["id"] == layout["id"]),
                    *[x for x in authorized["layout"] if x["id"] != layout["id"]][:4]
                ]
            }
        },
        "planPatch": None if kind == "image" else {
            "baseRevision": body.get("planRevision", 0),
            "kind": "article" if kind == "article" else "story-series",
            "slots": slots
        },
        "validResources": {"styles": len(authorized["style"]),
                           "layouts": len(authorized["layout"])},
        "cost": {"generationStarted": False, "runCreated": False}
    }
