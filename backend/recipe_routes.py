"""Studio recipes, prompt preview, and snapshot from work (Phase 3a-2).

Implements:
- 060 studio_recipes table CRUD with user_id scoping (S3).
- Optimistic concurrency control via revision and baseRevision (409 on conflict).
- S9 parameter and prompt synchronization (customized/stale states).
- Prompt preview with Skill prompter and daily_usage(scope='prompt', limit=100) (not holding write lock).
- Work snapshot draft (/api/studio/recipes/from-work/{workId}).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from typing import Any

from .db import Database, utc_now_iso
from .resource_discussions import resolve_resource
from .services import ServiceError, consume_daily_usage

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_RATIO_PATTERN = re.compile(r"^\d+(?:\.\d+)?:\d+(?:\.\d+)?$")


def compute_input_fingerprint(
    style_ids: list[str],
    layout_id: str,
    colors: list[str],
    tones: list[str],
    moods: list[str],
    whitespace: str,
    ratio: str,
    mode: str,
    subject: str,
) -> str:
    """Compute a canonical deterministic hash of prompt-affecting parameters."""
    canonical = {
        "style_ids": [s.strip().upper() for s in style_ids if s.strip()],
        "layout_id": (layout_id or "").strip().upper(),
        "colors": [c.strip() for c in colors if c.strip()],
        "tones": [t.strip().upper() for t in tones if t.strip()],
        "moods": [m.strip() for m in moods if m.strip()],
        "whitespace": (whitespace or "").strip(),
        "ratio": (ratio or "3:4").strip(),
        "mode": (mode or "graphic-text").strip(),
        "subject": (subject or "").strip(),
    }
    dumped = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()[:32]


def _clean_string_list(
    raw: Any,
    field_name: str,
    max_count: int,
    pattern: re.Pattern | None = None,
    item_max_len: int = 32,
    to_upper: bool = False,
) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [s.strip() for s in raw.split(",") if s.strip()]
    elif isinstance(raw, (list, tuple)):
        items = [str(s).strip() for s in raw if str(s).strip()]
    else:
        raise ServiceError(f"{field_name} 必须是数组", status=400, code=f"invalid_{field_name}")

    if len(items) > max_count:
        raise ServiceError(f"{field_name} 数量不能超过 {max_count}", status=400, code=f"too_many_{field_name}")

    cleaned: list[str] = []
    for item in items:
        val = item.upper() if to_upper else item
        if len(val) > item_max_len:
            raise ServiceError(f"{field_name} 项长度过长", status=400, code=f"invalid_{field_name}")
        if pattern and not pattern.fullmatch(val):
            raise ServiceError(f"无效的 {field_name} 格式: {item}", status=400, code=f"invalid_{field_name}")
        cleaned.append(val)
    return cleaned


def validate_recipe_media(db: Database, uid: int, raw_refs: Any) -> list[str]:
    """Validate reference media ownership using _media_owner."""
    if raw_refs is None:
        return []
    if not isinstance(raw_refs, (list, tuple)):
        raise ServiceError("references 必须是数组", status=400, code="invalid_references")
    if len(raw_refs) > 6:
        raise ServiceError("最多选择 6 张参考图", status=400, code="too_many_references")

    from .server import _media_owner, sanitize_media_url

    clean_refs: list[str] = []
    for item in raw_refs:
        if isinstance(item, str):
            raw_url = item.strip()
        elif isinstance(item, dict):
            raw_url = str(item.get("url") or item.get("src") or item.get("image") or "").strip()
        else:
            continue

        if not raw_url:
            continue

        safe = sanitize_media_url(raw_url)
        if not safe:
            continue

        if safe.startswith(("/uploads/", "/generated/")):
            owner = _media_owner(db, safe)
            if owner is not None and owner != uid:
                raise ServiceError("不能使用他人的图片作为参考图", status=403, code="foreign_media")

        clean_refs.append(safe)

    return clean_refs


def validate_recipe_fields(db: Database, uid: int, body: dict[str, Any], existing: sqlite3.Row | None = None) -> dict[str, Any]:
    """Validate and normalize all recipe parameters."""
    kind = str(body.get("kind") if body.get("kind") is not None else (existing["kind"] if existing else "single")).strip()
    if kind not in ("single", "batch", "article_card"):
        raise ServiceError("无效的配方类型 (kind 需为 single, batch 或 article_card)", status=400, code="invalid_kind")

    # style_ids / styleIds
    raw_styles = body.get("styleIds") if body.get("styleIds") is not None else body.get("style_ids")
    if raw_styles is None and existing:
        styles = json.loads(existing["style_ids"] or "[]")
    else:
        styles = _clean_string_list(raw_styles, "styleIds", max_count=2, pattern=_ID_PATTERN, to_upper=True)

    # layout_id / layoutId
    raw_layout = body.get("layoutId") if body.get("layoutId") is not None else body.get("layout_id")
    if raw_layout is None and existing:
        layout_id = str(existing["layout_id"] or "")
    else:
        layout_id = str(raw_layout or "").strip().upper()
        if layout_id and not _ID_PATTERN.fullmatch(layout_id):
            raise ServiceError("无效的图型编号格式", status=400, code="invalid_layout_id")

    # colors / color
    raw_colors = body.get("colors") if body.get("colors") is not None else body.get("color")
    if raw_colors is None and existing:
        colors = json.loads(existing["colors"] or "[]")
    else:
        colors = _clean_string_list(raw_colors, "colors", max_count=5)

    # tones / tone
    raw_tones = body.get("tones") if body.get("tones") is not None else body.get("tone")
    if raw_tones is None and existing:
        tones = json.loads(existing["tones"] or "[]")
    else:
        tones = _clean_string_list(raw_tones, "tones", max_count=5, pattern=_ID_PATTERN, to_upper=True)

    # moods / mood
    raw_moods = body.get("moods") if body.get("moods") is not None else body.get("mood")
    if raw_moods is None and existing:
        moods = json.loads(existing["moods"] or "[]")
    else:
        moods = _clean_string_list(raw_moods, "moods", max_count=5, item_max_len=32)

    # whitespace
    raw_ws = body.get("whitespace")
    if raw_ws is None and existing:
        whitespace = str(existing["whitespace"] or "")
    else:
        whitespace = str(raw_ws or "").strip()
        if len(whitespace) > 32:
            raise ServiceError("留白参数过长", status=400, code="invalid_whitespace")

    # ratio
    raw_ratio = body.get("ratio")
    if raw_ratio is None and existing:
        ratio = str(existing["ratio"] or "3:4")
    else:
        ratio = str(raw_ratio or "3:4").strip()
        if not _RATIO_PATTERN.fullmatch(ratio) or len(ratio) > 16:
            raise ServiceError("无效的比例格式", status=400, code="invalid_ratio")

    # mode
    raw_mode = body.get("mode")
    if raw_mode is None and existing:
        mode = str(existing["mode"] or "graphic-text")
    else:
        mode = str(raw_mode or "graphic-text").strip()
        if len(mode) > 32:
            raise ServiceError("模式参数过长", status=400, code="invalid_mode")

    # subject / theme
    raw_subject = body.get("subject") if body.get("subject") is not None else body.get("theme")
    if raw_subject is None and existing:
        subject = str(existing["subject"] or "")
    else:
        subject = str(raw_subject or "").strip()
        if len(subject) > 2000:
            raise ServiceError("主题内容过长（最多2000字）", status=400, code="subject_too_long")

    # prompt
    raw_prompt = body.get("prompt")
    if raw_prompt is None and existing:
        prompt = str(existing["prompt"] or "")
    else:
        prompt = str(raw_prompt or "").strip()
        if len(prompt) > 4000:
            raise ServiceError("提示词过长（最多4000字）", status=400, code="prompt_too_long")

    # references / refImages / references_json
    raw_refs = (
        body.get("references")
        if body.get("references") is not None
        else (body.get("refImages") if body.get("refImages") is not None else body.get("references_json"))
    )
    if raw_refs is None and existing:
        references = json.loads(existing["references_json"] or "[]")
    else:
        references = validate_recipe_media(db, uid, raw_refs)

    return {
        "kind": kind,
        "style_ids": styles,
        "layout_id": layout_id,
        "colors": colors,
        "tones": tones,
        "moods": moods,
        "whitespace": whitespace,
        "ratio": ratio,
        "mode": mode,
        "subject": subject,
        "prompt": prompt,
        "references": references,
    }


def format_recipe(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """Format recipe database row into API client response shape."""
    style_ids = json.loads(row["style_ids"] or "[]") if isinstance(row["style_ids"], str) else (row["style_ids"] or [])
    colors = json.loads(row["colors"] or "[]") if isinstance(row["colors"], str) else (row["colors"] or [])
    tones = json.loads(row["tones"] or "[]") if isinstance(row["tones"], str) else (row["tones"] or [])
    moods = json.loads(row["moods"] or "[]") if isinstance(row["moods"], str) else (row["moods"] or [])
    refs = json.loads(row["references_json"] or "[]") if isinstance(row["references_json"], str) else (row["references_json"] or [])
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "kind": row["kind"],
        "styleIds": style_ids,
        "layoutId": row["layout_id"] or "",
        "colors": colors,
        "tones": tones,
        "moods": moods,
        "whitespace": row["whitespace"] or "",
        "ratio": row["ratio"] or "3:4",
        "mode": row["mode"] or "graphic-text",
        "subject": row["subject"] or "",
        "references": refs,
        "prompt": row["prompt"] or "",
        "promptCustomized": bool(row["prompt_customized"]),
        "promptStale": bool(row["prompt_stale"]),
        "revision": int(row["revision"]),
        "inputFingerprint": row["input_fingerprint"] or "",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def create_recipe(db: Database, user: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Create a new recipe for authenticated user."""
    uid = int(user["id"])
    norm = validate_recipe_fields(db, uid, body)
    fp = compute_input_fingerprint(
        norm["style_ids"],
        norm["layout_id"],
        norm["colors"],
        norm["tones"],
        norm["moods"],
        norm["whitespace"],
        norm["ratio"],
        norm["mode"],
        norm["subject"],
    )
    prompt = norm["prompt"]
    if "promptCustomized" in body:
        prompt_customized = 1 if body["promptCustomized"] else 0
    elif "prompt_customized" in body:
        prompt_customized = 1 if body["prompt_customized"] else 0
    else:
        prompt_customized = 1 if prompt else 0
    prompt_stale = 0
    recipe_id = f"rcp_{uuid.uuid4().hex[:12]}"
    now = utc_now_iso()

    with db.transaction() as tx:
        tx.execute(
            """
            INSERT INTO studio_recipes (
                id, user_id, kind, style_ids, layout_id, colors, tones, moods,
                whitespace, ratio, mode, subject, references_json, prompt,
                prompt_customized, prompt_stale, revision, input_fingerprint,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (
                recipe_id,
                uid,
                norm["kind"],
                json.dumps(norm["style_ids"], ensure_ascii=False),
                norm["layout_id"],
                json.dumps(norm["colors"], ensure_ascii=False),
                json.dumps(norm["tones"], ensure_ascii=False),
                json.dumps(norm["moods"], ensure_ascii=False),
                norm["whitespace"],
                norm["ratio"],
                norm["mode"],
                norm["subject"],
                json.dumps(norm["references"], ensure_ascii=False),
                prompt,
                prompt_customized,
                prompt_stale,
                fp,
                now,
                now,
            ),
        )
        row = tx.execute("SELECT * FROM studio_recipes WHERE id = ?", (recipe_id,)).fetchone()

    return {"ok": True, "id": recipe_id, "revision": 0, "recipe": format_recipe(row)}


def get_recipe(db: Database, user: dict[str, Any], recipe_id: str) -> dict[str, Any]:
    """Get single recipe with user_id scoping (S3)."""
    uid = int(user["id"])
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM studio_recipes WHERE id = ? AND user_id = ?", (recipe_id, uid)).fetchone()
    if not row:
        raise ServiceError("配方不存在", status=404, code="recipe_not_found")
    return {"ok": True, "recipe": format_recipe(row)}


def list_recipes(
    db: Database,
    user: dict[str, Any],
    kind: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List recipes for user with pagination and optional kind filter."""
    uid = int(user["id"])
    limit = max(1, min(50, limit))
    params: list[Any] = [uid]
    where_parts = ["user_id = ?"]

    if kind:
        where_parts.append("kind = ?")
        params.append(kind)

    if cursor:
        parts = cursor.split("|", 1)
        if len(parts) == 2:
            where_parts.append("(updated_at < ? OR (updated_at = ? AND id < ?))")
            params.extend([parts[0], parts[0], parts[1]])

    sql = f"""
        SELECT * FROM studio_recipes
        WHERE {' AND '.join(where_parts)}
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
    """
    params.append(limit + 1)

    conn = db.get_conn()
    rows = conn.execute(sql, params).fetchall()

    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = f"{last['updated_at']}|{last['id']}"
        rows = rows[:limit]

    return {"ok": True, "items": [format_recipe(r) for r in rows], "nextCursor": next_cursor}


def update_recipe(db: Database, user: dict[str, Any], recipe_id: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Update recipe with optimistic lock (baseRevision) and S9 state sync.

    Returns (response_dict, status_code).
    """
    uid = int(user["id"])
    base_revision = body.get("baseRevision")
    if base_revision is None:
        raise ServiceError("缺少 baseRevision 参数", status=400, code="base_revision_required")

    try:
        base_rev_int = int(base_revision)
    except (ValueError, TypeError):
        raise ServiceError("baseRevision 必须是整数", status=400, code="invalid_base_revision")

    with db.transaction() as tx:
        existing = tx.execute("SELECT * FROM studio_recipes WHERE id = ? AND user_id = ?", (recipe_id, uid)).fetchone()
        if not existing:
            raise ServiceError("配方不存在", status=404, code="recipe_not_found")

        if int(existing["revision"]) != base_rev_int:
            return {
                "ok": False,
                "error": "配方已被修改，请刷新后重试",
                "code": "conflict",
                "revision": int(existing["revision"]),
                "recipe": format_recipe(existing),
            }, 409

        norm = validate_recipe_fields(db, uid, body, existing=existing)
        new_fp = compute_input_fingerprint(
            norm["style_ids"],
            norm["layout_id"],
            norm["colors"],
            norm["tones"],
            norm["moods"],
            norm["whitespace"],
            norm["ratio"],
            norm["mode"],
            norm["subject"],
        )

        old_fp = str(existing["input_fingerprint"] or "")
        params_changed = (new_fp != old_fp)
        old_customized = bool(existing["prompt_customized"])
        old_prompt = str(existing["prompt"] or "")

        # S9: Check whether user manually edited prompt
        if "prompt" in body and str(body["prompt"]).strip() != old_prompt.strip():
            final_prompt = str(body["prompt"])[:4000].strip()
            prompt_customized = 1
            prompt_stale = 0
        elif params_changed:
            if not old_customized:
                final_prompt = ""
                prompt_customized = 0
                prompt_stale = 0
            else:
                final_prompt = old_prompt
                prompt_customized = 1
                prompt_stale = 1
        else:
            final_prompt = old_prompt
            prompt_customized = 1 if old_customized else 0
            prompt_stale = 1 if bool(existing["prompt_stale"]) else 0

        now = utc_now_iso()
        cur = tx.execute(
            """
            UPDATE studio_recipes
            SET kind = ?, style_ids = ?, layout_id = ?, colors = ?, tones = ?, moods = ?,
                whitespace = ?, ratio = ?, mode = ?, subject = ?, references_json = ?,
                prompt = ?, prompt_customized = ?, prompt_stale = ?, revision = revision + 1,
                input_fingerprint = ?, updated_at = ?
            WHERE id = ? AND user_id = ? AND revision = ?
            """,
            (
                norm["kind"],
                json.dumps(norm["style_ids"], ensure_ascii=False),
                norm["layout_id"],
                json.dumps(norm["colors"], ensure_ascii=False),
                json.dumps(norm["tones"], ensure_ascii=False),
                json.dumps(norm["moods"], ensure_ascii=False),
                norm["whitespace"],
                norm["ratio"],
                norm["mode"],
                norm["subject"],
                json.dumps(norm["references"], ensure_ascii=False),
                final_prompt,
                prompt_customized,
                prompt_stale,
                new_fp,
                now,
                recipe_id,
                uid,
                base_rev_int,
            ),
        )
        if cur.rowcount == 0:
            current = tx.execute("SELECT * FROM studio_recipes WHERE id = ? AND user_id = ?", (recipe_id, uid)).fetchone()
            if not current:
                raise ServiceError("配方不存在", status=404, code="recipe_not_found")
            return {
                "ok": False,
                "error": "配方已被修改，请刷新后重试",
                "code": "conflict",
                "revision": int(current["revision"]),
                "recipe": format_recipe(current),
            }, 409

        updated = tx.execute("SELECT * FROM studio_recipes WHERE id = ?", (recipe_id,)).fetchone()
        return {"ok": True, "revision": base_rev_int + 1, "recipe": format_recipe(updated)}, 200


def preview_recipe_prompt(db: Database, user: dict[str, Any], recipe_id: str) -> tuple[dict[str, Any], int]:
    """Generate prompt preview outside transaction and update with revision condition."""
    uid = int(user["id"])

    # 1. Fetch recipe and enforce user scope
    conn = db.get_conn()
    recipe = conn.execute("SELECT * FROM studio_recipes WHERE id = ? AND user_id = ?", (recipe_id, uid)).fetchone()
    if not recipe:
        raise ServiceError("配方不存在", status=404, code="recipe_not_found")

    # 2. Rate limiting (100 times/day per user)
    if not consume_daily_usage(db, uid, "prompt", limit=100):
        raise ServiceError("今日提示词预览次数已达上限（每天 100 次），请明天再试", status=429, code="daily_quota_exceeded")

    current_revision = int(recipe["revision"])

    # 3. Model call outside transaction (AI call does NOT hold DB write lock)
    style_ids = json.loads(recipe["style_ids"] or "[]")
    style_code = style_ids[0] if len(style_ids) > 0 else ""
    style2_code = style_ids[1] if len(style_ids) > 1 else ""
    layout_code = str(recipe["layout_id"] or "")
    colors = json.loads(recipe["colors"] or "[]")
    colour = colors[0] if colors else ""
    theme = str(recipe["subject"] or "")
    tones = json.loads(recipe["tones"] or "[]")
    moods = json.loads(recipe["moods"] or "[]")
    whitespace = str(recipe["whitespace"] or "")
    ratio = str(recipe["ratio"] or "3:4")
    mode = str(recipe["mode"] or "graphic-text")

    from . import skill_prompt

    composed = skill_prompt.compose_prompt(
        style_code,
        layout_code,
        colour,
        theme,
        style2_code=style2_code,
        colors=colors,
        tones=tones,
        moods=moods,
        whitespace=whitespace,
        ratio=ratio,
        mode=mode,
    )
    generated_prompt = str(composed.get("prompt") or "").strip()[:4000]
    source = str(composed.get("source") or "model")

    # 4. Short transaction: write back prompt with revision check
    now = utc_now_iso()
    with db.transaction() as tx:
        cur = tx.execute(
            """
            UPDATE studio_recipes
            SET prompt = ?, prompt_customized = 0, prompt_stale = 0, revision = revision + 1, updated_at = ?
            WHERE id = ? AND user_id = ? AND revision = ?
            """,
            (generated_prompt, now, recipe_id, uid, current_revision),
        )
        if cur.rowcount == 0:
            current = tx.execute("SELECT * FROM studio_recipes WHERE id = ? AND user_id = ?", (recipe_id, uid)).fetchone()
            if not current:
                raise ServiceError("配方不存在", status=404, code="recipe_not_found")
            return {
                "ok": False,
                "error": "配方已被修改，请刷新后重试",
                "code": "conflict",
                "revision": int(current["revision"]),
                "recipe": format_recipe(current),
            }, 409

    return {"ok": True, "prompt": generated_prompt, "revision": current_revision + 1, "source": source}, 200


def draft_recipe_from_work(
    db: Database,
    user: dict[str, Any],
    work_id: str,
    image_index: int | None = None,
) -> dict[str, Any]:
    """Build a form draft from the selected image in a visible public work.

    A V3 work may contain multiple images with different recipes. Use the
    canonical image order and its matching generation snapshot, never the
    first image/cover's styles for a different image. The response contains
    only public resource codes and a sanitized subject, never a black-box prompt.
    """
    conn = db.get_conn()
    work = resolve_resource(conn, "work", work_id)
    if not work:
        raise ServiceError("作品不存在或不可见", status=404, code="work_not_found")

    from .forum_resources import _unlocked
    from .services import _serialize_work

    unlocked_set = _unlocked(db, user)
    serialized = _serialize_work(work, {}, unlocked_set, user)
    run_id = str(work.get("run_id") or "")
    if run_id:
        from .generation_v3 import work_images
        image_urls = work_images(conn, work_id)
    else:
        raw_images = serialized.get("images") or []
        image_urls = [
            str(img if isinstance(img, str) else (img.get("url") or ""))
            for img in raw_images if isinstance(img, (str, dict))
        ]
        image_urls = [url for url in image_urls if url]

    if image_index is not None and (image_index < 0 or image_index >= len(image_urls)):
        raise ServiceError("所选作品图片不存在", status=400, code="invalid_fork_image")

    if image_index is None:
        image_index = 0
        if run_id and work.get("cover_media_id"):
            cover = conn.execute(
                "SELECT storage_key FROM media_assets WHERE id=?",
                (work["cover_media_id"],),
            ).fetchone()
            if cover and str(cover["storage_key"]) in image_urls:
                image_index = image_urls.index(str(cover["storage_key"]))

    subject_hint = str(serialized.get("subject") or "").strip()[:80]
    if not subject_hint and not serialized.get("promptMasked"):
        raw_prompt = str(serialized.get("prompt") or "").strip()
        sentences = [part.strip() for part in re.split(r"[。！？\n.!?]", raw_prompt) if part.strip()]
        subject_hint = sentences[0][:80] if sentences else ""
    if not subject_hint and not serialized.get("promptMasked"):
        # Only use the public title for an unmasked work. The existing
        # black-box contract requires an empty hint on masked works.
        subject_hint = str(serialized.get("title") or "").strip()[:80]

    raw_styles = work.get("styles_json") or "[]"
    try:
        style_ids = json.loads(raw_styles) if isinstance(raw_styles, str) else list(raw_styles)
    except (ValueError, TypeError):
        style_ids = []
    style_ids = [str(code) for code in style_ids if isinstance(code, str)]
    layout_code = str(work.get("layout_code") or "")

    asset_scope = "work"
    if run_id and image_urls:
        from .generation_works import generation_image_assets
        snapshots = generation_image_assets(conn, work, image_urls)
        if snapshots:
            selected = snapshots[image_index]
            asset_scope = selected.get("scope") or "missing"
            # A recorded, but empty, per-image snapshot is explicitly missing;
            # it must not inherit the first picture's work-level metadata.
            style_ids = selected.get("styles") or []
            layout_code = str(selected.get("layout") or "")

    color_code = str(work.get("color_code") or "")
    tone_code = str(work.get("tone_code") or "")
    mood = str(work.get("mood") or "")
    return {
        "ok": True,
        "draft": {
            "kind": "single",
            "styleIds": style_ids,
            "layoutId": layout_code,
            "colors": [color_code] if color_code else [],
            "tones": [tone_code] if tone_code else [],
            "moods": [mood] if mood else [],
            "whitespace": "",
            "ratio": str(work.get("ratio") or "3:4"),
            "mode": str(work.get("mode") or "graphic-text"),
            "subject": "",
            "subjectHint": subject_hint,
            "references": [],
            "prompt": "",
            "promptCustomized": False,
            "promptStale": False,
            "source": {
                "workId": work_id,
                "author": str(serialized.get("author") or ""),
                "authorName": str(serialized.get("authorName") or ""),
                "imageIndex": image_index,
                "assetScope": asset_scope,
            },
        },
    }


def handle_recipe_get(handler: Any, req_path: str, query: dict[str, list[str]]) -> bool:
    """Handle GET /api/studio/recipes... requests."""
    # 1. GET /api/studio/recipes/from-work/{workId}
    m_from_work = re.match(r"^/api/studio/recipes/from-work/([^/]+)$", req_path)
    if m_from_work:
        user = handler._current_user(required=True)
        work_id = m_from_work.group(1)
        index_values = query.get("image", [])
        image_index = None
        if index_values:
            raw_index = str(index_values[0]).strip()
            if not re.fullmatch(r"0|[1-9][0-9]{0,5}", raw_index):
                raise ServiceError("无效的作品图片序号", status=400, code="invalid_fork_image")
            image_index = int(raw_index)
        res = draft_recipe_from_work(handler.db, user, work_id, image_index=image_index)
        handler._send_json(res)
        return True

    # 2. GET /api/studio/recipes/{id}
    m_id = re.match(r"^/api/studio/recipes/([^/]+)$", req_path)
    if m_id:
        user = handler._current_user(required=True)
        recipe_id = m_id.group(1)
        res = get_recipe(handler.db, user, recipe_id)
        handler._send_json(res)
        return True

    # 3. GET /api/studio/recipes
    if req_path in ("/api/studio/recipes", "/api/studio/recipes/"):
        user = handler._current_user(required=True)
        kind = query.get("kind", [None])[0]
        cursor = query.get("cursor", [None])[0]
        limit_str = query.get("limit", ["20"])[0]
        try:
            limit = int(limit_str)
        except (ValueError, TypeError):
            limit = 20
        res = list_recipes(handler.db, user, kind=kind, cursor=cursor, limit=limit)
        handler._send_json(res)
        return True

    return False


def handle_recipe_post(handler: Any, req_path: str, body: dict[str, Any]) -> bool:
    """Handle POST /api/studio/recipes... requests."""
    # 1. POST /api/studio/recipes/{id}/prompt
    m_prompt = re.match(r"^/api/studio/recipes/([^/]+)/prompt$", req_path)
    if m_prompt:
        user = handler._current_user(required=True)
        recipe_id = m_prompt.group(1)
        res, status = preview_recipe_prompt(handler.db, user, recipe_id)
        handler._send_json(res, status=status)
        return True

    # 2. POST /api/studio/recipes
    if req_path in ("/api/studio/recipes", "/api/studio/recipes/"):
        user = handler._current_user(required=True)
        res = create_recipe(handler.db, user, body)
        handler._send_json(res, status=201)
        return True

    return False


def handle_recipe_put(handler: Any, req_path: str, body: dict[str, Any]) -> bool:
    """Handle PUT /api/studio/recipes/{id} requests."""
    m_id = re.match(r"^/api/studio/recipes/([^/]+)$", req_path)
    if m_id:
        user = handler._current_user(required=True)
        recipe_id = m_id.group(1)
        res, status = update_recipe(handler.db, user, recipe_id, body)
        handler._send_json(res, status=status)
        return True

    return False
