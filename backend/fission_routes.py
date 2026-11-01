"""Studio Fission AI / Template Route (Phase 3b-2).

Provides:
- POST /api/studio/fission
  Request: { "seed": "...", "strategy": "daily_quote"|"selling_points"|"knowledge_cards"|"story_beats"|"custom", "customStrategy": "...", "count": 1-50 }
  Response: { "ok": True, "items": [...], "source": "model" | "template" }
  Requires login, rate limit 50/day per user (scope="fission"), token disallowed.
  Calls backend.ai_client.chat outside DB transaction.
  Falls back to template generation when model is unconfigured or fails.
"""
from __future__ import annotations

import re
from typing import Any

from .ai_client import chat
from .db import Database
from .services import ServiceError, consume_daily_usage

STRATEGY_MAP = {
    "daily_quote": "系列日签",
    "selling_points": "卖点切角",
    "knowledge_cards": "科普图鉴",
    "story_beats": "连续分镜",
    "custom": "自定义角度",
}

TEMPLATE_BANKS = {
    "daily_quote": {
        "hooks": [
            "早八重启时刻：一杯热美式蒸汽里的微小秩序感",
            "准点下班看到的橘子海晚霞与单车后座微风",
            "允许自己今天只完成三件小事的留白哲学",
            "周末雨天窝在窗边翻完半本旧诗集的松弛午后",
            "把焦虑写进手账格子里再轻轻划掉的释然",
            "傍晚散步路过面包房闻到黄油麦香的治愈瞬间",
            "关掉消息免打扰后独享两小时慢煮乌龙茶",
            "办公桌角落新冒出一片嫩叶的绿萝生命力",
            "深夜台灯下用钢笔速写记录今天的小确幸",
            "不赶时间的周日菜市场人间烟火气巡礼",
            "在地铁摇晃车厢里戴上耳机进入自己的小宇宙",
            "立秋第一阵凉风吹过梧桐树梢的呼吸感",
        ],
        "details": [
            "暖米宣纸底纹配松烟墨线",
            "水彩晕染光影与大量呼吸留白",
            "朱砂红印章点睛与手写感批注",
            "桑贝式微缩小人与开阔街景对比",
            "桌面俯拍手账拼贴与胶带肌理",
            "柔和暖黄台灯光晕与植物剪影",
        ],
    },
    "selling_points": {
        "hooks": [
            "核心痛点共鸣：为什么你试过很多方案依然容易半途而废",
            "原材溯源特写：看得见的天然肌理与严苛选材标准",
            "三秒极速上手：把繁琐步骤浓缩成随时随地的轻盈体验",
            "早八通勤场景：塞进随身托特包里的全天候能量补给",
            "下午茶搭档：0负担轻盈配方与精致办公桌美学",
            "细节控放大镜：包装触感、环保棉纸与东方器物巧思",
            "真实口碑切片：老客无限回购的三个高频心动瞬间",
            "横向对比图解：一眼看懂与传统普通方案的本质差异",
            "四季百搭指南：冷热双泡与不同生活节奏的灵感搭配",
            "节日伴手礼盒：体面又有温度的东方手绘礼赠仪式感",
        ],
        "details": [
            "左右分栏卖点对照排版",
            "手绘放大镜细节标注箭头",
            "高颜值生活场景种草构图",
            "信息图步骤拆解与重点高亮",
            "温暖纸本底色突出产品主体",
        ],
    },
    "knowledge_cards": {
        "hooks": [
            "一图读懂底层核心概念：抛开晦涩术语看本质逻辑",
            "新手最容易踩的三大认知误区与纠偏指南",
            "黄金四步实操SOP：从零起步也能稳稳落地的路径",
            "关键参数对照表：不同阶段与场景下的最优配置区间",
            "经典正反案例拆解：高手做对了哪一个微小动作",
            "工具箱全景清单：提升十倍效率的必备器物与方法",
            "进阶跃迁心法：突破瓶颈期的结构化复盘框架",
            "常见疑难急诊室：遇到卡点时的三分钟自查流程图",
            "长期主义复利曲线：每天坚持十五分钟的半年变化",
            "全景知识脑图总结：一页收藏随时翻阅的行动卡片",
        ],
        "details": [
            "手绘思维导图与清晰编号层级",
            "墨线流程图配暖色重点圈注",
            "图鉴式标本排列与简洁批注",
            "对比象限矩阵与视觉隐喻插画",
        ],
    },
    "story_beats": {
        "hooks": [
            "序幕开篇：清晨推开木门迎接第一缕阳光的期待",
            "偶遇插曲：街角屋檐下躲雨时遇见神秘同伴",
            "小小挑战：面对杂乱线索静下心来逐一梳理",
            "灵感闪现：翻开泛黄笔记本找到关键解谜钥匙",
            "并肩行动：分工协作把脑海构想一点点搭成现实",
            "转折微光：暮色四合时点亮温暖灯火迎来转机",
            "高光时刻：作品悄然绽放引来邻里驻足微笑",
            "余韵收尾：星空下围炉夜话珍藏这段奇妙旅程",
        ],
        "details": [
            "电影感宽画幅叙事构图",
            "统一主角神态与连续光影推移",
            "绘本水彩笔触与细腻环境道具",
            "前后景深层次与情绪留白",
        ],
    },
}

CUSTOM_ANGLES = [
    "切角一 · 反常识开篇提问与核心悬念",
    "切角二 · 高频真实痛点场景还原",
    "切角三 · 关键细节拆解与直观对照",
    "切角四 · 三步实操方法与避坑提醒",
    "切角五 · 情绪共鸣金句与生活切片",
    "切角六 · 前后状态反转对比特写",
    "切角七 · 进阶玩法灵感与器物搭配",
    "切角八 · 读者高频疑问一图直答",
    "切角九 · 长期复利变化与仪式感记录",
    "切角十 · 总结收藏清单与行动呼唤",
]


def generate_template_fission(seed: str, strategy: str, count: int, custom_strategy: str = "") -> list[str]:
    safe_count = max(1, min(50, count))
    clean_seed = str(seed or "").strip() or "都市青年反内卷治愈手绘日签"
    short_seed = re.sub(r"[。！!？?\n]+.*$", "", clean_seed)[:22]
    clean_custom = str(custom_strategy or "").strip()

    if clean_custom:
        det_pool = TEMPLATE_BANKS["daily_quote"]["details"] + TEMPLATE_BANKS["knowledge_cards"]["details"]
        out_custom = []
        for i in range(safe_count):
            num_str = f"{i + 1:02d}"
            angle = CUSTOM_ANGLES[i % len(CUSTOM_ANGLES)]
            det = det_pool[(i * 3 + i // len(CUSTOM_ANGLES)) % len(det_pool)]
            cycle_round = i // len(CUSTOM_ANGLES)
            suffix = f"（系列拓展 · 卷{cycle_round + 1}）" if cycle_round > 0 else ""
            out_custom.append(f"#{num_str} 【{short_seed}｜{clean_custom}】{angle}{suffix}｜{det}"[:120])
        return out_custom

    pack = TEMPLATE_BANKS.get(strategy) or TEMPLATE_BANKS["daily_quote"]
    hooks = pack["hooks"]
    details = pack["details"]
    out = []
    for i in range(safe_count):
        num_str = f"{i + 1:02d}"
        hook = hooks[i % len(hooks)]
        det = details[(i * 3 + i // len(hooks)) % len(details)]
        cycle_round = i // len(hooks)
        if cycle_round == 0:
            variant_suffix = ""
        elif cycle_round % 3 == 1:
            variant_suffix = "（晨间暖光视角）"
        elif cycle_round % 3 == 2:
            variant_suffix = "（暮色街角特写）"
        else:
            variant_suffix = f"（四季风物变奏 · 卷{cycle_round}）"
        out.append(f"#{num_str} 【{short_seed}】{hook}{variant_suffix}｜{det}"[:120])
    return out


def execute_fission(
    db: Database,
    user: dict[str, Any],
    seed: str,
    strategy: str = "daily_quote",
    custom_strategy: str = "",
    count: int = 10,
) -> dict[str, Any]:
    if user.get("_auth_kind") == "token":
        raise ServiceError("token_scope_denied", status=403, code="token_disallowed")

    clean_seed = str(seed or "").strip()
    if not clean_seed:
        raise ServiceError("母题不能为空", status=400, code="invalid_param")

    try:
        cnt = int(count)
    except (ValueError, TypeError):
        cnt = 10
    cnt = max(1, min(50, cnt))

    if strategy not in STRATEGY_MAP:
        strategy = "daily_quote"

    clean_custom = str(custom_strategy or "").strip()
    strat_label = clean_custom if (strategy == "custom" and clean_custom) else STRATEGY_MAP.get(strategy, "系列日签")

    # Rate limiting: 50 times/day per user
    if not consume_daily_usage(db, user["id"], "fission", limit=50):
        raise ServiceError("今日母题裂变次数已达上限（50次/天），请明天再试", status=429, code="rate_limited")

    # AI call outside DB transaction
    system_prompt = (
        "你是一名专业的手绘插画与视觉创作策划专家。根据用户提供的创作母题与裂变策略，"
        "扩写出适合批量生成手绘插图的创作主题列表。"
    )
    user_prompt = (
        f"母题：{clean_seed}\n"
        f"策略：{strat_label}\n"
        f"数量要求：恰好 {cnt} 条。\n"
        "输出规则：\n"
        f"1. 每条一行，格式为纯文本主题或画面描述，不要加序号或列表符号（如 1. - *）。\n"
        "2. 每条主题具体生动、契合母题与策略，互不重复。\n"
        "3. 每条不超过 120 字。\n"
        f"4. 只输出这 {cnt} 行，不要包含任何多余问候、前言或总结解释。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    response_text, meta = chat(messages, temperature=0.7, timeout=30.0)

    items: list[str] = []
    if meta.get("ok") and response_text:
        seen = set()
        for line in response_text.splitlines():
            line_clean = line.strip()
            # strip markdown list markers or numbering
            line_clean = re.sub(r"^(?:[0-9]+[.\-、]\s*|[\-*•]\s*|#\d+\s*)", "", line_clean).strip()
            if not line_clean:
                continue
            line_clean = line_clean[:120]
            if line_clean not in seen:
                seen.add(line_clean)
                items.append(line_clean)
            if len(items) >= cnt:
                break

    if items:
        return {"ok": True, "items": items, "source": "model"}

    # Fallback to template logic
    template_items = generate_template_fission(clean_seed, strategy, cnt, clean_custom)
    return {"ok": True, "items": template_items, "source": "template"}


def handle_fission_post(handler: Any, req_path: str, body: dict[str, Any]) -> bool:
    if req_path == "/api/studio/fission":
        user = handler._current_user(required=True)
        res = execute_fission(
            handler.db,
            user,
            seed=str(body.get("seed") or ""),
            strategy=str(body.get("strategy") or "daily_quote"),
            custom_strategy=str(body.get("customStrategy") or ""),
            count=body.get("count", 10),
        )
        handler._send_json(res)
        return True
    return False
