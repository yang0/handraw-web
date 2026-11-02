"""Admin Management Backend services for Handraw Web 2.0 (RBAC, Moderation, Blackbox, Economy, Audit)."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Any

from .config import CONTENT_DIR, get_image_config_path
from .db import Database, local_today_str, utc_now_iso
from .security import generate_api_key, hash_password
from .services import (
    ACTOR_RANK,
    FORUM_BOARD_LABELS,
    FORUM_BOARD_SHORT_LABELS,
    FORUM_BOARDS,
    ServiceError,
    _count_user_published_items,
    apply_wallet_delta,
    compute_honor_tier,
    format_relative_cn,
    format_short_time,
    get_site_settings,
    get_wallet_quota_state,
    is_demo_mode,
    record_audit_log,
    _seed_filter,
)

FORUM_CATEGORY_LABELS = {
    **FORUM_BOARD_LABELS,
    "showcase": "晒图交流",
    "workflow": "配方拆解",
    "qa": "求助悬赏",
    "official": "官方动态",
}


ROLE_MATRIX_SPEC: list[dict[str, Any]] = [
    {
        "role": "admin",
        "badge": "👑 超级管理员",
        "consoleTitle": "全站中枢超管控制台",
        "modules": ["dashboard", "users", "works", "catalog", "governance", "gateway", "settings"],
        "summary": "拥有全站最高权限：新建/管理所有用户与角色、任命论坛版主、读写云端黑盒底层 Prompt、积分人工调账、订单退单、网关监控与全量系统参数。",
    },
    {
        "role": "operator",
        "badge": "🧭 运营审查员",
        "consoleTitle": "社区运营与内容审查台",
        "modules": ["dashboard", "users", "works", "governance", "settings"],
        "summary": "全面负责社区运营增长与内容安全巡检：作品/帖子/评论审核上架与违规下架/删除、举报裁定、违规账号冻结、荣誉授勋、免费额度重置、兑换码发放与社区公告（严格禁止自审本人内容；隔离黑盒机密、生图网关与角色提权）。",
    },
    {
        "role": "moderator",
        "badge": "🏛️ 论坛版主",
        "consoleTitle": "论坛板块专属版务工作台",
        "modules": ["mod_overview", "mod_topics", "mod_replies", "mod_reports"],
        "summary": "仅限所辖论坛板块（如画风与图型专区、求调优悬赏等）执行帖子置顶、设精华、跨板块移动、违规帖/回复隐藏及本版举报处理；与全站用户库、作品库物理隔离。",
    },
]


def get_management_profile(conn: sqlite3.Connection, user: dict[str, Any] | None) -> dict[str, Any]:
    if not user or user.get("status") != "active":
        return {
            "effectiveRole": "guest",
            "badge": "🔒 未登录或无权限",
            "consoleTitle": "无后台访问权限",
            "allowedModules": [],
            "moderatedBoards": [],
            "moderatedBoardDetails": [],
            "capabilities": {},
        }
    raw_role = str(user.get("role") or "user")
    u_role = "operator" if raw_role == "reviewer" else raw_role
    moderator_user_filter, moderator_user_params = _admin_user_seed_filter("u.username")
    mod_rows = conn.execute(
        f"""
        SELECT fm.category, fm.title, fm.note
        FROM forum_moderators fm
        JOIN users u ON u.id = fm.user_id
        WHERE fm.user_id = ? AND {moderator_user_filter}
        ORDER BY CASE fm.category WHEN 'all' THEN 0 ELSE 1 END, fm.id ASC
        """,
        (int(user["id"]), *moderator_user_params),
    ).fetchall()
    mod_boards = [r["category"] for r in mod_rows]
    mod_details = [
        {
            "category": r["category"],
            "label": "📋 全区全部板块" if r["category"] == "all" else FORUM_BOARD_LABELS.get(r["category"], r["category"]),
            "shortLabel": FORUM_BOARD_SHORT_LABELS.get(r["category"], r["category"]),
            "title": r["title"] or "版主",
        }
        for r in mod_rows
    ]

    if u_role in ("admin", "operator"):
        eff = u_role
    elif mod_boards:
        eff = "moderator"
    else:
        eff = "user"

    spec = next((x for x in ROLE_MATRIX_SPEC if x["role"] == eff), None)
    caps = {
        "canCreateUser": eff == "admin",
        "canDeleteUser": eff == "admin",
        "canEditSystemRole": eff == "admin",
        "canResetUserPassword": eff == "admin",
        "canManageModerators": eff == "admin",
        "canAdjustCredits": eff == "admin",
        "canRefundUnlocks": eff == "admin",
        "canImportDiscourse": eff == "admin",
        "canManageRedeemCodes": eff in ("admin", "operator"),
        "canArbitrateBounty": eff in ("admin", "operator"),
        "canEditUserHonor": eff in ("admin", "operator"),
        "canResetFreeQuota": eff in ("admin", "operator"),
        "canEditAnnouncement": eff in ("admin", "operator"),
        "canEditSystemSettings": eff == "admin",
        "canViewAuditLogs": eff == "admin",
        "canManageGateway": eff == "admin",
        "canViewBlackbox": eff == "admin",
        "canDeleteContent": eff in ("admin", "operator"),
        "canModerateContent": eff in ("admin", "operator"),
        "canFreezeRegularUser": eff in ("admin", "operator"),
        "isBoardScoped": eff == "moderator",
    }
    return {
        "effectiveRole": eff,
        "systemRole": u_role,
        "badge": spec["badge"] if spec else "🎨 普通创作者",
        "consoleTitle": spec["consoleTitle"] if spec else "无后台权限",
        "summary": spec["summary"] if spec else "",
        "allowedModules": list(spec["modules"]) if spec else [],
        "moderatedBoards": mod_boards,
        "moderatedBoardDetails": mod_details,
        "capabilities": caps,
        "roleMatrix": ROLE_MATRIX_SPEC,
    }


def require_staff(
    user: dict[str, Any] | None,
    allow_reviewer: bool = True,
    allowed_roles: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if not user:
        raise ServiceError("请先登录管理账号", status=401, code="admin_login_required")
    if user.get("status") != "active":
        raise ServiceError("当前账号已被冻结，无法访问后台", status=403, code="account_frozen")
    role = str(user.get("role") or "user")
    norm_role = "operator" if role == "reviewer" else role
    if allowed_roles is not None:
        norm_allowed = set(allowed_roles)
        if "operator" in norm_allowed:
            norm_allowed.add("reviewer")
        if role not in norm_allowed and norm_role not in norm_allowed:
            raise ServiceError(
                f"权限不足：当前角色（{role}）无权执行此操作，需角色 {' / '.join(allowed_roles)}",
                status=403,
                code="role_forbidden",
            )
        return user
    if norm_role not in ("admin", "operator"):
        raise ServiceError("权限不足：仅超级管理员或运营审查员可访问该模块", status=403, code="staff_only")
    if not allow_reviewer and norm_role != "admin":
        raise ServiceError("权限不足：该敏感操作仅限超级管理员（admin）执行", status=403, code="admin_only")
    return user


def admin_get_permissions(db: Database, user: dict[str, Any] | None) -> dict[str, Any]:
    conn = db.get_conn()
    prof = get_management_profile(conn, user)
    if prof["effectiveRole"] not in ("admin", "operator", "reviewer", "moderator"):
        raise ServiceError("当前账号为普通创作者，无管理后台访问权限", status=403, code="no_mgmt_permission")
    return {"ok": True, "profile": prof}


def admin_get_moderator_console(db: Database, user: dict[str, Any] | None, board_filter: str = "", query: str = "") -> dict[str, Any]:
    """Board-scoped console payload exclusively for Forum Board Moderators (and global staff inspecting board view)."""
    if not user:
        raise ServiceError("请先登录版主账号", status=401, code="admin_login_required")
    if user.get("status") != "active":
        raise ServiceError("账号已冻结", status=403, code="account_frozen")
    conn = db.get_conn()
    prof = get_management_profile(conn, user)
    if prof["effectiveRole"] not in ("moderator", "admin", "operator", "reviewer"):
        raise ServiceError("权限不足：当前账号未被任命为任何板块版主", status=403, code="not_moderator")

    if prof["effectiveRole"] in ("admin", "operator", "reviewer") or "all" in prof["moderatedBoards"]:
        allowed_cats = ["tuning", "experience", "assets", "tools"]
    else:
        allowed_cats = [c for c in prof["moderatedBoards"] if c in ("tuning", "experience", "assets", "tools")]

    if not allowed_cats:
        raise ServiceError("当前未分配有效管辖板块", status=403, code="not_moderator")

    active_cats = [board_filter] if (board_filter and board_filter in allowed_cats) else allowed_cats
    placeholders = ",".join("?" for _ in active_cats)
    q = (query or "").strip().lower()

    from .resource_discussions import topic_visibility_sql
    f_vis = topic_visibility_sql(reply_filter="1=1", admin=True)
    topic_seed_filter, topic_seed_params = _seed_filter("id", "topics")
    topic_rows = conn.execute(
        f"SELECT * FROM forum_topics WHERE category IN ({placeholders}) AND {f_vis} AND {topic_seed_filter} ORDER BY pinned DESC, published_at_ms DESC",
        (*active_cats, *topic_seed_params),
    ).fetchall()
    topic_map = {r["id"]: r for r in topic_rows}

    replies_out = []
    replies_by_tid: dict[str, int] = {}
    if topic_map:
        t_ph = ",".join("?" for _ in topic_map)
        reply_seed_filter, reply_seed_params = _seed_filter("id", "forum_replies")
        for fr in conn.execute(
            f"SELECT * FROM forum_replies WHERE topic_id IN ({t_ph}) AND {reply_seed_filter} ORDER BY created_at DESC",
            (*topic_map.keys(), *reply_seed_params),
        ).fetchall():
            replies_by_tid[fr["topic_id"]] = replies_by_tid.get(fr["topic_id"], 0) + 1
            parent = topic_map[fr["topic_id"]]
            blob = f"{fr['id']} {fr['author_username']} {fr['text']} {parent['title']}".lower()
            if q and q not in blob:
                continue
            replies_out.append(
                {
                    "id": fr["id"],
                    "topicId": fr["topic_id"],
                    "topicTitle": parent["title"],
                    "category": parent["category"],
                    "categoryLabel": parent["category_label"],
                    "authorUsername": fr["author_username"],
                    "authorName": fr["author_name"],
                    "text": fr["text"],
                    "accepted": bool(fr["accepted"]),
                    "status": fr["status"],
                    "createdAt": format_short_time(fr["created_at"]),
                }
            )

    topics_out = []
    for t in topic_rows:
        blob = f"{t['id']} {t['title']} {t['author_username']} {t['summary']}".lower()
        if q and q not in blob:
            continue
        topics_out.append(
            {
                "id": t["id"],
                "category": t["category"],
                "categoryLabel": t["category_label"],
                "pinned": bool(t["pinned"]),
                "featured": bool(t["featured"]),
                "title": t["title"],
                "authorUsername": t["author_username"],
                "authorName": t["author_name"],
                "bounty": int(t["bounty"] or 0),
                "bountyStatus": t["bounty_status"],
                "status": t["status"],
                "views": int(t["views"] or 0),
                "likes": int(t["likes"] or 0),
                "repliesCount": replies_by_tid.get(t["id"], 0),
                "createdAt": format_relative_cn(int(t["published_at_ms"] or 0), t["created_label"]),
            }
        )

    # Board-scoped reports (only reports whose target topic or reply belongs to allowed_cats)
    reply_to_cat = {r["id"]: r["category"] for r in replies_out}
    reports_out = []
    moderator_user_filter, moderator_user_params = _admin_user_seed_filter("u.username")
    report_target_filter, report_target_params = _admin_visible_target_clause("target_type", "target_id")
    report_user_filter, report_user_params = _admin_user_seed_filter("reporter_username")
    for rep in conn.execute(
        f"SELECT * FROM reports WHERE target_type IN ('topic', 'reply') AND {report_target_filter} AND {report_user_filter} ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, id DESC",
        (*report_target_params, *report_user_params),
    ).fetchall():
        t_cat = ""
        if rep["target_type"] == "topic" and rep["target_id"] in topic_map:
            t_cat = topic_map[rep["target_id"]]["category"]
        elif rep["target_type"] == "reply":
            if rep["target_id"] in reply_to_cat:
                t_cat = reply_to_cat[rep["target_id"]]
            else:
                rr = conn.execute(
                    "SELECT ft.category FROM forum_replies fr JOIN forum_topics ft ON ft.id = fr.topic_id WHERE fr.id = ?",
                    (rep["target_id"],),
                ).fetchone()
                if rr:
                    t_cat = rr["category"]
        if t_cat not in active_cats:
            continue
        reports_out.append(
            {
                "id": int(rep["id"]),
                "reporterUsername": rep["reporter_username"],
                "targetType": rep["target_type"],
                "targetId": rep["target_id"],
                "targetTitle": rep["target_title"],
                "category": t_cat,
                "categoryLabel": FORUM_BOARD_LABELS.get(t_cat, t_cat),
                "reason": rep["reason"],
                "detail": rep["detail"],
                "status": rep["status"],
                "resolvedBy": rep["resolved_by"],
                "createdAt": format_short_time(rep["created_at"]),
            }
        )

    co_mods = [
        {
            "username": mr["username"],
            "displayName": mr["display_name"],
            "category": mr["category"],
            "shortLabel": FORUM_BOARD_SHORT_LABELS.get(mr["category"], mr["category"]),
            "title": mr["title"] or "版主",
        }
        for mr in conn.execute(
            f"""
            SELECT fm.*, u.display_name FROM forum_moderators fm
            JOIN users u ON u.id = fm.user_id
            WHERE u.status = 'active' AND {moderator_user_filter}
            ORDER BY CASE fm.category WHEN 'all' THEN 0 ELSE 1 END, fm.id ASC
            """,
            moderator_user_params,
        ).fetchall()
        if mr["category"] == "all" or mr["category"] in allowed_cats
    ]

    boards_info = [{"id": b["key"], **b} for b in FORUM_BOARDS if b["key"] in allowed_cats]
    return {
        "ok": True,
        "profile": prof,
        "allowedBoards": boards_info,
        "kpis": {
            "boardsCount": len(boards_info),
            "topicsTotal": len(topic_rows),
            "topicsPinned": sum(1 for t in topic_rows if int(t["pinned"])),
            "topicsFeatured": sum(1 for t in topic_rows if int(t["featured"])),
            "openBounties": sum(1 for t in topic_rows if int(t["bounty"] or 0) > 0 and t["bounty_status"] == "open"),
            "repliesTotal": sum(replies_by_tid.values()),
            "openReports": sum(1 for r in reports_out if r["status"] == "open"),
        },
        "topics": topics_out,
        "replies": replies_out,
        "reports": reports_out,
        "coModerators": co_mods,
    }


def _assert_not_self_review(
    actor: dict[str, Any],
    target_author_username: str,
    settings: dict[str, Any],
) -> None:
    actor_uname = str(actor.get("username") or "").strip().lower()
    author_uname = str(target_author_username or "").strip().lower()
    if not actor_uname or not author_uname or actor_uname != author_uname:
        return
    if actor.get("role") in ("operator", "reviewer"):
        raise ServiceError("风控限制：运营审查员禁止自审本人发布的内容（如加精、置顶、自审自推），请转交其他审查员或超级管理员处理", status=403, code="self_review_forbidden")
    allow_admin_self = bool(settings.get("moderation", {}).get("allow_self_review_for_admin", True))
    if not allow_admin_self:
        raise ServiceError("当前运营安全策略已关闭管理员自审，请由其他管理员处理或先在运营配置开启允许管理员自审", status=403, code="self_review_forbidden")


def _load_official_catalog_items() -> list[dict[str, Any]]:
    cat_file = CONTENT_DIR / "catalog.json"
    if not cat_file.is_file():
        return []
    try:
        data = json.loads(cat_file.read_text(encoding="utf-8"))
        return [r for r in data.get("resources", []) if isinstance(r, dict)]
    except Exception:
        return []


def _mask_secret_key(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return "未配置"
    if len(s) <= 8:
        return s[:2] + "****"
    return f"{s[:4]}****{s[-4:]}"


def _admin_user_seed_filter(column: str) -> tuple[str, tuple[str, ...]]:
    """Case-insensitive exclusion for known demo users in normal mode."""
    clause, params = _seed_filter(f"LOWER({column})", "users")
    return clause, tuple(str(value).lower() for value in params)


def _admin_visible_target_clause(type_column: str = "target_type", id_column: str = "target_id") -> tuple[str, tuple[str, ...]]:
    """Return a SQL predicate excluding known seed targets by target type.

    Unknown target types remain visible: this is an exact seed-source filter,
    not a broad content suppression rule.
    """
    work_clause, work_params = _seed_filter(id_column, "works")
    topic_clause, topic_params = _seed_filter(id_column, "topics")
    asset_clause, asset_params = _seed_filter(id_column, "assets")
    comment_clause, comment_params = _seed_filter(id_column, "work_comments")
    reply_clause, reply_params = _seed_filter(id_column, "forum_replies")
    return (
        f"({type_column} NOT IN ('work', 'topic', 'asset', 'comment', 'reply') "
        f"OR ({type_column} = 'work' AND {work_clause}) "
        f"OR ({type_column} = 'topic' AND {topic_clause}) "
        f"OR ({type_column} = 'asset' AND {asset_clause}) "
        f"OR ({type_column} = 'comment' AND {comment_clause}) "
        f"OR ({type_column} = 'reply' AND {reply_clause}))",
        (*work_params, *topic_params, *asset_params, *comment_params, *reply_params),
    )


def _admin_seed_value(value: Any, kind: str, *, casefold: bool = False) -> bool:
    """Check one exact known seed value without importing seed internals here."""
    _, params = _seed_filter("?", kind)
    needle = str(value or "")
    if casefold:
        needle = needle.lower()
        return needle in {str(item).lower() for item in params}
    return needle in {str(item) for item in params}


def _admin_reject_seed_value(value: Any, kind: str, label: str, *, casefold: bool = False) -> None:
    if _admin_seed_value(value, kind, casefold=casefold):
        raise ServiceError(f"normal 模式下不可访问演示{label}", status=404, code="seed_content_hidden")


def _admin_reject_seed_target(target_type: Any, target_id: Any) -> None:
    kind_by_type = {
        "work": "works",
        "topic": "topics",
        "asset": "assets",
        "comment": "work_comments",
        "reply": "forum_replies",
    }
    kind = kind_by_type.get(str(target_type or "").strip().lower())
    if kind:
        _admin_reject_seed_value(target_id, kind, "内容", casefold=False)


# ======================== 1. DASHBOARD KPI & ANALYTICS ========================

def admin_get_dashboard(db: Database, user: dict[str, Any] | None) -> dict[str, Any]:
    require_staff(user, allow_reviewer=True)
    conn = db.get_conn()
    settings = get_site_settings(conn)
    now_ms = int(time.time() * 1000)
    ms_72h = 72 * 3600 * 1000

    user_seed_filter, user_seed_params = _admin_user_seed_filter("username")
    work_seed_filter, work_seed_params = _seed_filter("id", "works")
    asset_seed_filter, asset_seed_params = _seed_filter("code", "assets")
    topic_seed_filter, topic_seed_params = _seed_filter("id", "topics")
    ledger_seed_filter, ledger_seed_params = _seed_filter("event_key", "ledger_events")
    generation_seed_filter, generation_seed_params = _seed_filter("id", "generations")
    report_target_filter, report_target_params = _admin_visible_target_clause("target_type", "target_id")
    report_user_filter, report_user_params = _admin_user_seed_filter("reporter_username")
    audit_actor_filter, audit_actor_params = _admin_user_seed_filter("actor_username")
    audit_target_filter, audit_target_params = _admin_visible_target_clause("target_type", "target_id")

    # Users KPIs
    users_total = int(conn.execute(f"SELECT COUNT(*) FROM users WHERE {user_seed_filter}", user_seed_params).fetchone()[0])
    users_active = int(conn.execute(f"SELECT COUNT(*) FROM users WHERE status = 'active' AND {user_seed_filter}", user_seed_params).fetchone()[0])
    users_frozen = int(conn.execute(f"SELECT COUNT(*) FROM users WHERE status = 'frozen' AND {user_seed_filter}", user_seed_params).fetchone()[0])
    users_staff = int(conn.execute(f"SELECT COUNT(*) FROM users WHERE role IN ('admin', 'reviewer') AND {user_seed_filter}", user_seed_params).fetchone()[0])
    discourse_migrated = int(conn.execute(f"SELECT COUNT(*) FROM users WHERE (discourse_user_id IS NOT NULL OR bio LIKE '%Discourse%') AND {user_seed_filter}", user_seed_params).fetchone()[0])

    # Works KPIs
    works_total = int(conn.execute(f"SELECT COUNT(*) FROM works WHERE {work_seed_filter}", work_seed_params).fetchone()[0])
    works_published = int(conn.execute(f"SELECT COUNT(*) FROM works WHERE status = 'published' AND {work_seed_filter}", work_seed_params).fetchone()[0])
    works_paused = int(conn.execute(f"SELECT COUNT(*) FROM works WHERE status = 'paused' AND {work_seed_filter}", work_seed_params).fetchone()[0])
    works_hidden = int(conn.execute(f"SELECT COUNT(*) FROM works WHERE status = 'hidden' AND {work_seed_filter}", work_seed_params).fetchone()[0])
    works_featured = int(conn.execute(f"SELECT COUNT(*) FROM works WHERE status = 'published' AND featured = 1 AND {work_seed_filter}", work_seed_params).fetchone()[0])
    works_new_72h = int(
        conn.execute(
            f"SELECT COUNT(*) FROM works WHERE status = 'published' AND published_at_ms >= ? AND published_at_ms <= ? AND {work_seed_filter}",
            (now_ms - ms_72h, now_ms, *work_seed_params),
        ).fetchone()[0]
    )

    # Asset work counts across published works
    asset_work_counts: dict[str, int] = {}
    for w in conn.execute(f"SELECT styles_json, layout_code FROM works WHERE status = 'published' AND {work_seed_filter}", work_seed_params).fetchall():
        try:
            for sc in json.loads(w["styles_json"] or "[]"):
                if sc:
                    c = str(sc).upper()
                    asset_work_counts[c] = asset_work_counts.get(c, 0) + 1
        except Exception:
            pass
        lc = str(w["layout_code"] or "").strip().upper()
        if lc:
            asset_work_counts[lc] = asset_work_counts.get(lc, 0) + 1

    official_items = _load_official_catalog_items()
    official_styles = [r for r in official_items if r.get("kind") == "style"]
    official_layouts = [r for r in official_items if r.get("kind") == "layout"]
    official_all = official_styles + official_layouts

    covered_official = 0
    zero_work_pioneer = 0
    group_map: dict[str, dict[str, Any]] = {}
    for item in official_all:
        code = str(item.get("id") or "").upper()
        kind = str(item.get("kind") or "style")
        grp = str(item.get("group") or item.get("category") or ("官方画风" if kind == "style" else "官方图型"))
        gkey = f"{kind}:{grp}"
        if gkey not in group_map:
            group_map[gkey] = {"kind": kind, "group": grp, "totalAssets": 0, "coveredAssets": 0, "totalWorks": 0}
        cnt = asset_work_counts.get(code, 0)
        group_map[gkey]["totalAssets"] += 1
        group_map[gkey]["totalWorks"] += cnt
        if cnt > 0:
            covered_official += 1
            group_map[gkey]["coveredAssets"] += 1
        else:
            zero_work_pioneer += 1

    group_coverage = []
    for g in group_map.values():
        tot = max(1, int(g["totalAssets"]))
        g["coveragePct"] = round(int(g["coveredAssets"]) * 100.0 / tot, 1)
        group_coverage.append(g)
    group_coverage.sort(key=lambda x: (-x["totalWorks"], -x["coveragePct"], x["group"]))

    exclusive_count = int(conn.execute(f"SELECT COUNT(*) FROM catalog_assets WHERE source_type = 'exclusive' AND {asset_seed_filter}", asset_seed_params).fetchone()[0])
    community_count = int(conn.execute(f"SELECT COUNT(*) FROM catalog_assets WHERE source_type = 'community' AND {asset_seed_filter}", asset_seed_params).fetchone()[0])
    override_count = int(conn.execute(f"SELECT COUNT(*) FROM catalog_assets WHERE source_type = 'official_override' AND {asset_seed_filter}", asset_seed_params).fetchone()[0])

    # Forum & Bounties
    from .resource_discussions import topic_visibility_sql
    f_vis = topic_visibility_sql(reply_filter="1=1", admin=True)
    topics_total = int(conn.execute(f"SELECT COUNT(*) FROM forum_topics WHERE {f_vis} AND {topic_seed_filter}", topic_seed_params).fetchone()[0])
    topics_published = int(conn.execute(f"SELECT COUNT(*) FROM forum_topics WHERE status = 'published' AND {f_vis} AND {topic_seed_filter}", topic_seed_params).fetchone()[0])
    bounty_row = conn.execute(
        f"SELECT COUNT(*) AS cnt, COALESCE(SUM(bounty), 0) AS escrow FROM forum_topics WHERE status = 'published' AND bounty > 0 AND bounty_status IN ('open', 'escrowed') AND {topic_seed_filter}",
        topic_seed_params,
    ).fetchone()
    open_bounties_count = int(bounty_row["cnt"] or 0)
    open_bounties_escrow = int(bounty_row["escrow"] or 0)

    # Economy & Ledger breakdown
    credits_circulation = int(
        conn.execute(
            f"SELECT COALESCE(SUM(w.balance), 0) FROM wallets w JOIN users u ON u.id = w.user_id WHERE {user_seed_filter.replace('username', 'u.username')}",
            user_seed_params,
        ).fetchone()[0]
    )
    credits_minted = int(conn.execute(f"SELECT COALESCE(SUM(delta), 0) FROM ledgers WHERE delta > 0 AND {ledger_seed_filter}", ledger_seed_params).fetchone()[0])
    credits_burned = abs(int(conn.execute(f"SELECT COALESCE(SUM(delta), 0) FROM ledgers WHERE delta < 0 AND {ledger_seed_filter}", ledger_seed_params).fetchone()[0]))
    buyer_seed_filter = user_seed_filter.replace("username", "COALESCE(buyer.username, '')")
    unlock_row = conn.execute(
        f"""
        SELECT COUNT(*) AS cnt, COALESCE(SUM(cost), 0) AS gmv, COALESCE(SUM(author_share), 0) AS royalties
        FROM unlocks ul
        LEFT JOIN users buyer ON buyer.id = ul.user_id
        WHERE ul.status = 'settled' AND {report_target_filter}
          AND {buyer_seed_filter}
        """,
        (*report_target_params, *user_seed_params),
    ).fetchone()

    mint_breakdown = [
        {"kind": r["kind"], "total": int(r["tot"]), "count": int(r["cnt"])}
        for r in conn.execute(
            f"SELECT kind, SUM(delta) AS tot, COUNT(*) AS cnt FROM ledgers WHERE delta > 0 AND {ledger_seed_filter} GROUP BY kind ORDER BY tot DESC LIMIT 8",
            ledger_seed_params,
        ).fetchall()
    ]
    burn_breakdown = [
        {"kind": r["kind"], "total": abs(int(r["tot"])), "count": int(r["cnt"])}
        for r in conn.execute(
            f"SELECT kind, SUM(delta) AS tot, COUNT(*) AS cnt FROM ledgers WHERE delta < 0 AND {ledger_seed_filter} GROUP BY kind ORDER BY tot ASC LIMIT 8",
            ledger_seed_params,
        ).fetchall()
    ]

    # Reports & Generations
    open_reports_count = int(conn.execute(f"SELECT COUNT(*) FROM reports WHERE status = 'open' AND {report_target_filter} AND {report_user_filter}", (*report_target_params, *report_user_params)).fetchone()[0])
    gen_total = int(conn.execute(f"SELECT COUNT(*) FROM studio_generations WHERE {generation_seed_filter}", generation_seed_params).fetchone()[0])
    gen_live = int(conn.execute(f"SELECT COUNT(*) FROM studio_generations WHERE engine = 'live' AND {generation_seed_filter}", generation_seed_params).fetchone()[0])
    gen_refunded = int(conn.execute(f"SELECT COUNT(*) FROM studio_generations WHERE status = 'refunded' AND {generation_seed_filter}", generation_seed_params).fetchone()[0])

    recent_reports = [
        {
            "id": int(r["id"]),
            "reporterUsername": r["reporter_username"],
            "targetType": r["target_type"],
            "targetId": r["target_id"],
            "targetTitle": r["target_title"],
            "reason": r["reason"],
            "detail": r["detail"],
            "status": r["status"],
            "createdAt": format_short_time(r["created_at"]),
        }
        for r in conn.execute(
            f"SELECT * FROM reports WHERE status = 'open' AND {report_target_filter} AND {report_user_filter} ORDER BY id DESC LIMIT 6",
            (*report_target_params, *report_user_params),
        ).fetchall()
    ]

    recent_generations = [
        {
            "id": r["id"],
            "username": r["username"] or "guest",
            "mode": r["mode"],
            "recipeSummary": r["recipe_summary"],
            "engine": r["engine"],
            "costType": r["cost_type"],
            "creditsSpent": int(r["credits_spent"] or 0),
            "status": r["status"],
            "createdAt": format_short_time(r["created_at"]),
        }
        for r in conn.execute(
            f"SELECT * FROM studio_generations WHERE {generation_seed_filter} ORDER BY created_at DESC LIMIT 8",
            generation_seed_params,
        ).fetchall()
    ]

    recent_audits = [
        {
            "id": int(r["id"]),
            "actorUsername": r["actor_username"],
            "actorRole": r["actor_role"],
            "action": r["action"],
            "targetType": r["target_type"],
            "targetId": r["target_id"],
            "reason": r["reason"],
            "createdAt": format_short_time(r["created_at"]),
        }
        for r in conn.execute(
            f"SELECT * FROM audit_logs WHERE {audit_actor_filter} AND {audit_target_filter} ORDER BY id DESC LIMIT 10",
            (*audit_actor_params, *audit_target_params),
        ).fetchall()
    ]

    return {
        "operator": {
            "id": user["id"],
            "username": user["username"],
            "displayName": user["display_name"],
            "role": user["role"],
        },
        "kpis": {
            "usersTotal": users_total,
            "usersActive": users_active,
            "usersFrozen": users_frozen,
            "usersStaff": users_staff,
            "discourseMigratedCount": discourse_migrated,
            "worksTotal": works_total,
            "worksPublished": works_published,
            "worksPaused": works_paused,
            "worksHidden": works_hidden,
            "worksFeatured": works_featured,
            "worksNew72h": works_new_72h,
            "officialStylesCount": len(official_styles),
            "officialLayoutsCount": len(official_layouts),
            "coveredOfficialCount": covered_official,
            "pioneerZeroWorkCount": zero_work_pioneer,
            "exclusiveAssetsCount": exclusive_count,
            "communityAssetsCount": community_count,
            "officialOverridesCount": override_count,
            "topicsTotal": topics_total,
            "topicsPublished": topics_published,
            "openBountiesCount": open_bounties_count,
            "openBountiesEscrow": open_bounties_escrow,
            "creditsCirculation": credits_circulation,
            "creditsMintedTotal": credits_minted,
            "creditsBurnedTotal": credits_burned,
            "unlockOrdersSettled": int(unlock_row["cnt"] or 0),
            "unlockGmvCredits": int(unlock_row["gmv"] or 0),
            "unlockAuthorRoyalties": int(unlock_row["royalties"] or 0),
            "openReportsCount": open_reports_count,
            "studioGenerationsTotal": gen_total,
            "studioGenerationsLive": gen_live,
            "studioGenerationsRefunded": gen_refunded,
        },
        "groupCoverage": group_coverage[:24],
        "creditBreakdown": {"mint": mint_breakdown, "burn": burn_breakdown},
        "recentReports": recent_reports,
        "recentGenerations": recent_generations if user and user.get("role") == "admin" else [],
        "recentAudits": recent_audits if user and user.get("role") == "admin" else [],
        "announcement": settings.get("announcement", {}),
        "roleProfile": get_management_profile(conn, user),
    }


# ======================== 2. WORKS, COMMUNITY ASSETS & COMMENTS MODERATION ========================

def admin_list_works(
    db: Database,
    user: dict[str, Any] | None,
    status: str = "",
    query: str = "",
    limit: int = 250,
) -> dict[str, Any]:
    require_staff(user, allow_reviewer=True)
    conn = db.get_conn()
    work_seed_filter, work_seed_params = _seed_filter("id", "works")
    sql = f"SELECT * FROM works WHERE {work_seed_filter}"
    params: list[Any] = list(work_seed_params)
    if status and status != "all":
        if status == "featured":
            sql += " AND featured = 1"
        else:
            sql += " AND status = ?"
            params.append(status)
    q = (query or "").strip()
    if q:
        like = f"%{q}%"
        sql += " AND (id LIKE ? OR title LIKE ? OR author_username LIKE ? OR author_name LIKE ? OR styles_json LIKE ? OR layout_code LIKE ?)"
        params.extend([like, like, like, like, like, like])
    sql += " ORDER BY published_at_ms DESC LIMIT ?"
    params.append(max(1, min(500, int(limit))))

    comment_seed_filter, comment_seed_params = _seed_filter("id", "work_comments")
    comment_work_filter, comment_work_params = _seed_filter("work_id", "works")
    reply_seed_filter, reply_seed_params = _seed_filter("id", "forum_replies")

    comment_counts: dict[str, int] = {}
    for r in conn.execute(
        f"SELECT work_id, COUNT(*) AS cnt FROM work_comments WHERE status = 'published' AND {comment_seed_filter} AND {comment_work_filter} GROUP BY work_id",
        (*comment_seed_params, *comment_work_params),
    ).fetchall():
        comment_counts[str(r["work_id"])] = int(r["cnt"])

    for r in conn.execute(
        f"SELECT m.target_id AS work_id, COUNT(*) AS cnt FROM forum_replies fr JOIN curation_resource_topics m ON m.topic_id = fr.topic_id AND m.kind = 'work' WHERE fr.status = 'published' AND {reply_seed_filter} GROUP BY m.target_id",
        reply_seed_params,
    ).fetchall():
        wid = str(r["work_id"])
        comment_counts[wid] = comment_counts.get(wid, 0) + int(r["cnt"])
    report_target_filter, report_target_params = _admin_visible_target_clause("target_type", "target_id")
    report_counts = {
        r["target_id"]: int(r["cnt"])
        for r in conn.execute(
            f"SELECT target_id, COUNT(*) AS cnt FROM reports WHERE target_type = 'work' AND status = 'open' AND {report_target_filter} GROUP BY target_id",
            report_target_params,
        ).fetchall()
    }

    is_admin = bool(user and user.get("role") == "admin")
    items = []
    for w in conn.execute(sql, params).fetchall():
        images = json.loads(w["images_json"] or "[]")
        styles = json.loads(w["styles_json"] or "[]")
        if is_admin:
            work_prompt = w["prompt"]
            work_masked = False
        else:
            from .services import get_work_client_prompt
            work_prompt, work_masked = get_work_client_prompt(w, is_admin_route=False)
        w_item = {
            "id": w["id"],
            "title": w["title"],
            "authorUsername": w["author_username"],
            "authorName": w["author_name"],
            "images": images,
            "image": images[0] if images else "",
            "styles": styles,
            "layout": w["layout_code"],
            "color": w["color_code"],
            "tone": w["tone_code"],
            "ratio": w["ratio"],
            "mode": w["mode"],
            "mood": w["mood"],
            "price": int(w["price"] or 0),
            "prompt": work_prompt,
            "notes": w["notes"],
            "status": w["status"],
            "featured": bool(w["featured"]),
            "isNew": bool(w["is_new_release"]),
            "pioneerRewarded": bool(w["pioneer_rewarded"]),
            "cheers": int(w["cheers"] or 0),
            "tips": int(w["tips"] or 0),
            "views": int(w["views"] or 0),
            "commentsCount": comment_counts.get(w["id"], 0),
            "openReportsCount": report_counts.get(w["id"], 0),
            "publishedAtMs": int(w["published_at_ms"] or 0),
            "createdAt": format_relative_cn(int(w["published_at_ms"] or 0), w["created_label"]),
        }
        if work_masked:
            w_item["promptMasked"] = True
        items.append(w_item)
    return {"items": items, "total": len(items)}


def admin_moderate_work(
    db: Database,
    user: dict[str, Any] | None,
    work_id: str,
    action: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not user or user.get("status") != "active":
        raise ServiceError("请先登录账号", status=401, code="login_required")
    payload = payload or {}
    act = (action or "").strip().lower()
    wid = (work_id or "").strip()
    reason = str(payload.get("reason") or "").strip()
    now_iso = utc_now_iso()
    now_ms = int(time.time() * 1000)

    u_role = str(user.get("role") or "user")
    norm_role = "operator" if u_role == "reviewer" else u_role
    is_admin = norm_role == "admin"
    is_operator = norm_role == "operator"

    with db.transaction() as tx:
        settings = get_site_settings(tx)
        _admin_reject_seed_value(wid, "works", "作品")
        w = tx.execute("SELECT * FROM works WHERE id = ?", (wid,)).fetchone()
        if not w:
            raise ServiceError(f"作品不存在：{wid}", status=404)

        curated=tx.execute("SELECT id FROM curation_submissions WHERE kind='work' AND target_id=?",(wid,)).fetchone()
        if curated and act=='edit':
            raise ServiceError('收录作品请由作者编辑重提',status=409)
        if curated and act in ('publish','feature','boost_new') and not tx.execute("SELECT 1 FROM curation_events WHERE submission_id=? AND event_type='publish'",(curated['id'],)).fetchone():
            raise ServiceError('作品尚未通过收录审核',status=409)
        is_author = (user.get("username") == w["author_username"])
        if is_author:
            if act not in ("delete", "edit"):
                if not (is_admin or is_operator):
                    raise ServiceError("创作者仅可编辑或删除自己发布的作品", status=403, code="author_action_limit")
        else:
            if not (is_admin or is_operator):
                raise ServiceError("权限不足：普通创作者无权操作他人作品", status=403, code="staff_only")

        # Anti-self-review on promotion
        if act in ("feature", "boost_new"):
            _assert_not_self_review(user, w["author_username"], settings)

        # Deletion protections
        if act == "delete" and not is_admin and not is_author:
            author_u = tx.execute("SELECT role FROM users WHERE username = ?", (w["author_username"],)).fetchone()
            if author_u and author_u["role"] == "admin":
                raise ServiceError("运营审查员无权删除超级管理员发布的作品", status=403)

        from .services import set_work_visibility, staff_actor_role

        # Rank of this decision.  An operator cannot reverse an admin's hide or
        # pause (M9, admin wins; see services.ACTOR_RANK).
        actor_role = staff_actor_role(user)
        if act == "publish":
            set_work_visibility(tx, wid, "published", now_iso, actor_role=actor_role)
        elif act == "pause":
            set_work_visibility(
                tx, wid, "paused", now_iso,
                source="moderator", reason=reason or "管理员暂停", actor_role=actor_role,
            )
        elif act == "hide":
            set_work_visibility(
                tx, wid, "hidden", now_iso,
                source="moderator", reason=reason or "管理员隐藏", actor_role=actor_role,
            )
        elif act == "feature":
            # Featuring is a promotion flag, not a visibility decision.  It used
            # to also set status='published', which let an operator un-hide a
            # moderated work just by adding a badge.
            if str(w["status"] or "") != "published":
                raise ServiceError("只能给已公开的作品加精", status=409, code="feature_requires_published")
            tx.execute("UPDATE works SET featured = 1, updated_at = ? WHERE id = ?", (now_iso, wid))
        elif act == "unfeature":
            tx.execute("UPDATE works SET featured = 0, updated_at = ? WHERE id = ?", (now_iso, wid))
        elif act == "boost_new":
            # Same rule: bumping "new release" must not republish hidden content.
            if str(w["status"] or "") != "published":
                raise ServiceError("只能推广已公开的作品", status=409, code="boost_requires_published")
            tx.execute(
                "UPDATE works SET is_new_release = 1, published_at_ms = ?, updated_at = ? WHERE id = ?",
                (now_ms, now_iso, wid),
            )
        elif act == "edit":
            title = str(payload.get("title") if payload.get("title") is not None else w["title"]).strip()
            if "price" in payload:
                raw_price = payload.get("price")
                if raw_price not in (None, ""):
                    try:
                        if isinstance(raw_price, float) and (raw_price != raw_price or raw_price in (float("inf"), float("-inf"))):
                            raise ValueError("non-finite price")
                        parsed_price = int(raw_price)
                    except (TypeError, ValueError, OverflowError):
                        raise ServiceError("作品定价必须是整数", status=400, code="invalid_price")
                    if parsed_price != 0:
                        raise ServiceError("作品不支持收费定价", status=400, code="work_price_not_allowed")
            price = 0
            raw_styles = payload.get("styles")
            if isinstance(raw_styles, str):
                styles = [s.strip().upper() for s in re.split(r"[,，\s]+", raw_styles) if s.strip()]
            elif isinstance(raw_styles, list):
                styles = [str(s).strip().upper() for s in raw_styles if str(s).strip()]
            else:
                styles = json.loads(w["styles_json"] or "[]")
            layout = str(payload.get("layout") if payload.get("layout") is not None else w["layout_code"]).strip().upper()
            mood = str(payload.get("mood") if payload.get("mood") is not None else w["mood"]).strip()
            # Keep the stored prompt byte-for-byte unless the admin actually
            # rewrote it: stripping would silently change the author's text.
            prompt = str(payload.get("prompt") if payload.get("prompt") is not None else w["prompt"])
            orig_subject = str(w["subject"] or "") if "subject" in w.keys() else ""
            req_subject = payload.get("subject")
            if req_subject is None or req_subject == "[包含资源专属指令，已隐藏]":
                subject = orig_subject
            else:
                subject = str(req_subject)
                if len(subject) > 2000:
                    raise ServiceError("主题内容过长（最多2000字）", status=400, code="subject_too_long")
            notes = str(payload.get("notes") if payload.get("notes") is not None else w["notes"]).strip()
            from .services import check_text_has_secret
            try:
                has_sec = check_text_has_secret(prompt, tx) or check_text_has_secret(subject, tx)
                prompt_has_sec = 1 if has_sec else 0
            except Exception:
                prompt_has_sec = None
            tx.execute(
                """
                UPDATE works SET title = ?, price = ?, styles_json = ?, layout_code = ?, mood = ?, prompt = ?, prompt_has_secret = ?, notes = ?, subject = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, price, json.dumps(styles, ensure_ascii=False), layout, mood, prompt, prompt_has_sec, notes, subject, now_iso, wid),
            )
        elif act == "delete":
            tx.execute("DELETE FROM work_comments WHERE work_id = ?", (wid,))
            tx.execute("DELETE FROM collections WHERE bucket = 'works' AND target_id = ?", (wid,))
            # The thread must go dark with the work: hiding it before dropping the
            # mapping, otherwise the topic stays published and anonymous readers
            # keep seeing a deleted work's discussion.
            mapped = tx.execute(
                "SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?",
                (wid,),
            ).fetchone()
            if mapped:
                from .services import set_topic_visibility

                # Mark the thread deleted, not merely hidden: once the mapping is
                # gone nothing else can tell it apart from an ordinary post, so
                # the state itself must carry the fact that its work is gone.
                # automated=True: an already-deleted thread is left as it is.
                set_topic_visibility(
                    tx, str(mapped["topic_id"]), "deleted", now_iso,
                    source="author" if is_author and not (is_admin or is_operator) else "moderator",
                    reason="作品已删除", actor_role=actor_role, automated=True,
                )
            tx.execute("DELETE FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?", (wid,))
            tx.execute("DELETE FROM works WHERE id = ?", (wid,))
        else:
            raise ServiceError(f"不支持的作品审核动作：{act}")

        record_audit_log(
            tx,
            user,
            f"work.{act}",
            "work",
            wid,
            reason or f"作品治理操作：{act}",
            {"title": w["title"], "author": w["author_username"]},
        )
    return {"ok": True, "workId": wid, "action": act}


def admin_list_comments(
    db: Database,
    user: dict[str, Any] | None,
    status: str = "",
    query: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    require_staff(user, allow_reviewer=True)
    conn = db.get_conn()
    q = (query or "").strip().lower()
    items: list[dict[str, Any]] = []

    work_comment_filter, work_comment_params = _seed_filter("c.id", "work_comments")
    work_parent_filter, work_parent_params = _seed_filter("c.work_id", "works")
    for r in conn.execute(
        f"SELECT c.*, w.title AS parent_title FROM work_comments c LEFT JOIN works w ON w.id = c.work_id WHERE c.status <> 'migrated' AND {work_comment_filter} AND {work_parent_filter} AND NOT EXISTS (SELECT 1 FROM forum_replies fr WHERE fr.legacy_source = 'work_comments:' || c.id) ORDER BY c.created_at DESC LIMIT ?",
        (*work_comment_params, *work_parent_params, max(1, min(500, int(limit)))),
    ).fetchall():
        if status and status != "all" and r["status"] != status:
            continue
        blob = f"{r['id']} {r['work_id']} {r['author_username']} {r['text']} {r['parent_title'] or ''}".lower()
        if q and q not in blob:
            continue
        items.append(
            {
                "commentType": "work_comment",
                "id": r["id"],
                "parentId": r["work_id"],
                "parentTitle": r["parent_title"] or r["work_id"],
                "authorUsername": r["author_username"],
                "authorName": r["author_name"],
                "text": r["text"],
                "status": r["status"],
                "createdAt": format_short_time(r["created_at"]),
            }
        )

    forum_reply_filter, forum_reply_params = _seed_filter("fr.id", "forum_replies")
    forum_topic_filter, forum_topic_params = _seed_filter("fr.topic_id", "topics")
    for r in conn.execute(
        f"SELECT fr.*, ft.title AS parent_title, m.kind AS resource_kind, m.target_id AS resource_target FROM forum_replies fr LEFT JOIN forum_topics ft ON ft.id = fr.topic_id LEFT JOIN curation_resource_topics m ON m.topic_id = fr.topic_id WHERE {forum_reply_filter} AND {forum_topic_filter} ORDER BY fr.created_at DESC LIMIT ?",
        (*forum_reply_params, *forum_topic_params, max(1, min(500, int(limit)))),
    ).fetchall():
        if status and status != "all" and r["status"] != status:
            continue
        blob = f"{r['id']} {r['topic_id']} {r['author_username']} {r['text']} {r['parent_title'] or ''} {r['resource_target'] or ''}".lower()
        if q and q not in blob:
            continue
        is_asset = r["resource_kind"] in ("style", "layout")
        items.append(
            {
                "commentType": "asset_comment" if is_asset else "forum_reply",
                "id": r["id"],
                "parentId": r["resource_target"] if is_asset else r["topic_id"],
                "parentTitle": r["parent_title"] or r["topic_id"],
                "authorUsername": r["author_username"],
                "authorName": r["author_name"],
                "text": r["text"],
                "accepted": bool(r["accepted"]),
                "status": r["status"],
                "createdAt": format_short_time(r["created_at"]),
            }
        )

    asset_comment_filter, asset_comment_params = _seed_filter("ac.id", "asset_comments")
    asset_parent_filter, asset_parent_params = _seed_filter("ac.asset_code", "assets")
    for r in conn.execute(
        f"SELECT ac.*, ca.name AS asset_name FROM asset_comments ac LEFT JOIN catalog_assets ca ON ca.code = ac.asset_code WHERE ac.status <> 'migrated' AND {asset_comment_filter} AND {asset_parent_filter} AND NOT EXISTS (SELECT 1 FROM forum_replies fr WHERE fr.legacy_source = 'asset_comments:' || ac.id) ORDER BY ac.created_at DESC LIMIT ?",
        (*asset_comment_params, *asset_parent_params, max(1, min(500, int(limit)))),
    ).fetchall():
        if status and status != "all" and r["status"] != status:
            continue
        kind_cn = "图型" if r["asset_kind"] == "layout" else "画风"
        ptitle = f"{r['asset_code']} · {r['asset_name']}" if r["asset_name"] else f"{r['asset_code']} ({kind_cn})"
        blob = f"{r['id']} {r['asset_code']} {r['author_username']} {r['text']} {ptitle}".lower()
        if q and q not in blob:
            continue
        items.append(
            {
                "commentType": "asset_comment",
                "id": r["id"],
                "parentId": r["asset_code"],
                "parentTitle": ptitle,
                "authorUsername": r["author_username"],
                "authorName": r["author_name"],
                "text": r["text"],
                "status": r["status"],
                "createdAt": format_short_time(r["created_at"]),
            }
        )

    return {"items": items[:limit], "total": len(items)}


def resolve_migrated_comment(
    tx: sqlite3.Connection,
    comment_type: str,
    comment_id: str,
) -> tuple[str, str, sqlite3.Row | None]:
    """
    Given (comment_type, comment_id), check if it points to a migrated legacy comment.
    - If active in forum_replies: returns ('forum_reply', reply_id, reply_row).
    - If migrated but current reply in forum_replies was deleted: returns ('deleted', comment_id, None).
    - Otherwise returns (comment_type, comment_id, original_row).
    """
    ctype = (comment_type or "").strip()
    cid = (comment_id or "").strip()
    if not cid:
        return (ctype, cid, None)

    # 1. If explicitly forum_reply / reply, look up in forum_replies
    if ctype in ("reply", "forum_reply"):
        r = tx.execute("SELECT * FROM forum_replies WHERE id = ?", (cid,)).fetchone()
        return ("forum_reply", cid, r)

    # 2. Check legacy_source in forum_replies
    sources = []
    if ctype in ("work_comment", "comment"):
        sources.append(f"work_comments:{cid}")
    elif ctype == "asset_comment":
        sources.append(f"asset_comments:{cid}")
    else:
        sources.extend([f"work_comments:{cid}", f"asset_comments:{cid}"])

    for s in sources:
        r = tx.execute("SELECT * FROM forum_replies WHERE legacy_source = ?", (s,)).fetchone()
        if r:
            return ("forum_reply", str(r["id"]), r)

    # 3. Check legacy tables if status is 'migrated'
    if ctype in ("work_comment", "comment"):
        w = tx.execute("SELECT * FROM work_comments WHERE id = ?", (cid,)).fetchone()
        if w:
            if str(w["status"]) == "migrated":
                # Migrated, but no row found in forum_replies -> reply was deleted!
                return ("deleted", cid, None)
            return (ctype, cid, w)

    if ctype == "asset_comment":
        a = tx.execute("SELECT * FROM asset_comments WHERE id = ?", (cid,)).fetchone()
        if a:
            if str(a["status"]) == "migrated":
                # Migrated, but no row found in forum_replies -> reply was deleted!
                return ("deleted", cid, None)
            return (ctype, cid, a)

    # If ctype is unknown or generic, check both legacy tables
    w = tx.execute("SELECT * FROM work_comments WHERE id = ?", (cid,)).fetchone()
    if w and str(w["status"]) == "migrated":
        return ("deleted", cid, None)
    a = tx.execute("SELECT * FROM asset_comments WHERE id = ?", (cid,)).fetchone()
    if a and str(a["status"]) == "migrated":
        return ("deleted", cid, None)

    return (ctype, cid, None)


def admin_moderate_comment(
    db: Database,
    user: dict[str, Any] | None,
    comment_type: str,
    comment_id: str,
    action: str,
    reason: str = "",
) -> dict[str, Any]:
    if not user or user.get("status") != "active":
        raise ServiceError("请先登录账号", status=401, code="login_required")
    act = (action or "").strip().lower()
    ctype = (comment_type or "").strip()
    cid = (comment_id or "").strip()
    table = (
        "work_comments"
        if ctype == "work_comment"
        else ("forum_replies" if ctype == "forum_reply" else ("asset_comments" if ctype == "asset_comment" else ""))
    )
    if not table:
        raise ServiceError("无效的评论类型")

    u_role = str(user.get("role") or "user")
    norm_role = "operator" if u_role == "reviewer" else u_role
    is_admin = norm_role == "admin"
    is_operator = norm_role == "operator"

    with db.transaction() as tx:
        # L1/M1: Resolve migrated comments to their forum_replies row
        resolved_type, actual_id, m_row = resolve_migrated_comment(tx, ctype, cid)
        if resolved_type == "deleted":
            if act == "publish":
                raise ServiceError("该评论已被删除，不能恢复", status=409, code="comment_deleted")
            # hide or delete: considered already completed (idempotent), keep old row unchanged
            return {"ok": True, "id": cid, "action": act}

        if resolved_type == "forum_reply" and m_row:
            table = "forum_replies"
            ctype = "forum_reply"
            row = m_row
            target_cid = actual_id
        else:
            target_cid = cid
            row = tx.execute(f"SELECT * FROM {table} WHERE id = ?", (cid,)).fetchone()
            if not row and table in ("asset_comments", "work_comments"):
                for fallback_table, fallback_type in (("forum_replies", "forum_reply"), ("asset_comments", "asset_comment"), ("work_comments", "work_comment")):
                    fallback_row = tx.execute(f"SELECT * FROM {fallback_table} WHERE id = ?", (cid,)).fetchone()
                    if fallback_row:
                        table = fallback_table
                        ctype = fallback_type
                        row = fallback_row
                        break
        if not row:
            raise ServiceError("评论或回复不存在", status=404)

        _admin_reject_seed_value(target_cid, "work_comments" if ctype == "work_comment" else ("forum_replies" if ctype == "forum_reply" else "asset_comments"), "评论")
        parent_kind = "works" if ctype == "work_comment" else ("topics" if ctype == "forum_reply" else "assets")
        parent_id = row["work_id"] if ctype == "work_comment" else (row["topic_id"] if ctype == "forum_reply" else row["asset_code"])
        _admin_reject_seed_value(parent_id, parent_kind, "评论所属内容")

        is_author = (user.get("username") == row["author_username"])
        is_board_mod = False
        if ctype == "forum_reply" and not is_admin and not is_operator:
            tp = tx.execute("SELECT category FROM forum_topics WHERE id = ?", (row["topic_id"],)).fetchone()
            if tp:
                b_cat = tp["category"]
                m_row = tx.execute(
                    "SELECT 1 FROM forum_moderators WHERE user_id = ? AND category IN ('all', ?)",
                    (int(user["id"]), b_cat),
                ).fetchone()
                is_board_mod = bool(m_row)

        if is_author:
            if act != "delete":
                if not (is_admin or is_operator or is_board_mod):
                    raise ServiceError("评论作者仅可删除自己发表的评论", status=403)
        else:
            if not (is_admin or is_operator or is_board_mod):
                raise ServiceError("权限不足：普通创作者无权操作他人评论", status=403)
            # Protected from non-admin modifying admin's comments
            target_author_u = tx.execute("SELECT role FROM users WHERE username = ?", (row["author_username"],)).fetchone()
            if not is_admin and target_author_u and target_author_u["role"] == "admin":
                raise ServiceError("无权操作超级管理员发表的评论或回复", status=403)

        from .services import set_comment_visibility, staff_actor_role

        actor_role = staff_actor_role(user, board_moderator=is_board_mod)
        if act == "hide":
            set_comment_visibility(tx, table, target_cid, "hidden", actor_role)
        elif act == "publish":
            set_comment_visibility(tx, table, target_cid, "published", actor_role)
        elif act == "delete":
            tx.execute(f"DELETE FROM {table} WHERE id = ?", (target_cid,))
            if ctype == "forum_reply":
                tx.execute("UPDATE forum_topics SET accepted_reply_id = NULL, solved = 0 WHERE id = ? AND accepted_reply_id = ?", (row["topic_id"], target_cid))
        else:
            raise ServiceError(f"不支持的评论操作：{act}")

        record_audit_log(tx, user, f"{ctype}.{act}", ctype, target_cid, reason or f"评论治理：{act}", {"author": row["author_username"]})
    return {"ok": True, "id": cid, "action": act}


# ======================== 3. EXCLUSIVE BLACKBOX, COMMUNITY CATALOG & PRESETS ========================

def admin_list_catalog_assets(
    db: Database,
    user: dict[str, Any] | None,
    kind: str = "",
    source_type: str = "",
    status: str = "",
    query: str = "",
) -> dict[str, Any]:
    actor = require_staff(user, allow_reviewer=True)
    is_admin = actor.get("role") == "admin"
    conn = db.get_conn()

    asset_seed_filter, asset_seed_params = _seed_filter("code", "assets")
    sql = f"SELECT * FROM catalog_assets WHERE {asset_seed_filter}"
    params: list[Any] = list(asset_seed_params)
    if kind and kind != "all":
        sql += " AND kind = ?"
        params.append(kind)
    if source_type and source_type != "all":
        sql += " AND source_type = ?"
        params.append(source_type)
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
    q = (query or "").strip()
    if q:
        like = f"%{q}%"
        sql += " AND (code LIKE ? OR name LIKE ? OR author_username LIKE ? OR group_name LIKE ? OR description LIKE ?)"
        params.extend([like, like, like, like, like])
    sql += " ORDER BY CASE source_type WHEN 'exclusive' THEN 0 WHEN 'official_override' THEN 1 ELSE 2 END, published_at_ms DESC"

    items = []
    for r in conn.execute(sql, params).fetchall():
        has_secret = bool((r["secret_blackbox_prompt"] or "").strip())
        items.append(
            {
                "code": r["code"],
                "kind": r["kind"],
                "sourceType": r["source_type"],
                "authorUsername": r["author_username"],
                "authorName": r["author_name"],
                "name": r["name"],
                "group": r["group_name"],
                "tier": r["tier"],
                "unlockCost": int(r["unlock_cost"] or 0),
                "image": r["image_url"],
                "description": r["description"],
                "definition": r["definition"],
                "promptEn": r["prompt_en"],
                "hasSecretBlackbox": has_secret,
                "secretBlackboxPrompt": r["secret_blackbox_prompt"] if is_admin else ("🔒 [仅超级管理员可查看/编辑云端黑盒底层 Prompt]" if has_secret else ""),
                "status": r["status"],
                "featured": bool(r["featured"]),
                "isNew": bool(r["is_new_release"]),
                "cheers": int(r["cheers"] or 0),
                "tips": int(r["tips"] or 0),
                "updatedAt": format_short_time(r["updated_at"]),
            }
        )

    official_brief = [
        {"id": str(it.get("id")), "kind": it.get("kind"), "name": it.get("name"), "group": it.get("group") or it.get("category") or "", "image": it.get("image") or ""}
        for it in _load_official_catalog_items()
        if it.get("kind") in ("style", "layout")
    ]
    return {"items": items, "total": len(items), "officialBrief": official_brief}


def admin_upsert_catalog_asset(
    db: Database,
    user: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    source_type = str(payload.get("sourceType") or "exclusive").strip()
    if source_type not in ("exclusive", "community", "official_override"):
        raise ServiceError("无效的资产来源类型")

    # Exclusive blackbox and official catalog overrides are strictly admin-only
    if source_type in ("exclusive", "official_override"):
        actor = require_staff(user, allow_reviewer=False)
    else:
        actor = require_staff(user, allow_reviewer=True)

    kind = "layout" if str(payload.get("kind") or "style") == "layout" else "style"
    code = str(payload.get("code") or "").strip().upper()
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ServiceError("请填写画风/图型名称")

    now_iso = utc_now_iso()
    now_ms = int(time.time() * 1000)

    with db.transaction() as tx:
        settings = get_site_settings(tx)
        _admin_reject_seed_value(code, "assets", "资产")
        existing = tx.execute("SELECT * FROM catalog_assets WHERE code = ?", (code,)).fetchone() if code else None
        if source_type == 'community' and not existing:
            raise ServiceError('新增共创资源请通过论坛分享投稿并申请收录',status=409)
        if code and tx.execute('SELECT 1 FROM curation_submissions WHERE target_id=? AND kind=?',(code,kind)).fetchone():
            raise ServiceError('共创投稿的定义请由作者编辑重提；申诉请进入收录管理',status=409)


        if existing:
            if existing["source_type"] in ("exclusive", "official_override") and actor.get("role") != "admin":
                raise ServiceError("仅超级管理员可编辑专属黑盒或官方覆盖配置", status=403)
            if existing["source_type"] == "community":
                _assert_not_self_review(actor, existing["author_username"], settings)
            source_type = existing["source_type"]
            kind = existing["kind"]
        else:
            if not code:
                if source_type == "exclusive":
                    prefix = "LX-" if kind == "layout" else "FX-"
                    max_num = 0
                    for r in tx.execute("SELECT code FROM catalog_assets WHERE code LIKE ?", (f"{prefix}%",)).fetchall():
                        m = re.search(r"(\d+)$", r["code"])
                        if m:
                            max_num = max(max_num, int(m.group(1)))
                    code = f"{prefix}{max_num + 1:03d}"
                elif source_type == "community":
                    prefix = "USR-L" if kind == "layout" else "USR-S"
                    max_num = 0
                    for r in tx.execute("SELECT code FROM catalog_assets WHERE code LIKE ?", (f"{prefix}%",)).fetchall():
                        m = re.search(r"(\d+)$", r["code"])
                        if m:
                            max_num = max(max_num, int(m.group(1)))
                    code = f"{prefix}{max_num + 1:02d}"
                else:
                    raise ServiceError("创建官方覆盖项必须指定目标官方编号（如 S-001 或 L-001）")

        unlock_cost = max(0, min(500, int(payload.get("unlockCost") or 0)))
        tier = str(payload.get("tier") or ("credit" if unlock_cost > 0 else "free")).strip()
        group_name = str(payload.get("group") or ("官网独占黑盒" if source_type == "exclusive" else ("社区共创图型" if kind == "layout" else "社区共创画风"))).strip()
        image_url = str(payload.get("image") or (existing["image_url"] if existing else "/images/styles/S-001.webp")).strip()
        description = str(payload.get("description") if payload.get("description") is not None else (existing["description"] if existing else "")).strip()
        definition = str(payload.get("definition") if payload.get("definition") is not None else (existing["definition"] if existing else "")).strip()
        prompt_en = str(payload.get("promptEn") if payload.get("promptEn") is not None else (existing["prompt_en"] if existing else "")).strip()

        if actor.get("role") == "admin":
            secret_blackbox = str(
                payload.get("secretBlackboxPrompt")
                if payload.get("secretBlackboxPrompt") is not None
                else (existing["secret_blackbox_prompt"] if existing else "")
            ).strip()
        else:
            secret_blackbox = existing["secret_blackbox_prompt"] if existing else ""

        status = str(payload.get("status") or (existing["status"] if existing else "published")).strip()
        if status not in ("published", "paused", "hidden", "pending"):
            status = "published"
        featured = 1 if payload.get("featured", bool(existing["featured"]) if existing else False) else 0
        is_new = 1 if payload.get("isNew", bool(existing["is_new_release"]) if existing else True) else 0

        author_uname = existing["author_username"] if existing else str(payload.get("authorUsername") or ("official" if source_type != "community" else actor["username"]))
        author_name = existing["author_name"] if existing else str(payload.get("authorName") or ("Handraw 官方实验室" if source_type != "community" else actor["display_name"]))

        if existing:
            tx.execute(
                """
                UPDATE catalog_assets SET
                    name = ?, group_name = ?, tier = ?, unlock_cost = ?, image_url = ?,
                    description = ?, definition = ?, prompt_en = ?, secret_blackbox_prompt = ?,
                    status = ?, featured = ?, is_new_release = ?, updated_at = ?
                WHERE code = ?
                """,
                (
                    name,
                    group_name,
                    tier,
                    unlock_cost,
                    image_url,
                    description,
                    definition,
                    prompt_en,
                    secret_blackbox,
                    status,
                    featured,
                    is_new,
                    now_iso,
                    code,
                ),
            )
            action_key = "catalog.update"
        else:
            tx.execute(
                """
                INSERT INTO catalog_assets (
                    code, kind, source_type, author_username, author_name, name, group_name,
                    tier, unlock_cost, image_url, description, definition, prompt_en,
                    secret_blackbox_prompt, status, featured, is_new_release,
                    published_at_ms, created_label, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '刚刚', ?, ?)
                """,
                (
                    code,
                    kind,
                    source_type,
                    author_uname,
                    author_name,
                    name,
                    group_name,
                    tier,
                    unlock_cost,
                    image_url,
                    description,
                    definition,
                    prompt_en,
                    secret_blackbox,
                    status,
                    featured,
                    is_new,
                    now_ms,
                    now_iso,
                    now_iso,
                ),
            )
            action_key = "catalog.create"

        if status == "published":
            norm_code = code.strip().upper().lstrip("#")
            mapped = tx.execute(
                "SELECT topic_id FROM curation_resource_topics WHERE kind = ? AND UPPER(target_id) = ?",
                (kind, norm_code),
            ).fetchone()
            if not mapped:
                from .resource_discussions import ensure_topic
                res_dict = {
                    "code": norm_code,
                    "kind": kind,
                    "name": name,
                    "image_url": image_url,
                    "description": description,
                    "definition": definition,
                    "source_type": source_type,
                    "author_username": author_uname,
                    "author_name": author_name,
                    "status": status,
                }
                ensure_topic(tx, kind, norm_code, res_dict, initial_origin="submission")

        secret_hash = hashlib.sha256(secret_blackbox.encode("utf-8")).hexdigest()[:12] if secret_blackbox else ""
        record_audit_log(
            tx,
            actor,
            action_key,
            "catalog_asset",
            code,
            str(payload.get("reason") or f"{'更新' if existing else '新建'}资产 {code}《{name}》"),
            {
                "sourceType": source_type,
                "kind": kind,
                "unlockCost": unlock_cost,
                "status": status,
                "featured": bool(featured),
                "blackboxDigest": secret_hash,
            },
        )
    return {"ok": True, "code": code}


def admin_delete_catalog_asset(
    db: Database,
    user: dict[str, Any] | None,
    code: str,
    reason: str = "",
) -> dict[str, Any]:
    actor = require_staff(user, allow_reviewer=False)
    clean = (code or "").strip().upper()
    _admin_reject_seed_value(clean, "assets", "资产")
    with db.transaction() as tx:
        row = tx.execute("SELECT * FROM catalog_assets WHERE code = ?", (clean,)).fetchone()
        if not row:
            raise ServiceError(f"未找到资产：{clean}", status=404)
        tx.execute("DELETE FROM catalog_assets WHERE code = ?", (clean,))
        record_audit_log(tx, actor, "catalog.delete", "catalog_asset", clean, reason or f"删除资产 {clean}", {"name": row["name"]})
    return {"ok": True, "code": clean}


def admin_list_presets(db: Database, user: dict[str, Any] | None) -> dict[str, Any]:
    require_staff(user, allow_reviewer=True)
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM studio_workflows WHERE is_official_preset = 1 ORDER BY sort_order ASC, updated_at_ms DESC").fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "title": r["title"],
                "blueprint": r["blueprint"],
                "scenarioBadge": r["scenario_badge"],
                "scenarioDesc": r["scenario_desc"],
                "enabled": bool(r["enabled"]),
                "sortOrder": int(r["sort_order"] or 0),
                "graph": json.loads(r["graph_json"] or "{}"),
            }
            for r in rows
        ]
    }


def admin_upsert_preset(db: Database, user: dict[str, Any] | None, payload: dict[str, Any]) -> dict[str, Any]:
    actor = require_staff(user, allow_reviewer=False)
    pid = str(payload.get("id") or f"preset_{int(time.time())}").strip()
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ServiceError("预设工作流标题不能为空")
    blueprint = str(payload.get("blueprint") or "single").strip()
    badge = str(payload.get("scenarioBadge") or "").strip()
    desc = str(payload.get("scenarioDesc") or "").strip()
    enabled = 1 if payload.get("enabled", True) else 0
    sort_order = int(payload.get("sortOrder") or 10)
    graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else {"blueprint": blueprint}
    now_ms = int(time.time() * 1000)
    now_iso = utc_now_iso()

    with db.transaction() as tx:
        tx.execute(
            """
            INSERT INTO studio_workflows (id, user_id, title, blueprint, scenario_badge, scenario_desc, graph_json, is_official_preset, enabled, sort_order, updated_at_ms, created_at)
            VALUES (?, 0, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                blueprint = excluded.blueprint,
                scenario_badge = excluded.scenario_badge,
                scenario_desc = excluded.scenario_desc,
                graph_json = excluded.graph_json,
                enabled = excluded.enabled,
                sort_order = excluded.sort_order,
                updated_at_ms = excluded.updated_at_ms
            """,
            (pid, title, blueprint, badge, desc, json.dumps(graph, ensure_ascii=False), enabled, sort_order, now_ms, now_iso),
        )
        record_audit_log(tx, actor, "preset.upsert", "studio_preset", pid, f"维护创作台官方预设《{title}》", {"blueprint": blueprint, "enabled": bool(enabled)})
    return {"ok": True, "id": pid}


# ======================== 4. FORUM GOVERNANCE, BOUNTY ARBITRATION & REPORTS ========================

def admin_list_topics(
    db: Database,
    user: dict[str, Any] | None,
    status: str = "",
    bounty_only: bool = False,
    query: str = "",
) -> dict[str, Any]:
    require_staff(user, allow_reviewer=True)
    conn = db.get_conn()
    topic_seed_filter, topic_seed_params = _seed_filter("id", "topics")
    from .resource_discussions import topic_visibility_sql
    f_vis = topic_visibility_sql(reply_filter="1=1", admin=True)
    sql = f"SELECT * FROM forum_topics WHERE {f_vis} AND {topic_seed_filter}"
    params: list[Any] = list(topic_seed_params)
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
    if bounty_only:
        sql += " AND bounty > 0"
    q = (query or "").strip()
    if q:
        like = f"%{q}%"
        sql += " AND (id LIKE ? OR title LIKE ? OR author_username LIKE ? OR summary LIKE ?)"
        params.extend([like, like, like, like])
    sql += " ORDER BY pinned DESC, published_at_ms DESC"

    reply_seed_filter, reply_seed_params = _seed_filter("id", "forum_replies")
    reply_topic_filter, reply_topic_params = _seed_filter("topic_id", "topics")
    replies_by_topic: dict[str, list[dict[str, Any]]] = {}
    for fr in conn.execute(
        f"SELECT * FROM forum_replies WHERE {reply_seed_filter} AND {reply_topic_filter} ORDER BY created_at ASC",
        (*reply_seed_params, *reply_topic_params),
    ).fetchall():
        replies_by_topic.setdefault(fr["topic_id"], []).append(
            {
                "id": fr["id"],
                "authorUsername": fr["author_username"],
                "authorName": fr["author_name"],
                "text": fr["text"],
                "accepted": bool(fr["accepted"]),
                "status": fr["status"],
                "createdAt": format_short_time(fr["created_at"]),
            }
        )

    items = []
    for t in conn.execute(sql, params).fetchall():
        reps = replies_by_topic.get(t["id"], [])
        items.append(
            {
                "id": t["id"],
                "category": t["category"],
                "categoryLabel": t["category_label"],
                "pinned": bool(t["pinned"]),
                "featured": bool(t["featured"]),
                "title": t["title"],
                "authorUsername": t["author_username"],
                "authorName": t["author_name"],
                "price": int(t["price"] or 0),
                "bounty": int(t["bounty"] or 0),
                "bountyStatus": t["bounty_status"],
                "solved": bool(t["solved"]),
                "acceptedReplyId": t["accepted_reply_id"],
                "images": json.loads(t["images_json"] or "[]"),
                "styles": json.loads(t["styles_json"] or "[]"),
                "layout": t["layout_code"],
                "summary": t["summary"],
                "lockedBody": t["locked_body"],
                "status": t["status"],
                "views": int(t["views"] or 0),
                "likes": int(t["likes"] or 0),
                "repliesCount": len(reps),
                "replies": reps,
                "createdAt": format_relative_cn(int(t["published_at_ms"] or 0), t["created_label"]),
            }
        )
    return {"items": items, "total": len(items)}


def admin_moderate_topic(
    db: Database,
    user: dict[str, Any] | None,
    topic_id: str,
    action: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not user or user.get("status") != "active":
        raise ServiceError("请先登录账号", status=401, code="login_required")
    payload = payload or {}
    act = (action or "").strip().lower()
    tid = (topic_id or "").strip()
    reason = str(payload.get("reason") or "").strip()
    now_iso = utc_now_iso()

    u_role = str(user.get("role") or "user")
    norm_role = "operator" if u_role == "reviewer" else u_role
    is_admin = norm_role == "admin"
    is_operator = norm_role == "operator"

    with db.transaction() as tx:
        settings = get_site_settings(tx)
        _admin_reject_seed_value(tid, "topics", "帖子")
        t = tx.execute("SELECT * FROM forum_topics WHERE id = ?", (tid,)).fetchone()
        if not t:
            raise ServiceError(f"帖子不存在：{tid}", status=404)

        is_author = (user.get("username") == t["author_username"])
        board_key = str(t["category"] or "experience")
        mod_row = tx.execute(
            "SELECT 1 FROM forum_moderators WHERE user_id = ? AND category IN ('all', ?)",
            (int(user["id"]), board_key),
        ).fetchone()
        is_board_mod = bool(mod_row)

        if act in ("settle_bounty", "refund_bounty"):
            if not (is_admin or is_operator):
                raise ServiceError("仅超级管理员或运营审查员可仲裁或退回悬赏积分", status=403)
        elif is_author:
            if act not in ("delete", "edit"):
                if not (is_admin or is_operator or is_board_mod):
                    raise ServiceError("帖子作者仅可编辑或删除自己发布的帖子", status=403)
        else:
            if not (is_admin or is_operator or is_board_mod):
                raise ServiceError("权限不足：你无权管理该帖子", status=403)
            author_u = tx.execute("SELECT role FROM users WHERE username = ?", (t["author_username"],)).fetchone()
            if not is_admin and author_u and author_u["role"] == "admin":
                raise ServiceError("无权操作超级管理员发布的帖子", status=403)

        if act in ("feature", "pin"):
            _assert_not_self_review(user, t["author_username"], settings)

        actor = user
        from .services import set_topic_visibility, staff_actor_role

        actor_role = staff_actor_role(user, board_moderator=is_board_mod)

        if act == "pin":
            tx.execute("UPDATE forum_topics SET pinned = 1, updated_at = ? WHERE id = ?", (now_iso, tid))
        elif act == "unpin":
            tx.execute("UPDATE forum_topics SET pinned = 0, updated_at = ? WHERE id = ?", (now_iso, tid))
        elif act == "feature":
            tx.execute("UPDATE forum_topics SET featured = 1, updated_at = ? WHERE id = ?", (now_iso, tid))
        elif act == "unfeature":
            tx.execute("UPDATE forum_topics SET featured = 0, updated_at = ? WHERE id = ?", (now_iso, tid))
        elif act == "publish":
            set_topic_visibility(tx, str(tid), "published", now_iso, source="moderator", actor_role=actor_role)
        elif act == "hide":
            set_topic_visibility(
                tx, str(tid), "hidden", now_iso,
                source="moderator", reason=reason or "管理员隐藏", actor_role=actor_role,
            )
        elif act == "edit":
            cat = str(payload.get("category") or t["category"]).strip()
            cat_label = FORUM_CATEGORY_LABELS.get(cat, t["category_label"])
            title = str(payload.get("title") if payload.get("title") is not None else t["title"]).strip()
            try:
                price = max(0, min(200, int(payload.get("price") if payload.get("price") is not None else t["price"])))
            except (TypeError, ValueError, OverflowError):
                raise ServiceError("帖子定价必须是整数", status=400, code="invalid_price")
            summary = str(payload.get("summary") if payload.get("summary") is not None else t["summary"]).strip()
            locked_body = str(payload.get("lockedBody") if payload.get("lockedBody") is not None else t["locked_body"]).strip()
            tx.execute(
                "UPDATE forum_topics SET category = ?, category_label = ?, title = ?, price = ?, summary = ?, locked_body = ?, updated_at = ? WHERE id = ?",
                (cat, cat_label, title, price, summary, locked_body, now_iso, tid),
            )
        elif act == "settle_bounty":
            bounty = int(t["bounty"] or 0)
            if bounty <= 0 or t["bounty_status"] not in ("open", "escrowed"):
                raise ServiceError("该帖没有处于托管待结算状态的积分悬赏")
            rid = str(payload.get("replyId") or "").strip()
            rep = tx.execute("SELECT * FROM forum_replies WHERE id = ? AND topic_id = ?", (rid, tid)).fetchone()
            if not rep:
                raise ServiceError("请选择要仲裁采纳的有效回复")
            winner = tx.execute("SELECT id FROM users WHERE username = ?", (rep["author_username"],)).fetchone()
            if winner:
                apply_wallet_delta(
                    tx,
                    int(winner["id"]),
                    bounty,
                    "bounty_admin_award",
                    f"管理员仲裁采纳悬赏回复《{t['title'][:18]}》",
                    event_key=f"bounty_win_{tid}",
                    ref_type="topic",
                    ref_id=tid,
                    actor_id=int(actor["id"]),
                )
            tx.execute("UPDATE forum_replies SET accepted = 0 WHERE topic_id = ?", (tid,))
            tx.execute("UPDATE forum_replies SET accepted = 1 WHERE id = ?", (rid,))
            tx.execute(
                "UPDATE forum_topics SET solved = 1, bounty_status = 'settled', accepted_reply_id = ?, updated_at = ? WHERE id = ?",
                (rid, now_iso, tid),
            )
        elif act == "refund_bounty":
            bounty = int(t["bounty"] or 0)
            if bounty <= 0 or t["bounty_status"] not in ("open", "escrowed"):
                raise ServiceError("该帖没有处于托管待退回状态的积分悬赏")
            author_row = tx.execute("SELECT id FROM users WHERE username = ?", (t["author_username"],)).fetchone()
            if author_row:
                apply_wallet_delta(
                    tx,
                    int(author_row["id"]),
                    bounty,
                    "bounty_admin_refund",
                    f"悬赏帖《{t['title'][:18]}》未达标/关闭，托管积分原路退回",
                    event_key=f"bounty_refund_{tid}",
                    ref_type="topic",
                    ref_id=tid,
                    actor_id=int(actor["id"]),
                )
            tx.execute("UPDATE forum_topics SET bounty_status = 'refunded', updated_at = ? WHERE id = ?", (now_iso, tid))
        elif act == "delete":
            tx.execute("DELETE FROM forum_replies WHERE topic_id = ?", (tid,))
            tx.execute("DELETE FROM collections WHERE bucket = 'topics' AND target_id = ?", (tid,))
            mapped = tx.execute("SELECT 1 FROM curation_resource_topics WHERE topic_id = ?", (tid,)).fetchone()
            if mapped:
                # A resource thread keeps its row, as the forum entry does:
                # removing it left the mapping pointing at nothing, so the
                # resource page could never take comments again (N5).
                set_topic_visibility(
                    tx, str(tid), "deleted", now_iso,
                    source="author" if is_author and not (is_admin or is_operator or is_board_mod) else "moderator",
                    reason=reason or "管理员删除", actor_role=actor_role, automated=True,
                )
            else:
                tx.execute("DELETE FROM forum_topics WHERE id = ?", (tid,))
        else:
            raise ServiceError(f"不支持的帖子操作：{act}")

        record_audit_log(
            tx,
            actor,
            f"topic.{act}",
            "topic",
            tid,
            reason or f"论坛治理操作：{act}",
            {"title": t["title"], "author": t["author_username"]},
        )
    return {"ok": True, "topicId": tid, "action": act}


def admin_list_forum_moderators(db: Database, user: dict[str, Any] | None) -> dict[str, Any]:
    require_staff(user, allow_reviewer=True)
    conn = db.get_conn()
    moderator_user_filter, moderator_user_params = _admin_user_seed_filter("u.username")
    rows = conn.execute(
        f"""
        SELECT fm.*, u.display_name, u.role, u.status AS user_status
        FROM forum_moderators fm
        JOIN users u ON u.id = fm.user_id
        WHERE {moderator_user_filter}
        ORDER BY CASE fm.category WHEN 'all' THEN 0 ELSE 1 END, fm.id ASC
        """,
        moderator_user_params,
    ).fetchall()
    items = [
        {
            "id": int(r["id"]),
            "userId": int(r["user_id"]),
            "username": r["username"],
            "displayName": r["display_name"],
            "role": r["role"],
            "userStatus": r["user_status"],
            "category": r["category"],
            "categoryLabel": "📋 全区总版主（管辖全部板块）" if r["category"] == "all" else FORUM_BOARD_LABELS.get(r["category"], r["category"]),
            "shortLabel": FORUM_BOARD_SHORT_LABELS.get(r["category"], r["category"]),
            "title": r["title"] or "版主",
            "note": r["note"] or "",
            "appointedBy": r["appointed_by"] or "yang0",
            "createdAt": format_short_time(r["created_at"]),
        }
        for r in rows
    ]
    candidates = [
        {
            "id": int(u["id"]),
            "username": u["username"],
            "displayName": u["display_name"],
            "role": u["role"],
        }
        for u in conn.execute(
            f"SELECT id, username, display_name, role FROM users WHERE status = 'active' AND {_admin_user_seed_filter('username')[0]} ORDER BY id ASC",
            _admin_user_seed_filter("username")[1],
        ).fetchall()
    ]
    boards_meta = [{"id": b["key"], **b} for b in FORUM_BOARDS]
    return {"items": items, "total": len(items), "boards": boards_meta, "candidates": candidates}


def admin_assign_forum_moderator(
    db: Database,
    user: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    actor = require_staff(user, allow_reviewer=False)
    raw_uname = str(payload.get("username") or "").strip().lstrip("@").lower()
    raw_uid = payload.get("userId")
    cat = str(payload.get("category") or "all").strip().lower()
    if cat not in ("all", "tuning", "experience", "assets", "tools"):
        raise ServiceError("无效的论坛板块标识（可选 all / tuning / experience / assets / tools）")
    title = str(payload.get("title") or ("总版主" if cat == "all" else "版主")).strip()[:24] or "版主"
    note = str(payload.get("note") or "").strip()[:200]
    now_iso = utc_now_iso()

    with db.transaction() as tx:
        if raw_uid:
            target = tx.execute("SELECT * FROM users WHERE id = ?", (int(raw_uid),)).fetchone()
        elif raw_uname:
            target = tx.execute("SELECT * FROM users WHERE LOWER(username) = ?", (raw_uname,)).fetchone()
        else:
            raise ServiceError("请选择或输入要任命版主的用户名")

        if not target:
            raise ServiceError("未找到该用户账号，请确认用户名是否正确", status=404)
        _admin_reject_seed_value(target["username"], "users", "用户", casefold=True)
        if target["status"] != "active":
            raise ServiceError("已冻结账号不能任命为论坛版主")

        tx.execute(
            """
            INSERT INTO forum_moderators (user_id, username, category, title, note, appointed_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, category) DO UPDATE SET
                user_id = excluded.user_id,
                title = excluded.title,
                note = excluded.note,
                appointed_by = excluded.appointed_by,
                created_at = excluded.created_at
            """,
            (int(target["id"]), target["username"], cat, title, note, actor["username"], now_iso),
        )
        board_label = "全区总版主" if cat == "all" else FORUM_BOARD_LABELS.get(cat, cat)
        record_audit_log(
            tx,
            actor,
            "moderator.assign",
            "forum_moderator",
            f"{target['username']}:{cat}",
            f"任命 @{target['username']} 为「{board_label}」{title}",
            {"username": target["username"], "category": cat, "title": title, "note": note},
        )
    return {
        "ok": True,
        "username": target["username"],
        "displayName": target["display_name"],
        "category": cat,
        "title": title,
    }


def admin_revoke_forum_moderator(
    db: Database,
    user: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    actor = require_staff(user, allow_reviewer=False)
    mod_id = payload.get("id")
    raw_uname = str(payload.get("username") or "").strip().lstrip("@").lower()
    cat = str(payload.get("category") or "").strip().lower()

    with db.transaction() as tx:
        if mod_id:
            row = tx.execute("SELECT * FROM forum_moderators WHERE id = ?", (int(mod_id),)).fetchone()
        elif raw_uname and cat:
            row = tx.execute(
                "SELECT * FROM forum_moderators WHERE LOWER(username) = ? AND category = ?",
                (raw_uname, cat),
            ).fetchone()
        else:
            raise ServiceError("缺少要撤销的版主任命记录 ID 或用户名+板块")

        if not row:
            raise ServiceError("未找到对应的版主任命记录", status=404)
        _admin_reject_seed_value(row["username"], "users", "用户", casefold=True)

        tx.execute("DELETE FROM forum_moderators WHERE id = ?", (int(row["id"]),))
        board_label = "全区总版主" if row["category"] == "all" else FORUM_BOARD_LABELS.get(row["category"], row["category"])
        record_audit_log(
            tx,
            actor,
            "moderator.revoke",
            "forum_moderator",
            f"{row['username']}:{row['category']}",
            str(payload.get("reason") or f"卸任 @{row['username']} 的「{board_label}」版主职务"),
            {"username": row["username"], "category": row["category"], "title": row["title"]},
        )
    return {"ok": True, "username": row["username"], "category": row["category"]}


def admin_list_reports(db: Database, user: dict[str, Any] | None, status: str = "") -> dict[str, Any]:
    require_staff(user, allow_reviewer=True)
    conn = db.get_conn()
    sql = "SELECT * FROM reports WHERE 1=1"
    params: list[Any] = []
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, id DESC"
    items = [
        {
            "id": int(r["id"]),
            "reporterUsername": r["reporter_username"],
            "targetType": r["target_type"],
            "targetId": r["target_id"],
            "targetTitle": r["target_title"],
            "reason": r["reason"],
            "detail": r["detail"],
            "status": r["status"],
            "resolvedBy": r["resolved_by"],
            "resolutionNote": r["resolution_note"],
            "createdAt": format_short_time(r["created_at"]),
            "resolvedAt": format_short_time(r["resolved_at"] or "") if r["resolved_at"] else "",
        }
        for r in conn.execute(sql, params).fetchall()
    ]
    return {"items": items, "total": len(items)}


def _lookup_target_author(tx: sqlite3.Connection, target_type: str, target_id: str) -> str:
    resolved_type, actual_id, m_row = resolve_migrated_comment(tx, target_type, target_id)
    if resolved_type == "forum_reply" and m_row:
        return str(m_row["author_username"] or "")
    if resolved_type == "deleted":
        for tbl in ("work_comments", "asset_comments"):
            row = tx.execute(f"SELECT author_username FROM {tbl} WHERE id = ?", (target_id,)).fetchone()
            if row:
                return str(row["author_username"] or "")
        return ""
    if target_type == "work":
        row = tx.execute("SELECT author_username FROM works WHERE id = ?", (target_id,)).fetchone()
    elif target_type == "topic":
        row = tx.execute("SELECT author_username FROM forum_topics WHERE id = ?", (target_id,)).fetchone()
    elif target_type == "asset":
        row = tx.execute("SELECT author_username FROM catalog_assets WHERE code = ?", (target_id,)).fetchone()
    elif target_type == "comment":
        row = tx.execute("SELECT author_username FROM work_comments WHERE id = ?", (target_id,)).fetchone()
    elif target_type == "reply":
        row = tx.execute("SELECT author_username FROM forum_replies WHERE id = ?", (target_id,)).fetchone()
    elif target_type == "dm_message":
        row = tx.execute("SELECT u.username AS author_username FROM dm_messages m JOIN users u ON u.id = m.sender_id WHERE m.id = ?", (target_id,)).fetchone()
    else:
        row = None
    return str(row["author_username"] or "") if row else ""


def admin_resolve_report(
    db: Database,
    user: dict[str, Any] | None,
    report_id: int,
    resolution: str,
    note: str = "",
    auto_action: bool = True,
) -> dict[str, Any]:
    if not user:
        raise ServiceError("请先登录管理账号", status=401, code="admin_login_required")
    conn = db.get_conn()
    prof = get_management_profile(conn, user)
    if prof["effectiveRole"] not in ("admin", "operator", "reviewer", "moderator"):
        raise ServiceError("权限不足：无举报裁定权限", status=403, code="staff_only")
    actor = user
    res = (resolution or "").strip().lower()
    if res not in ("confirmed", "dismissed"):
        raise ServiceError("无效的举报裁定状态（需为 confirmed 或 dismissed）")
    now_iso = utc_now_iso()

    with db.transaction() as tx:
        settings = get_site_settings(tx)
        rep = tx.execute("SELECT * FROM reports WHERE id = ?", (int(report_id),)).fetchone()
        if not rep:
            raise ServiceError("举报记录不存在", status=404)

        # L1/M1: Resolve migrated comments
        r_type, r_id, r_row = resolve_migrated_comment(tx, rep["target_type"], rep["target_id"])
        if r_type == "deleted":
            effective_target_type = "deleted"
            effective_target_id = r_id
        elif r_type == "forum_reply" and r_row:
            effective_target_type = "reply"
            effective_target_id = r_id
        else:
            effective_target_type = rep["target_type"]
            effective_target_id = rep["target_id"]

        if prof["effectiveRole"] == "moderator":
            if effective_target_type not in ("topic", "reply"):
                raise ServiceError("论坛版主仅可裁定本板块内的帖子或回复举报", status=403)
            if "all" not in prof["moderatedBoards"]:
                if effective_target_type == "topic":
                    tr = tx.execute("SELECT category FROM forum_topics WHERE id = ?", (effective_target_id,)).fetchone()
                    tcat = tr["category"] if tr else ""
                else:
                    rr = tx.execute(
                        "SELECT ft.category FROM forum_replies fr JOIN forum_topics ft ON ft.id = fr.topic_id WHERE fr.id = ?",
                        (effective_target_id,),
                    ).fetchone()
                    tcat = rr["category"] if rr else ""
                if tcat not in prof["moderatedBoards"]:
                    raise ServiceError("权限不足：该举报不属于您管辖的论坛板块", status=403)

        target_author = _lookup_target_author(tx, rep["target_type"], rep["target_id"])
        if target_author:
            _assert_not_self_review(actor, target_author, settings)

        # One verdict per target.  Reports on the same target are about the same
        # content, and since each account has at most one open report per
        # target they are all from different people, so the verdict closes
        # every open report on it.  The audit log names the report that was
        # actually reviewed.
        tx.execute(
            "UPDATE reports SET status = ?, resolved_by = ?, resolution_note = ?, resolved_at = ? "
            "WHERE status = 'open' AND (id = ? OR (target_type = ? AND target_id = ?))",
            (res, actor["username"], (note or "").strip(), now_iso, int(report_id), rep["target_type"], rep["target_id"]),
        )

        from .services import (
            release_topic_report_hold,
            set_comment_visibility,
            set_topic_visibility,
            set_work_visibility,
        )

        ttype = effective_target_type
        tid = str(effective_target_id)
        actor_role = {"admin": "admin", "operator": "operator", "reviewer": "operator"}.get(
            prof["effectiveRole"], "moderator"
        )
        verdict = f"举报成立（#{report_id}）"
        if res == "confirmed" and auto_action:
            # Confirming is a human verdict, recorded as 'moderator' with the
            # reviewer's rank, so a later dismissal cannot republish it.  Each
            # call skips quietly when a higher-ranked decision or a deletion
            # already covers the target: the report still gets resolved.
            if ttype == "work":
                set_work_visibility(
                    tx, tid, "hidden", now_iso,
                    source="moderator", reason=verdict, actor_role=actor_role,
                    automated=True, allow_sources=("", "report"),
                )
            elif ttype == "topic":
                set_topic_visibility(
                    tx, tid, "hidden", now_iso,
                    source="moderator", reason=verdict, actor_role=actor_role, automated=True,
                )
                # A work's main thread shows the work itself (title, images,
                # prompt), so a confirmed report on it is a verdict on the work
                # (V9).  Board moderators cannot moderate works, so only staff
                # verdicts reach the work.  Needs founder confirmation.
                linked = tx.execute(
                    "SELECT target_id FROM curation_resource_topics WHERE kind = 'work' AND topic_id = ?",
                    (tid,),
                ).fetchone()
                if linked and actor_role in ("admin", "operator"):
                    set_work_visibility(
                        tx, str(linked["target_id"]), "hidden", now_iso,
                        source="moderator", reason=verdict, actor_role=actor_role,
                        automated=True, allow_sources=("", "report"),
                    )
            elif ttype == "asset":
                tx.execute("UPDATE catalog_assets SET status = 'hidden', updated_at = ? WHERE code = ?", (now_iso, tid))
            elif ttype in ("comment", "reply"):
                table = "work_comments" if ttype == "comment" else "forum_replies"
                row = tx.execute(f"SELECT status, status_actor_role FROM {table} WHERE id = ?", (tid,)).fetchone()
                if row is not None and (
                    str(row["status"]) == "published"
                    or ACTOR_RANK.get(actor_role, 0) >= ACTOR_RANK.get(str(row["status_actor_role"] or ""), 0)
                ):
                    set_comment_visibility(tx, table, tid, "hidden", actor_role)
        elif res == "confirmed":
            # autoAction=false: the reviewer agrees it is a violation but takes
            # no new action.  If the report flow had paused the target, the
            # pause now rests on a human verdict, so a later dismissal of some
            # other report cannot lift it (M11).  The visible state is kept.
            if ttype == "work":
                cur = tx.execute("SELECT status FROM works WHERE id = ?", (tid,)).fetchone()
                if cur is not None:
                    set_work_visibility(
                        tx, tid, str(cur["status"]), now_iso,
                        source="moderator", reason=verdict, actor_role=actor_role,
                        automated=True, allow_from=("paused", "hidden"), allow_sources=("report",),
                    )
            elif ttype == "topic":
                cur = tx.execute("SELECT status FROM forum_topics WHERE id = ?", (tid,)).fetchone()
                if cur is not None:
                    set_topic_visibility(
                        tx, tid, str(cur["status"]), now_iso,
                        source="moderator", reason=verdict, actor_role=actor_role,
                        automated=True, allow_from=("paused", "hidden"), allow_sources=("report",),
                    )
        elif res == "dismissed":
            # A dismissal only undoes what the report flow itself did: the
            # allow_sources guards mean it never publishes something a human
            # hid or paused.  Its thread mirror is written with source 'work',
            # which never overrides a thread-level decision, so no source
            # needs to be passed here (M-g).
            if ttype == "work":
                set_work_visibility(
                    tx, tid, "published", now_iso,
                    automated=True, allow_from=("paused", "hidden"), allow_sources=("report",),
                )
            elif ttype == "topic":
                # Returns to what its work allows, not straight to published (M7).
                release_topic_report_hold(tx, tid, now_iso)
            elif ttype == "asset":
                tx.execute("UPDATE catalog_assets SET status = 'published', updated_at = ? WHERE code = ? AND status = 'paused'", (now_iso, tid))

        record_audit_log(
            tx,
            actor,
            f"report.{res}",
            ttype,
            tid,
            note or f"处理举报 #{report_id} -> {res}",
            {"reportId": int(report_id), "reason": rep["reason"], "autoAction": bool(auto_action)},
        )
    return {"ok": True, "reportId": int(report_id), "status": res}


# ======================== 5. USERS, HONOR, WALLETS, REFUNDS & REDEEM CODES ========================

def admin_list_users(
    db: Database,
    user: dict[str, Any] | None,
    role: str = "",
    status: str = "",
    query: str = "",
) -> dict[str, Any]:
    require_staff(user, allow_reviewer=True)
    conn = db.get_conn()
    settings = get_site_settings(conn)

    sql = "SELECT * FROM users WHERE 1=1"
    params: list[Any] = []
    if role and role != "all":
        sql += " AND role = ?"
        params.append(role)
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
    q = (query or "").strip()
    if q:
        like = f"%{q}%"
        sql += " AND (username LIKE ? OR display_name LIKE ? OR email LIKE ? OR invite_code LIKE ?)"
        params.extend([like, like, like, like])
    sql += " ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'reviewer' THEN 1 ELSE 2 END, id ASC"

    session_counts = {
        int(r["user_id"]): int(r["cnt"])
        for r in conn.execute("SELECT user_id, COUNT(*) AS cnt FROM sessions WHERE expires_at > ? GROUP BY user_id", (int(time.time()),)).fetchall()
    }
    mod_by_uid: dict[int, list[dict[str, str]]] = {}
    for mr in conn.execute("SELECT user_id, category, title FROM forum_moderators ORDER BY CASE category WHEN 'all' THEN 0 ELSE 1 END, id ASC").fetchall():
        mod_by_uid.setdefault(int(mr["user_id"]), []).append(
            {
                "category": mr["category"],
                "shortLabel": FORUM_BOARD_SHORT_LABELS.get(mr["category"], mr["category"]),
                "title": mr["title"] or "版主",
            }
        )

    items = []
    for u in conn.execute(sql, params).fetchall():
        uid = int(u["id"])
        wq = get_wallet_quota_state(conn, uid, settings)
        pub_cnt = _count_user_published_items(conn, u["username"])
        honor = compute_honor_tier(pub_cnt, u["honor_override"])
        items.append(
            {
                "id": uid,
                "username": u["username"],
                "displayName": u["display_name"],
                "email": u["email"] or "",
                "role": u["role"],
                "status": u["status"],
                "bio": u["bio"] or "",
                "inviteCode": u["invite_code"],
                "honorOverride": u["honor_override"],
                "honorBadge": honor["badge"],
                "moderatedBoards": mod_by_uid.get(uid, []),
                "publishedCount": pub_cnt,
                "credits": wq["balance"],
                "freeQuotaRemaining": wq["freeQuotaRemaining"],
                "freeQuotaMax": wq["freeQuotaMax"],
                "walletLocked": wq["locked"],
                "activeSessions": session_counts.get(uid, 0),
                "discourseMigrated": bool(u["discourse_user_id"] or "Discourse" in (u["bio"] or "")),
                "createdAt": format_short_time(u["created_at"]),
                "lastLoginAt": format_short_time(u["last_login_at"] or "") if u["last_login_at"] else "从未",
            }
        )
    return {"items": items, "total": len(items)}


def admin_get_user_detail(db: Database, user: dict[str, Any] | None, target_user_id: int) -> dict[str, Any]:
    actor = require_staff(user, allow_reviewer=True)
    conn = db.get_conn()
    settings = get_site_settings(conn)
    uid = int(target_user_id)
    u = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not u:
        raise ServiceError("用户不存在", status=404)

    wq = get_wallet_quota_state(conn, uid, settings)
    pub_cnt = _count_user_published_items(conn, u["username"])
    honor = compute_honor_tier(pub_cnt, u["honor_override"])

    ledgers = [
        {
            "id": int(r["id"]),
            "delta": int(r["delta"]),
            "balanceAfter": int(r["balance_after"]),
            "kind": r["kind"],
            "reason": r["reason"],
            "createdAt": format_short_time(r["created_at"]),
        }
        for r in conn.execute("SELECT * FROM ledgers WHERE user_id = ? ORDER BY id DESC LIMIT 50", (uid,)).fetchall()
    ]
    works = [
        {"id": r["id"], "title": r["title"], "status": r["status"], "price": int(r["price"] or 0), "cheers": int(r["cheers"] or 0)}
        for r in conn.execute("SELECT id, title, status, price, cheers FROM works WHERE author_username = ? ORDER BY published_at_ms DESC", (u["username"],)).fetchall()
    ]
    assets = [
        {"code": r["code"], "name": r["name"], "kind": r["kind"], "status": r["status"], "unlockCost": int(r["unlock_cost"] or 0)}
        for r in conn.execute("SELECT code, name, kind, status, unlock_cost FROM catalog_assets WHERE author_username = ?", (u["username"],)).fetchall()
    ]
    active_sessions = int(
        conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ? AND expires_at > ?", (uid, int(time.time()))).fetchone()[0]
    )
    mod_boards = [
        {
            "id": int(mr["id"]),
            "category": mr["category"],
            "shortLabel": FORUM_BOARD_SHORT_LABELS.get(mr["category"], mr["category"]),
            "title": mr["title"] or "版主",
        }
        for mr in conn.execute("SELECT id, category, title FROM forum_moderators WHERE user_id = ? ORDER BY id ASC", (uid,)).fetchall()
    ]

    return {
        "user": {
            "id": uid,
            "username": u["username"],
            "displayName": u["display_name"],
            "email": u["email"] or "",
            "role": u["role"],
            "status": u["status"],
            "bio": u["bio"] or "",
            "inviteCode": u["invite_code"],
            "honorOverride": u["honor_override"],
            "honor": honor,
            "moderatedBoards": mod_boards,
            "publishedCount": pub_cnt,
            "apiKeyMasked": "",
            "wallet": wq,
            "activeSessions": active_sessions,
            "createdAt": format_short_time(u["created_at"]),
        },
        "ledgers": ledgers,
        "works": works,
        "assets": assets,
    }


def admin_create_user(
    db: Database,
    user: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    actor = require_staff(user, allowed_roles=("admin",))
    uname = re.sub(r"[^a-zA-Z0-9_\-]", "", str(payload.get("username") or "").strip())
    if len(uname) < 2 or len(uname) > 32:
        raise ServiceError("用户名需为 2~32 位字母、数字、下划线或连字符")
    raw_pw = str(payload.get("password") or "handraw123")
    if len(raw_pw) < 6:
        raise ServiceError("初始密码长度至少 6 位")
    role = str(payload.get("role") or "user").strip()
    if role not in ("user", "reviewer", "operator", "admin"):
        raise ServiceError("无效的系统角色（可选 user / reviewer / operator / admin）")
    dname = str(payload.get("displayName") or uname).strip()[:40]
    email = str(payload.get("email") or f"{uname}@handraw-style.com").strip().lower()[:120]
    bio = str(payload.get("bio") or "Handraw 社区认证成员").strip()[:300]
    init_credits = max(0, min(5000, int(payload.get("initialCredits") if payload.get("initialCredits") is not None else 20)))
    mod_board = str(payload.get("moderatorBoard") or "").strip().lower()
    mod_title = str(payload.get("moderatorTitle") or ("总版主" if mod_board == "all" else "版主")).strip()[:24] or "版主"
    now_iso = utc_now_iso()

    with db.transaction() as tx:
        dup = tx.execute(
            "SELECT id FROM users WHERE LOWER(username) = ? OR (email != '' AND LOWER(email) = ?)",
            (uname.lower(), email),
        ).fetchone()
        if dup:
            raise ServiceError("该用户名或绑定邮箱已存在")

        cur = tx.execute(
            """
            INSERT INTO users (
                username, display_name, email, password_hash, password_algo,
                role, status, bio, invite_code, api_key, created_at, last_login_at
            ) VALUES (?, ?, ?, ?, 'pbkdf2_sha256', ?, 'active', ?, ?, ?, ?, '')
            """,
            (uname, dname, email, hash_password(raw_pw), role, bio, uname, None, now_iso),
        )
        uid = int(cur.lastrowid)
        tx.execute(
            "INSERT INTO wallets (user_id, balance, free_quota_date, free_quota_used, checkin_date, locked, updated_at) VALUES (?, 0, '', 0, '', 0, ?)",
            (uid, now_iso),
        )
        if init_credits > 0:
            apply_wallet_delta(
                tx,
                uid,
                init_credits,
                "admin_grant",
                "管理员新建账号初始积分发放",
                event_key=f"admin_create_init_{uid}",
                actor_id=int(actor["id"]),
            )
        if mod_board in ("all", "tuning", "experience", "assets", "tools"):
            tx.execute(
                "INSERT INTO forum_moderators (user_id, username, category, title, note, appointed_by, created_at) VALUES (?, ?, ?, ?, '新建账号同步任命版主', ?, ?)",
                (uid, uname, mod_board, mod_title, actor["username"], now_iso),
            )
        record_audit_log(
            tx,
            actor,
            "user.create",
            "user",
            uname,
            f"管理员新建账号 @{uname}（角色：{role}）",
            {"role": role, "initialCredits": init_credits, "moderatorBoard": mod_board},
        )
    return {"ok": True, "userId": uid, "username": uname, "role": role}


def admin_delete_user(
    db: Database,
    user: dict[str, Any] | None,
    target_user_id: int,
    reason: str = "",
) -> dict[str, Any]:
    actor = require_staff(user, allowed_roles=("admin",))
    uid = int(target_user_id)
    if uid == int(actor["id"]):
        raise ServiceError("安全保护：禁止删除当前登录的超级管理员自身账号")
    with db.transaction() as tx:
        target = tx.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if not target:
            raise ServiceError("目标用户不存在", status=404)
        if target["username"] == "yang0":
            raise ServiceError("安全保护：禁止删除创站主超级管理员账号 yang0")
        for child_sql in (
            "DELETE FROM sessions WHERE user_id = ?",
            "DELETE FROM forum_moderators WHERE user_id = ?",
            "DELETE FROM redeem_code_uses WHERE user_id = ?",
            "DELETE FROM collections WHERE user_id = ?",
            "DELETE FROM interactions WHERE user_id = ?",
            "DELETE FROM unlocks WHERE user_id = ?",
            "DELETE FROM user_uploads WHERE user_id = ?",
            "DELETE FROM studio_workflows WHERE user_id = ? AND is_official_preset = 0",
            "DELETE FROM studio_articles WHERE user_id = ?",
            "DELETE FROM ledgers WHERE user_id = ?",
            "DELETE FROM wallets WHERE user_id = ?",
        ):
            tx.execute(child_sql, (uid,))
        tx.execute("DELETE FROM users WHERE id = ?", (uid,))
        record_audit_log(
            tx,
            actor,
            "user.delete",
            "user",
            target["username"],
            reason or f"管理员移除账号 @{target['username']}",
            {"role": target["role"]},
        )
    return {"ok": True, "userId": uid, "username": target["username"]}


def admin_update_user(
    db: Database,
    user: dict[str, Any] | None,
    target_user_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    wants_role_change = "role" in payload and payload.get("role") is not None
    wants_pw_reset = bool(str(payload.get("newPassword") or "").strip())
    if wants_role_change or wants_pw_reset or payload.get("resetApiKey"):
        actor = require_staff(user, allowed_roles=("admin",))
    else:
        actor = require_staff(user, allow_reviewer=True)
    uid = int(target_user_id)
    reason = str(payload.get("reason") or "后台更新用户账号与权限状态").strip()
    now_iso = utc_now_iso()

    with db.transaction() as tx:
        target = tx.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if not target:
            raise ServiceError("目标用户不存在", status=404)

        actor_role = str(actor.get("role") or "user")
        if actor_role == "reviewer":
            actor_role = "operator"
        if actor_role != "admin" and target["role"] in ("admin", "operator", "reviewer"):
            raise ServiceError("非超级管理员无权修改管理团队成员账号", status=403)

        new_role = str(payload.get("role") or target["role"]).strip()
        if new_role not in ("user", "reviewer", "operator", "admin"):
            raise ServiceError("无效的角色类型")

        new_status = str(payload.get("status") or target["status"]).strip()
        if new_status not in ("active", "frozen"):
            raise ServiceError("无效的账号状态")

        if uid == int(actor["id"]):
            if new_status == "frozen":
                raise ServiceError("安全保护：禁止冻结当前登录的管理员自身账号")
            if new_role != target["role"]:
                raise ServiceError("安全保护：禁止降级当前登录的管理员自身角色")

        if "honorOverride" in payload:
            raw_ho = payload.get("honorOverride")
            honor_override = None if (raw_ho is None or raw_ho == "" or raw_ho == "auto") else max(0, min(4, int(raw_ho)))
        else:
            honor_override = target["honor_override"]

        dname = str(payload.get("displayName") if payload.get("displayName") is not None else target["display_name"]).strip()[:40]
        email = str(payload.get("email") if payload.get("email") is not None else (target["email"] or "")).strip().lower()[:120]
        bio = str(payload.get("bio") if payload.get("bio") is not None else target["bio"]).strip()[:300]
        api_key = generate_api_key() if payload.get("resetApiKey") else target["api_key"]

        pw_hash = target["password_hash"]
        pw_algo = target["password_algo"]
        disc_salt = target["discourse_salt"]
        raw_new_pw = str(payload.get("newPassword") or "").strip()
        if raw_new_pw:
            if len(raw_new_pw) < 6:
                raise ServiceError("重置的新密码至少需要 6 位")
            pw_hash = hash_password(raw_new_pw)
            pw_algo = "pbkdf2_sha256"
            disc_salt = ""

        tx.execute(
            """
            UPDATE users SET display_name = ?, email = ?, bio = ?, role = ?, status = ?, honor_override = ?,
                             api_key = ?, password_hash = ?, password_algo = ?, discourse_salt = ?
            WHERE id = ?
            """,
            (dname, email, bio, new_role, new_status, honor_override, api_key, pw_hash, pw_algo, disc_salt, uid),
        )

        if "walletLocked" in payload:
            w_locked = 1 if payload.get("walletLocked") else 0
            tx.execute("UPDATE wallets SET locked = ?, updated_at = ? WHERE user_id = ?", (w_locked, now_iso, uid))

        revoked_sessions = 0
        if new_status == "frozen":
            cur = tx.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
            revoked_sessions = int(cur.rowcount or 0)

        record_audit_log(
            tx,
            actor,
            "user.update",
            "user",
            target["username"],
            reason,
            {
                "role": new_role,
                "status": new_status,
                "honorOverride": honor_override,
                "walletLocked": payload.get("walletLocked"),
                "revokedSessions": revoked_sessions,
            },
        )
    return {"ok": True, "userId": uid, "revokedSessions": revoked_sessions}


def admin_adjust_user_credits(
    db: Database,
    user: dict[str, Any] | None,
    target_user_id: int,
    delta: int,
    reason: str,
) -> dict[str, Any]:
    actor = require_staff(user, allow_reviewer=False)
    uid = int(target_user_id)
    amt = int(delta)
    clean_reason = (reason or "").strip()
    if amt == 0:
        raise ServiceError("积分变动值不能为 0")
    if len(clean_reason) < 2:
        raise ServiceError("必须填写积分人工调账审计原因（至少 2 个字）")

    with db.transaction() as tx:
        target = tx.execute("SELECT id, username FROM users WHERE id = ?", (uid,)).fetchone()
        if not target:
            raise ServiceError("目标用户不存在", status=404)
        new_bal, _ = apply_wallet_delta(
            tx,
            uid,
            amt,
            "admin_grant" if amt > 0 else "admin_deduct",
            f"管理员调账：{clean_reason}",
            ref_type="admin_adjust",
            ref_id=str(actor["id"]),
            actor_id=int(actor["id"]),
            allow_negative=True,
        )
        record_audit_log(
            tx,
            actor,
            "wallet.adjust",
            "user",
            target["username"],
            clean_reason,
            {"delta": amt, "balanceAfter": new_bal},
        )
    return {"ok": True, "userId": uid, "delta": amt, "balanceAfter": new_bal}


def admin_list_unlocks(db: Database, user: dict[str, Any] | None, status: str = "", limit: int = 200) -> dict[str, Any]:
    require_staff(user, allow_reviewer=True)
    conn = db.get_conn()
    sql = """
        SELECT ul.*, u.username AS buyer_username, u.display_name AS buyer_name
        FROM unlocks ul
        LEFT JOIN users u ON u.id = ul.user_id
        WHERE 1=1
    """
    params: list[Any] = []
    if status and status != "all":
        sql += " AND ul.status = ?"
        params.append(status)
    sql += " ORDER BY ul.id DESC LIMIT ?"
    params.append(max(1, min(500, int(limit))))

    items = [
        {
            "id": int(r["id"]),
            "buyerUserId": int(r["user_id"]),
            "buyerUsername": r["buyer_username"] or str(r["user_id"]),
            "buyerName": r["buyer_name"] or "",
            "authorUsername": r["author_username"],
            "targetType": r["target_type"],
            "targetId": r["target_id"],
            "cost": int(r["cost"] or 0),
            "authorShare": int(r["author_share"] or 0),
            "platformFee": max(0, int(r["cost"] or 0) - int(r["author_share"] or 0)),
            "status": r["status"],
            "refundReason": r["refund_reason"],
            "createdAt": format_short_time(r["created_at"]),
            "refundedAt": format_short_time(r["refunded_at"] or "") if r["refunded_at"] else "",
        }
        for r in conn.execute(sql, params).fetchall()
    ]
    return {"items": items, "total": len(items)}


def admin_refund_unlock(
    db: Database,
    user: dict[str, Any] | None,
    unlock_id: int,
    reason: str,
) -> dict[str, Any]:
    actor = require_staff(user, allow_reviewer=False)
    clean_reason = (reason or "管理员人工退款并追回分成").strip()
    now_iso = utc_now_iso()

    with db.transaction() as tx:
        ul = tx.execute("SELECT * FROM unlocks WHERE id = ?", (int(unlock_id),)).fetchone()
        if not ul:
            raise ServiceError("解锁订单不存在", status=404)
        if ul["status"] != "settled":
            raise ServiceError("该订单已退款处理，请勿重复操作")

        buyer_id = int(ul["user_id"])
        cost = int(ul["cost"] or 0)
        author_share = int(ul["author_share"] or 0)

        # 1. Refund buyer full cost
        buyer_bal, _ = apply_wallet_delta(
            tx,
            buyer_id,
            cost,
            "unlock_refund",
            f"解锁订单 #{unlock_id} ({ul['target_id']}) 管理员退还积分：{clean_reason}",
            event_key=f"ul_refund_buyer_{unlock_id}",
            ref_type=ul["target_type"],
            ref_id=ul["target_id"],
            actor_id=int(actor["id"]),
        )

        # 2. Claw back 80% royalty from author if applicable
        clawed_back = 0
        if author_share > 0 and ul["author_username"] and ul["author_username"] != "official":
            arow = tx.execute("SELECT id FROM users WHERE username = ?", (ul["author_username"],)).fetchone()
            if arow and int(arow["id"]) != buyer_id:
                apply_wallet_delta(
                    tx,
                    int(arow["id"]),
                    -author_share,
                    "unlock_royalty_clawback",
                    f"解锁订单 #{unlock_id} ({ul['target_id']}) 退款追回分成：{clean_reason}",
                    event_key=f"ul_refund_author_{unlock_id}",
                    ref_type=ul["target_type"],
                    ref_id=ul["target_id"],
                    actor_id=int(actor["id"]),
                    allow_negative=True,
                )
                clawed_back = author_share

        tx.execute(
            "UPDATE unlocks SET status = 'refunded', refund_reason = ?, refunded_by = ?, refunded_at = ? WHERE id = ?",
            (clean_reason, int(actor["id"]), now_iso, int(unlock_id)),
        )
        record_audit_log(
            tx,
            actor,
            "unlock.refund",
            "unlock",
            str(unlock_id),
            clean_reason,
            {"target": f"{ul['target_type']}:{ul['target_id']}", "refundedCost": cost, "clawedBackRoyalty": clawed_back, "buyerBalanceAfter": buyer_bal},
        )
    return {"ok": True, "unlockId": int(unlock_id), "refundedCost": cost, "clawedBackRoyalty": clawed_back}


def admin_list_redeem_codes(db: Database, user: dict[str, Any] | None) -> dict[str, Any]:
    require_staff(user, allowed_roles=("admin", "operator"))
    conn = db.get_conn()
    items = [
        {
            "code": r["code"],
            "credits": int(r["credits"]),
            "maxUses": int(r["max_uses"]),
            "usedCount": int(r["used_count"]),
            "note": r["note"],
            "active": bool(r["active"]),
            "expiresAt": r["expires_at"],
            "createdBy": r["created_by"],
            "createdAt": format_short_time(r["created_at"]),
        }
        for r in conn.execute("SELECT * FROM redeem_codes ORDER BY created_at DESC").fetchall()
    ]
    return {"items": items}


def admin_create_redeem_code(db: Database, user: dict[str, Any] | None, payload: dict[str, Any]) -> dict[str, Any]:
    actor = require_staff(user, allowed_roles=("admin", "operator"))
    code = re.sub(r"[^A-Z0-9_\-]", "", str(payload.get("code") or "").strip().upper())
    if len(code) < 4:
        raise ServiceError("兑换码至少需要 4 位大写字母/数字")
    credits = max(1, min(5000, int(payload.get("credits") or 20)))
    max_uses = max(1, min(100000, int(payload.get("maxUses") or 100)))
    note = str(payload.get("note") or "运营活动积分兑换码").strip()[:120]
    expires_at = str(payload.get("expiresAt") or "").strip()
    now_iso = utc_now_iso()

    with db.transaction() as tx:
        dup = tx.execute("SELECT 1 FROM redeem_codes WHERE code = ?", (code,)).fetchone()
        if dup:
            raise ServiceError(f"兑换码 {code} 已存在")
        tx.execute(
            "INSERT INTO redeem_codes (code, credits, max_uses, used_count, note, active, expires_at, created_by, created_at) VALUES (?, ?, ?, 0, ?, 1, ?, ?, ?)",
            (code, credits, max_uses, note, expires_at, actor["username"], now_iso),
        )
        record_audit_log(tx, actor, "redeem.create", "redeem_code", code, note, {"credits": credits, "maxUses": max_uses})
    return {"ok": True, "code": code}


def admin_toggle_redeem_code(db: Database, user: dict[str, Any] | None, code: str, active: bool) -> dict[str, Any]:
    actor = require_staff(user, allowed_roles=("admin", "operator"))
    clean = (code or "").strip().upper()
    with db.transaction() as tx:
        row = tx.execute("SELECT * FROM redeem_codes WHERE code = ?", (clean,)).fetchone()
        if not row:
            raise ServiceError(f"兑换码不存在：{clean}", status=404)
        tx.execute("UPDATE redeem_codes SET active = ? WHERE code = ?", (1 if active else 0, clean))
        record_audit_log(tx, actor, "redeem.toggle", "redeem_code", clean, f"{'启用' if active else '停用'}兑换码 {clean}", {"active": bool(active)})
    return {"ok": True, "code": clean, "active": bool(active)}


# ======================== 6. GATEWAY & GENERATION TASK MONITOR ========================

def admin_get_gateway_overview(db: Database, user: dict[str, Any] | None, probe: bool = False) -> dict[str, Any]:
    require_staff(user, allowed_roles=("admin",))
    conn = db.get_conn()
    settings = get_site_settings(conn)
    gw_settings = settings.get("gateway", {})

    cfg_path = get_image_config_path()
    file_cfg: dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            file_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            file_cfg = {}

    raw_url = str(file_cfg.get("url") or file_cfg.get("base_url") or "http://127.0.0.1:5005").rstrip("/")
    base_url = raw_url[:-3] if raw_url.endswith("/v1") else raw_url
    api_key = str(file_cfg.get("key") or file_cfg.get("api_key") or "")

    probe_result: dict[str, Any] = {
        "probed": False,
        "reachable": False,
        "latencyMs": 0,
        "detail": "点击「立即探测网关」检测实时连通性",
    }
    if probe:
        t0 = time.time()
        try:
            req = urllib.request.Request(
                f"{base_url}/v1/models",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                latency = int((time.time() - t0) * 1000)
                probe_result = {
                    "probed": True,
                    "reachable": 200 <= resp.status < 500,
                    "latencyMs": latency,
                    "detail": f"HTTP {resp.status} · 网关在线 ({latency}ms)",
                }
        except urllib.error.HTTPError as exc:
            latency = int((time.time() - t0) * 1000)
            probe_result = {
                "probed": True,
                "reachable": exc.code < 500,
                "latencyMs": latency,
                "detail": f"HTTP {exc.code} · 网关进程响应在线 ({latency}ms)",
            }
        except Exception as exc:
            latency = int((time.time() - t0) * 1000)
            probe_result = {
                "probed": True,
                "reachable": False,
                "latencyMs": latency,
                "detail": f"未连接 ({str(exc)[:80]}) · 自动启用本地高保真样张回退",
            }

    stats_row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN engine = 'live' THEN 1 ELSE 0 END) AS live_cnt,
            SUM(CASE WHEN engine = 'sample' THEN 1 ELSE 0 END) AS sample_cnt,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_cnt,
            SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_cnt,
            SUM(CASE WHEN status = 'refunded' THEN 1 ELSE 0 END) AS refunded_cnt,
            COALESCE(SUM(credits_spent), 0) AS total_credits_spent
        FROM studio_generations
        """
    ).fetchone()

    return {
        "gateway": {
            "configFileExists": cfg_path.is_file(),
            "baseUrl": base_url,
            "apiKeyMasked": _mask_secret_key(api_key),
            "model": gw_settings.get("model", file_cfg.get("model", "gpt-image-2")),
            "timeoutSeconds": int(gw_settings.get("timeout_seconds", 35)),
            "quality": gw_settings.get("quality", "auto"),
            "allowSampleFallback": bool(gw_settings.get("allow_sample_fallback", True)),
        },
        "probe": probe_result,
        "stats": {
            "total": int(stats_row["total"] or 0),
            "live": int(stats_row["live_cnt"] or 0),
            "sample": int(stats_row["sample_cnt"] or 0),
            "success": int(stats_row["success_cnt"] or 0),
            "running": int(stats_row["running_cnt"] or 0),
            "refunded": int(stats_row["refunded_cnt"] or 0),
            "totalCreditsSpent": int(stats_row["total_credits_spent"] or 0),
        },
    }


def admin_list_generations(
    db: Database,
    user: dict[str, Any] | None,
    status: str = "",
    engine: str = "",
    query: str = "",
    limit: int = 150,
) -> dict[str, Any]:
    require_staff(user, allowed_roles=("admin",))
    conn = db.get_conn()
    sql = "SELECT * FROM studio_generations WHERE 1=1"
    params: list[Any] = []
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
    if engine and engine != "all":
        sql += " AND engine = ?"
        params.append(engine)
    q = (query or "").strip()
    if q:
        like = f"%{q}%"
        sql += " AND (id LIKE ? OR username LIKE ? OR recipe_summary LIKE ? OR prompt LIKE ?)"
        params.extend([like, like, like, like])
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(300, int(limit))))

    items = [
        {
            "id": r["id"],
            "userId": r["user_id"],
            "username": r["username"] or "guest",
            "tabTitle": r["tab_title"],
            "mode": r["mode"],
            "kind": r["kind"],
            "recipeSummary": r["recipe_summary"],
            "prompt": (r["prompt"] or "")[:240],
            "engine": r["engine"],
            "costType": r["cost_type"],
            "creditsSpent": int(r["credits_spent"] or 0),
            "taskId": r["task_id"],
            "status": r["status"],
            "errorMsg": r["error_msg"],
            "createdAt": format_short_time(r["created_at"]),
        }
        for r in conn.execute(sql, params).fetchall()
    ]
    return {"items": items, "total": len(items)}


def admin_reset_user_free_quota(
    db: Database,
    user: dict[str, Any] | None,
    target_user_id: int,
    reason: str = "",
) -> dict[str, Any]:
    actor = require_staff(user, allowed_roles=("admin", "operator"))
    uid = int(target_user_id)
    today = local_today_str()
    now_iso = utc_now_iso()
    with db.transaction() as tx:
        target = tx.execute("SELECT id, username FROM users WHERE id = ?", (uid,)).fetchone()
        if not target:
            raise ServiceError("目标用户不存在", status=404)
        tx.execute(
            "UPDATE wallets SET free_quota_date = ?, free_quota_used = 0, updated_at = ? WHERE user_id = ?",
            (today, now_iso, uid),
        )
        record_audit_log(
            tx,
            actor,
            "quota.reset",
            "user",
            target["username"],
            reason or "重置用户今日创作台免费生图额度",
        )
    return {"ok": True, "userId": uid}


# ======================== 7. SITE SETTINGS & AUDIT LOGS ========================

def admin_get_settings(db: Database, user: dict[str, Any] | None) -> dict[str, Any]:
    require_staff(user, allowed_roles=("admin", "operator"))
    return {"settings": get_site_settings(db.get_conn())}


def admin_update_settings(
    db: Database,
    user: dict[str, Any] | None,
    section: str,
    values: dict[str, Any],
    reason: str = "",
) -> dict[str, Any]:
    sec = (section or "").strip()
    if sec == "announcement":
        actor = require_staff(user, allowed_roles=("admin", "operator"))
    else:
        actor = require_staff(user, allowed_roles=("admin",))
    if sec not in ("economy", "announcement", "moderation", "gateway"):
        raise ServiceError(f"不支持的配置分组：{sec}")
    if not isinstance(values, dict):
        raise ServiceError("配置项内容格式错误")
    now_iso = utc_now_iso()

    with db.transaction() as tx:
        current = get_site_settings(tx).get(sec, {})
        merged = dict(current) if isinstance(current, dict) else {}
        for k, v in values.items():
            if k in merged and isinstance(merged[k], bool):
                merged[k] = bool(v)
            elif k in merged and isinstance(merged[k], int) and not isinstance(merged[k], bool):
                merged[k] = int(v)
            elif k in merged and isinstance(merged[k], float):
                merged[k] = float(v)
            else:
                merged[k] = v

        tx.execute(
            """
            INSERT INTO site_settings (key, value_json, updated_by, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (sec, json.dumps(merged, ensure_ascii=False), actor["username"], now_iso),
        )
        record_audit_log(
            tx,
            actor,
            f"settings.update.{sec}",
            "site_settings",
            sec,
            reason or f"更新全站运营配置分组：{sec}",
            merged,
        )
        updated_all = get_site_settings(tx)
    return {"ok": True, "section": sec, "settings": updated_all}


def admin_list_audit_logs(
    db: Database,
    user: dict[str, Any] | None,
    action_filter: str = "",
    actor_filter: str = "",
    target_type: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    require_staff(user, allowed_roles=("admin",))
    conn = db.get_conn()
    sql = "SELECT * FROM audit_logs WHERE 1=1"
    params: list[Any] = []
    if action_filter:
        sql += " AND action LIKE ?"
        params.append(f"%{action_filter.strip()}%")
    if actor_filter:
        sql += " AND actor_username LIKE ?"
        params.append(f"%{actor_filter.strip()}%")
    if target_type and target_type != "all":
        sql += " AND target_type = ?"
        params.append(target_type)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(500, int(limit))))

    items = [
        {
            "id": int(r["id"]),
            "actorId": r["actor_id"],
            "actorUsername": r["actor_username"],
            "actorRole": r["actor_role"],
            "action": r["action"],
            "targetType": r["target_type"],
            "targetId": r["target_id"],
            "reason": r["reason"],
            "details": json.loads(r["details_json"] or "{}"),
            "createdAt": format_short_time(r["created_at"]),
            "rawCreatedAt": r["created_at"],
        }
        for r in conn.execute(sql, params).fetchall()
    ]
    return {"items": items, "total": len(items)}
