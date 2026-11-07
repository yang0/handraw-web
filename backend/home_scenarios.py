"""Home scenarios service, schema, and API helpers for Handraw Web 2.0.

Provides:
- Additive database schema and post-migration hook for default 8 scenarios.
- Public API for scenarios with deterministic rotation and ETag caching.
- Admin APIs for scenarios management, ordering, toggling, and work pinning.
- Shared SQL match rules builder used by public scenarios and works square feed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import time
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .db import Database

logger = logging.getLogger("handraw.home_scenarios")

# ---------------------------------------------------------------------------
# Default Scenarios (8 standard use-cases)
# ---------------------------------------------------------------------------

DEFAULT_SCENARIOS: list[dict[str, Any]] = [
    {
        "key": "xiaohongshu",
        "title": "小红书套图",
        "subtitle": "小红书爆款封面与排版，多图连贯成套输出",
        "studio_entry": "batch",
        "studio_params": {"purpose": "小红书套图", "layout": "SC-001"},
        "match_rules": {
            "series": ["SC"],
            "ratios": ["3:4"],
            "keywords": ["小红书", "套图", "组图", "社媒卡", "小红书主页"],
        },
        "sort_order": 10,
        "is_enabled": 1,
    },
    {
        "key": "gzh_inline",
        "title": "公众号贴图",
        "subtitle": "文章插图、次条与金句卡片，单张快速生成",
        "studio_entry": "quick",
        "studio_params": {"purpose": "公众号贴图", "layout": "SC-008"},
        "match_rules": {
            "series": ["SC"],
            "ratios": ["16:9", "3:4", "1:1"],
            "keywords": ["公众号", "贴图", "插图", "首图", "次条", "金句"],
        },
        "sort_order": 20,
        "is_enabled": 1,
    },
    {
        "key": "article_illus",
        "title": "文章配图",
        "subtitle": "长文智能分块与段落提炼，全篇批量统一视觉",
        "studio_entry": "article",
        "studio_params": {"purpose": "文章配图"},
        "match_rules": {
            "series": ["SC", "FA", "FB", "FC"],
            "keywords": ["文章", "配图", "段落", "长文", "专栏", "图文"],
        },
        "sort_order": 30,
        "is_enabled": 1,
    },
    {
        "key": "comic_4panel",
        "title": "漫画四格",
        "subtitle": "起承转合分镜连环画，故事生活化幽默表达",
        "studio_entry": "quick",
        "studio_params": {"purpose": "漫画四格", "layout": "SB-002"},
        "match_rules": {
            "series": ["SB"],
            "keywords": ["漫画", "分镜", "四格", "连环画", "生活漫画", "绘本"],
        },
        "sort_order": 40,
        "is_enabled": 1,
    },
    {
        "key": "ip_character",
        "title": "IP 形象设计",
        "subtitle": "三视图、表情包与百变穿搭，打造标志性专属吉祥物",
        "studio_entry": "quick",
        "studio_params": {"purpose": "IP形象", "layout": "IP-001"},
        "match_rules": {
            "series": ["IP"],
            "keywords": ["IP", "形象", "三视图", "吉祥物", "角色", "表情包"],
        },
        "sort_order": 50,
        "is_enabled": 1,
    },
    {
        "key": "ecommerce",
        "title": "电商图",
        "subtitle": "高质感主图、卖点标注与场景陈列，提升转化吸睛力",
        "studio_entry": "quick",
        "studio_params": {"purpose": "电商图", "layout": "EC-001"},
        "match_rules": {
            "series": ["EC"],
            "keywords": ["电商", "主图", "卖点", "产品", "结构", "SKU", "详情"],
        },
        "sort_order": 60,
        "is_enabled": 1,
    },
    {
        "key": "infographic",
        "title": "信息图/知识卡",
        "subtitle": "金字塔、步骤流与多维对比，复杂知识一图直观讲透",
        "studio_entry": "quick",
        "studio_params": {"purpose": "信息图", "layout": "IG-001"},
        "match_rules": {
            "series": ["IG"],
            "keywords": ["信息图", "知识卡", "对比", "流程", "步骤", "思维导图", "金字塔"],
        },
        "sort_order": 70,
        "is_enabled": 1,
    },
    {
        "key": "poster",
        "title": "海报",
        "subtitle": "大冲击力主视觉与标题版式，活动宣传与视觉封面首选",
        "studio_entry": "quick",
        "studio_params": {"purpose": "海报", "ratio": "3:4"},
        "match_rules": {
            "series": ["SC", "FC", "FE", "FG", "LX"],
            "ratios": ["3:4", "9:16"],
            "keywords": ["海报", "KV", "主视觉", "活动", "封面", "宣传"],
        },
        "sort_order": 80,
        "is_enabled": 1,
    },
]

# ---------------------------------------------------------------------------
# Migration DDL & Post-migration Hook
# ---------------------------------------------------------------------------

HOME_SCENARIOS_SQL = """
CREATE TABLE IF NOT EXISTS home_scenarios (
    key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    subtitle TEXT NOT NULL,
    studio_entry TEXT NOT NULL,
    studio_params_json TEXT NOT NULL DEFAULT '{}',
    match_rules_json TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_home_scenarios_order
    ON home_scenarios(sort_order ASC, is_enabled DESC);

CREATE TABLE IF NOT EXISTS scenario_pinned_works (
    scenario_key TEXT NOT NULL,
    work_id TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (scenario_key, work_id),
    FOREIGN KEY (scenario_key) REFERENCES home_scenarios(key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scenario_pins_order
    ON scenario_pinned_works(scenario_key, sort_order ASC);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_default_home_scenarios_hook(conn: sqlite3.Connection) -> None:
    """Insert default scenarios if they do not exist; never overwrite admin edits."""
    now_iso = _now_iso()
    for sc in DEFAULT_SCENARIOS:
        existing = conn.execute(
            "SELECT 1 FROM home_scenarios WHERE key = ?", (sc["key"],)
        ).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT INTO home_scenarios (
                    key, title, subtitle, studio_entry, studio_params_json,
                    match_rules_json, sort_order, is_enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sc["key"],
                    sc["title"],
                    sc["subtitle"],
                    sc["studio_entry"],
                    json.dumps(sc.get("studio_params") or {}, ensure_ascii=False),
                    json.dumps(sc.get("match_rules") or {}, ensure_ascii=False),
                    int(sc.get("sort_order") or 0),
                    1 if sc.get("is_enabled", True) else 0,
                    now_iso,
                    now_iso,
                ),
            )


SCENARIOS_MIGRATIONS: list[tuple[int, str, str]] = [
    (86, "086_home_scenarios", HOME_SCENARIOS_SQL),
]

SCENARIOS_POST_MIGRATION_HOOKS: dict[int, Any] = {
    86: seed_default_home_scenarios_hook,
}

# ---------------------------------------------------------------------------
# In-Memory Server Cache
# ---------------------------------------------------------------------------

SCENARIOS_CACHE_TTL_SECONDS = 120
_SCENARIOS_CACHE: dict[str, tuple[dict[str, Any], str, float]] = {}


@lru_cache(maxsize=4)
def _scenario_redis_client(redis_url: str):
    import redis
    return redis.Redis.from_url(
        redis_url, socket_connect_timeout=2, socket_timeout=2,
        decode_responses=True,
    )


def _scenario_revision_key() -> str:
    prefix = os.environ.get("HANDRAW_REDIS_PREFIX", "handraw:prod").strip()
    if not re.fullmatch(r"[a-zA-Z0-9:_-]{1,100}", prefix):
        raise ValueError("Unsafe Redis scenario cache namespace")
    return prefix + ":home-scenarios:revision"


def _scenario_cache_key(date_key: str) -> str | None:
    redis_url = os.environ.get("HANDRAW_REDIS_URL", "").strip()
    if not redis_url:
        return date_key
    try:
        revision = _scenario_redis_client(redis_url).get(_scenario_revision_key()) or "0"
        return f"{date_key}:{revision}"
    except Exception:
        # Multi-worker mode cannot safely serve a stale per-process cache
        # if the shared revision is unreachable.
        logger.warning("Home-scenario Redis cache revision unavailable; bypassing local cache")
        return None


def invalidate_scenarios_cache() -> None:
    """Invalidate home-scene cards in this worker and other Redis workers."""
    _SCENARIOS_CACHE.clear()
    redis_url = os.environ.get("HANDRAW_REDIS_URL", "").strip()
    if redis_url:
        try:
            _scenario_redis_client(redis_url).incr(_scenario_revision_key())
        except Exception:
            logger.warning("Home-scenario Redis invalidation failed; peers will bypass cache if Redis is down")


# ---------------------------------------------------------------------------
# Rule Matching Logic (Used by Scenarios and Works Feed)
# ---------------------------------------------------------------------------

def build_scenario_match_clause(
    rules: dict[str, Any],
    table_alias: str = "w",
) -> tuple[str, list[Any]]:
    """Build parameterized WHERE clause matching a work against scenario rules."""
    prefix = f"{table_alias}." if table_alias else ""
    series_list = [str(s).strip().upper() for s in (rules.get("series") or []) if str(s).strip()]
    ratios_list = [str(r).strip() for r in (rules.get("ratios") or []) if str(r).strip()]
    keywords_list = [str(k).strip() for k in (rules.get("keywords") or []) if str(k).strip()]

    clauses: list[str] = []
    params: list[Any] = []

    or_subclauses: list[str] = []
    or_params: list[Any] = []

    # 1. Series prefix match
    if series_list:
        series_ors: list[str] = []
        for s in series_list:
            series_ors.append(
                f"({prefix}layout_code = ? OR {prefix}layout_code LIKE ? OR {prefix}styles_json LIKE ?)"
            )
            or_params.extend([s, f"{s}-%", f'%"{s}-%'])
        or_subclauses.append("(" + " OR ".join(series_ors) + ")")

    # 2. Keywords match across title, subject, notes (prompt excluded per #70 review)
    if keywords_list:
        kw_ors: list[str] = []
        for kw in keywords_list:
            kw_param = f"%{kw}%"
            kw_ors.append(
                f"({prefix}title LIKE ? OR {prefix}subject LIKE ? OR {prefix}notes LIKE ?)"
            )
            or_params.extend([kw_param, kw_param, kw_param])
        or_subclauses.append("(" + " OR ".join(kw_ors) + ")")

    if or_subclauses:
        clauses.append("(" + " OR ".join(or_subclauses) + ")")
        params.extend(or_params)

    # 3. Ratio filter: if specified, constrains the aspect ratio
    if ratios_list:
        placeholders = ", ".join("?" for _ in ratios_list)
        clauses.append(f"{prefix}ratio IN ({placeholders})")
        params.extend(ratios_list)

    if not clauses:
        return "1 = 1", []

    return " AND ".join(clauses), params


def get_scenario_match_clause_by_key(
    conn: sqlite3.Connection,
    scenario_key: str,
    table_alias: str = "w",
) -> tuple[str, list[Any]]:
    """Look up scenario by key and build match clause; returns 1=0 if key unknown."""
    row = conn.execute(
        "SELECT match_rules_json FROM home_scenarios WHERE key = ?", (scenario_key,)
    ).fetchone()
    if not row:
        return "1 = 0", []
    try:
        rules = json.loads(row["match_rules_json"] or "{}")
    except Exception:
        rules = {}
    return build_scenario_match_clause(rules, table_alias=table_alias)


def _extract_first_image(images_json: str | None) -> str:
    """Safely extract the first valid image URL from images_json."""
    if not images_json:
        return ""
    try:
        parsed = json.loads(images_json)
        if isinstance(parsed, list):
            for img in parsed:
                if isinstance(img, str) and img.strip():
                    return img.strip()
                if isinstance(img, dict) and str(img.get("url") or "").strip():
                    return str(img.get("url") or "").strip()
    except Exception:
        pass
    return ""


def _cover_for_work(row: Any) -> str:
    """Honor the V3 cover selection, including pinned and admin scene cards."""
    first = _extract_first_image(row["images_json"])
    selected = str(row["selected_cover_url"] or "").strip()
    if selected and first:
        try:
            images = json.loads(row["images_json"] or "[]")
            if selected in images:
                return selected
        except (TypeError, ValueError):
            pass
    return first


# ---------------------------------------------------------------------------
# Public API: GET /api/public/home-scenarios
# ---------------------------------------------------------------------------

def get_public_home_scenarios(
    db: Database,
    date_key: str | None = None,
    max_samples_per_scenario: int = 4,
) -> tuple[dict[str, Any], str]:
    """Retrieve enabled home scenarios and 3~4 sample works per scenario.

    Uses deterministic rotation based on date_key and weights by user engagement.
    Reuses existing public visibility validation (status='published', valid images, seed exclusion).
    Ensures that within the same day's results across all scenarios, each work appears at most once:
      1. Pinned works take precedence and claim slots first.
      2. Auto-filling proceeds in scenario sort_order, skipping works already claimed.
    Supports in-memory caching with a short TTL (120s) fallback.
    Returns (payload_dict, etag_str).
    """
    from .services import _seed_filter
    from .works_feed import is_valid_work_row

    conn = db.get_conn()
    if not date_key:
        date_key = _now_iso()[:10]

    now_mono = time.monotonic()
    cache_key = _scenario_cache_key(date_key)
    cache_entry = _SCENARIOS_CACHE.get(cache_key) if cache_key is not None else None
    if cache_entry is not None:
        payload, etag, expires_at = cache_entry
        if now_mono < expires_at:
            return payload, etag
        else:
            if cache_key is not None:
                _SCENARIOS_CACHE.pop(cache_key, None)

    # Evict any other entries to prevent memory inflation from variable date queries
    _SCENARIOS_CACHE.clear()

    seed_clause, seed_params = _seed_filter("w.id", "works")

    sc_rows = conn.execute(
        """
        SELECT * FROM home_scenarios
        WHERE is_enabled = 1
        ORDER BY sort_order ASC, created_at ASC
        """
    ).fetchall()

    globally_claimed_work_ids: set[str] = set()
    scenario_samples_map: dict[str, list[dict[str, Any]]] = {}

    # Pass 1: Collect pinned works for each scenario in sort_order (pinned works take precedence)
    for sc in sc_rows:
        s_key = sc["key"]
        pinned_rows = conn.execute(
            f"""
            SELECT spw.work_id, spw.sort_order AS pin_order, w.*,
                   cover.storage_key AS selected_cover_url
            FROM scenario_pinned_works spw
            JOIN works w ON w.id = spw.work_id
            LEFT JOIN media_assets cover ON cover.id = w.cover_media_id
            WHERE spw.scenario_key = ?
              AND w.status = 'published'
              AND {seed_clause}
            ORDER BY spw.sort_order ASC, spw.created_at ASC
            """,
            (s_key, *seed_params),
        ).fetchall()

        picked_samples: list[dict[str, Any]] = []
        for pr in pinned_rows:
            if not is_valid_work_row(pr):
                continue
            wid = pr["id"]
            if wid in globally_claimed_work_ids:
                continue
            first_img = _cover_for_work(pr)
            if not first_img:
                continue
            globally_claimed_work_ids.add(wid)
            picked_samples.append(
                {
                    "id": wid,
                    "title": pr["title"] or "",
                    "imageUrl": first_img,
                    "coverUrl": first_img,
                    "author": pr["author_name"] or pr["author_username"] or "",
                    "authorUsername": pr["author_username"] or "",
                    "detailUrl": f"/?view=work&id={wid}",
                    "isPinned": True,
                }
            )
            if len(picked_samples) >= max_samples_per_scenario:
                break
        scenario_samples_map[s_key] = picked_samples

    # Pass 2: Prepare candidate lists for each scenario (using date_key and engagement weighting)
    candidates_by_scenario: dict[str, list[dict[str, Any]]] = {}
    for sc in sc_rows:
        s_key = sc["key"]
        try:
            match_rules = json.loads(sc["match_rules_json"] or "{}")
        except Exception:
            match_rules = {}

        match_sql, match_params = build_scenario_match_clause(match_rules, table_alias="w")
        candidate_rows = conn.execute(
            f"""
            SELECT w.*, cover.storage_key AS selected_cover_url
            FROM works w
            LEFT JOIN media_assets cover ON cover.id = w.cover_media_id
            WHERE w.status = 'published'
              AND {seed_clause}
              AND ({match_sql})
            """,
            (*seed_params, *match_params),
        ).fetchall()

        scored_cands: list[dict[str, Any]] = []
        for cr in candidate_rows:
            wid = cr["id"]
            if wid in globally_claimed_work_ids:
                continue
            if not is_valid_work_row(cr):
                continue
            first_img = _cover_for_work(cr)
            if not first_img:
                continue

            # Deterministic daily rotation score
            seed_str = f"{date_key}:{s_key}:{wid}"
            h = int(hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:8], 16)
            norm_h = h / 0xFFFFFFFF
            likes = int(cr["likes"] or 0)
            cheers = int(cr["cheers"] or 0)
            weight = 1.0 + math.log1p(max(0, likes + cheers))
            score = norm_h * weight

            scored_cands.append(
                {
                    "id": wid,
                    "title": cr["title"] or "",
                    "imageUrl": first_img,
                    "coverUrl": first_img,
                    "author": cr["author_name"] or cr["author_username"] or "",
                    "authorUsername": cr["author_username"] or "",
                    "detailUrl": f"/?view=work&id={wid}",
                    "isPinned": False,
                    "score": score,
                }
            )

        scored_cands.sort(key=lambda x: x["score"], reverse=True)
        candidates_by_scenario[s_key] = scored_cands

    # Pass 2: Round-robin allocation across scenarios
    # In each round, every scenario that is not full and has available candidates takes 1 work.
    # Scenarios with fewer available candidates pick first; ties broken by sort_order.
    while True:
        active_scenarios = []
        for sc in sc_rows:
            s_key = sc["key"]
            if len(scenario_samples_map[s_key]) >= max_samples_per_scenario:
                continue
            avail = [c for c in candidates_by_scenario[s_key] if c["id"] not in globally_claimed_work_ids]
            if avail:
                active_scenarios.append(
                    {
                        "sc": sc,
                        "key": s_key,
                        "avail_count": len(avail),
                        "sort_order": sc["sort_order"],
                    }
                )

        if not active_scenarios:
            break

        active_scenarios.sort(key=lambda x: (x["avail_count"], x["sort_order"], x["key"]))

        claimed_in_this_round = False
        for act in active_scenarios:
            s_key = act["key"]
            if len(scenario_samples_map[s_key]) >= max_samples_per_scenario:
                continue
            # Pick the top unclaimed candidate for this scenario
            for c in candidates_by_scenario[s_key]:
                if c["id"] not in globally_claimed_work_ids:
                    globally_claimed_work_ids.add(c["id"])
                    scenario_samples_map[s_key].append(
                        {
                            "id": c["id"],
                            "title": c["title"],
                            "imageUrl": c["imageUrl"],
                            "coverUrl": c["coverUrl"],
                            "author": c["author"],
                            "authorUsername": c["authorUsername"],
                            "detailUrl": c["detailUrl"],
                            "isPinned": False,
                        }
                    )
                    claimed_in_this_round = True
                    break

        if not claimed_in_this_round:
            break

    # Build response items
    items: list[dict[str, Any]] = []
    for sc in sc_rows:
        s_key = sc["key"]
        try:
            match_rules = json.loads(sc["match_rules_json"] or "{}")
        except Exception:
            match_rules = {}
        try:
            studio_params = json.loads(sc["studio_params_json"] or "{}")
        except Exception:
            studio_params = {}

        items.append(
            {
                "key": s_key,
                "title": sc["title"],
                "subtitle": sc["subtitle"],
                "studioEntry": sc["studio_entry"],
                "studioParams": studio_params,
                "matchRules": match_rules,
                "sortOrder": sc["sort_order"],
                "samples": scenario_samples_map[s_key],
            }
        )

    payload = {
        "ok": True,
        "dateKey": date_key,
        "items": items,
        "total": len(items),
    }

    raw_json = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    etag = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()[:16]

    if cache_key is not None:
        _SCENARIOS_CACHE[cache_key] = (
            payload, etag, time.monotonic() + SCENARIOS_CACHE_TTL_SECONDS,
        )
    return payload, etag


# ---------------------------------------------------------------------------
# Admin APIs: /api/admin/home-scenarios
# ---------------------------------------------------------------------------

def admin_list_home_scenarios(
    db: Database,
    user: dict[str, Any] | None,
) -> dict[str, Any]:
    """Admin endpoint to list all scenarios with pinned works and current preview samples."""
    from .admin_services import require_staff
    from .services import _seed_filter
    from .works_feed import is_valid_work_row

    require_staff(user, allow_reviewer=True)
    conn = db.get_conn()
    seed_clause, seed_params = _seed_filter("w.id", "works")

    rows = conn.execute(
        "SELECT * FROM home_scenarios ORDER BY sort_order ASC, created_at ASC"
    ).fetchall()

    # Pre-fetch preview samples for display in admin
    public_data, _ = get_public_home_scenarios(db)
    sample_map = {item["key"]: item.get("samples") or [] for item in public_data.get("items") or []}

    items: list[dict[str, Any]] = []
    for r in rows:
        k = r["key"]
        try:
            m_rules = json.loads(r["match_rules_json"] or "{}")
        except Exception:
            m_rules = {}
        try:
            s_params = json.loads(r["studio_params_json"] or "{}")
        except Exception:
            s_params = {}

        # Fetch pinned works info
        pinned_rows = conn.execute(
            f"""
            SELECT spw.sort_order AS pin_order, spw.created_by, spw.created_at AS pinned_at,
                   w.id, w.title, w.status, w.author_username, w.author_name,
                   w.images_json, w.likes, w.cheers, cover.storage_key AS selected_cover_url
            FROM scenario_pinned_works spw
            LEFT JOIN works w ON w.id = spw.work_id
            LEFT JOIN media_assets cover ON cover.id = w.cover_media_id
            WHERE spw.scenario_key = ?
            ORDER BY spw.sort_order ASC, spw.created_at ASC
            """,
            (k,),
        ).fetchall()

        pins = []
        for pr in pinned_rows:
            pins.append(
                {
                    "workId": pr["id"] or "",
                    "pinOrder": pr["pin_order"],
                    "title": pr["title"] or "(已删除作品)",
                    "status": pr["status"] or "deleted",
                    "author": pr["author_name"] or pr["author_username"] or "",
                    "imageUrl": _cover_for_work(pr) if pr["images_json"] else "",
                    "isPublic": bool(pr["status"] == "published" and is_valid_work_row(pr)),
                    "createdBy": pr["created_by"],
                    "pinnedAt": pr["pinned_at"],
                }
            )

        items.append(
            {
                "key": k,
                "title": r["title"],
                "subtitle": r["subtitle"],
                "studioEntry": r["studio_entry"],
                "studioParams": s_params,
                "matchRules": m_rules,
                "sortOrder": r["sort_order"],
                "isEnabled": bool(r["is_enabled"]),
                "createdAt": r["created_at"],
                "updatedAt": r["updated_at"],
                "pins": pins,
                "previewSamples": sample_map.get(k, []),
            }
        )

    return {
        "ok": True,
        "items": items,
        "total": len(items),
    }


def admin_save_home_scenario(
    db: Database,
    user: dict[str, Any] | None,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Admin endpoint to create or update scenario fields."""
    from .admin_services import record_audit_log, require_staff

    require_staff(user, allow_reviewer=False)
    key = str(data.get("key") or "").strip().lower()
    if not key or not re.match(r"^[a-z0-9_-]{2,40}$", key):
        raise ValueError("场景标识 key 格式不合法（支持2~40位英文字母、数字及连字符）")

    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("场景标题不能为空")

    subtitle = str(data.get("subtitle") or "").strip()
    studio_entry = str(data.get("studioEntry") or data.get("studio_entry") or "quick").strip().lower()
    if studio_entry not in ("quick", "batch", "article", "canvas"):
        raise ValueError("创作台入口只能是 quick / batch / article / canvas")

    studio_params = data.get("studioParams") or data.get("studio_params") or {}
    if not isinstance(studio_params, dict):
        studio_params = {}

    match_rules = data.get("matchRules") or data.get("match_rules") or {}
    if not isinstance(match_rules, dict):
        match_rules = {}

    sort_order = int(data.get("sortOrder") if data.get("sortOrder") is not None else data.get("sort_order", 0))
    is_enabled = 1 if data.get("isEnabled", data.get("is_enabled", True)) else 0

    now_iso = _now_iso()

    with db.transaction() as tx:
        existing = tx.execute("SELECT * FROM home_scenarios WHERE key = ?", (key,)).fetchone()
        if existing:
            tx.execute(
                """
                UPDATE home_scenarios
                SET title = ?, subtitle = ?, studio_entry = ?, studio_params_json = ?,
                    match_rules_json = ?, sort_order = ?, is_enabled = ?, updated_at = ?
                WHERE key = ?
                """,
                (
                    title,
                    subtitle,
                    studio_entry,
                    json.dumps(studio_params, ensure_ascii=False),
                    json.dumps(match_rules, ensure_ascii=False),
                    sort_order,
                    is_enabled,
                    now_iso,
                    key,
                ),
            )
            action = "scenario.update"
        else:
            tx.execute(
                """
                INSERT INTO home_scenarios (
                    key, title, subtitle, studio_entry, studio_params_json,
                    match_rules_json, sort_order, is_enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    title,
                    subtitle,
                    studio_entry,
                    json.dumps(studio_params, ensure_ascii=False),
                    json.dumps(match_rules, ensure_ascii=False),
                    sort_order,
                    is_enabled,
                    now_iso,
                    now_iso,
                ),
            )
            action = "scenario.create"

        record_audit_log(
            tx,
            user,
            action,
            "home_scenario",
            key,
            details={
                "title": title,
                "studio_entry": studio_entry,
                "sort_order": sort_order,
                "is_enabled": is_enabled,
            },
        )

    invalidate_scenarios_cache()
    return {"ok": True, "key": key}


def admin_toggle_home_scenario(
    db: Database,
    user: dict[str, Any] | None,
    key: str,
    is_enabled: bool,
) -> dict[str, Any]:
    """Toggle enabled status of a scenario."""
    from .admin_services import record_audit_log, require_staff

    require_staff(user, allow_reviewer=False)
    key = str(key or "").strip().lower()
    now_iso = _now_iso()

    with db.transaction() as tx:
        row = tx.execute("SELECT 1 FROM home_scenarios WHERE key = ?", (key,)).fetchone()
        if not row:
            raise ValueError(f"场景不存在：{key}")
        tx.execute(
            "UPDATE home_scenarios SET is_enabled = ?, updated_at = ? WHERE key = ?",
            (1 if is_enabled else 0, now_iso, key),
        )
        record_audit_log(
            tx,
            user,
            "scenario.toggle",
            "home_scenario",
            key,
            details={"is_enabled": is_enabled},
        )

    invalidate_scenarios_cache()
    return {"ok": True, "key": key, "isEnabled": is_enabled}


def admin_reorder_home_scenarios(
    db: Database,
    user: dict[str, Any] | None,
    orders: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reorder scenarios."""
    from .admin_services import record_audit_log, require_staff

    require_staff(user, allow_reviewer=False)
    now_iso = _now_iso()

    with db.transaction() as tx:
        for it in orders:
            k = str(it.get("key") or "").strip().lower()
            so = int(it.get("sortOrder") if it.get("sortOrder") is not None else it.get("sort_order", 0))
            if k:
                tx.execute(
                    "UPDATE home_scenarios SET sort_order = ?, updated_at = ? WHERE key = ?",
                    (so, now_iso, k),
                )
        record_audit_log(
            tx,
            user,
            "scenario.reorder",
            "home_scenario",
            "all",
            details={"count": len(orders)},
        )

    invalidate_scenarios_cache()
    return {"ok": True, "reordered": len(orders)}


def admin_pin_scenario_work(
    db: Database,
    user: dict[str, Any] | None,
    scenario_key: str,
    work_id: str,
    sort_order: int = 0,
) -> dict[str, Any]:
    """Pin a work to a scenario."""
    from .admin_services import record_audit_log, require_staff

    require_staff(user, allow_reviewer=False)
    scenario_key = str(scenario_key or "").strip().lower()
    work_id = str(work_id or "").strip()
    if not scenario_key or not work_id:
        raise ValueError("场景 key 和作品 ID 不能为空")

    now_iso = _now_iso()
    actor_name = user["username"] if user else ""

    with db.transaction() as tx:
        sc = tx.execute("SELECT 1 FROM home_scenarios WHERE key = ?", (scenario_key,)).fetchone()
        if not sc:
            raise ValueError(f"场景不存在：{scenario_key}")
        w = tx.execute("SELECT id, title, status FROM works WHERE id = ?", (work_id,)).fetchone()
        if not w:
            raise ValueError(f"作品不存在：{work_id}")

        tx.execute(
            """
            INSERT INTO scenario_pinned_works (scenario_key, work_id, sort_order, created_by, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(scenario_key, work_id)
            DO UPDATE SET sort_order=excluded.sort_order,
                          created_by=excluded.created_by,
                          created_at=excluded.created_at
            """,
            (scenario_key, work_id, sort_order, actor_name, now_iso),
        )
        record_audit_log(
            tx,
            user,
            "scenario.pin_work",
            "home_scenario",
            scenario_key,
            details={"work_id": work_id, "sort_order": sort_order},
        )

    invalidate_scenarios_cache()
    return {"ok": True, "scenarioKey": scenario_key, "workId": work_id}


def admin_unpin_scenario_work(
    db: Database,
    user: dict[str, Any] | None,
    scenario_key: str,
    work_id: str,
) -> dict[str, Any]:
    """Unpin a work from a scenario."""
    from .admin_services import record_audit_log, require_staff

    require_staff(user, allow_reviewer=False)
    scenario_key = str(scenario_key or "").strip().lower()
    work_id = str(work_id or "").strip()

    with db.transaction() as tx:
        tx.execute(
            "DELETE FROM scenario_pinned_works WHERE scenario_key = ? AND work_id = ?",
            (scenario_key, work_id),
        )
        record_audit_log(
            tx,
            user,
            "scenario.unpin_work",
            "home_scenario",
            scenario_key,
            details={"work_id": work_id},
        )

    invalidate_scenarios_cache()
    return {"ok": True, "scenarioKey": scenario_key, "workId": work_id}


def admin_reorder_scenario_pins(
    db: Database,
    user: dict[str, Any] | None,
    scenario_key: str,
    work_ids: list[str],
) -> dict[str, Any]:
    """Reorder pins for a scenario."""
    from .admin_services import record_audit_log, require_staff

    require_staff(user, allow_reviewer=False)
    scenario_key = str(scenario_key or "").strip().lower()

    with db.transaction() as tx:
        for idx, wid in enumerate(work_ids):
            tx.execute(
                "UPDATE scenario_pinned_works SET sort_order = ? WHERE scenario_key = ? AND work_id = ?",
                ((idx + 1) * 10, scenario_key, str(wid).strip()),
            )
        record_audit_log(
            tx,
            user,
            "scenario.reorder_pins",
            "home_scenario",
            scenario_key,
            details={"pins": work_ids},
        )

    invalidate_scenarios_cache()
    return {"ok": True, "scenarioKey": scenario_key, "reordered": len(work_ids)}
