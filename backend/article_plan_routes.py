"""Studio Article Plan AI / Template Route (Phase 3b-5).

Provides:
- POST /api/studio/article-plan
  Request: {
    "articleId": "art_xxx",
    "title": "留白工作法",
    "blocks": [{ "idx": 0, "kind": "h1", "text": "留白工作法" }, ...],
    "charCount": 3200,
    "styleId": "FA-001",
    "coverRatio": "2.35:1",
    "inlineRatio": "4:3",
    "includeCover": true
  }
  Response: {
    "ok": True,
    "source": "model" | "template",
    "articleType": "knowledge" | "narrative",
    "cover": { "subject": "...", "purpose": "..." },
    "illustrations": [
      {
        "afterBlockIdx": 2,
        "anchorText": "...",
        "subject": "...",
        "purpose": "...",
        "layout": "IG-013",
        "imageType": "process"
      }
    ],
    "warnings": []
  }

Requires login, max 30 calls/day per user, token auth disallowed.
Calls backend.ai_client.chat outside DB transaction.
Validates layout codes, anchors, deduplicates, caps illustrations at 6.
Falls back to template plan if model/skills unavailable or call fails.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .ai_client import chat
from .batch_plan_routes import get_style_display_name, get_valid_layout_map
from .db import Database
from .services import ServiceError, consume_daily_usage
from .skill_paths import SKILL_DIR

VALID_IMAGE_TYPES = {"process", "concept", "comparison", "infographic", "scene", "mood"}


@lru_cache(maxsize=1)
def load_skill_prompts() -> str | None:
    """Read article illustration planner and cover designer skills (up to 6000 chars each)."""
    try:
        base_dir = SKILL_DIR.parent
        planner_file = base_dir / "article-illustration-planner" / "SKILL.md"
        designer_file = base_dir / "article-cover-designer" / "SKILL.md"

        if not planner_file.is_file() or not designer_file.is_file():
            return None

        planner_text = planner_file.read_text(encoding="utf-8")[:6000]
        designer_text = designer_file.read_text(encoding="utf-8")[:6000]

        return (
            "【文章配图策划 Skill 规范】\n"
            f"{planner_text}\n\n"
            "【文章封面设计 Skill 规范】\n"
            f"{designer_text}\n"
        )
    except Exception:
        return None


def generate_template_article_plan(
    title: str,
    blocks: list[dict[str, Any]],
    char_count: int = 0,
    include_cover: bool = True,
    valid_layouts: dict[str, str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Deterministic fallback generator for article illustration and cover plan."""
    if valid_layouts is None:
        valid_layouts = {}
    warns = list(warnings or [])

    clean_title = str(title or "").strip() or "未命名文章"
    block_map = {b["idx"]: b for b in blocks if "idx" in b}

    # Find candidate anchor blocks: all h2 -> all h3 -> first 3 p
    h2_blocks = [b for b in blocks if b.get("kind") == "h2"]
    cand_anchors = h2_blocks
    if not cand_anchors:
        cand_anchors = [b for b in blocks if b.get("kind") == "h3"]
    if not cand_anchors:
        cand_anchors = [b for b in blocks if b.get("kind") == "p"][:3]

    # Template anchor selection: up to 6 anchors (all h2 -> all h3 -> first 3 p)
    target_count = max(0, min(6, len(cand_anchors)))

    chosen_anchors = cand_anchors[:target_count]
    illustrations: list[dict[str, Any]] = []

    for idx, sec_block in enumerate(chosen_anchors):
        sec_idx = sec_block["idx"]
        anchor_text = str(sec_block.get("text") or "")[:24]

        # Gather text from next 2 non-heading blocks for snippet
        subsequent_texts: list[str] = []
        for k in range(sec_idx + 1, sec_idx + 6):
            if k not in block_map:
                continue
            nb = block_map[k]
            if nb.get("kind") in ("h1", "h2", "h3"):
                break
            if nb.get("text"):
                subsequent_texts.append(str(nb["text"]))
            if len(subsequent_texts) >= 2:
                break

        clean_heading = sec_block.get("text") if sec_block.get("kind") != "p" else f"段落重点 {idx + 1}"
        snippet = " ".join(subsequent_texts)[:110]
        subject = f"章节「{clean_heading}」—— {snippet or clean_heading}"[:120]
        purpose = "辅助阐释本节核心观点与知识框架"[:40]

        is_info = any(w in str(clean_heading) for w in ["步骤", "对比", "架构", "清单", "流程", "分析"])
        image_type = "infographic" if is_info else "concept"
        layout = "IG-001" if (is_info and "IG-001" in valid_layouts) else ("SC-001" if "SC-001" in valid_layouts else "")

        illustrations.append({
            "afterBlockIdx": sec_idx,
            "anchorText": anchor_text,
            "subject": subject,
            "purpose": purpose,
            "layout": layout,
            "imageType": image_type
        })

    # Cover
    cover: dict[str, Any] | None = None
    if include_cover:
        lead_block = next((b for b in blocks if b.get("kind") == "p" and b.get("text")), None)
        lead_text = str(lead_block.get("text") or clean_title)[:40] if lead_block else clean_title[:40]
        cover_subject = f"围绕文章《{clean_title}》（核心导语：{lead_text}）创作富有故事张力的手绘主题封面"[:120]
        cover_purpose = "确立文章视觉隐喻与主基调"[:40]
        cover = {
            "subject": cover_subject,
            "purpose": cover_purpose,
            "layout": "",
            "imageType": "scene"
        }

    return {
        "ok": True,
        "source": "template",
        "articleType": "knowledge",
        "cover": cover,
        "illustrations": illustrations,
        "warnings": warns
    }


def execute_article_plan(
    db: Database,
    user: dict[str, Any],
    article_id: str,
    title: str,
    blocks: list[dict[str, Any]],
    char_count: int = 0,
    style_id: str = "",
    cover_ratio: str = "2.35:1",
    inline_ratio: str = "4:3",
    include_cover: bool = True,
) -> dict[str, Any]:
    """Execute AI article illustration and cover plan."""
    if user.get("_auth_kind") == "token":
        raise ServiceError("token_scope_denied", status=403, code="token_disallowed")

    # Rate limiting: 30 requests/day per user
    if not consume_daily_usage(db, user["id"], "article_plan", limit=30):
        raise ServiceError("今日文章规划次数已达上限（30 次/天），请明天再试", status=429, code="rate_limited")

    clean_title = str(title or "").strip() or "未命名文章"
    warnings: list[str] = []

    # Truncate blocks to max 200 items, each block text to 300 chars
    raw_blocks = blocks if isinstance(blocks, list) else []
    if len(raw_blocks) > 200:
        raw_blocks = raw_blocks[:200]
        warnings.append("blocks_truncated")

    norm_blocks: list[dict[str, Any]] = []
    block_map: dict[int, dict[str, Any]] = {}
    for i, b in enumerate(raw_blocks):
        if not isinstance(b, dict):
            continue
        try:
            b_idx = int(b.get("idx", i))
        except (ValueError, TypeError):
            b_idx = i
        kind = str(b.get("kind") or "p").strip().lower()
        txt = str(b.get("text") or "").strip()[:300]
        entry = {"idx": b_idx, "kind": kind, "text": txt}
        norm_blocks.append(entry)
        block_map[b_idx] = entry

    # Valid layouts lookup
    valid_layouts = get_valid_layout_map(db)

    # Empty body check: no p, h2, h3, ul, blockquote
    has_body_blocks = any(
        b["kind"] in ("p", "h2", "h3", "ul", "blockquote") and b["text"]
        for b in norm_blocks
    )
    if not has_body_blocks:
        template_empty = generate_template_article_plan(
            clean_title, norm_blocks, char_count, include_cover, valid_layouts, warnings
        )
        template_empty["illustrations"] = []
        return template_empty

    # Skill files check
    skill_prompts = load_skill_prompts()
    if skill_prompts is None:
        warnings.append("skill_unavailable")
        return generate_template_article_plan(
            clean_title, norm_blocks, char_count, include_cover, valid_layouts, warnings
        )

    # Prepare available layout sample options (up to 40)
    sample_options: list[str] = []
    for prefix in ("IG-", "SC-", "SB-", "IP-", "EC-"):
        matching = [f"{k}: {valid_layouts[k]}" for k in valid_layouts if k.startswith(prefix)]
        sample_options.extend(matching[:8])
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
    style_display = get_style_display_name(style_id, db)

    # Blocks listing for prompt
    blocks_lines = [f"[{b['idx']}] {b['kind']}: {b['text'][:120]}" for b in norm_blocks]
    blocks_summary = "\n".join(blocks_lines[:80])

    system_prompt = (
        f"{skill_prompts}\n\n"
        "【任务要求】\n"
        "你是一名资深手绘风格编辑与排版规划师。根据给出的文章标题、正文块列表与画风，"
        "规划文章手绘主题封面与文中各章节插图的图位、主题隐喻与版式图型。"
    )

    user_prompt = (
        f"文章标题：{clean_title}\n"
        f"正文字数：约 {char_count or 1000} 字\n"
        f"封面比例：{cover_ratio} · 插图比例：{inline_ratio}\n"
        f"指定画风：{style_display or '未指定（保持统一手绘感）'}\n"
        f"是否包含封面：{'是' if include_cover else '否'}\n\n"
        "正文块清单（[块号] 类型: 摘要）：\n"
        f"{blocks_summary}\n\n"
        "可选图型清单（layout 编号必须从中选用）：\n"
        f"{layout_options_str}\n\n"
        "规划与输出规则：\n"
        "1. 严格输出合法 JSON，禁止包含任何非 JSON 说明文字，根结构格式如下：\n"
        "{\n"
        '  "articleType": "knowledge" 或 "narrative",\n'
        '  "cover": { "subject": "核心隐喻+标题意图（不超过120字）", "purpose": "配图定位（不超过40字）" },\n'
        '  "illustrations": [\n'
        '    {\n'
        '      "afterBlockIdx": 块号（整数，必须来自给出的正文块号清单）,\n'
        '      "subject": "该处插图具体描绘与主题隐喻（不超过120字）",\n'
        '      "purpose": "功能定位（不超过40字）",\n'
        '      "layout": "图型编号",\n'
        '      "imageType": "process" | "concept" | "comparison" | "infographic" | "scene" | "mood"\n'
        '    }\n'
        "  ]\n"
        "}\n"
        "2. 插图必须锚定在给出的块号之后；同一块号只能锚定一次；插图之间至少跨一个标题或间隔一定内容。\n"
        "3. 插图数量要求：1500字以下 1-2 张；1500-4000字 3-4 张；4000字以上 5-6 张；最多不超过 6 张。\n"
        "4. 封面 subject 请遵循 article-cover-designer 规范，采用核心隐喻与主标题意图，不写长摘要流水账。\n"
        "5. layout 必须在可选图型清单中；若无契合图型可留空串 \"\"。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    response_text, meta = chat(messages, temperature=0.4, timeout=30.0)

    if not meta.get("ok") or not response_text:
        return generate_template_article_plan(
            clean_title, norm_blocks, char_count, include_cover, valid_layouts, warnings
        )

    try:
        clean_json = response_text.strip()
        if "```" in clean_json:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_json)
            if m:
                clean_json = m.group(1).strip()
        parsed = json.loads(clean_json)
    except Exception:
        return generate_template_article_plan(
            clean_title, norm_blocks, char_count, include_cover, valid_layouts, warnings
        )

    if not isinstance(parsed, dict):
        return generate_template_article_plan(
            clean_title, norm_blocks, char_count, include_cover, valid_layouts, warnings
        )

    article_type = "narrative" if str(parsed.get("articleType") or "").strip().lower() == "narrative" else "knowledge"

    # 1. Cover validation
    cover: dict[str, Any] | None = None
    if include_cover:
        raw_cov = parsed.get("cover")
        if isinstance(raw_cov, dict) and raw_cov.get("subject"):
            cov_subj = str(raw_cov.get("subject") or "").strip()[:120]
            cov_purp = str(raw_cov.get("purpose") or "").strip()[:40]
            cover = {
                "subject": cov_subj,
                "purpose": cov_purp,
                "layout": "",
                "imageType": "scene"
            }
        else:
            # Fallback cover via template
            tpl_res = generate_template_article_plan(clean_title, norm_blocks, char_count, True, valid_layouts)
            cover = tpl_res.get("cover")

    # 2. Illustrations validation
    raw_ills = parsed.get("illustrations")
    valid_ills: list[dict[str, Any]] = []
    seen_indices: set[int] = set()

    if isinstance(raw_ills, list):
        for item in raw_ills:
            if not isinstance(item, dict):
                continue
            after_idx = item.get("afterBlockIdx")
            if not isinstance(after_idx, int) or after_idx not in block_map:
                continue
            if after_idx in seen_indices:
                continue
            seen_indices.add(after_idx)

            raw_layout = str(item.get("layout") or item.get("layoutId") or "").strip().upper()
            eff_layout = raw_layout if raw_layout in valid_layouts else ""

            # anchorText must be re-extracted from genuine request blocks (first 24 chars)
            anchor_text = str(block_map[after_idx].get("text") or "")[:24]

            subj = str(item.get("subject") or "").strip()[:120]
            purp = str(item.get("purpose") or "").strip()[:40]

            img_type = str(item.get("imageType") or "concept").strip().lower()
            if img_type not in VALID_IMAGE_TYPES:
                img_type = "concept"

            valid_ills.append({
                "afterBlockIdx": after_idx,
                "anchorText": anchor_text,
                "subject": subj,
                "purpose": purp,
                "layout": eff_layout,
                "imageType": img_type
            })

    # Sort ascending by afterBlockIdx, cap at 6
    valid_ills.sort(key=lambda x: x["afterBlockIdx"])
    valid_ills = valid_ills[:6]

    if not valid_ills:
        # If model produced no valid illustrations, fall back to template illustrations
        tpl_res = generate_template_article_plan(
            clean_title, norm_blocks, char_count, include_cover, valid_layouts, warnings
        )
        return tpl_res

    return {
        "ok": True,
        "source": "model",
        "articleType": article_type,
        "cover": cover,
        "illustrations": valid_ills,
        "warnings": warnings
    }


def handle_article_plan_post(handler: Any, req_path: str, body: dict[str, Any]) -> bool:
    if req_path == "/api/studio/article-plan":
        user = handler._current_user(required=True)
        res = execute_article_plan(
            handler.db,
            user,
            article_id=str(body.get("articleId") or ""),
            title=str(body.get("title") or ""),
            blocks=body.get("blocks") or [],
            char_count=int(body.get("charCount") or 0),
            style_id=str(body.get("styleId") or ""),
            cover_ratio=str(body.get("coverRatio") or "2.35:1"),
            inline_ratio=str(body.get("inlineRatio") or "4:3"),
            include_cover=body.get("includeCover") is not False,
        )
        handler._send_json(res)
        return True
    return False
