"""Community curation service: submissions, review, revision, appeals.

Only user submissions style/layout/work enter here. Publishing to
``catalog_assets``/``works`` happens exclusively on approval, once, guarded by
a unique ledger ``event_key``. Media is assumed already sanitised by the router
(``validate_publish_media``); this module only accepts clean image URLs.

ServiceError comes from :mod:`backend.services`.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .db import Database
from .services import ServiceError, apply_wallet_delta, get_site_settings, utc_now_iso

KINDS: tuple[str, ...] = ("style", "layout", "work")
SUB_STATUSES = ("pending", "approved", "changes_requested", "withdrawn")
ASSIGN_LIMIT = 2
MAX_PAYLOAD_TEXT = 6000
MAX_IMAGES = 9


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return utc_now_iso()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _uid() -> str:
    return uuid.uuid4().hex


def _is_admin(user: dict[str, Any]) -> bool:
    return str(user.get("role") or "") == "admin"


def _username(user: dict[str, Any]) -> str:
    name = str(user.get("username") or "").strip()
    if not name:
        raise ServiceError("身份无效", status=403, code="invalid_user")
    return name


def _user_id(user: dict[str, Any]) -> int:
    try:
        return int(user["id"])
    except (KeyError, TypeError, ValueError):
        raise ServiceError("身份无效", status=403, code="invalid_user")


def _s(value: Any, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def _clean_images(images: Any) -> list[str]:
    """Accept {url}-shaped objects or plain strings; normalize via sanitize_media_url.

    No filename heuristics. Router owns network URL / local path ownership checks;
    here we only reject unsafe schemes and dedupe.
    """
    from .runtime_policy import sanitize_media_url

    if isinstance(images, str):
        images = [images]
    if not isinstance(images, (list, tuple)):
        images = []
    out: list[str] = []
    seen: set[str] = set()
    for raw in images:
        if isinstance(raw, dict):
            candidate = raw.get("url") or raw.get("src") or raw.get("path")
        else:
            candidate = raw
        url = str(candidate or "").strip()
        if not url:
            continue
        cleaned = sanitize_media_url(url)
        if cleaned is None:
            continue
        cleaned = cleaned.strip()
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned[:500])
        if len(out) >= MAX_IMAGES:
            break
    return out



def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        return {k: row[k] for k in row.keys()}
    except Exception:
        return dict(row)


def _load_json(raw: Any, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


def _event(tx: Any, submission_id: str, actor: str, event_type: str, detail: dict[str, Any] | None = None) -> None:
    tx.execute(
        """
        INSERT INTO curation_events (id, submission_id, actor_username, event_type, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (_uid(), submission_id, actor, event_type, json.dumps(detail or {}, ensure_ascii=False), _now()),
    )


# ---------------------------------------------------------------------------
# Payload validation / normalisation
# ---------------------------------------------------------------------------

def _normalise_item(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    if kind == "style":
        name = _s(item.get("name") or item.get("title"), 80)
        definition = _s(item.get("definition") or item.get("prompt"), MAX_PAYLOAD_TEXT)
        if not name:
            raise ServiceError("画风名称不能为空", status=400, code="missing_name")
        if not definition:
            raise ServiceError("画风定义不能为空", status=400, code="missing_definition")
        images = _clean_images(item.get("images") or item.get("image"))
        if not images:
            raise ServiceError("画风需上传至少一张真实示例图", status=400, code="missing_image")
        cost = max(0, min(50, _int(item.get("unlockCost") or item.get("price") or 0)))
        return {
            "kind": "style",
            "name": name,
            "description": _s(item.get("description") or item.get("notes"), 300),
            "definition": definition,
            "group": _s(item.get("group"), 80),
            "unlockCost": cost,
            "image": images[0],
            "images": images,
        }
    if kind == "layout":
        name = _s(item.get("name") or item.get("title"), 80)
        definition = _s(item.get("definition") or item.get("prompt"), MAX_PAYLOAD_TEXT)
        if not name:
            raise ServiceError("图型名称不能为空", status=400, code="missing_name")
        if not definition:
            raise ServiceError("图型定义不能为空", status=400, code="missing_definition")
        images = _clean_images(item.get("images") or item.get("image"))
        if not images:
            raise ServiceError("图型需上传至少一张真实示例图", status=400, code="missing_image")
        cost = max(0, min(50, _int(item.get("unlockCost") or item.get("price") or 0)))
        return {
            "kind": "layout",
            "name": name,
            "description": _s(item.get("description") or item.get("notes"), 300),
            "definition": definition,
            "group": _s(item.get("group"), 80),
            "unlockCost": cost,
            "image": images[0],
            "images": images,
        }
    # work
    title = _s(item.get("title") or item.get("name"), 120)
    prompt = _s(item.get("prompt") or item.get("definition"), MAX_PAYLOAD_TEXT)
    if not title:
        raise ServiceError("作品标题不能为空", status=400, code="missing_title")
    if not prompt:
        raise ServiceError("作品提示词不能为空", status=400, code="missing_prompt")
    images = _clean_images(item.get("images") or item.get("image"))
    if not images:
        raise ServiceError("作品需上传至少一张真实图", status=400, code="missing_image")
    if not isinstance(item.get('styles',[]),list):
        raise ServiceError('画风参数格式错误')
    styles = [str(s).strip().upper().lstrip("#") for s in (item.get("styles") or []) if str(s).strip()]
    # No silent coercion.  Truncating to 3 styles and clamping the price to 100
    # let a work bypass the publish validation by riding along with a style
    # submission, so the review queue would publish a work with mutated fields.
    if len(styles) > 2:
        raise ServiceError("一件作品最多关联两个画风", status=400, code="too_many_styles")
    try:
        if isinstance(item.get("price"), float) and item.get("price") != item.get("price"):
            raise ValueError("NaN price")
        price = int(item.get("price") or 0)
    except (TypeError, ValueError, OverflowError):
        raise ServiceError("作品定价必须是整数", status=400, code="invalid_price")
    if price < 0 or price > 100:
        raise ServiceError("作品定价需在 0 到 100 积分之间", status=400, code="price_out_of_range")
    return {
        "kind": "work",
        "title": title,
        "prompt": prompt,
        "images": images,
        "styles": styles,
        "layout": _s(item.get("layout"), 40).upper().lstrip("#"),
        "color": _s(item.get("color"), 40) or "C-15",
        "tone": _s(item.get("tone"), 40) or "T-01",
        "ratio": _s(item.get("ratio"), 20) or "3:4",
        "mode": _s(item.get("mode"), 40) or "graphic-text",
        "mood": _s(item.get("mood"), 40) or "治愈",
        "price": price,
        "notes": _s(item.get("notes") or item.get("description"), 600),
    }


def _parse_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = body.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ServiceError("请至少提交一项内容", status=400, code="missing_items")
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ServiceError("提交项格式错误", status=400, code="bad_item")
        kind = _s(raw.get("kind"), 20).lower()
        if kind not in KINDS:
            raise ServiceError(f"不支持的收录类型：{kind or '(空)'}", status=400, code="bad_kind")
        items.append(_normalise_item(kind, raw))
        if len(items) > 20:
            raise ServiceError("单次提交项过多", status=400, code="too_many_items")
    return items


# ---------------------------------------------------------------------------
# Review access resolution
# ---------------------------------------------------------------------------

def _access_map(tx: Any) -> dict[tuple[str, str], dict[str, Any]]:
    rows = tx.execute("SELECT * FROM curation_review_access").fetchall()
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        d = _row_to_dict(r) or {}
        out[(d.get("username", ""), d.get("kind", ""))] = d
    return out


def _accepted_kinds_for(tx, username):
    # Only collected contributions confer earned access; demo and launch accounts never do.
    from .seed import seed_ids
    if tx.execute("SELECT 1 FROM sqlite_master WHERE name='cold_start_registry'").fetchone() and tx.execute("SELECT 1 FROM cold_start_registry WHERE kind='user' AND item_id=?", (username,)).fetchone():
        return set()
    assets = tx.execute("SELECT code,kind FROM catalog_assets WHERE author_username=? COLLATE NOCASE AND source_type='community' AND status='published'", (username,)).fetchall()
    works = tx.execute("SELECT id FROM works WHERE author_username=? COLLATE NOCASE AND status='published'", (username,)).fetchall()
    kinds = {r['kind'] for r in assets if r['code'] not in seed_ids('assets')}
    if any(r['id'] not in seed_ids('works') for r in works):
        kinds.add('work')
    return kinds




def _review_access_for(tx: Any, user: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve per-kind review eligibility.

    - paused always disables, including for admins.
    - admin without pause gets eligible (backup slot), but self-review is still
      blocked at vote level (see vote()).
    - explicit grant (granted_by) enables.
    - otherwise eligible only if _accepted_kinds_for confirms a live artefact.
    """
    username = _username(user)
    base = _access_map(tx)
    accepted = _accepted_kinds_for(tx, username)
    is_admin = _is_admin(user)
    out: list[dict[str, Any]] = []
    for kind in KINDS:
        rec = base.get((username, kind)) or {}
        paused = bool(rec.get("paused"))
        granted = bool(rec.get("manual_granted"))
        if paused:
            eligible = False
            source = "paused"
        elif granted:
            eligible = True
            source = "grant"
        elif is_admin:
            eligible = True
            source = "admin"
        elif kind in accepted:
            eligible = True
            source = "accepted"
        else:
            eligible = False
            source = "none"
        out.append(
            {
                "kind": kind,
                "eligible": eligible,
                "admin": is_admin,
                "paused": paused,
                "source": source,
            }
        )
    return out



def _has_eligible_access(tx: Any, user: dict[str, Any], kind: str) -> bool:
    for entry in _review_access_for(tx, user):
        if entry["kind"] == kind:
            return bool(entry["eligible"])
    return False


# ---------------------------------------------------------------------------
# Public / summary helpers
# ---------------------------------------------------------------------------

def _submission_row(tx: Any, submission_id: str) -> dict[str, Any]:
    row = tx.execute("SELECT * FROM curation_submissions WHERE id = ?", (submission_id,)).fetchone()
    if not row:
        raise ServiceError("投稿不存在", status=404, code="submission_not_found")
    return _row_to_dict(row) or {}


def _current_payload(tx: Any, submission_id: str, revision: int) -> dict[str, Any]:
    row = tx.execute(
        "SELECT payload_json FROM curation_versions WHERE submission_id = ? AND revision = ?",
        (submission_id, revision),
    ).fetchone()
    if not row:
        raise ServiceError("投稿版本缺失", status=500, code="version_missing")
    return _load_json(row["payload_json"], {}) or {}


def _safe_preview(payload: dict[str, Any]) -> dict[str, Any]:
    """Public preview that never leaks full definition/prompt of unreviewed items."""
    kind = payload.get("kind")
    preview: dict[str, Any] = {"kind": kind}
    for key in ("name", "title", "description", "notes", "layout", "ratio", "mode", "styles", "price", "unlockCost", "mood", "color", "tone"):
        if key in payload:
            preview[key] = payload[key]
    images = payload.get("images") or ([payload["image"]] if payload.get("image") else [])
    preview["images"] = images[:MAX_IMAGES]
    return preview


# ---------------------------------------------------------------------------
# Core submission
# ---------------------------------------------------------------------------

def submit(db: Database, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    username = _username(user)
    uid = _user_id(user)
    body = body or {}
    request_id = _s(body.get("requestId"), 80)
    items = _parse_items(body)

    # Works no longer travel through review at all (D-02).  Publishing is the
    # single path for a work, so a work item inside a submission — alone or
    # alongside styles/layouts — is rejected rather than queued.  Previously a
    # mixed submission carried the work past review with mutated fields.
    kinds = [str(it.get("kind") or "").lower() for it in items]
    if "work" in kinds:
        raise ServiceError(
            "作品已改为即时发布，请通过作品发布接口单独提交", status=400, code="work_publish_moved"
        )

    title = _s(body.get("title"), 140) or "社区投稿征集"
    from .runtime_policy import sanitize_html
    text = sanitize_html(_s(body.get("text") or body.get("summary"), 60000)) or "以下为本帖投稿内容，等待社区审核收录。"
    now_iso = _now()
    now_ms = _now_ms()

    with db.transaction() as tx:
        # Idempotent replay of the same client request (curation_requests is the ledger).
        if request_id:
            dup = tx.execute(
                "SELECT submission_id FROM curation_requests WHERE owner_username = ? AND request_id = ?",
                (username, request_id),
            ).fetchone()
            if dup:
                first = _submission_row(tx, str(dup["submission_id"]))
                siblings = tx.execute(
                    "SELECT * FROM curation_submissions WHERE topic_id = ? ORDER BY created_at",
                    (first.get("topic_id"),),
                ).fetchall()
                subs = [
                    {
                        "id": r["id"],
                        "kind": r["kind"],
                        "targetId": r["target_id"],
                        "status": r["status"],
                        "revision": int(r["current_revision"]),
                    }
                    for r in (_row_to_dict(x) or {} for x in siblings)
                ]
                work_id = next((s["targetId"] for s in subs if s["kind"] == "work"), None)
                code = next((s["targetId"] for s in subs if s["kind"] in ("style", "layout")), None)
                return {
                    "ok": True,
                    "topicId": first.get("topic_id"),
                    "submissions": subs,
                    "workId": work_id,
                    "code": code,
                    "deduplicated": True,
                }

        topic_id = f"topic_{now_ms}_{uuid.uuid4().hex[:4]}"
        images_preview: list[str] = []
        for it in items:
            imgs = it.get("images") or ([it["image"]] if it.get("image") else [])
            for url in imgs:
                if url not in images_preview:
                    images_preview.append(url)
        styles_preview: list[str] = []
        layout_preview = ""
        for it in items:
            if it.get("kind") == "work":
                for s in it.get("styles") or []:
                    if s not in styles_preview:
                        styles_preview.append(s)
                if it.get("layout") and not layout_preview:
                    layout_preview = it["layout"]

        tx.execute(
            """
            INSERT INTO forum_topics (
                id, category, category_label, pinned, featured, title, author_username, author_name,
                views, likes, favorites, price, bounty, bounty_status, solved, accepted_reply_id,
                images_json, styles_json, layout_code, work_id, recipe_json, summary, locked_body,
                status, published_at_ms, created_label, created_at, updated_at
            ) VALUES (?, 'assets', '🎨 画风与图型专区', 0, 0, ?, ?, ?, 0, 0, 0, 0, 0, 'none', 0, '', ?, ?, ?, '', '', ?, '', 'published', ?, '刚刚', ?, ?)
            """,
            (
                topic_id,
                title,
                username,
                str(user.get("display_name") or username),
                json.dumps(images_preview[:MAX_IMAGES], ensure_ascii=False),
                json.dumps(styles_preview[:3], ensure_ascii=False),
                layout_preview,
                text,
                now_ms,
                now_iso,
                now_iso,
            ),
        )

        submissions_out: list[dict[str, Any]] = []
        work_id: str | None = None
        code: str | None = None

        for it in items:
            _validate_references(tx,it)
            kind = it["kind"]
            # Assign stable final id now; first publish and every revision UPSERT to it.
            target_id = _stable_target_id(kind, None)
            sid = _uid()
            tx.execute(
                """
                INSERT INTO curation_submissions (
                    id, topic_id, owner_username, owner_user_id, kind, target_id,
                    status, current_revision, request_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 1, ?, ?, ?)
                """,
                (sid, topic_id, username, uid, kind, target_id, request_id, now_iso, now_iso),
            )
            tx.execute(
                """
                INSERT INTO curation_versions (id, submission_id, revision, payload_json, created_at)
                VALUES (?, ?, 1, ?, ?)
                """,
                (_uid(), sid, json.dumps(it, ensure_ascii=False), now_iso),
            )
            tx.execute(
                """
                INSERT INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at)
                VALUES (?, ?, ?, 'submission', ?)
                """,
                (kind, target_id, topic_id, now_iso),
            )
            _event(tx, sid, username, "submit", {"kind": kind, "revision": 1, "targetId": target_id})
            submissions_out.append(
                {"id": sid, "kind": kind, "targetId": target_id, "status": "pending", "revision": 1}
            )
            if kind == "work" and work_id is None:
                work_id = target_id
            if kind in ("style", "layout") and code is None:
                code = target_id

        if request_id:
            tx.execute(
                """
                INSERT INTO curation_requests (id, owner_username, request_id, submission_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (_uid(), username, request_id, submissions_out[0]["id"], now_iso),
            )

        result: dict[str, Any] = {"ok": True, "topicId": topic_id, "submissions": submissions_out}
        if work_id:
            result["workId"] = work_id
        if code:
            result["code"] = code
        return result



# ---------------------------------------------------------------------------
# Author-facing
# ---------------------------------------------------------------------------

def my_submissions(db: Database, user: dict[str, Any]) -> dict[str, Any]:
    username = _username(user)
    with db.transaction() as tx:
        rows = tx.execute(
            "SELECT * FROM curation_submissions WHERE owner_username = ? ORDER BY created_at DESC",
            (username,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            sub = _row_to_dict(row) or {}
            sid = sub["id"]
            payload = _current_payload(tx, sid, int(sub["current_revision"]))
            versions = []
            vrows = tx.execute(
                "SELECT revision, payload_json, created_at FROM curation_versions WHERE submission_id = ? ORDER BY revision",
                (sid,),
            ).fetchall()
            for v in vrows:
                vd = _row_to_dict(v) or {}
                votes = tx.execute(
                    "SELECT reviewer_username, decision, reason, revision, created_at FROM curation_votes WHERE submission_id = ? AND revision = ? ORDER BY created_at",
                    (sid, int(vd["revision"])),
                ).fetchall()
                versions.append(
                    {
                        "revision": int(vd["revision"]),
                        "payload": _load_json(vd.get("payload_json"), {}),
                        "createdAt": vd.get("created_at"),
                        "votes": [
                            {
                                "reviewer": vr["reviewer_username"],
                                "decision": vr["decision"],
                                "reason": vr["reason"],
                                "createdAt": vr["created_at"],
                            }
                            for vr in votes
                        ],
                    }
                )
            appeals = tx.execute(
                "SELECT id, reason, status, created_at FROM curation_appeals WHERE submission_id = ? ORDER BY created_at DESC",
                (sid,),
            ).fetchall()
            out.append(
                {
                    "id": sid,
                    "topicId": sub["topic_id"],
                    "kind": sub["kind"],
                    "targetId": sub["target_id"],
                    "status": sub["status"],
                    "revision": int(sub["current_revision"]),
                    "payload": payload,
                    "versions": versions,
                    "appeals": [_row_to_dict(a) for a in appeals],
                    "adminActions": [dict(a) for a in tx.execute('SELECT admin_username,action,reason,created_at FROM curation_admin_actions WHERE submission_id=? ORDER BY created_at',(sid,)).fetchall()],
                }
            )
        return {"ok": True, "submissions": out}


# ---------------------------------------------------------------------------
# Access management
# ---------------------------------------------------------------------------

def review_access(db: Database, user: dict[str, Any]) -> dict[str, Any]:
    with db.transaction() as tx:
        entries = _review_access_for(tx, user)
    eligible_kinds = [e["kind"] for e in entries if e["eligible"]]
    return {
        "ok": True,
        "kinds": eligible_kinds,
        "admin": _is_admin(user),
        "sources": {
            "admin": _is_admin(user),
            "granted": [e["kind"] for e in entries if e["source"] == "grant"],
            "accepted": [e["kind"] for e in entries if e["source"] == "accepted"],
            "paused": [e["kind"] for e in entries if e["paused"]],
        },
        "entries": entries,
    }


def grant_access(db: Database, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    if not _is_admin(user):
        raise ServiceError("仅管理员可管理审核资格", status=403, code="forbidden")
    admin_name = _username(user)
    body = body or {}
    usernames = [ _s(u, 80) for u in (body.get("usernames") or []) if _s(u, 80)]
    kinds = [ _s(k, 20).lower() for k in (body.get("kinds") or []) if _s(k, 20) ]
    action = _s(body.get("action"), 20).lower()
    reason = _s(body.get("reason"), 400)
    if not usernames:
        raise ServiceError("请提供用户名列表", status=400, code="missing_usernames")
    if not kinds:
        raise ServiceError("请提供类型列表", status=400, code="missing_kinds")
    for k in kinds:
        if k not in KINDS:
            raise ServiceError(f"不支持的收录类型：{k}", status=400, code="bad_kind")
    if action not in ("grant", "pause", "resume"):
        raise ServiceError("不支持的操作", status=400, code="bad_action")

    now = _now()
    results: list[dict[str, Any]] = []
    with db.transaction() as tx:
        for name in usernames:
            exists = tx.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE", (name,)).fetchone()
            if not exists:
                results.append({"username": name, "ok": False, "error": "user_not_found"})
                continue
            real_name = str(tx.execute("SELECT username FROM users WHERE username = ? COLLATE NOCASE", (name,)).fetchone()["username"])
            for kind in kinds:
                row = tx.execute(
                    "SELECT * FROM curation_review_access WHERE username = ? AND kind = ?",
                    (real_name, kind),
                ).fetchone()
                if action == "grant":
                    if row:
                        tx.execute(
                            "UPDATE curation_review_access SET paused = 0, manual_granted = 1, granted_by = ?, reason = ?, updated_at = ? WHERE username = ? AND kind = ?",
                            (admin_name, reason, now, real_name, kind),
                        )
                    else:
                        tx.execute(
                            """
                            INSERT INTO curation_review_access (username, kind, paused, granted_by, reason, created_at, updated_at)
                            VALUES (?, ?, 0, ?, ?, ?, ?)
                            """,
                            (real_name, kind, admin_name, reason, now, now),
                        )
                elif action == "pause":
                    if not row:
                        tx.execute(
                            """
                            INSERT INTO curation_review_access (username, kind, paused, granted_by, reason, created_at, updated_at)
                            VALUES (?, ?, 1, ?, ?, ?, ?)
                            """,
                            (real_name, kind, admin_name, reason, now, now),
                        )
                    else:
                        tx.execute(
                            "UPDATE curation_review_access SET paused = 1, reason = ?, updated_at = ? WHERE username = ? AND kind = ?",
                            (reason, now, real_name, kind),
                        )
                    # Release active assignments on pause.
                    tx.execute(
                        """
                        UPDATE curation_assignments SET status = 'released'
                        WHERE reviewer_username = ? AND status = 'active'
                          AND submission_id IN (SELECT id FROM curation_submissions WHERE kind = ?)
                        """,
                        (real_name, kind),
                    )
                else:  # resume
                    if not row:
                        results.append({"username": real_name, "kind": kind, "ok": False, "error": "not_granted"})
                        continue
                    tx.execute(
                        "UPDATE curation_review_access SET paused = 0, reason = ?, updated_at = ? WHERE username = ? AND kind = ?",
                        (reason, now, real_name, kind),
                    )
                if action == "grant":
                    tx.execute("UPDATE curation_review_access SET manual_granted=1 WHERE username=? AND kind=?", (real_name,kind))
                results.append({"username": real_name, "kind": kind, "ok": True, "action": action})
            _event(tx, "", admin_name, "grant_access", {"usernames": [real_name], "kinds": kinds, "action": action, "reason": reason})
    return {"ok": True, "results": results}


# ---------------------------------------------------------------------------
# Review queue and voting
# ---------------------------------------------------------------------------

def _count_votes(tx: Any, submission_id: str, revision: int) -> tuple[int, int]:
    rows = tx.execute(
        "SELECT decision, COUNT(*) AS c FROM curation_votes WHERE submission_id = ? AND revision = ? GROUP BY decision",
        (submission_id, revision),
    ).fetchall()
    approve = changes = 0
    for r in rows:
        if r["decision"] == "approve":
            approve = int(r["c"])
        elif r["decision"] == "changes":
            changes = int(r["c"])
    return approve, changes


def _assign_slot(tx, submission_id, revision, reviewer, seq):
    old = tx.execute("SELECT * FROM curation_assignments WHERE submission_id=? AND revision=? AND reviewer_username=?", (submission_id, revision, reviewer)).fetchone()
    aid = old['id'] if old else _uid()
    tx.execute("INSERT INTO curation_assignments (id,submission_id,revision,reviewer_username,seq,status,created_at) VALUES (?,?,?,?,?,'active',?) ON CONFLICT(submission_id,revision,reviewer_username) DO UPDATE SET status='active',seq=excluded.seq,created_at=excluded.created_at", (aid,submission_id,revision,reviewer,seq,_now()))
    return dict(tx.execute("SELECT * FROM curation_assignments WHERE id=?",(aid,)).fetchone())







def review_queue(db, user):
    reviewer=_username(user)
    with db.transaction() as tx:
        _release_invalid_assignments(tx)
        eligible=[e['kind'] for e in _review_access_for(tx,user) if e['eligible']]
        active=tx.execute("SELECT status FROM users WHERE id=? AND username=?",(_user_id(user),reviewer)).fetchone()
        if not active or active['status']!='active':
            eligible=[]
        if not eligible:
            return {'ok':True,'access':[],'assignment':None}
        old=tx.execute("SELECT * FROM curation_assignments WHERE reviewer_username=? AND status='active' ORDER BY created_at LIMIT 1",(reviewer,)).fetchone()
        if old:
            return {'ok':True,'access':eligible,'assignment':_assignment_view(tx,dict(old),_submission_row(tx,old['submission_id']))}
        pending=tx.execute("SELECT * FROM curation_submissions WHERE status='pending' AND owner_username!=? COLLATE NOCASE ORDER BY created_at,id",(reviewer,)).fetchall()
        for r in pending:
            sub=dict(r)
            if sub['kind'] not in eligible:
                continue
            rev=int(sub['current_revision'])
            voted={r['reviewer_username'].lower() for r in tx.execute("SELECT reviewer_username FROM curation_votes WHERE submission_id=? AND revision=?",(sub['id'],rev))}
            if reviewer.lower() in voted:
                continue
            approve,changes=_count_votes(tx,sub['id'],rev)
            if max(approve,changes)>=2:
                continue
            names={r['reviewer_username'].lower() for r in tx.execute("SELECT reviewer_username FROM curation_assignments WHERE submission_id=? AND revision=? AND status='active'",(sub['id'],rev))}
            cap=3 if approve==changes==1 else 2
            if len(voted|names)>=cap:
                continue
            slot=_assign_slot(tx,sub['id'],rev,reviewer,len(voted|names)+1)
            _event(tx,sub['id'],reviewer,'assign',{'revision':rev})
            return {'ok':True,'access':eligible,'assignment':_assignment_view(tx,slot,sub)}
        return {'ok':True,'access':eligible,'assignment':None}




def _assignment_view(tx: Any, assignment: dict[str, Any], sub: dict[str, Any]) -> dict[str, Any]:
    payload = _current_payload(tx, sub["id"], int(assignment["revision"]))
    return {
        "id": assignment["id"],
        "assignmentId": assignment["id"],
        "submissionId": sub["id"],
        "revision": int(assignment["revision"]),
        "kind": sub["kind"],
        "payload": payload,  # for assigned reviewers only
        "topicId": sub["topic_id"],
    }


def vote(db: Database, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    reviewer = _username(user)
    body = body or {}
    assignment_id = _s(body.get("assignmentId"), 80)
    decision = _s(body.get("decision"), 20).lower()
    reason = _s(body.get("reason"), 600)
    if not assignment_id:
        raise ServiceError("缺少分配编号", status=400, code="missing_assignment")
    if decision not in ("approve", "changes"):
        raise ServiceError("无效的投票选项", status=400, code="bad_decision")
    if decision == "changes" and not reason:
        raise ServiceError("退回修改必须说明理由", status=400, code="reason_required")

    with db.transaction() as tx:
        _release_invalid_assignments(tx)
        arow = tx.execute("SELECT * FROM curation_assignments WHERE id = ?", (assignment_id,)).fetchone()
        if not arow:
            raise ServiceError("分配不存在", status=404, code="assignment_not_found")
        a = _row_to_dict(arow) or {}
        if str(a["reviewer_username"]).lower() != reviewer.lower():
            raise ServiceError("无权处理该分配", status=403, code="not_assigned")
        sub = _submission_row(tx, str(a["submission_id"]))
        if sub["owner_username"].lower() == reviewer.lower():
            raise ServiceError("不能审核自己的投稿", status=403, code="self_review")

        status = str(a["status"])
        if status != "active":
            # Idempotent replay only if this exact assignment already voted same decision.
            prev = tx.execute("SELECT * FROM curation_votes WHERE assignment_id = ?", (assignment_id,)).fetchone()
            if prev:
                pd = _row_to_dict(prev) or {}
                if pd["decision"] == decision:
                    return {
                        "ok": True,
                        "submissionId": sub["id"],
                        "status": sub["status"],
                        "revision": int(sub["current_revision"]),
                        "decision": decision,
                        "idempotent": True,
                    }
            raise ServiceError("该分配已失效", status=409, code="assignment_inactive")

        rev = int(a["revision"])
        if rev != int(sub["current_revision"]):
            tx.execute("UPDATE curation_assignments SET status = 'stale' WHERE id = ?", (assignment_id,))
            raise ServiceError("版本已更新，分配失效", status=409, code="revision_changed")
        if str(sub["status"]) != "pending":
            raise ServiceError("该投稿当前不可投票", status=409, code="not_votable")
        if not _has_eligible_access(tx, user, sub["kind"]):
            raise ServiceError("你当前没有该类审核资格", status=403, code="no_access")

        prev_vote = tx.execute(
            "SELECT * FROM curation_votes WHERE submission_id = ? AND revision = ? AND reviewer_username = ?",
            (sub["id"], rev, reviewer),
        ).fetchone()
        if prev_vote:
            pv = _row_to_dict(prev_vote) or {}
            if pv["decision"] == decision:
                return {
                    "ok": True,
                    "submissionId": sub["id"],
                    "status": sub["status"],
                    "revision": rev,
                    "decision": decision,
                    "idempotent": True,
                }
            raise ServiceError("投票已记录，不能更改", status=409, code="vote_locked")

        now = _now()
        tx.execute(
            """
            INSERT INTO curation_votes (id, assignment_id, submission_id, revision, reviewer_username, decision, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_uid(), assignment_id, sub["id"], rev, reviewer, decision, reason, now),
        )
        tx.execute("UPDATE curation_assignments SET status = 'voted' WHERE id = ?", (assignment_id,))
        _event(tx, sub["id"], reviewer, "vote", {"revision": rev, "decision": decision})

        approve, changes = _count_votes(tx, sub["id"], rev)
        new_status = sub["status"]
        published: dict[str, Any] | None = None

        if approve >= 2:
            new_status = "approved"
            published = _publish_approved(tx, sub, rev)
        elif changes >= 2:
            new_status = "changes_requested"
        # On divergence (1 approve / 1 changes) we do NOT assign a third reviewer here.
        # The next reviewer pulls via review_queue (slot cap=3).

        if new_status != sub["status"]:
            tx.execute(
                "UPDATE curation_submissions SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now, sub["id"]),
            )
            _event(tx, sub["id"], reviewer, "status", {"from": sub["status"], "to": new_status, "revision": rev})
            # Decide/close remaining active assignments on this revision.
            if new_status in ("approved", "changes_requested"):
                tx.execute(
                    "UPDATE curation_assignments SET status = 'stale' WHERE submission_id = ? AND revision = ? AND status = 'active'",
                    (sub["id"], rev),
                )

        result = {
            "ok": True,
            "submissionId": sub["id"],
            "status": new_status,
            "revision": rev,
            "decision": decision,
            "approve": approve,
            "changes": changes,
        }
        if published:
            result["published"] = published
        return result





def _publish_approved(tx: Any, sub: dict[str, Any], revision: int) -> dict[str, Any]:
    """Upsert the public resource to its stable target_id; reward once per target.

    - Uses curation_submissions.target_id (assigned at submit) as the stable key.
    - First publish and every revision: ON CONFLICT DO UPDATE content/status/updated_at,
      preserving interactions, created_at, published_at_ms.
    - No INSERT OR REPLACE.
    - Writes an immutable version snapshot (payload_json in curation_versions already;
      add curation_publish_snapshots if table exists).
    - Applies publish reward once via event_key tied to stable target_id.
    """
    payload = _current_payload(tx, sub["id"], revision)
    _validate_references(tx, payload)
    kind = sub["kind"]
    owner = sub["owner_username"]
    target_id = str(sub["target_id"])
    owner_row = tx.execute(
        "SELECT id, display_name, honor_override FROM users WHERE username = ? COLLATE NOCASE",
        (owner,),
    ).fetchone()
    owner_uid = int(owner_row["id"]) if owner_row else int(sub["owner_user_id"])
    display = str(owner_row["display_name"]) if owner_row else owner
    now_iso = _now()
    now_ms = _now_ms()
    settings = get_site_settings(tx)
    econ = settings.get("economy", {})
    from .services import _count_user_published_items, compute_honor_tier, compute_public_asset_counts_and_creators
    before_count = _count_user_published_items(tx, owner)
    override = owner_row['honor_override'] if owner_row else None
    before_honor = compute_honor_tier(before_count, override)
    counts = compute_public_asset_counts_and_creators(tx)[0] if kind == 'work' else {}
    threshold = int(econ.get('pioneer_work_threshold', 3))
    refs = list(payload.get('styles') or []) + ([payload['layout']] if payload.get('layout') else [])
    pioneer = kind == 'work' and any(counts.get(code, 0) < threshold for code in refs)

    if kind in ("style", "layout"):
        images = payload.get("images") or ([payload.get("image")] if payload.get("image") else [])
        if not images:
            raise ServiceError("发布失败：缺少图像", status=500, code="publish_missing_image")
        image_url = images[0]
        cost = int(payload.get("unlockCost") or 0)
        group_name = payload.get("group") or (
            "USR 社区共创画风 / Community" if kind == "style" else "social-card"
        )

        existing = tx.execute(
            "SELECT code FROM catalog_assets WHERE code = ?",
            (target_id,),
        ).fetchone()
        if existing is None:
            # First publish: keep original publication time.
            tx.execute(
                """
                INSERT INTO catalog_assets (
                    code, kind, source_type, author_username, author_name, name, group_name,
                    tier, unlock_cost, image_url, description, definition, prompt_en,
                    secret_blackbox_prompt, status, featured, is_new_release, cheers,
                    published_at_ms, created_label, created_at, updated_at
                ) VALUES (?, ?, 'community', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 'published', 0, 1, 0, ?, '刚刚', ?, ?)
                """,
                (
                    target_id,
                    kind,
                    owner,
                    display,
                    payload.get("name") or ("社区共创画风" if kind == "style" else "社区共创图型"),
                    group_name,
                    "pro_credit" if cost > 0 else "free",
                    cost,
                    image_url,
                    payload.get("description") or "",
                    payload.get("definition") or "",
                    f"Community {kind}: {payload.get('name') or ''}",
                    now_ms,
                    now_iso,
                    now_iso,
                ),
            )
        else:
            # Revision on same stable code: update content only.
            tx.execute(
                """
                UPDATE catalog_assets SET
                    author_username = ?, author_name = ?, name = ?, group_name = ?,
                    tier = ?, unlock_cost = ?, image_url = ?, description = ?, definition = ?,
                    prompt_en = ?, status = 'published', updated_at = ?
                WHERE code = ?
                """,
                (
                    owner,
                    display,
                    payload.get("name") or ("社区共创画风" if kind == "style" else "社区共创图型"),
                    group_name,
                    "pro_credit" if cost > 0 else "free",
                    cost,
                    image_url,
                    payload.get("description") or "",
                    payload.get("definition") or "",
                    f"Community {kind}: {payload.get('name') or ''}",
                    now_iso,
                    target_id,
                ),
            )

        reward_kind = "publish_asset"
        reward = int(econ.get("asset_publish_credits", 15))
        event_key = f"pub_asset_{target_id}"
        reason = f"收录社区{'画风' if kind == 'style' else '图型'} {target_id}《{payload.get('name') or ''}》"
        published: dict[str, Any] = {"kind": kind, "code": target_id}
        ref_type = "asset"
        ref_id = target_id
    else:
        images = payload.get("images") or []
        styles = payload.get("styles") or []
        existing_work = tx.execute(
            "SELECT id FROM works WHERE id = ?",
            (target_id,),
        ).fetchone()
        if existing_work is None:
            tx.execute(
                """
                INSERT INTO works (
                    id, author_username, author_name, title, images_json, styles_json,
                    layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes,
                    status, featured, is_new_release, pioneer_rewarded, cheers, likes, favorites, forks,
                    published_at_ms, created_label, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', 0, 1, 0, 0, 0, 0, 0, ?, '刚刚', ?, ?)
                """,
                (
                    target_id,
                    owner,
                    display,
                    payload.get("title") or "社区作品",
                    json.dumps(images, ensure_ascii=False),
                    json.dumps(styles, ensure_ascii=False),
                    payload.get("layout") or "",
                    payload.get("color") or "C-15",
                    payload.get("tone") or "T-01",
                    payload.get("ratio") or "3:4",
                    payload.get("mode") or "graphic-text",
                    payload.get("mood") or "治愈",
                    int(payload.get("price") or 0),
                    payload.get("prompt") or "",
                    payload.get("notes") or "",
                    now_ms,
                    now_iso,
                    now_iso,
                ),
            )
        else:
            tx.execute(
                """
                UPDATE works SET
                    author_username = ?, author_name = ?, title = ?, images_json = ?, styles_json = ?,
                    layout_code = ?, color_code = ?, tone_code = ?, ratio = ?, mode = ?, mood = ?,
                    price = ?, prompt = ?, notes = ?, status = 'published', updated_at = ?
                WHERE id = ?
                """,
                (
                    owner,
                    display,
                    payload.get("title") or "社区作品",
                    json.dumps(images, ensure_ascii=False),
                    json.dumps(styles, ensure_ascii=False),
                    payload.get("layout") or "",
                    payload.get("color") or "C-15",
                    payload.get("tone") or "T-01",
                    payload.get("ratio") or "3:4",
                    payload.get("mode") or "graphic-text",
                    payload.get("mood") or "治愈",
                    int(payload.get("price") or 0),
                    payload.get("prompt") or "",
                    payload.get("notes") or "",
                    now_iso,
                    target_id,
                ),
            )

        reward_kind = "publish_work"
        reward = int(econ.get("work_publish_credits", 5)) + (int(econ.get('pioneer_bonus_credits',10)) if pioneer else 0)
        event_key = f"pub_work_{target_id}"
        reason = f"收录实测作品《{payload.get('title') or ''}》"
        published = {"kind": "work", "workId": target_id}
        ref_type = "work"
        ref_id = target_id

    # Traceable snapshot per revision (table optional; guarded).
    snap_exists = tx.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'curation_publish_snapshots'"
    ).fetchone()
    if snap_exists:
        tx.execute(
            """
            INSERT INTO curation_publish_snapshots (id, submission_id, revision, target_id, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (_uid(), sub["id"], revision, target_id, json.dumps(payload, ensure_ascii=False), now_iso),
        )

    balance, credited = apply_wallet_delta(
        tx,
        owner_uid,
        reward,
        reward_kind,
        reason,
        event_key=event_key,
        ref_type=ref_type,
        ref_id=ref_id,
    )
    if credited and pioneer:
        tx.execute('UPDATE works SET pioneer_rewarded=1 WHERE id=?', (target_id,))
    after_honor = compute_honor_tier(_count_user_published_items(tx, owner), override)
    upgraded = ''
    if after_honor['tier'] > before_honor['tier']:
        balance, honor_credited = apply_wallet_delta(tx,owner_uid,int(econ.get('honor_upgrade_credits',10)), 'honor_upgrade',f"创作者荣誉晋升至{after_honor['badge']}",event_key=f"honor_up_{owner_uid}_{after_honor['tier']}")
        if honor_credited:
            upgraded = after_honor['badge']
    # Preserve explicit public grants for the collected resource, independently of its forum entry.
    for url in payload.get('images',[]):
        media = tx.execute('SELECT user_id FROM studio_generation_media WHERE media_url=? UNION SELECT user_id FROM user_uploads WHERE image_url=? LIMIT 1',(url,url)).fetchone()
        if media and media[0] == owner_uid:
            tx.execute('INSERT INTO media_public_grants (id,media_url,owner_user_id,target_type,target_id,granted_by_user_id,granted_at,revoked_at) VALUES (?,?,?,?,?,?,?,NULL) ON CONFLICT(media_url,target_type,target_id) DO UPDATE SET revoked_at=NULL,granted_at=excluded.granted_at',(_uid(),url,owner_uid,ref_type,target_id,owner_uid,now_iso))
    published["reward"] = reward if credited else 0
    published["credits"] = balance
    published['pioneer'] = pioneer if credited else False
    published['upgradedBadge'] = upgraded
    _event(tx, sub["id"], "system", "publish", {**published, "revision": revision})
    return published



# ---------------------------------------------------------------------------
# Revision / appeal / admin
# ---------------------------------------------------------------------------

def revise(db: Database, user: dict[str, Any], submission_id: str, body: dict[str, Any]) -> dict[str, Any]:
    username = _username(user)
    body = body or {}
    raw_payload = body.get("payload")
    if not isinstance(raw_payload, dict):
        raise ServiceError("缺少新的提交内容", status=400, code="missing_payload")
    submission_id = _s(submission_id, 80)

    with db.transaction() as tx:
        sub = _submission_row(tx, submission_id)
        if sub["owner_username"].lower() != username.lower():
            raise ServiceError("只能修改自己的投稿", status=403, code="not_owner")
        if sub["status"] == "withdrawn":
            raise ServiceError("该投稿已下架，请先申诉", status=409, code="withdrawn")
        if sub["status"] not in ("pending", "changes_requested", "approved"):
            raise ServiceError("当前状态不可修改", status=409, code="not_revisable")

        kind = sub["kind"]
        item = dict(raw_payload)
        item["kind"] = kind
        normalised = _normalise_item(kind, item)
        _validate_references(tx,normalised)
        new_rev = int(sub["current_revision"]) + 1
        now = _now()

        tx.execute(
            "INSERT INTO curation_versions (id, submission_id, revision, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (_uid(), submission_id, new_rev, json.dumps(normalised, ensure_ascii=False), now),
        )
        # Invalidate old version's pending assignments.
        tx.execute(
            "UPDATE curation_assignments SET status = 'stale' WHERE submission_id = ? AND status = 'active'",
            (submission_id,),
        )
        tx.execute(
            "UPDATE curation_submissions SET current_revision = ?, status = 'pending', updated_at = ? WHERE id = ?",
            (new_rev, now, submission_id),
        )
        _event(tx, submission_id, username, "revise", {"revision": new_rev})
        _sync_topic_preview(tx, sub["topic_id"])
        updated = _submission_row(tx, submission_id)
        return {
            "ok": True,
            "id": submission_id,
            "topicId": sub["topic_id"],
            "kind": kind,
            "targetId": updated["target_id"],
            "status": updated["status"],
            "revision": int(updated["current_revision"]),
            "payload": normalised,
        }


def appeal(db: Database, user: dict[str, Any], submission_id: str, reason: str) -> dict[str, Any]:
    username = _username(user)
    reason = _s(reason, 1000)
    if not reason:
        raise ServiceError("请填写申诉理由", status=400, code="reason_required")
    submission_id = _s(submission_id, 80)
    with db.transaction() as tx:
        sub = _submission_row(tx, submission_id)
        if sub["owner_username"].lower() != username.lower():
            raise ServiceError("只能申诉自己的投稿", status=403, code="not_owner")
        if sub['status'] not in ('changes_requested','withdrawn'):
            raise ServiceError('仅退回或下架的投稿可以申诉',status=409)
        existing=tx.execute("SELECT id FROM curation_appeals WHERE submission_id=? AND status='open'",(submission_id,)).fetchone()
        if existing:
            return {'ok':True,'appealId':existing['id'],'submissionId':submission_id,'status':'open'}
        aid = _uid()
        now = _now()
        tx.execute(
            "INSERT INTO curation_appeals (id, submission_id, author_username, reason, status, created_at) VALUES (?, ?, ?, ?, 'open', ?)",
            (aid, submission_id, username, reason, now),
        )
        _event(tx, submission_id, username, "appeal", {"appealId": aid})
    return {"ok": True, "appealId": aid, "submissionId": submission_id, "status": "open"}


def admin_review(db, user, body):
    if not _is_admin(user):
        raise ServiceError('仅管理员可处理',status=403)
    sid=_s(body.get('submissionId'),80)
    action=_s(body.get('action'),20)
    reason=_s(body.get('reason'),1000)
    if action not in ('approve','changes','reopen','withdraw') or not reason:
        raise ServiceError('请选择操作并填写处理理由')
    with db.transaction() as tx:
        sub=_submission_row(tx,sid)
        if sub['owner_username'].lower()==_username(user).lower():
            raise ServiceError('不能处理自己的投稿',status=403,code='self_review')
        appeal_open=tx.execute("SELECT 1 FROM curation_appeals WHERE submission_id=? AND status='open'",(sid,)).fetchone()
        if action!='withdraw' and not appeal_open:
            raise ServiceError('常态审核请进入参与审核；此入口仅处理申诉',status=409)
        now=_now()
        published=None
        rev=int(sub['current_revision'])
        if action=='approve':
            published=_publish_approved(tx,sub,rev)
            status='approved'
        elif action=='changes':
            status='changes_requested'
        elif action=='reopen':
            payload=_current_payload(tx,sid,rev)
            rev+=1
            tx.execute('INSERT INTO curation_versions (id,submission_id,revision,payload_json,created_at) VALUES (?,?,?,?,?)',(_uid(),sid,rev,json.dumps(payload,ensure_ascii=False),now))
            status='pending'
        else:
            status='withdrawn'
            table,key=('works','id') if sub['kind']=='work' else ('catalog_assets','code')
            tx.execute(f"UPDATE {table} SET status='withdrawn',updated_at=? WHERE {key}=?",(now,sub['target_id']))
        tx.execute("UPDATE curation_assignments SET status='stale' WHERE submission_id=? AND status='active'",(sid,))
        tx.execute('UPDATE curation_submissions SET status=?,current_revision=?,updated_at=? WHERE id=?',(status,rev,now,sid))
        tx.execute('INSERT INTO curation_admin_actions (id,submission_id,admin_username,action,reason,created_at) VALUES (?,?,?,?,?,?)',(_uid(),sid,user['username'],action,reason,now))
        tx.execute("UPDATE curation_appeals SET status='resolved' WHERE submission_id=? AND status='open'",(sid,))
        _event(tx,sid,user['username'],'admin_review',{'action':action,'reason':reason,'revision':rev})
        return {'ok':True,'submissionId':sid,'status':status,'revision':rev,'published':published}



# ---------------------------------------------------------------------------
# Admin overview and public previews
# ---------------------------------------------------------------------------

def _safe_user_list(tx: Any) -> list[dict[str, Any]]:
    rows = tx.execute("SELECT id, username, display_name, role, status FROM users ORDER BY id").fetchall()
    return [{"id": r["id"], "username": r["username"], "displayName": r["display_name"], "role": r["role"], "status": r["status"]} for r in rows]


def admin_overview(db: Database, user: dict[str, Any]) -> dict[str, Any]:
    if not _is_admin(user):
        raise ServiceError("仅管理员可查看", status=403, code="forbidden")
    with db.transaction() as tx:
        users = _safe_user_list(tx)
        access_rows = tx.execute("SELECT username, kind, paused, granted_by, reason, updated_at FROM curation_review_access ORDER BY username, kind").fetchall()
        records={(r['username'],r['kind']):dict(r) for r in access_rows}
        access=[]
        for person in users:
            for entry in _review_access_for(tx,person):
                if entry['eligible'] or entry['paused']:
                    access.append(dict(records.get((person['username'],entry['kind']),{}),username=person['username'],kind=entry['kind'],paused=entry['paused'],eligible=entry['eligible'],source=entry['source']))
        pending_rows = tx.execute(
            "SELECT * FROM curation_submissions WHERE status IN ('pending', 'changes_requested') ORDER BY created_at ASC"
        ).fetchall()
        pending = []
        for row in pending_rows:
            s = _row_to_dict(row) or {}
            pending.append(
                {
                    "id": s["id"],
                    "topicId": s["topic_id"],
                    "owner": s["owner_username"],
                    "kind": s["kind"],
                    "targetId": s["target_id"],
                    "status": s["status"],
                    "revision": int(s["current_revision"]),
                    "createdAt": s["created_at"],
                    "payload": _current_payload(tx, s["id"], int(s["current_revision"])),
                }
            )
        appeal_rows = tx.execute("SELECT * FROM curation_appeals ORDER BY created_at DESC").fetchall()
        appeals = [_row_to_dict(r) for r in appeal_rows]
        for entry in appeals:
            sub=_submission_row(tx,entry['submission_id'])
            entry.update(kind=sub['kind'],revision=sub['current_revision'],topicId=sub['topic_id'],payload=_current_payload(tx,sub['id'],sub['current_revision']))
        action_rows = tx.execute("SELECT * FROM curation_admin_actions ORDER BY created_at DESC LIMIT 200").fetchall()
        actions = [_row_to_dict(r) for r in action_rows]
    return {
        "ok": True,
        "users": users,
        "access": access,
        "pending": pending,
        "appeals": appeals,
        "adminActions": actions,
    }


def public_submissions(db: Database, topic_ids: Any) -> list[dict[str, Any]]:
    if isinstance(topic_ids, str):
        topic_ids = [topic_ids]
    if not isinstance(topic_ids, (list, tuple)):
        return []
    ids = [str(t) for t in topic_ids if str(t or "").strip()]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    out: list[dict[str, Any]] = []
    with db.transaction() as tx:
        rows = tx.execute(
            f"SELECT * FROM curation_submissions WHERE topic_id IN ({placeholders}) ORDER BY created_at",
            tuple(ids),
        ).fetchall()
        for row in rows:
            sub = _row_to_dict(row) or {}
            sid = sub["id"]
            rev = int(sub["current_revision"])
            payload = _current_payload(tx, sid, rev)
            status = sub["status"]
            # Definitions remain behind the normal resource/work entitlement API.
            votes = tx.execute(
                "SELECT reviewer_username, decision, reason, revision, created_at FROM curation_votes WHERE submission_id = ? ORDER BY created_at",
                (sid,),
            ).fetchall()
            out.append(
                {
                    "id": sid,
                    "topicId": sub["topic_id"],
                    "kind": sub["kind"],
                    "targetId": sub["target_id"],
                    "status": status,
                    "revision": rev,
                    "preview": _safe_preview(payload),
                    
                    "reviews": [
                        {
                            "reviewer": v["reviewer_username"],
                            "decision": v["decision"],
                            "reason": v["reason"],
                            "revision": int(v["revision"]),
                            "createdAt": v["created_at"],
                        }
                        for v in votes
                    ],
                }
            )
    return out

def _stable_target_id(kind: str, existing_seq_lookup: Any) -> str:
    """Deterministic-per-item stable final id assigned at submission time.

    style/layout: USR-S/USR-L + hex suffix (uppercase), or sequential if the
    router wants numbering; we use UUID suffix to avoid cross-tx races. Unlisted
    placeholders reuse this same id, so first publish and every revision UPSERT
    to the same key.
    work: work_<hex>.
    """
    suffix = uuid.uuid4().hex[:10].upper()
    if kind == "style":
        return f"USR-S{suffix}"
    if kind == "layout":
        return f"USR-L{suffix}"
    return f"work_{uuid.uuid4().hex[:16]}"


def _release_invalid_assignments(tx, reviewer=None, kind=None):
    from datetime import datetime, timezone, timedelta
    cutoff=(datetime.now(timezone.utc)-timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
    rows=tx.execute("SELECT a.*,s.kind,s.status AS sub_status,s.current_revision,s.owner_username,u.id AS uid,u.role,u.status AS user_status FROM curation_assignments a JOIN curation_submissions s ON s.id=a.submission_id LEFT JOIN users u ON u.username=a.reviewer_username WHERE a.status='active'").fetchall()
    access={}
    for r in rows:
        name=r['reviewer_username']
        if name not in access:
            access[name]=set(e['kind'] for e in _review_access_for(tx,{'id':r['uid'],'username':name,'role':r['role']}) if e['eligible']) if r['uid'] else set()
        if r['sub_status']!='pending' or r['revision']!=r['current_revision'] or r['user_status']!='active' or name==r['owner_username'] or r['kind'] not in access[name] or r['created_at']<cutoff:
            tx.execute("UPDATE curation_assignments SET status='released' WHERE id=?", (r['id'],))




def _sync_topic_preview(tx, topic_id):
    images=[]
    for r in tx.execute('SELECT id,current_revision FROM curation_submissions WHERE topic_id=?',(topic_id,)).fetchall():
        payload=_current_payload(tx,r['id'],r['current_revision'])
        for url in payload.get('images',[]):
            if url not in images:
                images.append(url)
    tx.execute('UPDATE forum_topics SET images_json=?,updated_at=? WHERE id=?',(json.dumps(images[:MAX_IMAGES],ensure_ascii=False),_now(),topic_id))


def _int(value):
    try:
        return int(value)
    except (ValueError,TypeError,OverflowError):
        raise ServiceError('价格必须是数字')

def _validate_references(tx,payload):
    if payload['kind']!='work':
        return
    from .resource_discussions import resolve_resource
    for code in payload.get('styles',[]):
        if not resolve_resource(tx,'style',code):
            raise ServiceError('画风不存在或尚未收录',status=400)
    if payload.get('layout') and not resolve_resource(tx,'layout',payload['layout']):
        raise ServiceError('图型不存在或尚未收录',status=400)


# ---------------------------------------------------------------------------
# Direct (immediate) work publishing
# ---------------------------------------------------------------------------
#
# Works publish immediately: the work row, its discussion topic and the mapping
# between them are written in one transaction, with no review vote in the path.
# Double-review stays for styles and layouts only, which enter the shared
# generation catalogue and therefore deserve a gate.  Keeping this separate from
# ``submit`` means the review pipeline is untouched for the kinds that still
# use it.

SHOWCASE_CATEGORY = "showcase"


def publish_work_direct(db: Database, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Publish one work immediately and return its canonical link.

    ``requestId`` is the idempotency key: replaying the same request returns the
    same work instead of creating a second one.
    """
    body = body or {}
    username = _username(user)
    uid = _user_id(user)
    request_id = _s(body.get("requestId"), 80)
    title = _s(body.get("title"), 140).strip()
    if not title:
        raise ServiceError("发布作品需要填写标题", status=400, code="title_required")
    prompt = str(body.get("prompt") or "")
    # The prompt is stored verbatim (only the length is bounded and the value
    # checked for blankness); the Skill promises the user's words survive intact.
    if len(prompt) > 20000:
        raise ServiceError("提示词过长", status=400, code="prompt_too_long")
    if not prompt.strip():
        raise ServiceError("发布作品需要填写提示词", status=400, code="prompt_required")

    raw_images = body.get("images") or ([body["image"]] if body.get("image") else [])
    if isinstance(raw_images, (list, tuple)) and len(raw_images) > 9:
        # Checked before cleaning: ``_clean_images`` dedupes and drops unsafe
        # entries, so a length test afterwards would silently truncate instead
        # of telling the caller (the skill contract forbids silent image loss).
        raise ServiceError("一次最多 9 张图片，请分批发布", status=400, code="too_many_images")
    images = _clean_images(raw_images)
    if not images:
        raise ServiceError("发布作品需要至少一张图片", status=400, code="image_required")

    styles = [str(s).strip().upper() for s in (body.get("styles") or []) if str(s).strip()]
    if len(styles) > 2:
        raise ServiceError("一件作品最多关联两个画风", status=400, code="too_many_styles")
    layout = str(body.get("layout") or "").strip().upper()

    # Price must be an integer credit amount; reject garbage instead of letting
    # int() raise and turn a validation error into a 500.
    raw_price = body.get("price")
    try:
        # ``int()`` accepts float('inf') and raises OverflowError on it, which
        # used to escape as a 500.  Reject non-finite numbers explicitly.
        if isinstance(raw_price, float) and (raw_price != raw_price or raw_price in (float("inf"), float("-inf"))):
            raise ValueError("non-finite price")
        price = int(raw_price) if raw_price not in (None, "") else 0
    except (TypeError, ValueError, OverflowError):
        raise ServiceError("作品定价必须是整数", status=400, code="invalid_price")
    if price < 0 or price > 100:
        raise ServiceError("作品定价需在 0 到 100 积分之间", status=400, code="price_out_of_range")

    now_iso = _now()
    now_ms = _now_ms()

    with db.transaction() as tx:
        # Idempotent replay.
        if request_id:
            dup = tx.execute(
                "SELECT id FROM works WHERE author_username = ? AND request_id = ?",
                (username, request_id),
            ).fetchone()
            if dup:
                wid = str(dup["id"])
                return _work_receipt(tx, wid, deduplicated=True)

        owner_row = tx.execute(
            "SELECT id, display_name, honor_override FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        display = str(owner_row["display_name"]) if owner_row else username

        _validate_references(tx, {"kind": "work", "styles": styles, "layout": layout})

        # Snapshot the pre-publish state *before* the row exists.  Computing it
        # afterwards silently swallowed the honour-tier upgrade on a user's first
        # work, because the new work already counted towards the tier.
        from .services import _count_user_published_items, compute_honor_tier

        honor_override = owner_row["honor_override"] if owner_row else None
        before_count = _count_user_published_items(tx, username)
        before_tier = int(compute_honor_tier(before_count, honor_override)["tier"])

        # Fork lineage is recorded only when the source work actually exists, so
        # a stale client link cannot create a dangling edge.
        forked_from = str(body.get("forkOf") or "").strip()
        if forked_from and not tx.execute(
            "SELECT 1 FROM works WHERE id = ? AND status = 'published'", (forked_from,)
        ).fetchone():
            forked_from = ""

        work_id = str(uuid.uuid4())
        tx.execute(
            """
            INSERT INTO works (
                id, author_username, author_name, title, images_json, styles_json,
                layout_code, color_code, tone_code, ratio, mode, mood, price, prompt, notes,
                status, featured, is_new_release, pioneer_rewarded, cheers, likes, favorites, forks,
                published_at_ms, created_label, created_at, updated_at, origin, request_id, forked_from_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', 0, 1, 0, 0, 0, 0, 0,
                      ?, '刚刚', ?, ?, ?, ?, ?)
            """,
            (
                work_id,
                username,
                display,
                title,
                json.dumps(images, ensure_ascii=False),
                json.dumps(styles, ensure_ascii=False),
                layout,
                body.get("color") or "C-15",
                body.get("tone") or "T-01",
                body.get("ratio") or "3:4",
                body.get("mode") or "graphic-text",
                body.get("mood") or "治愈",
                price,
                prompt,
                _s(body.get("notes"), 20000),
                now_ms,
                now_iso,
                now_iso,
                str(body.get("origin") or "web"),
                request_id,
                forked_from,
            ),
        )

        if forked_from:
            _record_fork(tx, forked_from, uid, body.get("generationId") or "", now_iso)

        topic_id = _ensure_work_topic(tx, work_id, username, display, title, images, styles, layout, now_iso, now_ms)
        tx.execute(
            "INSERT OR IGNORE INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('work', ?, ?, 'submission', ?)",
            (work_id, topic_id, now_iso),
        )
        reward_info = _reward_direct_work(
            tx, uid, username, work_id, title, styles, layout, images, now_iso,
            before_tier=before_tier, honor_override=honor_override,
        )
        return _work_receipt(tx, work_id, topic_id=topic_id, reward_info=reward_info)


def _record_fork(tx, parent_work_id: str, uid: int, generation_id: str, now_iso: str) -> None:
    """Deliberately does nothing.

    ``forkOf`` arrives from the client, so it cannot be trusted to write the
    ``work_forks`` fact table: five throwaway accounts could publish with
    ``forkOf`` set and then a single ``reconcile_social_counters`` run would
    turn them into five "real" forks.  Fork facts are written only by
    ``count_fork_if_new``, which the generation-completion path calls after a
    real image exists.  Lineage on the child work (``forked_from_id``) is still
    recorded by the caller, so the "复刻自" label keeps working.
    """
    return None


def count_fork_if_new(tx, parent_work_id: str, uid: int, generation_id: str, now_iso: str) -> int:
    """Book one fork and return the new cached count.

    Called from the generation-completion path, after a real image exists and
    the caller is not the parent's author.
    """
    row = tx.execute(
        "SELECT 1 FROM work_forks WHERE work_id = ? AND user_id = ?", (parent_work_id, int(uid))
    ).fetchone()
    if row:
        return int(
            tx.execute("SELECT forks FROM works WHERE id = ?", (parent_work_id,)).fetchone()["forks"]
        )
    tx.execute(
        "INSERT INTO work_forks (work_id, user_id, first_generation_id, created_at) VALUES (?, ?, ?, ?)",
        (parent_work_id, int(uid), str(generation_id or ""), now_iso),
    )
    forks = int(
        tx.execute("SELECT COUNT(*) FROM work_forks WHERE work_id = ?", (parent_work_id,)).fetchone()[0]
    )
    tx.execute("UPDATE works SET forks = ? WHERE id = ?", (forks, parent_work_id))
    return forks


def _reward_direct_work(
    tx, uid, username, work_id, title, styles, layout, images, now_iso,
    *, before_tier: int | None = None, honor_override: Any = None,
) -> None:
    """Apply the same publish reward a reviewed work would get, once per work.

    ``before_tier`` must be captured *before* the work row is inserted; passing
    it in keeps the honour-upgrade check meaningful.
    """
    from .services import _count_user_published_items, compute_honor_tier, compute_public_asset_counts_and_creators

    settings = get_site_settings(tx)
    econ = settings.get("economy", {})
    owner_row = tx.execute("SELECT id, honor_override FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
    owner_uid = int(owner_row["id"]) if owner_row else int(uid)
    override = honor_override if honor_override is not None else (owner_row["honor_override"] if owner_row else None)

    if before_tier is None:
        before_tier = int(compute_honor_tier(_count_user_published_items(tx, username), override)["tier"])
    counts = compute_public_asset_counts_and_creators(tx)[0]
    threshold = int(econ.get("pioneer_work_threshold", 3))
    refs = list(styles or []) + ([layout] if layout else [])
    pioneer = any(counts.get(code, 0) < threshold for code in refs) if refs else False

    reward = int(econ.get("work_publish_credits", 5)) + (
        int(econ.get("pioneer_bonus_credits", 10)) if pioneer else 0
    )
    balance, credited = apply_wallet_delta(
        tx,
        owner_uid,
        reward,
        "publish_work",
        f"发布实测作品《{title}》",
        event_key=f"pub_work_{work_id}",
        ref_type="work",
        ref_id=work_id,
    )
    if credited and pioneer:
        tx.execute("UPDATE works SET pioneer_rewarded=1 WHERE id=?", (work_id,))

    after_honor = compute_honor_tier(_count_user_published_items(tx, username), override)
    upgraded_badge = ""
    if after_honor["tier"] > before_tier:
        balance, honor_credited = apply_wallet_delta(
            tx,
            owner_uid,
            int(econ.get("honor_upgrade_credits", 10)),
            "honor_upgrade",
            f"创作者荣誉晋升至{after_honor['badge']}",
            event_key=f"honor_up_{owner_uid}_{after_honor['tier']}",
        )
        if honor_credited:
            upgraded_badge = str(after_honor["badge"])

    for url in images or []:
        media = tx.execute(
            "SELECT user_id FROM studio_generation_media WHERE media_url=? UNION SELECT user_id FROM user_uploads WHERE image_url=? LIMIT 1",
            (url, url),
        ).fetchone()
        if media and media[0] == owner_uid:
            tx.execute(
                "INSERT INTO media_public_grants (id,media_url,owner_user_id,target_type,target_id,granted_by_user_id,granted_at,revoked_at) VALUES (?,?,?,?,?,?,?,NULL) ON CONFLICT(media_url,target_type,target_id) DO UPDATE SET revoked_at=NULL,granted_at=excluded.granted_at",
                (_uid(), url, owner_uid, "work", work_id, owner_uid, now_iso),
            )

    return {
        "reward": reward if credited else 0,
        "pioneer": bool(pioneer and credited),
        "upgradedBadge": upgraded_badge,
    }


def _ensure_work_topic(tx, work_id, username, display, title, images, styles, layout, now_iso, now_ms) -> str:
    row = tx.execute(
        "SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?",
        (work_id,),
    ).fetchone()
    if row:
        return str(row["topic_id"])
    topic_id = f"topic_{now_ms}_{uuid.uuid4().hex[:4]}"
    tx.execute(
        """
        INSERT INTO forum_topics (
            id, category, category_label, pinned, featured, title, author_username, author_name,
            views, likes, favorites, price, bounty, bounty_status, solved, accepted_reply_id,
            images_json, styles_json, layout_code, work_id, recipe_json, summary, locked_body,
            status, published_at_ms, created_label, created_at, updated_at
        ) VALUES (?, ?, '🎨 晒作品', 0, 0, ?, ?, ?, 0, 0, 0, 0, 0, 'none', 0, '',
                  ?, ?, ?, ?, '', ?, '', 'published', ?, '刚刚', ?, ?)
        """,
        (
            topic_id,
            SHOWCASE_CATEGORY,
            title,
            username,
            display,
            json.dumps(images, ensure_ascii=False),
            json.dumps(styles, ensure_ascii=False),
            layout,
            work_id,
            "",
            now_ms,
            now_iso,
            now_iso,
        ),
    )
    return topic_id


def _work_receipt(
    tx,
    work_id: str,
    topic_id: str | None = None,
    deduplicated: bool = False,
    reward_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = tx.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
    work = _row_to_dict(row) or {}
    if topic_id is None:
        mapped = tx.execute(
            "SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?",
            (work_id,),
        ).fetchone()
        topic_id = str(mapped["topic_id"]) if mapped else ""
    owner = str(work.get("author_username") or "")
    credits = 0
    reward = 0
    if owner:
        owner_row = tx.execute(
            "SELECT w.balance AS balance FROM wallets w JOIN users u ON u.id = w.user_id WHERE u.username = ? COLLATE NOCASE",
            (owner,),
        ).fetchone()
        credits = int(owner_row["balance"]) if owner_row else 0
        ledger = tx.execute(
            "SELECT delta FROM ledgers WHERE event_key = ?",
            (f"pub_work_{work_id}",),
        ).fetchone()
        reward = int(ledger["delta"]) if ledger else 0
    info = reward_info or {}
    # ``reward`` covers the publish bonus only; the honour upgrade is a separate
    # payout, so the receipt names it explicitly instead of leaving the balance
    # increase unexplained.
    return {
        "ok": True,
        "workId": work_id,
        "topicId": topic_id,
        "status": work.get("status") or "published",
        "url": f"/forum/?view=resource&kind=work&id={work_id}",
        "reward": 0 if deduplicated else reward,
        "pioneer": False if deduplicated else bool(info.get("pioneer")),
        "upgradedBadge": "" if deduplicated else str(info.get("upgradedBadge") or ""),
        "credits": credits,
        "deduplicated": deduplicated,
    }
