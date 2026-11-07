"""Studio Batch Plan AI / Template Route (Phase 3b-4).

Provides:
- POST /api/studio/batch-plan
  Request: {
    "seed": "都市慢生活与手绘手账",
    "count": 6,
    "layoutMode": "fixed" | "ai",
    "fixedLayout": "SC-021",
    "layoutRequirement": "前 3 张分镜，后面图鉴",
    "styleId": "FE-012"
  }
  Response: { "ok": True, "items": [{ "subject": "...", "layout": "SC-021" }], "source": "model" | "template" }
  Requires login, rate limit 50/day per user (scope="batch_plan"), hwt_ tokens disallowed.
  Calls backend.ai_client.chat outside DB transaction.
  Validates layout codes against official catalog.json and DB catalog_assets.
  Falls back to deterministic template generation when model is unconfigured or fails.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .ai_client import chat
from .config import CONTENT_DIR
from .db import Database
from .services import ServiceError, consume_daily_usage

TEMPLATE_THEME_VARIATIONS = [
    "序章初探 · 晨光微熹与环境空镜",
    "主角特写 · 治愈神态与细腻手绘",
    "核心器物 · 桌面细节与质感排列",
    "场景漫游 · 街角巷陌的人间烟火",
    "互动定格 · 温暖陪伴与生活仪式感",
    "高光时刻 · 灵感绽放与焦点呈现",
    "情绪留白 · 窗外晚霞与慢煮时光",
    "尾声余韵 · 归家夜色与静谧收拢",
    "步骤拆解 · 从零构筑的清晰脉络",
    "全景图鉴 · 经典要素一览汇总",
]


def get_valid_layout_map(db: Database | None = None) -> dict[str, str]:
    """Retrieve all genuinely existing layout codes and their display names."""
    layouts: dict[str, str] = {}

    cat_file = CONTENT_DIR / "catalog.json"
    if cat_file.is_file():
        try:
            data = json.loads(cat_file.read_text(encoding="utf-8"))
            for item in data.get("resources", []):
                iid = str(item.get("id") or "").strip().upper()
                ikind = str(item.get("kind") or "").strip().lower()
                if ikind == "layout" or iid.startswith("SC-") or iid.startswith("SB-") or iid.startswith("IG-"):
                    if iid:
                        layouts[iid] = str(item.get("name") or item.get("name_zh") or iid).strip()
        except Exception:
            pass

    if db:
        try:
            conn = db.get_conn()
            rows = conn.execute(
                "SELECT code, name FROM catalog_assets WHERE kind = 'layout' AND status = 'published'"
            ).fetchall()
            for r in rows:
                code = str(r["code"] or "").strip().upper()
                if code:
                    layouts[code] = str(r["name"] or code).strip()
        except Exception:
            pass

    return layouts


def get_layout_descriptions(valid_layouts: dict[str, str]) -> dict[str, str]:
    """Optional catalog metadata, never a preferred list or example set."""
    descriptions: dict[str, str] = {}
    cat_file = CONTENT_DIR / "catalog.json"
    if not cat_file.is_file():
        return descriptions
    try:
        data = json.loads(cat_file.read_text(encoding="utf-8"))
        for item in data.get("resources", []):
            code = str(item.get("id") or "").strip().upper()
            if code not in valid_layouts:
                continue
            detail = str(item.get("description") or item.get("summary") or "").strip()
            if detail:
                descriptions[code] = re.sub(r"\s+", " ", detail)[:180]
    except (OSError, ValueError, TypeError):
        pass
    return descriptions


def get_style_display_name(style_id: str, db: Database | None = None) -> str:
    """Lookup style name from catalog or DB."""
    clean_id = str(style_id or "").strip().upper()
    if not clean_id:
        return ""

    cat_file = CONTENT_DIR / "catalog.json"
    if cat_file.is_file():
        try:
            data = json.loads(cat_file.read_text(encoding="utf-8"))
            for item in data.get("resources", []):
                if str(item.get("id") or "").strip().upper() == clean_id:
                    name = str(item.get("name") or item.get("name_zh") or "").strip()
                    return f"{clean_id} ({name})" if name else clean_id
        except Exception:
            pass

    if db:
        try:
            conn = db.get_conn()
            row = conn.execute(
                "SELECT code, name FROM catalog_assets WHERE code = ? AND kind = 'style' AND status = 'published'",
                (clean_id,),
            ).fetchone()
            if row:
                name = str(row["name"] or "").strip()
                return f"{clean_id} ({name})" if name else clean_id
        except Exception:
            pass

    return clean_id


def generate_template_batch_plan(
    seed: str,
    count: int,
    layout_mode: str,
    fixed_layout: str,
    layout_requirement: str,
    valid_layouts: dict[str, str],
) -> list[dict[str, str]]:
    """Deterministic fallback generator for batch set planning."""
    cnt = max(1, min(20, count))
    clean_seed = str(seed or "").strip() or "都市慢生活手绘手账"
    short_seed = re.sub(r"[。！!？?\n]+.*$", "", clean_seed)[:22]

    # Determine layout candidates
    req_lower = str(layout_requirement or "").strip().lower()
    candidate_layouts: list[str] = []

    if layout_mode == "fixed" and fixed_layout:
        candidate_layouts = [fixed_layout.upper()]
    else:
        # AI recommendations never use fixed templates or curated code lists.
        raise ValueError("AI layout recommendations require the model")

    items: list[dict[str, str]] = []
    for i in range(cnt):
        var = TEMPLATE_THEME_VARIATIONS[i % len(TEMPLATE_THEME_VARIATIONS)]
        cycle = i // len(TEMPLATE_THEME_VARIATIONS)
        cycle_suffix = f"（卷{cycle + 1}）" if cycle > 0 else ""
        subject = f"【{short_seed}】{var}{cycle_suffix}"[:120]

        layout = (
            fixed_layout.upper()
            if layout_mode == "fixed" and fixed_layout
            else candidate_layouts[i % len(candidate_layouts)]
        )
        items.append({"subject": subject, "layout": layout})

    return items


def execute_batch_plan(
    db: Database,
    user: dict[str, Any],
    seed: str,
    count: int = 6,
    layout_mode: str = "fixed",
    fixed_layout: str = "",
    layout_requirement: str = "",
    style_id: str = "",
) -> dict[str, Any]:
    if user.get("_auth_kind") == "token":
        raise ServiceError("token_scope_denied", status=403, code="token_disallowed")

    clean_seed = str(seed or "").strip()
    if not clean_seed:
        raise ServiceError("母题不能为空", status=400, code="invalid_param")

    try:
        cnt = int(count)
    except (ValueError, TypeError):
        cnt = 6
    cnt = max(1, min(20, cnt))

    norm_mode = "ai" if str(layout_mode or "").strip().lower() == "ai" else "fixed"
    norm_fixed_layout = str(fixed_layout or "").strip().upper()
    norm_style_id = str(style_id or "").strip().upper()
    clean_req = str(layout_requirement or "").strip()

    # Valid layouts lookup
    valid_layouts = get_valid_layout_map(db)

    # Validate fixed layout in fixed mode
    default_layout_used = False
    if norm_mode == "fixed":
        if not norm_fixed_layout:
            default_candidates = sorted(valid_layouts)
            if not default_candidates:
                raise ServiceError("暂无可用图型目录", status=503, code="layout_catalog_empty")
            seed_hash = sum(ord(c) for c in clean_seed)
            norm_fixed_layout = default_candidates[seed_hash % len(default_candidates)]
            default_layout_used = True
        elif norm_fixed_layout not in valid_layouts:
            raise ServiceError("指定的固定图型编号不存在或非法", status=400, code="invalid_fixed_layout")

    # Rate limiting: 50 requests/day per user
    if not consume_daily_usage(db, user["id"], "batch_plan", limit=50):
        raise ServiceError("今日套图规划次数已达上限（50次/天），请明天再试", status=429, code="rate_limited")

    # Use the complete catalog; no first-N sampling or code-family favoritism.
    if norm_mode == "ai" and not valid_layouts:
        raise ServiceError("暂无可用图型，无法推荐", status=503, code="layout_catalog_empty")
    descriptions = get_layout_descriptions(valid_layouts)
    layout_options_str = "\n".join(
        f"{code}: {valid_layouts[code]}" + (f" — {descriptions[code]}" if code in descriptions else "")
        for code in sorted(valid_layouts)
    )
    style_display = get_style_display_name(norm_style_id, db)

    # AI Model call outside DB transaction
    system_prompt = (
        "你是手绘插画套图策划。根据用户提供的创作母题、画风特征与图型要求，"
        "规划一套风格统一、叙事连贯、版式丰富的手绘插画套图。"
    )
    user_prompt = (
        f"创作母题：{clean_seed}\n"
        f"套图张数：{cnt} 张\n"
        f"画风：{style_display or '未指定（保持手绘统一感）'}\n"
        f"图型策略：{'固定图型（全部使用 ' + norm_fixed_layout + '）' if norm_mode == 'fixed' else 'AI 推荐图型（每张按主题匹配，不强制不同）'}\n"
        f"图型要求：{clean_req or '无特殊要求，根据画面内容契合度搭配最适合的图型'}\n\n"
        "完整可用图型目录（只能从中选，不能按编号顺序或默认偏好选择）：\n"
        f"{layout_options_str}\n\n"
        "输出规则：\n"
        "1. 只输出 JSON 对象；顶层只有 items 数组，每条仅有 subject 和 layout 字段。禁止附加示例。\n"
        f"2. 必须恰好返回 {cnt} 条 items，主题不重复、紧扣本次母题；每条不超过120字，无编号。\n"
        "3. layout 必须来自完整目录，按每条主题的画面内容、信息密度及叙事需求匹配。\n"
        f"4. {'固定模式全部使用用户指定的图型。' if norm_mode == 'fixed' else 'AI 模式允许语义合理重复，禁止轮换固定编号。'}\n"
        "5. 不使用历史示例、few-shot、默认图型或预设搭配。只输出合法 JSON。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    response_text, meta = chat(messages, temperature=0.7, timeout=30.0)

    if norm_mode == "ai" and (not meta.get("ok") or not response_text):
        raise ServiceError("AI 图型推荐不可用，请检查 AI 服务配置后重试", status=503, code="batch_plan_ai_unavailable")

    items: list[dict[str, str]] = []
    if meta.get("ok") and response_text:
        try:
            clean_json = response_text.strip()
            if "```" in clean_json:
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_json)
                if match:
                    clean_json = match.group(1).strip()
            parsed = json.loads(clean_json)
            raw_items = parsed.get("items") if isinstance(parsed, dict) else None
            if not isinstance(raw_items, list):
                raise ValueError("items must be an array")
            seen_subjects: set[str] = set()
            for raw_it in raw_items:
                if not isinstance(raw_it, dict):
                    raise ValueError("invalid item")
                subj = str(raw_it.get("subject") or "").strip()
                subj = re.sub(r"^(?:[0-9]+[.\-、]\s*|[\-*•]\s*|#\d+\s*)", "", subj).strip()
                if not subj or subj in seen_subjects:
                    raise ValueError("missing or duplicate subject")
                seen_subjects.add(subj)
                cand_lyt = str(raw_it.get("layout") or "").strip().upper()
                if norm_mode == "fixed":
                    lyt = norm_fixed_layout
                elif cand_lyt in valid_layouts:
                    lyt = cand_lyt
                else:
                    raise ValueError("model returned an unavailable layout")
                items.append({"subject": subj[:120], "layout": lyt})
            if len(items) != cnt:
                raise ValueError("wrong item count")
        except (ValueError, TypeError, KeyError):
            if norm_mode == "ai":
                raise ServiceError("AI 推荐结果不完整或包含无效图型，请重试", status=502, code="batch_plan_ai_invalid")
            items = []

    if items:
        res = {"ok": True, "items": items, "source": "model"}
        if default_layout_used:
            res["defaultLayoutUsed"] = True
        return res

    if norm_mode == "ai":
        raise ServiceError("AI 图型推荐没有返回有效结果，请重试", status=502, code="batch_plan_ai_invalid")

    # Fixed mode only: deterministic offline plan remains available.
    template_items = generate_template_batch_plan(
        clean_seed, cnt, norm_mode, norm_fixed_layout, clean_req, valid_layouts
    )
    res = {"ok": True, "items": template_items, "source": "template"}
    if default_layout_used:
        res["defaultLayoutUsed"] = True
    return res


def handle_batch_plan_post(handler: Any, req_path: str, body: dict[str, Any]) -> bool:
    if req_path == "/api/studio/batch-plan":
        user = handler._current_user(required=True)
        res = execute_batch_plan(
            handler.db,
            user,
            seed=str(body.get("seed") or ""),
            count=body.get("count", 6),
            layout_mode=str(body.get("layoutMode") or "fixed"),
            fixed_layout=str(body.get("fixedLayout") or ""),
            layout_requirement=str(body.get("layoutRequirement") or ""),
            style_id=str(body.get("styleId") or ""),
        )
        handler._send_json(res)
        return True
    return False
