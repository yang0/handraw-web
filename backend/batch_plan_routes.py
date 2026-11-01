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

# Curated fallback layouts for template generation
DEFAULT_TEMPLATE_LAYOUTS = [
    "SC-001", "SC-006", "SC-020", "SC-021", "SC-023",
    "IG-001", "IG-003", "IG-005", "SB-001", "SB-002",
]

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
        # Check requirement hints
        if "分镜" in req_lower:
            candidate_layouts.extend([k for k in valid_layouts if k.startswith("SB-")][:6])
        if "图鉴" in req_lower or "科普" in req_lower:
            candidate_layouts.extend([k for k in valid_layouts if k.startswith("IG-")][:6])
        if "卡片" in req_lower or "封面" in req_lower or "社交" in req_lower:
            candidate_layouts.extend([k for k in valid_layouts if k.startswith("SC-")][:6])

        # Fill with default layouts if candidates are insufficient
        for d in DEFAULT_TEMPLATE_LAYOUTS:
            if d in valid_layouts and d not in candidate_layouts:
                candidate_layouts.append(d)

        if not candidate_layouts:
            candidate_layouts = list(valid_layouts.keys())[:10] or ["SC-001"]

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
    if norm_mode == "fixed":
        if not norm_fixed_layout or norm_fixed_layout not in valid_layouts:
            raise ServiceError("指定的固定图型编号不存在或非法", status=400, code="invalid_fixed_layout")

    # Rate limiting: 50 requests/day per user
    if not consume_daily_usage(db, user["id"], "batch_plan", limit=50):
        raise ServiceError("今日套图规划次数已达上限（50次/天），请明天再试", status=429, code="rate_limited")

    # Prepare available layout options (limit to <= 40 items)
    sample_options: list[str] = []
    # Prioritize SC, IG, SB families
    for prefix in ("SC-", "IG-", "SB-", "IP-", "EC-"):
        matching = [f"{k}: {valid_layouts[k]}" for k in valid_layouts if k.startswith(prefix)]
        sample_options.extend(matching[:10])
        if len(sample_options) >= 40:
            break
    if len(sample_options) < 40:
        for k, v in valid_layouts.items():
            entry = f"{k}: {v}"
            if entry not in sample_options:
                sample_options.append(entry)
            if len(sample_options) >= 40:
                break

    layout_options_str = "\n".join(sample_options[:40])
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
        f"图型策略：{'固定图型（全部使用 ' + norm_fixed_layout + '）' if norm_mode == 'fixed' else 'AI 推荐图型（每张选择不同版式）'}\n"
        f"图型要求：{clean_req or '无特殊要求，根据画面内容契合度搭配最适合的图型'}\n\n"
        "可选图型编号及名称清单（图型编号必须从中选用）：\n"
        f"{layout_options_str}\n\n"
        "输出规则：\n"
        "1. 输出严格的 JSON 格式，必须包含且仅包含以下结构：\n"
        '{"items": [{"subject": "画面具体描述或创作主题", "layout": "图型编号"}]}\n'
        f"2. 必须恰好返回 {cnt} 条 items，互不重复，叙事层层递进或从不同切角展开。\n"
        "3. 每条主题描述不超过 120 字，不要带有序号或编号标记（如 1. - * 等）。\n"
        f"4. 每条的 layout 必须是清单中真实存在的图型编号；若图型策略为固定图型，所有条目的 layout 均填写为 {norm_fixed_layout}。\n"
        "5. 不要输出任何代码块以外的解释或寒暄，直接输出合法 JSON。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    response_text, meta = chat(messages, temperature=0.7, timeout=30.0)

    items: list[dict[str, str]] = []
    if meta.get("ok") and response_text:
        try:
            # Strip markdown json blocks if wrapped
            clean_json = response_text.strip()
            if "```" in clean_json:
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_json)
                if match:
                    clean_json = match.group(1).strip()

            parsed = json.loads(clean_json)
            raw_items = parsed.get("items") if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])

            if isinstance(raw_items, list):
                seen_subjects: set[str] = set()
                for raw_it in raw_items:
                    if not isinstance(raw_it, dict):
                        continue
                    subj = str(raw_it.get("subject") or raw_it.get("theme") or "").strip()
                    # Strip bullet / numbering prefix
                    subj = re.sub(r"^(?:[0-9]+[.\-、]\s*|[\-*•]\s*|#\d+\s*)", "", subj).strip()
                    if not subj:
                        continue
                    subj = subj[:120]
                    if subj in seen_subjects:
                        continue
                    seen_subjects.add(subj)

                    # Validate layout
                    if norm_mode == "fixed":
                        lyt = norm_fixed_layout
                    else:
                        cand_lyt = str(raw_it.get("layout") or "").strip().upper()
                        if cand_lyt in valid_layouts:
                            lyt = cand_lyt
                        else:
                            # Discard invalid layout from AI; fallback to fixed_layout if valid or empty
                            lyt = norm_fixed_layout if (norm_fixed_layout and norm_fixed_layout in valid_layouts) else ""

                    items.append({"subject": subj, "layout": lyt})
                    if len(items) >= cnt:
                        break
        except Exception:
            items = []

    if items:
        # If AI generated fewer than cnt items, pad with template items
        if len(items) < cnt:
            template_pad = generate_template_batch_plan(
                clean_seed, cnt, norm_mode, norm_fixed_layout, clean_req, valid_layouts
            )
            for pad_it in template_pad:
                if len(items) >= cnt:
                    break
                if pad_it["subject"] not in {it["subject"] for it in items}:
                    items.append(pad_it)

        return {"ok": True, "items": items[:cnt], "source": "model"}

    # Fallback to deterministic template logic
    template_items = generate_template_batch_plan(
        clean_seed, cnt, norm_mode, norm_fixed_layout, clean_req, valid_layouts
    )
    return {"ok": True, "items": template_items, "source": "template"}


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
