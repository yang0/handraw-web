"""Initial database seed loader for Handraw Web 2.0."""
from __future__ import annotations

import json
import os
import re
import time
from functools import lru_cache
from pathlib import Path

from .db import Database, utc_now_iso
from .security import generate_api_key, hash_password

SEED_JSON_PATH = Path(__file__).resolve().parent / "seed_data.json"
DEMO_DEFAULT_PASSWORD = "handraw123"

SERVER_EXCLUSIVE_BLACKBOX: dict[str, str] = {
    "FX-001": (
        "东方现代节气社论插画风：采用温润手工宣纸纤维底纹（暖象牙米白），松弛写意的毛笔淡墨细钩线搭配克制高纯度朱砂红平涂色块，"
        "局部点缀细腻哑光碎金箔肌理，人物采用极简微缩比例与巨型器物形成诗意尺度反差，保留 60% 以上呼吸负空间。"
    ),
    "FX-002": (
        "独立书店双色孔版丝网印刷插画（Risograph）：限定普鲁士深蓝与朱砂珊瑚红双色大豆油墨叠印，刻意保留 0.8mm 自然套印错位白边、"
        "粗颗粒半调网点与未涂布特种纸粗糙纤维感，现代几何概括剪影。"
    ),
    "FX-003": (
        "复古银盐暗房手作拼贴画报风：高反差黑白银盐相纸颗粒底影，局部叠贴手撕牛皮纸色块、红色油性记号笔圈注与打字机微排版标签，"
        "兼具电影剧照叙事张力与独立艺术画册质感。"
    ),
    "FX-004": (
        "京都现代商业木版水印浮世绘：梨木刀刻硬朗流畅墨线轮廓，植物矿物水性颜料马连擦印柔和渐变，平视二维空间构图融合当代都市生活场景。"
    ),
    "LX-001": (
        "三段式杂志封面级痛点拆解排版：顶部 18% 为极简留白刊头区排印醒目主标题；中部 62% 为黄金分割视觉焦点主图且四周严禁贴边；"
        "底部 20% 横向排布三枚无边框轻量要点短句，层级分明手机端秒读。"
    ),
    "LX-002": (
        "全景折叠长卷式故事分镜排版：不使用硬质漫画黑框，通过建筑剖面、云雾或道路动线呈 Z 字形串联上中下三个连续叙事场景，微缩角色贯穿始终。"
    ),
}

DEFAULT_SITE_SETTINGS: dict[str, object] = {
    "economy": {
        "welcome_credits": 20,
        "daily_checkin_credits": 5,
        "work_publish_credits": 5,
        "pioneer_bonus_credits": 10,
        "pioneer_work_threshold": 3,
        "asset_publish_credits": 15,
        "honor_upgrade_credits": 10,
        "topic_publish_credits": 0,
        "reply_publish_credits": 0,
        "reply_daily_cap": 0,
        "invite_inviter_credits": 15,
        "invite_invitee_credits": 10,
        "first_collect_credits": 2,
        "first_cheer_credits": 2,
        "daily_free_quota": 3,
        "studio_credit_per_image": 2,
        "author_share_ratio": 0.80,
        "discourse_migration_credits": 50,
        "official_tip_payee": "",
    },
    "announcement": {
        "enabled": True,
        "badge": "✨ 2.0 正式上线",
        "text": "Handraw 手绘风社区升级版：360+ 画风与 160+ 图型全量打通无限画布，荒地首晒立奖 +15✦！",
        "cta_label": "去创作台体验 ↗",
        "cta_channel": "studio",
    },
    "moderation": {
        "auto_pause_report_threshold": 3,
        "community_asset_default_status": "published",
        "work_default_status": "published",
        "allow_self_review_for_admin": False,
    },
    "gateway": {
        "model": "gpt-image-2",
        "timeout_seconds": 35,
        "quality": "auto",
        "allow_sample_fallback": True,
        "max_inflight_per_user": 1,
    },
}

OFFICIAL_STUDIO_PRESETS: list[dict[str, object]] = [
    {
        "id": "preset_v24_single",
        "blueprint": "single",
        "title": "🎯 节气海报极速出图",
        "scenario_badge": "日常单图 · 3节点",
        "scenario_desc": "最常用的日常海报/图文工作流：仅用「风格参数 + 文本参数 → 输出控制」3 个核心节点，零冗余极速出图。",
        "sort_order": 1,
    },
    {
        "id": "preset_v24_loop100",
        "blueprint": "loop_100",
        "title": "🔁 百图矩阵批量生产（1母题→100张）",
        "scenario_badge": "百图批量 · 4节点",
        "scenario_desc": "演示如何输出 100 张图而不建 100 个节点：「选题裂变」从 1 个母题生成 100 条日签 →「循环批量」驱动仅 1 个「输出控制」，结果自动收敛进 1 个分页「批量图集」节点。",
        "sort_order": 2,
    },
    {
        "id": "preset_v24_style_ab",
        "blueprint": "style_ab",
        "title": "🎨 同文案多画风横评比稿",
        "scenario_badge": "提案选风 · 3节点",
        "scenario_desc": "定好一句主文案，无需单独连风格参数，直接用「循环批量（多画风模式）」一次横评 4 款手绘风格快速定稿。",
        "sort_order": 3,
    },
    {
        "id": "preset_v24_ip_story",
        "blueprint": "ip_story",
        "title": "👤 IP角色连续故事绘本",
        "scenario_badge": "角色一致性 · 4节点",
        "scenario_desc": "通过「图片参数」锁定原创角色与道具外观一致性，配合「套图模式」一次生成 4 幕连续故事分镜。",
        "sort_order": 4,
    },
    {
        "id": "preset_v24_omnimedia",
        "blueprint": "omnimedia",
        "title": "🔗 全媒体一稿三端宣发包",
        "scenario_badge": "桥接一分多 · 6节点",
        "scenario_desc": "新品发布标准链路：一套视觉与卖点经「桥接」同时分发给 3 个不同规格输出控制（2.35:1 公众号头图 + 3:4 种草套图 + 9:16 竖版海报）。",
        "sort_order": 5,
    },
    {
        "id": "preset_v24_article",
        "blueprint": "article",
        "title": "📰 深度长文自动配图与排版",
        "scenario_badge": "专栏配图 · .md交付",
        "scenario_desc": "「文本参数」挂载 Markdown 长文，「输出控制」设为文章配图，自动拆解章节生成封面与正文插图并支持打包下载 ZIP。",
        "sort_order": 6,
    },
    {
        "id": "preset_v24_fusion",
        "blueprint": "fusion",
        "title": "🎭 跨媒介双画风融合实验",
        "scenario_badge": "双风碰撞 · 3节点",
        "scenario_desc": "开启「风格参数」双画风融合开关：角色主体采用手作插画肌理，场景环境采用纪实胶片/水墨山水，打造高辨识度跨次元视觉。",
        "sort_order": 7,
    },
]


@lru_cache(maxsize=1)
def seed_registry() -> dict[str, frozenset[str]]:
    """Return exact identifiers written by the demo seed loader.

    This registry is intentionally ID-based: normal mode hides only records
    known to have come from the seed, without deleting rows or hiding later
    genuine user content merely because it belongs to the same account.
    """
    try:
        raw = json.loads(SEED_JSON_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}

    core_users = {
        "yang0",
        "ops_lin",
        "reviewer_su",
        "su_editorial",
        "lin_sketch",
        "momo_design",
        "pm_chen",
        "brand_zhou",
        "sprout_xia",
    }
    asset_ids = {str(item.get("id") or "").upper() for item in raw.get("exclusiveResources", []) + raw.get("communityResources", []) if item.get("id")}
    work_ids = {str(item.get("id") or "") for item in raw.get("works", []) if item.get("id")}
    topic_ids = {str(item.get("id") or "") for item in raw.get("topics", []) if item.get("id")}
    work_comment_ids: set[str] = set()
    reply_ids: set[str] = set()
    users = set(core_users)
    for work_index, item in enumerate(raw.get("works", [])):
        author = str(item.get("author") or "")
        if author:
            users.add(author)
        work_id = str(item.get("id") or f"work_seed_{work_index}")
        for comment_index, comment in enumerate(item.get("comments") or []):
            work_comment_ids.add(str(comment.get("id") or f"wc_{work_id}_{work_index}"))
            commenter = str(comment.get("user") or "")
            if commenter:
                users.add(commenter)
    for topic_index, item in enumerate(raw.get("topics", [])):
        author = str(item.get("author") or "")
        if author:
            users.add(author)
        topic_id = str(item.get("id") or f"topic_seed_{topic_index}")
        for reply in item.get("replies") or []:
            reply_ids.add(str(reply.get("id") or f"rp_{topic_id}"))
            replier = str(reply.get("user") or "")
            if replier:
                users.add(replier)
    for item in raw.get("communityResources", []):
        author = str(item.get("author") or "")
        if author:
            users.add(author)

    return {
        "users": frozenset(users),
        "assets": frozenset(asset_ids),
        "works": frozenset(work_ids),
        "topics": frozenset(topic_ids),
        "work_comments": frozenset(work_comment_ids),
        "forum_replies": frozenset(reply_ids),
        "asset_comments": frozenset({f"acm_seed_{idx:02d}" for idx in range(1, 9)}),
        "generations": frozenset({"gen_seed_01", "gen_seed_02"}),
        "workflows": frozenset(str(item.get("id") or "") for item in OFFICIAL_STUDIO_PRESETS if item.get("id")),
        "reports": frozenset({"work_117", "topic_202"}),
        "ledger_events": frozenset({"seed_yang0_0", "seed_yang0_1", "seed_yang0_2", "seed_yang0_3", "seed_init_ops_lin"}),
    }


def seed_ids(kind: str) -> frozenset[str]:
    return seed_registry().get(kind, frozenset())


def is_seed_username(username: str) -> bool:
    return str(username or "").strip().lower() in {item.lower() for item in seed_ids("users")}


def _recency_offset_ms(label: str) -> int:
    s = (label or "").strip()
    if not s or "刚刚" in s:
        return 60_000
    m = re.search(r"(\d+)\s*分钟前", s)
    if m:
        return int(m.group(1)) * 60_000
    h = re.search(r"(\d+)\s*小时前", s)
    if h:
        return int(h.group(1)) * 3_600_000
    d = re.search(r"(\d+)\s*天前", s)
    if d:
        return int(d.group(1)) * 86_400_000
    if "昨天" in s:
        return 86_400_000
    return 172_800_000


# Realistic multi-horizon timestamps (<=7d weekly, 8~29d monthly, 35~70d all-time classics)
# so Weekly, Monthly, and All-Time leaderboards surface genuinely distinct creators and works.
SEED_WORK_TIMELINE_DAYS: dict[str, tuple[float, str, int]] = {
    # Weekly fresh & breakout works (<= 7 days)
    "work_126": (0.005, "6 分钟前", 1),
    "work_125": (0.035, "48 分钟前", 1),
    "work_102": (0.17, "4 小时前", 1),
    "work_123": (0.62, "15 小时前", 1),
    "work_104": (1.8, "2 天前", 0),
    "work_107": (2.9, "3 天前", 0),
    "work_109": (3.8, "4 天前", 0),
    "work_110": (4.7, "5 天前", 0),
    "work_113": (5.8, "6 天前", 0),
    # Monthly rising & hit works (8 ~ 29 days)
    "work_103": (9.2, "9 天前", 0),
    "work_112": (10.5, "11 天前", 0),
    "work_105": (10.8, "11 天前", 0),
    "work_117": (12.2, "12 天前", 0),
    "work_133": (14.0, "14 天前", 0),
    "work_106": (15.4, "15 天前", 0),
    "work_114": (17.2, "17 天前", 0),
    "work_116": (19.6, "20 天前", 0),
    "work_118": (21.8, "22 天前", 0),
    "work_121": (23.5, "24 天前", 0),
    "work_124": (24.8, "25 天前", 0),
    "work_108": (26.0, "26 天前", 0),
    "work_115": (27.1, "27 天前", 0),
    "work_111": (28.0, "28 天前", 0),
    "work_119": (28.8, "29 天前", 0),
    # All-time Hall-of-Fame classics (35 ~ 70 days)
    "work_101": (38.0, "1 个月前", 0),
    "work_120": (41.0, "1 个月前", 0),
    "work_131": (43.0, "1 个月前", 0),
    "work_122": (45.0, "1 个月前", 0),
    "work_134": (50.0, "2 个月前", 0),
    "work_127": (52.0, "2 个月前", 0),
    "work_129": (56.0, "2 个月前", 0),
    "work_132": (62.0, "2 个月前", 0),
    "work_128": (64.0, "2 个月前", 0),
    "work_130": (68.0, "2 个月前", 0),
}

SEED_ASSET_TIMELINE_DAYS: dict[str, tuple[float, str, int]] = {
    # Weekly co-created assets
    "USR-L04": (0.018, "25 分钟前", 1),
    "USR-S04": (0.045, "1 小时前", 1),
    # Monthly co-created assets
    "USR-L02": (9.0, "9 天前", 0),
    "USR-L03": (15.5, "16 天前", 0),
    "USR-S03": (18.0, "18 天前", 0),
    "USR-L01": (19.2, "19 天前", 0),
    # All-time classic co-created assets
    "USR-S05": (35.0, "1 个月前", 0),
    "USR-S01": (48.0, "2 个月前", 0),
    "USR-S02": (54.0, "2 个月前", 0),
}


def _calibrate_seed_period_horizons(db: Database) -> None:
    conn = db.get_conn()
    flag = conn.execute("SELECT 1 FROM site_settings WHERE key = 'seed_period_horizons_v3'").fetchone()
    if flag:
        return
    now_ms = int(time.time() * 1000)
    now_iso = utc_now_iso()
    with db.transaction() as tx:
        for wid, (days_ago, lbl, is_new) in SEED_WORK_TIMELINE_DAYS.items():
            pub_ms = now_ms - int(days_ago * 86_400_000)
            tx.execute(
                "UPDATE works SET published_at_ms = ?, created_label = ?, is_new_release = ? WHERE id = ?",
                (pub_ms, lbl, is_new, wid),
            )
        # Ensure historical Hall-of-Fame flagship work_101 reflects cumulative multi-month engagement
        tx.execute(
            "UPDATE works SET cheers = MAX(cheers, 238), likes = MAX(likes, 356), favorites = MAX(favorites, 310), forks = MAX(forks, 136) WHERE id = 'work_101'"
        )
        for code, (days_ago, lbl, is_new) in SEED_ASSET_TIMELINE_DAYS.items():
            pub_ms = now_ms - int(days_ago * 86_400_000)
            tx.execute(
                "UPDATE catalog_assets SET published_at_ms = ?, created_label = ?, is_new_release = ? WHERE code = ?",
                (pub_ms, lbl, is_new, code),
            )
        tx.execute(
            "INSERT OR REPLACE INTO site_settings (key, value_json, updated_by, updated_at) VALUES ('seed_period_horizons_v3', '{\"calibrated\":true}', 'system', ?)",
            (now_iso,),
        )


def _seed_default_forum_moderators(db: Database) -> None:
    conn = db.get_conn()
    flag = conn.execute("SELECT 1 FROM site_settings WHERE key = 'seed_forum_moderators_v1'").fetchone()
    if flag:
        return
    now_iso = utc_now_iso()
    default_appointments = [
        ("reviewer_su", "all", "总版主", "全区社区内容风控与悬赏秩序维护"),
        ("momo_design", "assets", "特邀版主", "画风与图型共创专区主理版主"),
        ("lin_sketch", "tuning", "版主", "作品调优与提示词诊断版主"),
        ("pm_chen", "experience", "版主", "实战变现与工作流SOP版主"),
        ("pm_chen", "tools", "版主", "工具流与效率插件答疑版主"),
    ]
    with db.transaction() as tx:
        for uname, cat, title, note in default_appointments:
            urow = tx.execute("SELECT id, username FROM users WHERE username = ?", (uname,)).fetchone()
            if urow:
                tx.execute(
                    """
                    INSERT OR IGNORE INTO forum_moderators (user_id, username, category, title, appointed_by, note, created_at)
                    VALUES (?, ?, ?, ?, 'yang0', ?, ?)
                    """,
                    (int(urow["id"]), urow["username"], cat, title, note, now_iso),
                )
        tx.execute(
            "INSERT OR REPLACE INTO site_settings (key, value_json, updated_by, updated_at) VALUES ('seed_forum_moderators_v1', '{\"seeded\":true}', 'system', ?)",
            (now_iso,),
        )


def _seed_default_asset_social(db: Database) -> None:
    conn = db.get_conn()
    flag = conn.execute("SELECT 1 FROM site_settings WHERE key = 'seed_asset_social_v1'").fetchone()
    if flag:
        return
    now_iso = utc_now_iso()
    base_metrics = [
        ("FA-001", 168, 124),
        ("FX-001", 152, 118),
        ("FB-001", 119, 86),
        ("FB-031", 96, 74),
        ("FC-029", 108, 82),
        ("SC-021", 184, 146),
        ("SC-001", 112, 88),
        ("LX-001", 136, 102),
        ("IG-001", 128, 95),
        ("USR-S01", 64, 42),
        ("USR-S04", 72, 49),
        ("USR-L01", 58, 39),
        ("USR-L04", 66, 45),
    ]
    sample_comments = [
        ("acm_seed_01", "FA-001", "style", "su_editorial", "苏苏的纸上茶馆", "这款法式淡彩水墨感特别通透，配 3:4 留白标题几乎零翻车，做茶饮和节气卡首选！", "2天前"),
        ("acm_seed_02", "FA-001", "style", "lin_sketch", "林默 · 独立插画师", "笔触边缘控制得很柔和，搭配 C-15 暖米纸底色非常有杂志插画感。", "1天前"),
        ("acm_seed_03", "FX-001", "style", "brand_zhou", "周周品牌提案室", "云端独占黑盒出来的金箔与矿物颗粒层次很细腻，商业提案客户一眼过稿。", "3天前"),
        ("acm_seed_04", "SC-021", "layout", "pm_chen", "阿陈做产品", "小红书图文干货神级骨架！标题区与三段要点呼吸感极佳，字数控制在 45 字内效果最稳。", "1天前"),
        ("acm_seed_05", "SC-021", "layout", "momo_design", "沫沫视觉实验室", "无论是配 FA-001 还是 FC-029 都能稳住版心，已经收藏进常用创作台置顶栏了。", "8小时前"),
        ("acm_seed_06", "IG-001", "layout", "sprout_xia", "小夏初学手绘", "用来拆解读书笔记和产品流程图太省心了，逻辑箭头清晰不乱！", "5小时前"),
        ("acm_seed_07", "LX-001", "layout", "su_editorial", "苏苏的纸上茶馆", "中式竖排海报构图黄金比例，主副标题落款位置很讲究。", "2天前"),
        ("acm_seed_08", "USR-S04", "style", "yang0", "Yang · 创作者", "社区共创里非常惊艳的肌理配方，暖光层次感很强，值得点赞收藏！", "4小时前"),
    ]
    with db.transaction() as tx:
        for code, blikes, bfavs in base_metrics:
            tx.execute(
                "INSERT OR REPLACE INTO asset_social_seeds (asset_code, base_likes, base_favorites) VALUES (?, ?, ?)",
                (code, blikes, bfavs),
            )
        for cid, code, kind, uname, aname, txt, tlabel in sample_comments:
            tx.execute(
                """
                INSERT OR IGNORE INTO asset_comments (id, asset_code, asset_kind, author_username, author_name, text, status, time_label, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'published', ?, ?)
                """,
                (cid, code, kind, uname, aname, txt, tlabel, now_iso),
            )
        tx.execute(
            "INSERT OR REPLACE INTO site_settings (key, value_json, updated_by, updated_at) VALUES ('seed_asset_social_v1', '{\"seeded\":true}', 'system', ?)",
            (now_iso,),
        )


def _seed_default_operator_user(db: Database) -> None:
    conn = db.get_conn()
    existing = conn.execute("SELECT id FROM users WHERE username = 'ops_lin'").fetchone()
    if existing:
        return
    now_iso = utc_now_iso()
    pw_hash = hash_password(DEMO_DEFAULT_PASSWORD)
    with db.transaction() as tx:
        cur = tx.execute(
            """
            INSERT INTO users (
                username, display_name, email, password_hash, password_algo,
                role, status, bio, invite_code, api_key, created_at, last_login_at
            ) VALUES ('ops_lin', '林运营 · 社区增长官', 'ops_lin@handraw-style.com', ?, 'pbkdf2_sha256', 'operator', 'active', 'Handraw 社区活动、榜单与兑换码增长运营', 'ops_lin', ?, ?, ?)
            """,
            (pw_hash, generate_api_key(), now_iso, now_iso),
        )
        uid = int(cur.lastrowid)
        tx.execute(
            "INSERT INTO wallets (user_id, balance, free_quota_date, free_quota_used, checkin_date, locked, updated_at) VALUES (?, 160, '', 0, '', 0, ?)",
            (uid, now_iso),
        )
        tx.execute(
            "INSERT INTO ledgers (user_id, delta, balance_after, kind, event_key, reason, created_at) VALUES (?, 160, 160, 'welcome', 'seed_init_ops_lin', '运营管理员账号激活基金', ?)",
            (uid, now_iso),
        )


def is_demo_mode() -> bool:
    """Return whether synthetic demo content was explicitly requested.

    Production boot must be empty by default.  Deliberately accept only the
    documented value ``1`` so a typo such as ``true`` cannot turn on fake
    users, works, metrics, or generation history.
    """
    return os.environ.get("HANDRAW_DEMO_MODE", "").strip() == "1"


def _ensure_default_site_settings(db: Database) -> None:
    """Install missing policy defaults without replacing operator changes."""
    now_iso = utc_now_iso()
    with db.transaction() as tx:
        for key, value in DEFAULT_SITE_SETTINGS.items():
            tx.execute(
                "INSERT OR IGNORE INTO site_settings (key, value_json, updated_by, updated_at) VALUES (?, ?, 'system', ?)",
                (key, json.dumps(value, ensure_ascii=False), now_iso),
            )


def ensure_seeded(db: Database, force_reset: bool = False) -> None:
    db.migrate()
    demo_mode = is_demo_mode()
    if force_reset and not demo_mode:
        raise RuntimeError("force_reset requires HANDRAW_DEMO_MODE=1")

    conn = db.get_conn()
    if not force_reset:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
        if row and int(row["cnt"]) > 0:
            with db.transaction() as tx:
                tx.execute("UPDATE users SET role = 'operator' WHERE role = 'reviewer'")
            _ensure_default_site_settings(db)
            if demo_mode:
                _seed_default_operator_user(db)
                _calibrate_seed_period_horizons(db)
                _seed_default_forum_moderators(db)
                _seed_default_asset_social(db)
            return

        # A fresh production database gets only policy defaults.  The
        # community seed below is strictly demo-only and never deletes or
        # invents data in an existing installation.
        if not demo_mode:
            _ensure_default_site_settings(db)
            return

    seed_raw = json.loads(SEED_JSON_PATH.read_text(encoding="utf-8"))
    now_iso = utc_now_iso()
    now_ms = int(time.time() * 1000)
    default_pw_hash = hash_password(DEMO_DEFAULT_PASSWORD)

    with db.transaction() as tx:
        if force_reset:
            for tbl in (
                "audit_logs",
                "site_settings",
                "asset_comments",
                "asset_social_seeds",
                "forum_moderators",
                "user_uploads",
                "studio_generations",
                "studio_articles",
                "studio_workflows",
                "redeem_code_uses",
                "redeem_codes",
                "reports",
                "interactions",
                "unlocks",
                "collections",
                "forum_replies",
                "forum_topics",
                "work_comments",
                "works",
                "catalog_assets",
                "ledgers",
                "wallets",
                "sessions",
                "users",
            ):
                tx.execute(f"DELETE FROM {tbl};")

        # 1. Core Users (Admin, Operator, Reviewer, Creators)
        author_Directory: dict[str, tuple[str, str, int]] = {
            "yang0": ("Yang · 创作者", "admin", 128),
            "ops_lin": ("林运营 · 社区增长官", "operator", 160),
            "reviewer_su": ("苏审 · 运营与内容治理官", "operator", 90),
            "su_editorial": ("苏苏的纸上茶馆", "user", 216),
            "lin_sketch": ("林默 · 独立插画师", "user", 185),
            "momo_design": ("沫沫视觉实验室", "user", 154),
            "pm_chen": ("阿陈做产品", "user", 142),
            "brand_zhou": ("周周品牌提案室", "user", 168),
            "sprout_xia": ("小夏初学手绘", "user", 45),
        }

        for item in seed_raw.get("communityResources", []):
            uname = item.get("author")
            if uname and uname not in author_Directory:
                author_Directory[uname] = (item.get("authorName") or uname, "user", 60)

        for w in seed_raw.get("works", []):
            uname = w.get("author")
            if uname and uname not in author_Directory:
                author_Directory[uname] = (w.get("authorName") or uname, "user", 68)
            for cm in w.get("comments", []) or []:
                cu = cm.get("user")
                if cu and cu not in author_Directory:
                    author_Directory[cu] = (cm.get("name") or cu, "user", 35)

        for tp in seed_raw.get("topics", []):
            uname = tp.get("author")
            if uname and uname not in author_Directory:
                author_Directory[uname] = (tp.get("authorName") or uname, "user", 65)
            for rp in tp.get("replies", []) or []:
                ru = rp.get("user")
                if ru and ru not in author_Directory:
                    author_Directory[ru] = (rp.get("name") or ru, "user", 40)

        user_id_by_username: dict[str, int] = {}
        for uname, (dname, role, init_credits) in author_Directory.items():
            api_key = "hwk_yang0_local_dev_key" if uname == "yang0" else generate_api_key()
            cur = tx.execute(
                """
                INSERT INTO users (
                    username, display_name, email, password_hash, password_algo,
                    role, status, bio, invite_code, api_key, created_at, last_login_at
                ) VALUES (?, ?, ?, ?, 'pbkdf2_sha256', ?, 'active', ?, ?, ?, ?, ?)
                """,
                (
                    uname,
                    dname,
                    f"{uname}@handraw-style.com",
                    default_pw_hash,
                    role,
                    "Handraw 手绘风社区创作者",
                    uname,
                    api_key,
                    now_iso,
                    now_iso,
                ),
            )
            uid = int(cur.lastrowid)
            user_id_by_username[uname] = uid
            tx.execute(
                """
                INSERT INTO wallets (user_id, balance, free_quota_date, free_quota_used, checkin_date, locked, updated_at)
                VALUES (?, ?, '', 0, '', 0, ?)
                """,
                (uid, init_credits, now_iso),
            )
            if uname == "yang0":
                for idx, led in enumerate(reversed(seed_raw.get("initialLedger", []))):
                    tx.execute(
                        """
                        INSERT INTO ledgers (user_id, delta, balance_after, kind, event_key, reason, created_at)
                        VALUES (?, ?, ?, 'seed', ?, ?, ?)
                        """,
                        (
                            uid,
                            int(led.get("delta", 0)),
                            init_credits,
                            f"seed_yang0_{idx}",
                            str(led.get("reason") or "初始积分记录"),
                            str(led.get("time") or now_iso),
                        ),
                    )
            else:
                tx.execute(
                    """
                    INSERT INTO ledgers (user_id, delta, balance_after, kind, event_key, reason, created_at)
                    VALUES (?, ?, ?, 'welcome', ?, '账号激活与初始创作基金', ?)
                    """,
                    (uid, init_credits, init_credits, f"seed_init_{uname}", now_iso),
                )

        # 2. Exclusive & Community Catalog Assets
        for idx, ex in enumerate(seed_raw.get("exclusiveResources", [])):
            code = str(ex["id"]).upper()
            tx.execute(
                """
                INSERT INTO catalog_assets (
                    code, kind, source_type, author_username, author_name, name, group_name,
                    tier, unlock_cost, image_url, description, definition, prompt_en,
                    secret_blackbox_prompt, status, featured, is_new_release, cheers,
                    published_at_ms, created_label, created_at, updated_at
                ) VALUES (?, ?, 'exclusive', 'yang0', 'Handraw 官方实验室', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', 1, 0, ?, ?, '官方独占', ?, ?)
                """,
                (
                    code,
                    ex.get("kind", "style"),
                    ex.get("name", code),
                    ex.get("group", ""),
                    ex.get("tier", "login_free"),
                    int(ex.get("unlockCost") or 0),
                    ex.get("image", ""),
                    ex.get("description", ""),
                    ex.get("definition", ""),
                    f"Handraw cloud exclusive {code}",
                    SERVER_EXCLUSIVE_BLACKBOX.get(code, ""),
                    int(ex.get("featuredWorksBonus") or 20) * 3,
                    now_ms - (idx + 20) * 3_600_000,
                    now_iso,
                    now_iso,
                ),
            )

        for idx, cm in enumerate(seed_raw.get("communityResources", [])):
            code = str(cm["id"]).upper()
            created_lbl = str(cm.get("createdAt") or "2 天前")
            pub_ms = now_ms - _recency_offset_ms(created_lbl) - idx * 1000
            tx.execute(
                """
                INSERT INTO catalog_assets (
                    code, kind, source_type, author_username, author_name, name, group_name,
                    tier, unlock_cost, image_url, description, definition, prompt_en,
                    secret_blackbox_prompt, status, featured, is_new_release, cheers,
                    published_at_ms, created_label, created_at, updated_at
                ) VALUES (?, ?, 'community', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 'published', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    cm.get("kind", "style"),
                    cm.get("author", "yang0"),
                    cm.get("authorName", "创作者"),
                    cm.get("name", code),
                    cm.get("group", ""),
                    cm.get("tier", "free"),
                    int(cm.get("unlockCost") or 0),
                    cm.get("image", ""),
                    cm.get("description", ""),
                    cm.get("definition", ""),
                    f"Community {cm.get('kind', 'style')}: {cm.get('name', code)}",
                    1 if int(cm.get("cheers") or 0) >= 60 else 0,
                    1 if cm.get("isNewRelease") else 0,
                    int(cm.get("cheers") or 18),
                    pub_ms,
                    created_lbl,
                    now_iso,
                    now_iso,
                ),
            )

        # 3. Community Works + Comments
        for idx, w in enumerate(seed_raw.get("works", [])):
            wid = str(w["id"])
            created_lbl = str(w.get("createdAt") or "1 天前")
            pub_ms = now_ms - _recency_offset_ms(created_lbl) - idx * 1000
            cheers_val = int(w.get("cheers") if w.get("cheers") is not None else max(8, round(int(w.get("likes") or 16) * 0.74)))
            tx.execute(
                """
                INSERT INTO works (
                    id, author_username, author_name, title, images_json, styles_json,
                    layout_code, sc021_type, color_code, tone_code, ratio, mode, shoot_type,
                    mood, price, prompt, prompt_has_secret, notes, status, featured, is_new_release, pioneer_rewarded,
                    cheers, likes, favorites, forks, tips, views, stamp_counts_json,
                    published_at_ms, created_label, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'published', ?, ?, 0, ?, ?, ?, ?, 0, ?, '{}', ?, ?, ?, ?)
                """,
                (
                    wid,
                    w.get("author", "yang0"),
                    w.get("authorName", "创作者"),
                    w.get("title", "社区作品"),
                    json.dumps(w.get("images") or [], ensure_ascii=False),
                    json.dumps(w.get("styles") or [], ensure_ascii=False),
                    str(w.get("layout") or ""),
                    str(w.get("sc021Type") or ""),
                    str(w.get("color") or "C-15"),
                    str(w.get("tone") or "T-01"),
                    str(w.get("ratio") or "3:4"),
                    str(w.get("mode") or "graphic-text"),
                    str(w.get("shootType") or ""),
                    str(w.get("mood") or "治愈"),
                    int(w.get("price") or 0),
                    str(w.get("prompt") or ""),
                    str(w.get("notes") or ""),
                    1 if int(w.get("likes") or 0) >= 200 else 0,
                    1 if w.get("isNewRelease") else 0,
                    cheers_val,
                    int(w.get("likes") or 15),
                    int(w.get("favorites") or 10),
                    int(w.get("forks") or 3),
                    int(w.get("likes") or 15) * 4,
                    pub_ms,
                    created_lbl,
                    now_iso,
                    now_iso,
                ),
            )
            for cm in w.get("comments", []) or []:
                tx.execute(
                    """
                    INSERT INTO work_comments (id, work_id, author_username, author_name, text, status, time_label, created_at)
                    VALUES (?, ?, ?, ?, ?, 'published', ?, ?)
                    """,
                    (
                        str(cm.get("id") or f"wc_{wid}_{idx}"),
                        wid,
                        str(cm.get("user") or "yang0"),
                        str(cm.get("name") or "创作者"),
                        str(cm.get("text") or ""),
                        str(cm.get("time") or "1 小时前"),
                        now_iso,
                    ),
                )

        # 4. Forum Topics + Replies
        for idx, tp in enumerate(seed_raw.get("topics", [])):
            tid = str(tp["id"])
            created_lbl = str(tp.get("createdAt") or "5 小时前")
            pub_ms = now_ms - _recency_offset_ms(created_lbl) - idx * 1000
            bounty_val = int(tp.get("bounty") or 0)
            solved = 1 if tp.get("solved") else 0
            b_status = "settled" if (bounty_val > 0 and solved) else ("open" if bounty_val > 0 else "none")
            recipe_str = json.dumps(tp["recipe"], ensure_ascii=False) if tp.get("recipe") else ""
            tx.execute(
                """
                INSERT INTO forum_topics (
                    id, category, category_label, pinned, featured, title, author_username, author_name,
                    views, likes, favorites, price, bounty, bounty_status, solved, accepted_reply_id,
                    images_json, styles_json, layout_code, work_id, recipe_json, recipe_has_secret, summary, locked_body,
                    status, published_at_ms, created_label, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, 0, ?, ?, 'published', ?, ?, ?, ?)
                """,
                (
                    tid,
                    str(tp.get("category") or "experience"),
                    str(tp.get("categoryLabel") or "📘 实战经验与变现"),
                    1 if tp.get("pinned") else 0,
                    1 if int(tp.get("likes") or 0) >= 150 else 0,
                    str(tp.get("title") or ""),
                    str(tp.get("author") or "yang0"),
                    str(tp.get("authorName") or "创作者"),
                    int(tp.get("views") or 100),
                    int(tp.get("likes") or 12),
                    int(tp.get("favorites") or 8),
                    int(tp.get("price") or 0),
                    bounty_val,
                    b_status,
                    solved,
                    json.dumps(tp.get("images") or [], ensure_ascii=False),
                    json.dumps(tp.get("styles") or [], ensure_ascii=False),
                    str(tp.get("layout") or ""),
                    str(tp.get("workId") or ""),
                    recipe_str,
                    str(tp.get("summary") or ""),
                    str(tp.get("lockedBody") or ""),
                    pub_ms,
                    created_lbl,
                    now_iso,
                    now_iso,
                ),
            )
            for rp in tp.get("replies", []) or []:
                tx.execute(
                    """
                    INSERT INTO forum_replies (
                        id, topic_id, author_username, author_name, text, mounted_style, mounted_layout,
                        likes, accepted, status, time_label, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?)
                    """,
                    (
                        str(rp.get("id") or f"rp_{tid}"),
                        tid,
                        str(rp.get("user") or "yang0"),
                        str(rp.get("name") or "创作者"),
                        str(rp.get("text") or ""),
                        str(rp.get("mountedStyle") or ""),
                        str(rp.get("mountedLayout") or ""),
                        int(rp.get("likes") or 1),
                        1 if rp.get("accepted") else 0,
                        str(rp.get("time") or "1 小时前"),
                        now_iso,
                    ),
                )

        # 5. Initial Collections & Unlocks for yang0
        yang_id = user_id_by_username["yang0"]
        init_cols = seed_raw.get("initialCollections") or {}
        for bucket, id_list in init_cols.items():
            for tid in id_list or []:
                tx.execute(
                    "INSERT OR IGNORE INTO collections (user_id, bucket, target_id, created_at) VALUES (?, ?, ?, ?)",
                    (yang_id, bucket, str(tid), now_iso),
                )

        for unlocked_id in seed_raw.get("initialUnlockedIds") or []:
            tx.execute(
                """
                INSERT OR IGNORE INTO unlocks (user_id, author_username, target_type, target_id, cost, author_share, status, created_at)
                VALUES (?, 'ip_maker', 'work', ?, 10, 8, 'settled', ?)
                """,
                (yang_id, str(unlocked_id), now_iso),
            )

        # 6. Redeem Codes
        sample_codes = [
            ("HANDRAW2026", 30, 500, "2.0 全量上线社区福利兑换码"),
            ("VIP888", 88, 100, "创作者内测VIP积分加油包"),
            ("PIONEER50", 50, 200, "荒地开垦先锋创作礼券"),
        ]
        for code, creds, max_u, note in sample_codes:
            tx.execute(
                """
                INSERT INTO redeem_codes (code, credits, max_uses, used_count, note, active, expires_at, created_by, created_at)
                VALUES (?, ?, ?, 0, ?, 1, '2027-12-31', 'yang0', ?)
                """,
                (code, creds, max_u, note, now_iso),
            )

        # 7. Sample Reports for Admin Moderation Queue
        tx.execute(
            """
            INSERT INTO reports (reporter_id, reporter_username, target_type, target_id, target_title, reason, detail, status, created_at)
            VALUES (?, 'pm_chen', 'work', 'work_117', '夏日手工柠檬海盐气泡水 · 电商主图卖点拆解卡', '疑似画风编号标注偏差', '该作品主要偏写实产品图，建议核查是否应归入 FI-001 为主分类。', 'open', ?)
            """,
            (user_id_by_username["pm_chen"], now_iso),
        )
        tx.execute(
            """
            INSERT INTO reports (reporter_id, reporter_username, target_type, target_id, target_title, reason, detail, status, created_at)
            VALUES (?, 'su_editorial', 'topic', 'topic_202', '【悬赏 15 积分】用 SC-021 做猫咪窗台双拼转译', '悬赏超期待提醒结题', '已有两位创作者给出高质量调优方案，建议提醒楼主采纳结算。', 'open', ?)
            """,
            (user_id_by_username["su_editorial"], now_iso),
        )

        # 8. Official Studio Workflow Presets Metadata
        for preset in OFFICIAL_STUDIO_PRESETS:
            tx.execute(
                """
                INSERT INTO studio_workflows (
                    id, user_id, title, blueprint, scenario_badge, scenario_desc,
                    graph_json, is_official_preset, enabled, sort_order, updated_at_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, '{}', 1, 1, ?, ?, ?)
                """,
                (
                    str(preset["id"]),
                    yang_id,
                    str(preset["title"]),
                    str(preset["blueprint"]),
                    str(preset["scenario_badge"]),
                    str(preset["scenario_desc"]),
                    int(preset["sort_order"]),
                    now_ms,
                    now_iso,
                ),
            )

        # 9. Site Settings
        for k, val in DEFAULT_SITE_SETTINGS.items():
            tx.execute(
                "INSERT INTO site_settings (key, value_json, updated_by, updated_at) VALUES (?, ?, 'system', ?)",
                (k, json.dumps(val, ensure_ascii=False), now_iso),
            )

        # 10. Sample Studio Generation Log Entries for Dashboard & Gateway Monitor
        tx.execute(
            """
            INSERT INTO studio_generations (
                id, user_id, username, tab_title, mode, mode_label, kind,
                recipe_summary, prompt, items_json, engine, cost_type, credits_spent, status, created_at
            ) VALUES
                ('gen_seed_01', ?, 'yang0', '🎯 节气海报极速出图', 'poster', '海报 · 1 张', 'single', '画风:FX-001 · 图型:LX-001', '秋分桂花乌龙海报', '["/images/poster-demo-autumn-equinox.webp"]', 'live', 'free_quota', 0, 'success', ?),
                ('gen_seed_02', ?, 'su_editorial', '🔁 百图矩阵批量生产', 'graphic-text', '循环批量 · 10 张', 'loop', '循环:批量×10轮 · 画风:FA-001', '打工人反内卷治愈日签', '["/images/individual/FA/FA-001.webp"]', 'sample', 'credits', 2, 'success', ?)
            """,
            (yang_id, now_iso, user_id_by_username["su_editorial"], now_iso),
        )

        # 11. Initial Immutable Audit Log
        tx.execute(
            """
            INSERT INTO audit_logs (actor_id, actor_username, actor_role, action, target_type, target_id, reason, details_json, created_at)
            VALUES (?, 'yang0', 'admin', 'system.bootstrap', 'system', 'handraw_v2', '初始化 Handraw Web 2.0 数据库与默认运营策略', '{"version":"2.0.0"}', ?)
            """,
            (yang_id, now_iso),
        )

    _calibrate_seed_period_horizons(db)
    _seed_default_forum_moderators(db)
    _seed_default_asset_social(db)
