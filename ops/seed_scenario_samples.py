#!/usr/bin/env python3
"""Seed scenario samples tool for Handraw Web 2.0.

For scenarios with fewer than 3 works:
Generates official sample works using the site's official Skill prompt and image gateway,
and publishes them as official public works.

Per requirements:
- Reuses existing Skill prompt workflow (backend.skill_prompt.compose_prompt).
- Reuses existing image generation calling code (backend.server.gateway_request, download_and_cache_generated_image).
- Configuration read from HANDRAW_IMAGE_CONFIG / HANDRAW_AI_CONFIG.
- Publishes via backend.curation.publish_work_direct with admin account.
- CLI arguments: --db (required), --dry-run, --scenario, --max.
- Idempotent: does not regenerate existing works (keyed by requestId).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time
import urllib.parse
import uuid

# Ensure repository root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_scenario_samples")


def ensure_env_configs() -> None:
    """Ensure HANDRAW_IMAGE_CONFIG and HANDRAW_AI_CONFIG are populated from environment or user registry."""
    if not os.environ.get("HANDRAW_IMAGE_CONFIG"):
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                val, _ = winreg.QueryValueEx(key, "HANDRAW_IMAGE_CONFIG")
                if val:
                    os.environ["HANDRAW_IMAGE_CONFIG"] = str(val)
        except Exception:
            pass
    if not os.environ.get("HANDRAW_AI_CONFIG"):
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                val, _ = winreg.QueryValueEx(key, "HANDRAW_AI_CONFIG")
                if val:
                    os.environ["HANDRAW_AI_CONFIG"] = str(val)
        except Exception:
            pass


ensure_env_configs()

from backend.curation import publish_work_direct
from backend.db import Database
from backend.home_scenarios import (
    DEFAULT_SCENARIOS,
    admin_pin_scenario_work,
    build_scenario_match_clause,
    invalidate_scenarios_cache,
)
from backend.server import (
    download_and_cache_generated_image,
    gateway_request,
    load_image_service_config,
    size_for_ratio,
)
from backend.services import _seed_filter
from backend.skill_prompt import compose_prompt
from backend.works_feed import is_valid_work_row

SCENARIO_SAMPLE_PRESETS: dict[str, list[dict[str, Any]]] = {
    "xiaohongshu": [
        {
            "title": "小红书爆款图文笔记 · 暖秋手账日常",
            "style": "FA-001",
            "layout": "SC-001",
            "ratio": "3:4",
            "theme": "秋天治愈系红薯日常穿搭与生活碎片手账",
            "notes": "【小红书套图】爆款手账图文排版，松散黑线与温暖点色",
        },
        {
            "title": "小红书组图笔记 · 周末书房漫游记",
            "style": "FB-001",
            "layout": "SC-021",
            "ratio": "3:4",
            "theme": "周末书房手冲咖啡与阳光窗台猫咪手账",
            "notes": "【小红书套图】双拼绘本风自适应社媒卡",
        },
        {
            "title": "小红书干货卡 · 职场人的治愈自我对话",
            "style": "FC-001",
            "layout": "SC-003",
            "ratio": "3:4",
            "theme": "极简人物喝咖啡沉思短句生活卡片",
            "notes": "【小红书套图】现代平面艺术风格上图下文社媒卡",
        },
    ],
    "gzh_inline": [
        {
            "title": "公众号次条金句卡 · 深夜书房独处时光",
            "style": "FC-001",
            "layout": "SC-008",
            "ratio": "16:9",
            "theme": "深夜书房一杯热茶与思考金句插图",
            "notes": "【公众号贴图】极速单张卡片，适合文章内部嵌入与分享",
        },
        {
            "title": "公众号长文插画 · 晨光微熹的林间漫步",
            "style": "FB-001",
            "layout": "SC-001",
            "ratio": "16:9",
            "theme": "晨光水彩树林与小路轻透自然小景",
            "notes": "【公众号贴图】轻透水彩手账画风次条封面图",
        },
        {
            "title": "公众号金句图 · 保持热忱与内心的从容",
            "style": "FA-001",
            "layout": "SC-016",
            "ratio": "1:1",
            "theme": "怪萌圆脸小人端坐茶杯旁惬意微笑",
            "notes": "【公众号贴图】极简留白金句配图",
        },
    ],
    "article_illus": [
        {
            "title": "深度专栏配图 · 城市漫游与建筑速写",
            "style": "FB-002",
            "layout": "SC-003",
            "ratio": "3:4",
            "theme": "老街咖啡馆与梧桐树荫漫游速写故事",
            "notes": "【文章配图】长文段落提炼配图，经典绘本叙事风",
        },
        {
            "title": "商业观察专栏 · 数字化协作的未来图景",
            "style": "FC-001",
            "layout": "SC-011",
            "ratio": "3:4",
            "theme": "团队远程连接与跨时区协作抽象几何图景",
            "notes": "【文章配图】全篇视觉统一，现代平面艺术风格",
        },
        {
            "title": "生活美学散文配图 · 陶艺手作与慢生活",
            "style": "FB-001",
            "layout": "SC-001",
            "ratio": "3:4",
            "theme": "拉胚成型的陶器与侧光微尘手绘插画",
            "notes": "【文章配图】温润水彩手账风格段落插图",
        },
    ],
    "comic_4panel": [
        {
            "title": "生活漫画四格 · 周末猫咪与我的日常",
            "style": "FD-001",
            "layout": "SB-002",
            "ratio": "3:4",
            "theme": "周末猫咪与主人的搞笑生活四格分镜",
            "notes": "【漫画四格】四格起承转合分镜连环画",
        },
        {
            "title": "职场生活四格 · 需求变更的心路历程",
            "style": "FD-001",
            "layout": "SB-002",
            "ratio": "3:4",
            "theme": "打工人面对突然改需求的面部特写与幽默反转",
            "notes": "【漫画四格】规整分镜生活幽默漫画",
        },
        {
            "title": "萌宠剧场四格 · 寻找失踪的小鱼干",
            "style": "FD-001",
            "layout": "SB-002",
            "ratio": "3:4",
            "theme": "小柯基在家中翻箱倒柜寻找零食的四格连环画",
            "notes": "【漫画四格】起承转合四格故事",
        },
    ],
    "ip_character": [
        {
            "title": "官方吉祥物 · 暖心小柴犬 IP 形象设计",
            "style": "FC-002",
            "layout": "IP-001",
            "ratio": "1:1",
            "theme": "手绘呆萌小柴犬吉祥物设定与三视图表情",
            "notes": "【IP形象设计】三视图与标志性角色定位卡",
        },
        {
            "title": "原创潮玩 IP · 森林小怪兽软胶手办设定",
            "style": "FC-001",
            "layout": "IP-002",
            "ratio": "1:1",
            "theme": "圆滚滚绿色小怪兽多角度形象基准三视图",
            "notes": "【IP形象设计】角色形象三视图基准图",
        },
        {
            "title": "IP 表情包矩阵 · 办公打工人呆萌日常",
            "style": "FA-001",
            "layout": "IP-003",
            "ratio": "1:1",
            "theme": "小柴犬 16 宫格微信日常聊天表情包手绘草图",
            "notes": "【IP形象设计】16宫格角色微信表情包",
        },
    ],
    "ecommerce": [
        {
            "title": "手工粗陶咖啡滤杯 · 极简电商主图与卖点解析",
            "style": "FC-003",
            "layout": "EC-001",
            "ratio": "1:1",
            "theme": "手工粗陶咖啡滤杯静物卖点与材质特写",
            "notes": "【电商图】高质感单品主图，突出质感与手工肌理",
        },
        {
            "title": "纯手工亚麻围裙 · 多角度使用场景展示图",
            "style": "FC-001",
            "layout": "EC-002",
            "ratio": "1:1",
            "theme": "咖啡师穿戴手织亚麻围裙的工作场景与细节展示",
            "notes": "【电商图】多角度展示图与生活方式场景",
        },
        {
            "title": "复古金属黄铜尺 · 结构解析与工艺说明图",
            "style": "FC-001",
            "layout": "EC-008",
            "ratio": "1:1",
            "theme": "实心黄铜精密刻度直尺材质爆炸图与参数标注",
            "notes": "【电商图】材质与结构解析电商详情图",
        },
    ],
    "infographic": [
        {
            "title": "手冲咖啡风味轮与萃取步骤 · 知识信息图",
            "style": "FC-004",
            "layout": "IG-001",
            "ratio": "3:4",
            "theme": "精品手冲咖啡风味萃取步骤与温度参数图谱",
            "notes": "【信息图/知识卡】标题金字塔与步骤流信息图",
        },
        {
            "title": "时间管理四象限矩阵 · 极简效率知识卡",
            "style": "FC-001",
            "layout": "IG-014",
            "ratio": "3:4",
            "theme": "重要紧急四象限矩阵决策流程图手绘解构",
            "notes": "【信息图/知识卡】四象限矩阵知识信息图",
        },
        {
            "title": "创作者个人品牌成长路径 · 阶梯式进阶图解",
            "style": "FC-001",
            "layout": "IG-010",
            "ratio": "3:4",
            "theme": "从新手到资深创作者技能树与阶梯进阶流程图",
            "notes": "【信息图/知识卡】阶段等级进阶信息图",
        },
    ],
    "poster": [
        {
            "title": "秋日手绘音乐节 · 视觉大片宣传海报",
            "style": "FC-001",
            "layout": "SC-023",
            "ratio": "3:4",
            "theme": "秋日草地复古手绘音乐节主视觉宣传海报",
            "notes": "【海报】大冲击力主视觉与标题版式，活动宣传封面",
        },
        {
            "title": "东方节气茶事展 · 金箔朱砂大视觉艺术海报",
            "style": "FE-001",
            "layout": "SC-023",
            "ratio": "3:4",
            "theme": "东方茶道雅集朱砂墨色大字排版艺术海报",
            "notes": "【海报】中国传统新国风海报KV",
        },
        {
            "title": "城市夜跑俱乐部 · 荧光赛博手绘活动海报",
            "style": "FG-001",
            "layout": "SC-023",
            "ratio": "3:4",
            "theme": "霓虹荧光都市夜跑者动态线条视觉冲击海报",
            "notes": "【海报】动漫潮酷感活动宣传海报",
        },
    ],
}


def find_author_user(db: Database, username: str) -> dict[str, Any]:
    """Retrieve existing active user by username, or error out. Never creates accounts."""
    clean = (username or "").strip()
    if not clean:
        raise ValueError("必须指定 --author <username>")
    row = db.get_conn().execute(
        "SELECT id, username, display_name, role, status FROM users WHERE username = ? COLLATE NOCASE",
        (clean,),
    ).fetchone()
    if not row:
        raise ValueError(f"指定的账号不存在: {username}")
    if row["status"] != "active":
        raise ValueError(f"指定的账号未处于激活状态: {username}")
    return {
        "id": int(row["id"]),
        "username": str(row["username"]),
        "display_name": str(row["display_name"]),
        "role": str(row["role"]),
        "status": "active",
    }


def generate_and_cache_sample_image(prompt_text: str, ratio: str, request_id: str) -> str:
    """Generate image via local image gateway and cache bytes into storage."""
    cfg = load_image_service_config()
    if not cfg:
        raise RuntimeError("未检测到本地生图网关配置 image-service.json")

    task_id = request_id or str(uuid.uuid4())
    gw_payload = {
        "client_task_id": task_id,
        "prompt": prompt_text,
        "model": "gpt-image-2",
        "size": size_for_ratio(ratio),
        "quality": "auto",
    }
    logger.info("Calling gateway /api/image-tasks/generations (task_id: %s)...", task_id)
    gw_res = gateway_request("/api/image-tasks/generations", payload=gw_payload, timeout=35)
    actual_task_id = str(gw_res.get("id") or task_id)
    status = gw_res.get("status") or "queued"

    poll_start = time.time()
    while status in ("queued", "running") and (time.time() - poll_start) < 180:
        time.sleep(3)
        poll_res = gateway_request(f"/api/image-tasks?ids={urllib.parse.quote(actual_task_id)}")
        items = poll_res.get("items") or []
        if items:
            item = items[0]
            status = item.get("status") or status
            if status in ("success", "succeeded", "completed", "done"):
                for idx, d in enumerate(item.get("data") or []):
                    r_url = d.get("url") if isinstance(d, dict) else None
                    if r_url:
                        cached_url = download_and_cache_generated_image(r_url, f"{actual_task_id}_{idx}")
                        logger.info("Image successfully generated and cached: %s", cached_url)
                        return cached_url
            elif status in ("failed", "error", "cancelled", "canceled"):
                raise RuntimeError(f"网关任务失败: {status}")

    for idx, d in enumerate(gw_res.get("data") or []):
        r_url = d.get("url") if isinstance(d, dict) else None
        if r_url:
            return download_and_cache_generated_image(r_url, f"{actual_task_id}_{idx}")

    raise RuntimeError(f"网关生图任务超时未完成 (status: {status})")


def run_seed_scenario_samples(
    db_path: str | Path,
    author_username: str,
    dry_run: bool = False,
    scenario_filter: str | None = None,
    max_per_scenario: int = 3,
    max_total_generations: int | None = None,
) -> dict[str, Any]:
    """Execute scenario sample seed plan."""
    db = Database(str(db_path))
    db.migrate()
    conn = db.get_conn()

    author_user = find_author_user(db, author_username)
    logger.info("Using author user: @%s (id: %s, role: %s)", author_user["username"], author_user["id"], author_user["role"])

    seed_clause, seed_params = _seed_filter("w.id", "works")

    scenarios = conn.execute(
        "SELECT * FROM home_scenarios WHERE is_enabled = 1 ORDER BY sort_order ASC"
    ).fetchall()

    if scenario_filter:
        scenarios = [s for s in scenarios if s["key"] == scenario_filter]
        if not scenarios:
            logger.warning("No scenario found with key '%s'", scenario_filter)
            return {"ok": True, "planned": [], "executed": []}

    planned: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []
    total_generated = 0

    for sc in scenarios:
        if not dry_run and max_total_generations is not None and total_generated >= max_total_generations:
            break
        s_key = sc["key"]
        s_title = sc["title"]
        try:
            match_rules = json.loads(sc["match_rules_json"] or "{}")
        except Exception:
            match_rules = {}

        # Count publicly visible works matching this scenario
        match_sql, match_params = build_scenario_match_clause(match_rules, table_alias="w")
        existing_count = conn.execute(
            f"""
            SELECT COUNT(*) FROM works w
            WHERE w.status = 'published'
              AND {seed_clause}
              AND ({match_sql})
            """,
            (*seed_params, *match_params),
        ).fetchone()[0]

        logger.info(
            "Scenario '%s' (%s): current public works count = %d",
            s_key, s_title, existing_count
        )

        needed = max(0, 3 - existing_count)
        if needed <= 0:
            logger.info("Scenario '%s' already has >= 3 works, skipping.", s_key)
            continue

        presets = SCENARIO_SAMPLE_PRESETS.get(s_key, [])
        to_create = min(needed, max_per_scenario, len(presets))

        for idx in range(to_create):
            preset = presets[idx]
            req_id = f"seed_sample_{s_key}_{idx + 1}"

            # Idempotency check: already exists in DB?
            already_done = conn.execute(
                "SELECT id, title, images_json FROM works WHERE request_id = ?", (req_id,)
            ).fetchone()
            if already_done:
                logger.info(
                    "Work with request_id '%s' already exists (%s), skipping.",
                    req_id, already_done["id"]
                )
                continue

            plan_item = {
                "scenarioKey": s_key,
                "scenarioTitle": s_title,
                "sampleIndex": idx + 1,
                "requestId": req_id,
                "preset": preset,
            }
            planned.append(plan_item)

            if dry_run:
                logger.info(
                    "[DRY-RUN] Would generate for '%s': title='%s', style='%s', layout='%s', reqId='%s'",
                    s_key, preset["title"], preset["style"], preset["layout"], req_id
                )
                continue

            if max_total_generations is not None and total_generated >= max_total_generations:
                logger.info("Reached max_total_generations limit (%d), stopping.", max_total_generations)
                break

            logger.info(
                "Executing generation for '%s': title='%s', style='%s', layout='%s'...",
                s_key, preset["title"], preset["style"], preset["layout"]
            )

            # 1. Official Skill prompt
            prompt_res = compose_prompt(
                style_code=preset["style"],
                layout_code=preset["layout"],
                theme=preset["theme"],
                ratio=preset["ratio"],
            )
            full_prompt = prompt_res.get("prompt") or preset["theme"]

            # 2. Call gateway & download cached image
            image_url = generate_and_cache_sample_image(
                prompt_text=full_prompt,
                ratio=preset["ratio"],
                request_id=req_id,
            )

            # 3. Publish work via official publish_work_direct
            publish_body = {
                "title": preset["title"],
                "prompt": full_prompt,
                "images": [image_url],
                "styles": [preset["style"]],
                "layout": preset["layout"],
                "ratio": preset["ratio"],
                "notes": preset.get("notes") or f"官方场景示例：{s_title}",
                "requestId": req_id,
            }
            receipt = publish_work_direct(db, author_user, publish_body, listed=True)
            work_id = receipt["workId"]
            logger.info("Successfully published work '%s' for scenario '%s'", work_id, s_key)

            # Record public media grant so anonymous visitors can view the generated sample image
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            with db.transaction() as tx:
                tx.execute(
                    """
                    INSERT OR REPLACE INTO studio_generation_media
                    (id, generation_id, user_id, media_url, media_kind, storage_path, visibility, created_at)
                    VALUES (?, ?, ?, ?, 'generated', '', 'public', ?)
                    """,
                    (f"gm_{work_id}", f"gen_{work_id}", int(author_user["id"]), image_url, now_iso),
                )
                tx.execute(
                    """
                    INSERT INTO media_public_grants
                    (id, media_url, owner_user_id, target_type, target_id, granted_by_user_id, granted_at, revoked_at)
                    VALUES (?, ?, ?, 'work', ?, ?, ?, NULL)
                    ON CONFLICT(media_url, target_type, target_id) DO UPDATE SET revoked_at=NULL, granted_at=excluded.granted_at
                    """,
                    (str(uuid.uuid4()), image_url, int(author_user["id"]), work_id, int(author_user["id"]), now_iso),
                )

            # 4. Pin work to the scenario
            admin_pin_scenario_work(
                db, author_user,
                scenario_key=s_key,
                work_id=work_id,
                sort_order=(idx + 1) * 10,
            )

            total_generated += 1
            executed.append(
                {
                    "scenarioKey": s_key,
                    "workId": work_id,
                    "requestId": req_id,
                    "imageUrl": image_url,
                    "title": preset["title"],
                }
            )

    invalidate_scenarios_cache()
    return {
        "ok": True,
        "dryRun": dry_run,
        "plannedCount": len(planned),
        "executedCount": len(executed),
        "planned": planned,
        "executed": executed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed sample works for home scenarios.")
    parser.add_argument("--db", required=True, help="Path to SQLite database file.")
    parser.add_argument("--author", required=True, help="Username of existing user to publish samples as.")
    parser.add_argument("--dry-run", action="store_true", help="Print generation plan without calling gateway or modifying DB.")
    parser.add_argument("--scenario", default=None, help="Filter to run only for a specific scenario key.")
    parser.add_argument("--max", type=int, default=3, help="Max sample works to generate per scenario (default: 3).")
    parser.add_argument("--max-total", type=int, default=None, help="Max total works to generate across all scenarios.")

    args = parser.parse_args()
    db_path = Path(args.db).resolve()
    if not db_path.exists():
        logger.error("Database file not found: %s", db_path)
        sys.exit(1)

    result = run_seed_scenario_samples(
        db_path=db_path,
        author_username=args.author,
        dry_run=args.dry_run,
        scenario_filter=args.scenario,
        max_per_scenario=args.max,
        max_total_generations=args.max_total,
    )
    print("\n--- SEED EXECUTION SUMMARY ---")
    print(f"Dry Run: {result['dryRun']}")
    print(f"Planned Generations: {result['plannedCount']}")
    print(f"Executed Generations: {result['executedCount']}")
    for ex in result["executed"]:
        print(f"  [{ex['scenarioKey']}] Work: {ex['workId']}, Title: {ex['title']}, Image: {ex['imageUrl']}")


if __name__ == "__main__":
    main()
