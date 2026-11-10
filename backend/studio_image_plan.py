"""Studio 2.0 single-image AI director: legal catalog-only structured suggestions.

A planning request never generates an image, creates a Run, reserves credits,
or returns protected prompt/black-box definitions. See #110 / #125 / #117.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from .ai_client import chat
from .batch_plan_routes import parse_batch_plan_response
from .db import Database
from .resource_registry import resolve, static_catalog
from .services import ServiceError, consume_daily_usage

log = logging.getLogger(__name__)
_ALLOWED_RATIOS = {"3:4", "1:1", "4:3", "9:16", "16:9", "2.35:1"}


def _rank(subject: str, code: str, text: str) -> tuple[float, str]:
    # Score each real resource using the full directory; never use a fixed
    # first-N catalog prefix. Very short Chinese prompts still get diversity.
    def grams(s: str) -> set[str]:
        s = re.sub(r"\s+", "", s.casefold())
        return {s[i:i + 2] for i in range(len(s) - 1)} or set(s)
    query, searchable = grams(subject), grams(text)
    overlap = len(query & searchable) / max(1, len(query))
    tie = hashlib.sha256((subject + ":" + code).encode("utf-8")).hexdigest()
    return (-overlap, tie)


def _candidates(db: Database, user: dict[str, Any], subject: str, kind: str,
                preferred: str = "") -> list[dict[str, str]]:
    all_options: dict[str, dict[str, str]] = {}
    for code, item in static_catalog().items():
        if str(item.get("kind") or "").lower() != kind:
            continue
        all_options[code] = {
            "id": code, "name": str(item.get("name") or item.get("name_zh") or code),
            "summary": str(item.get("description") or item.get("summary") or "")[:110]
        }
    conn = db.get_conn()
    for row in conn.execute(
        "SELECT code,kind,name,description FROM catalog_assets WHERE kind = ? AND status = 'published'",
        (kind,),
    ).fetchall():
        code = str(row["code"] or "").strip().upper()
        if code:
            all_options[code] = {
                "id": code, "name": str(row["name"] or code),
                "summary": str(row["description"] or "")[:110]
            }
    ranked = sorted(all_options.values(), key=lambda x: _rank(
        subject, x["id"], x["name"] + " " + x["summary"]))
    if preferred:
        preferred = preferred.strip().upper()
        ranked.sort(key=lambda item: 0 if item["id"] == preferred else 1)
    # Resolve ownership / entitlement for each candidate. Never send a
    # hidden or locked asset's definition or a user's unshared asset to AI.
    approved: list[dict[str, str]] = []
    for item in ranked:
        res = resolve(conn, item["id"], viewer=user, purpose="generate")
        if not res or not res.get("canUse"):
            continue
        approved.append({
            "id": item["id"],
            "name": str(res.get("name") or item["name"])[:80],
            "summary": str(res.get("description") or "")[:110]
                if res.get("access", {}).get("canRead") else ""
        })
        if len(approved) >= 40:
            break
    return approved


def execute_image_plan(
    db: Database, user: dict[str, Any], *, subject: str,
    selected_style: str = "", selected_layout: str = "",
    ratio: str = "", locked_fields: list[str] | None = None,
) -> dict[str, Any]:
    if user.get("_auth_kind") == "token":
        raise ServiceError("token_scope_denied", status=403, code="token_disallowed")
    theme = str(subject or "").strip()[:1000]
    if not theme:
        raise ServiceError("请输入创作主题", status=400, code="missing_subject")
    locks = {str(x) for x in (locked_fields or []) if x in ("style", "layout", "ratio")}
    styles = _candidates(db, user, theme, "style", selected_style)
    layouts = _candidates(db, user, theme, "layout", selected_layout)
    if not styles:
        raise ServiceError("没有可用画风，请检查资源授权", status=422, code="style_catalog_empty")
    style_ids, layout_ids = {r["id"] for r in styles}, {r["id"] for r in layouts}
    chosen_style, chosen_layout = selected_style.strip().upper(), selected_layout.strip().upper()
    if chosen_style and chosen_style not in style_ids:
        raise ServiceError("当前画风不存在或无权使用", status=403, code="invalid_style")
    if chosen_layout and chosen_layout not in layout_ids:
        raise ServiceError("当前图型不存在或无权使用", status=403, code="invalid_layout")
    if ratio and ratio not in _ALLOWED_RATIOS:
        raise ServiceError("无效的 AI 规划画幅", status=400, code="invalid_ratio")
    if not consume_daily_usage(db, user["id"], "image_plan", limit=50):
        raise ServiceError("今日 AI 规划次数已达上限", status=429, code="rate_limited")
    request = {
        "theme": theme,
        "styles": styles, "layouts": layouts,
        "current": {"styleId": chosen_style, "layoutId": chosen_layout, "ratio": ratio},
        "lockedFields": sorted(locks),
        "ratios": sorted(_ALLOWED_RATIOS)
    }
    system = (
        "你是 Handraw 插画创作导演。只能从提供的 style/layout ID 清单中挑选，"
        "禁止发明资源编号、泄漏隐藏提示词或自由编造资源。只返回 JSON 对象"
        " {styleId,layoutId,ratio,reason}；理由短于120字。"
        "保持 lockedFields 所指定的既有资源与画幅；不开始实际生图。"
    )
    content, meta = chat([
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(request, ensure_ascii=False)}
    ], json_mode=True, temperature=0.5, timeout=35)
    if not meta.get("ok") or not content:
        log.warning("studio_image_plan_failed stage=upstream reason=%s", str(meta.get("reason") or "empty")[:60])
        raise ServiceError("AI 方案暂不可用，请检查服务后重试", status=503, code="image_plan_unavailable")
    try:
        raw = parse_batch_plan_response(content)
        if not isinstance(raw, dict):
            raise ValueError("not_object")
        style_id = str(raw.get("styleId") or "").strip().upper()
        layout_id = str(raw.get("layoutId") or "").strip().upper()
        proposed_ratio = str(raw.get("ratio") or "").strip()
        if "style" in locks and chosen_style:
            style_id = chosen_style
        if "layout" in locks and chosen_layout:
            layout_id = chosen_layout
        if "ratio" in locks and ratio:
            proposed_ratio = ratio
        if style_id not in style_ids or (layout_id and layout_id not in layout_ids):
            raise ValueError("invalid_resource")
        if proposed_ratio not in _ALLOWED_RATIOS:
            raise ValueError("invalid_ratio")
    except (TypeError, ValueError, KeyError) as err:
        log.warning("studio_image_plan_failed stage=validation reason=%s", str(err)[:40])
        raise ServiceError("AI 返回的资源或格式无效，请重新规划", status=502, code="image_plan_invalid") from None
    # Rationale is AI-written untrusted text, never interpreted as code/HTML.
    return {
        "ok": True,
        "source": "model",
        "proposal": {
            "styleId": style_id,
            "layoutId": layout_id,
            "ratio": proposed_ratio,
            "reason": str(raw.get("reason") or "")[:120]
        },
        "lockedFields": sorted(locks),
        "validResources": {"styles": len(styles), "layouts": len(layouts)}
    }
