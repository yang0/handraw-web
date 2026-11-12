"""Privacy-conscious P2 growth milestones, cohorts, security-device signals.

Never store submitted identifiers, passwords, session tokens, or raw IP addresses
in the analytics tables. All per-user analytics access is staff-only.
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import utc_now_iso
from .services import ServiceError


def record_visit(db: Any, user: dict | None) -> None:
    if not user or user.get("status") != "active":
        return
    with db.transaction() as tx:
        _record_site_visit(tx, int(user["id"]), utc_now_iso())


def _record_site_visit(tx, user_id: int, now: str) -> None:
    tx.execute(
        """INSERT INTO growth_events (user_id, event_name, event_day, happened_at)
           VALUES (?, 'site_visit', ?, ?) ON CONFLICT DO NOTHING""",
        (user_id, now[:10], now),
    )


def record_login(db: Any, user: dict, user_agent: str) -> bool:
    """Record a daily login and notify on a *new platform/browser combination*.

    This is a coarse browser signature, not a trustworthy hardware identity.
    The first ever device does not trigger a warning.
    """
    uid = int(user["id"])
    agent = str(user_agent or "")[:200]
    platform = next((x for pat, x in [
        ("Windows", r"Windows"), ("macOS", r"Macintosh|Mac OS X"),
        ("Android", r"Android"), ("iOS", r"iPhone|iPad"),
        ("Linux", r"Linux")] if re.search(pat, agent, re.I)), "未知系统")
    browser = next((x for pat, x in [
        ("Edge", r"Edg/"), ("Firefox", r"Firefox/"),
        ("Chrome", r"Chrome/"), ("Safari", r"Safari/")] if re.search(pat, agent, re.I)), "浏览器")
    label = platform + " / " + browser
    fingerprint = hashlib.sha256(("v1|" + label).encode()).hexdigest()
    now = utc_now_iso()
    with db.transaction() as tx:
        known_before = tx.execute(
            "SELECT 1 FROM security_devices WHERE user_id=? LIMIT 1", (uid,)
        ).fetchone() is not None
        prior = tx.execute(
            "SELECT 1 FROM security_devices WHERE user_id=? AND fingerprint=?",
            (uid, fingerprint),
        ).fetchone()
        tx.execute(
            """INSERT INTO security_devices(user_id,fingerprint,label,first_seen_at,last_seen_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(user_id,fingerprint) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
            (uid, fingerprint, label, now, now),
        )
        _record_site_visit(tx, uid, now)
        if known_before and not prior:
            tx.execute(
                """INSERT INTO notifications(user_id,kind,title,target_type,target_id,created_at)
                   VALUES(?,'security',?,'','',?)""",
                (uid, "发现新的浏览器环境登录：" + label + "。如非本人，请立即更改密码并退出其他设备。", now),
            )
    return known_before and not prior


def log_funnel_view(db: Any, event_name: str) -> None:
    if event_name not in {"signup_view", "signup_submit", "login_view"}:
        raise ServiceError("无效的统计事件")
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO auth_funnel_events(event_name,created_at,source) VALUES(?,?,?)",
            (event_name, int(time.time()), "web"),
        )


_COHORTS_SQL = """
    SELECT left(u.created_at, 10) AS day,
           COUNT(*) AS registered,
           COUNT(v.user_id) AS verified,
           COUNT(*) FILTER (
               WHERE (a.happened_at::timestamptz - u.created_at::timestamptz)
                   BETWEEN interval '0 seconds' AND interval '7 days'
           ) AS activated_7d,
           COUNT(*) FILTER (WHERE left(u.created_at, 10) <= ?) AS eligible_d7,
           COUNT(r.user_id) FILTER (WHERE left(u.created_at, 10) <= ?) AS retained_d7
    FROM users AS u
    LEFT JOIN verified_emails AS v ON v.user_id = u.id
    LEFT JOIN LATERAL (
        SELECT g.happened_at
        FROM growth_events AS g
        WHERE g.user_id = u.id
          AND g.event_name IN ('first_collection', 'first_work', 'first_topic', 'first_generation')
        ORDER BY g.happened_at
        LIMIT 1
    ) AS a ON true
    LEFT JOIN growth_events AS r
        ON r.user_id = u.id AND r.event_name = 'site_visit'
        AND r.event_day = to_char(left(u.created_at, 10)::date + 7, 'YYYY-MM-DD')
    WHERE u.created_at >= ? AND u.role = 'user' AND u.discourse_user_id IS NULL
    GROUP BY left(u.created_at, 10) ORDER BY day
"""


def growth_report(db: Any, actor: dict, days: int = 30) -> dict:
    if actor.get("role") not in {"admin", "operator"} and actor.get("managementRole") not in {"admin", "operator"}:
        raise ServiceError("无权查看增长指标", status=403, code="forbidden")
    days = max(7, min(90, int(days)))
    conn = db.get_conn()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    eligible_day = (now.date() - timedelta(days=8)).isoformat()
    funnel = [dict(row) for row in conn.execute(
        """
        SELECT (to_timestamp(created_at) AT TIME ZONE 'UTC')::date::text AS day,
               event_name, COUNT(*) AS total
        FROM auth_funnel_events
        WHERE created_at >= ?
        GROUP BY day, event_name ORDER BY day, event_name
        """, (int(start.timestamp()),),
    )]
    cohorts = [dict(row) for row in conn.execute(
        _COHORTS_SQL, (eligible_day, eligible_day, start.date().isoformat()),
    )]
    total = lambda key: sum(int(d.get(key) or 0) for d in cohorts)
    registered = total("registered")
    d7_eligible = total("eligible_d7")
    return {"ok": True, "days": days,
            "definitions": {
                "registered": "注册创建的普通用户账号（按 UTC 日期）",
                "verified": "当前绑定邮箱已验证的注册用户",
                "activated_7d": "注册后七天内首次收藏/发作品/发帖/成功生图",
                "retained_d7": "注册满七天且注册第七天再次访问网站",
                "login_attempt": "请求次数，不是去重访客",
            },
            "summary": {
                "registered": registered,
                "verified": total("verified"),
                "activated7d": total("activated_7d"),
                "activationRate": round(100 * total("activated_7d") / registered, 1) if registered else 0,
                "eligibleD7": d7_eligible,
                "retainedD7": total("retained_d7"),
                "retentionD7Rate": round(100 * total("retained_d7") / d7_eligible, 1) if d7_eligible else 0,
            },
            "cohorts": cohorts, "funnel": funnel}
