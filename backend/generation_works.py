from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("handraw.generation_works")

CODE_RE = re.compile(r"^(?:USR-)?[A-Z]{1,4}-[A-Z0-9]+$", re.IGNORECASE)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def derive_item_key(item: Any, fallback_idx: int = 0) -> tuple[str, str]:
    """Derive deterministic item_key and clean image_url.

    Prioritizes persisted item ID. For legacy items without ID, allocates a
    stable key based on the image URL SHA-256 hash so array reordering cannot
    mutate the identity.
    """
    image_url = ""
    item_key = ""
    if isinstance(item, dict):
        image_url = str(item.get("imageUrl") or item.get("url") or "").strip()
        raw_id = item.get("id")
        if raw_id and str(raw_id).strip():
            item_key = str(raw_id).strip()
    elif isinstance(item, str):
        image_url = item.strip()

    if not item_key:
        if image_url:
            h = hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:16]
            item_key = f"img_{h}"
        else:
            item_key = f"item_{fallback_idx}"

    return item_key, image_url


def extract_generation_styles_and_layout(
    conn: sqlite3.Connection,
    row: sqlite3.Row | dict[str, Any],
    item: dict[str, Any] | None = None,
) -> tuple[list[str], str]:
    """Extract distinct style codes and single layout code from generation metadata."""
    styles: list[str] = []
    layout: str = ""

    # 1. From item recipeSnapshot if present
    if item and isinstance(item.get("recipeSnapshot"), dict):
        snap = item["recipeSnapshot"]
        s_list = snap.get("styles") or snap.get("style_ids") or []
        if isinstance(s_list, list):
            for s in s_list:
                c = str(s).strip().upper().lstrip("#")
                if CODE_RE.match(c) and c not in styles:
                    styles.append(c)
        l_code = str(snap.get("layout") or snap.get("layout_id") or "").strip().upper().lstrip("#")
        if CODE_RE.match(l_code):
            layout = l_code

    # 2. From studio_recipes if recipe_id is present
    row_keys = row.keys() if hasattr(row, "keys") else row
    recipe_id = str(row["recipe_id"] or "") if "recipe_id" in row_keys else ""
    if recipe_id:
        try:
            rcp = conn.execute("SELECT style_ids, layout_id FROM studio_recipes WHERE id = ?", (recipe_id,)).fetchone()
            if rcp:
                s_list = json.loads(rcp["style_ids"] or "[]")
                if isinstance(s_list, list):
                    for s in s_list:
                        c = str(s).strip().upper().lstrip("#")
                        if CODE_RE.match(c) and c not in styles:
                            styles.append(c)
                if not layout and rcp["layout_id"]:
                    l_code = str(rcp["layout_id"]).strip().upper().lstrip("#")
                    if CODE_RE.match(l_code):
                        layout = l_code
        except Exception:
            pass

    # 3. From recipe_summary regex
    summary = str(row["recipe_summary"] or "") if "recipe_summary" in row_keys else ""
    if summary:
        for m in re.finditer(r"#((?:USR-)?[A-Z]{1,4}-[A-Z0-9]+)", summary, re.IGNORECASE):
            c = m.group(1).upper()
            if c.startswith(("SC-", "IG-", "SB-", "IP-", "EC-", "LAY-", "USR-L")):
                if not layout:
                    layout = c
            else:
                if c not in styles:
                    styles.append(c)

    return styles, layout


def resolve_work_title(
    row: sqlite3.Row | dict[str, Any],
    item: dict[str, Any] | None = None,
) -> str:
    """Resolve public work title adhering to the 5-priority scheme in Issue #5."""
    # Priority 1: User explicitly edited title
    if item and isinstance(item, dict):
        custom = item.get("title")
        if custom and not re.match(r"^成图\s*#?\d+$", str(custom).strip()):
            return str(custom).strip()[:120]

    # Priority 2: Generation subject
    row_keys = row.keys() if hasattr(row, "keys") else row
    if item and isinstance(item, dict) and item.get("subject") and str(item["subject"]).strip():
        return str(item["subject"]).strip()[:120]

    if "subject" in row_keys and row["subject"] and str(row["subject"]).strip():
        return str(row["subject"]).strip()[:120]

    # Priority 3: Recipe snapshot subject
    if item and isinstance(item.get("recipeSnapshot"), dict):
        snap_subj = item["recipeSnapshot"].get("subject")
        if snap_subj and str(snap_subj).strip():
            return str(snap_subj).strip()[:120]

    # Priority 4: Article title from markdown
    if "markdown" in row_keys and row["markdown"]:
        m = re.search(r"^#\s+(.+)$", str(row["markdown"]), re.MULTILINE)
        if m and m.group(1).strip():
            return m.group(1).strip()[:120]

    # Priority 5: Fallback
    return "未命名作品"


def project_generation_to_works(
    conn: sqlite3.Connection,
    generation_id_or_row: str | sqlite3.Row | dict[str, Any],
    *,
    force_visibility: str | None = None,
) -> list[str]:
    """Project completed generation images into real works rows idempotently.

    - Validates generation success, non-empty items, and public visibility.
    - Creates or reuses mapping in generation_works (generation_id, item_key) -> work_id.
    - Preserves original generation timestamp published_at_ms (never uses backfill time).
    - Respects administrator moderation locks (never republishes admin-hidden works).
    - Never leaks internal prompt secrets or private recipes to public fields.
    """
    if isinstance(generation_id_or_row, str):
        row = conn.execute("SELECT * FROM studio_generations WHERE id = ?", (generation_id_or_row,)).fetchone()
    else:
        row = generation_id_or_row

    if not row:
        return []

    row_keys = row.keys() if hasattr(row, "keys") else row
    gen_id = str(row["id"])
    status = str(row["status"] or "")
    if status != "success":
        return []

    if "deleted_at" in row_keys and row["deleted_at"]:
        # Soft-deleted: ensure hidden
        sync_generation_visibility(conn, gen_id, "private", is_deleted=True)
        return []

    vis = force_visibility or (str(row["visibility"] or "public") if "visibility" in row_keys else "public")
    if vis != "public":
        # Private generation: ensure hidden
        sync_generation_visibility(conn, gen_id, "private", is_deleted=False)
        return []

    engine = str(row["engine"] or "") if "engine" in row_keys else ""
    if engine == "demo":
        return []

    raw_items_str = row["items_json"] if "items_json" in row_keys else "[]"
    try:
        raw_items = json.loads(raw_items_str or "[]")
    except Exception:
        raw_items = []

    if not isinstance(raw_items, list) or not raw_items:
        return []

    from .services import get_generation_visible_prompt, check_text_has_secret

    vis_prompt, was_masked = get_generation_visible_prompt(row)
    has_sec = False
    try:
        has_sec = check_text_has_secret(vis_prompt, conn)
    except Exception:
        pass
    prompt_has_secret = 1 if (was_masked or has_sec) else 0
    safe_prompt = "" if prompt_has_secret else vis_prompt

    created_at_iso = str(row["created_at"] or "") or utc_now_iso()
    try:
        dt = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
        published_at_ms = int(dt.timestamp() * 1000)
    except Exception:
        published_at_ms = int(time.time() * 1000)

    author_username = str(row["username"] or "")
    u_row = conn.execute("SELECT display_name FROM users WHERE username = ?", (author_username,)).fetchone()
    author_name = str(u_row["display_name"]) if u_row and u_row["display_name"] else author_username

    fork_work_id = str(row["fork_work_id"] or "") if "fork_work_id" in row_keys else ""
    subject = str(row["subject"] or "") if "subject" in row_keys else ""
    mode = str(row["mode"] or "graphic-text") if "mode" in row_keys else "graphic-text"

    projected_work_ids: list[str] = []

    for idx, raw_item in enumerate(raw_items):
        item_key, image_url = derive_item_key(raw_item, fallback_idx=idx)
        if not image_url:
            continue

        item_dict = raw_item if isinstance(raw_item, dict) else None

        # Check existing mapping
        mapping = conn.execute(
            "SELECT work_id FROM generation_works WHERE generation_id = ? AND item_key = ?",
            (gen_id, item_key),
        ).fetchone()

        if mapping:
            existing_wid = str(mapping["work_id"])
            # Ensure work still exists and check moderation status
            w_cur = conn.execute(
                "SELECT id, status, status_source, status_actor_role FROM works WHERE id = ?",
                (existing_wid,),
            ).fetchone()
            if w_cur:
                w_status = str(w_cur["status"] or "")
                w_source = str(w_cur["status_source"] or "")
                # Rule: Never re-publish works hidden by a moderator/admin!
                if w_status != "published" and w_source in ("moderator", "admin", "report"):
                    # Keep as-is, do not re-publish
                    projected_work_ids.append(existing_wid)
                    continue
                elif w_status != "published" and w_source == "generation":
                    # Was previously hidden by generation visibility, now public again
                    from .services import set_work_visibility
                    set_work_visibility(conn, existing_wid, "published", utc_now_iso(), automated=True)
            projected_work_ids.append(existing_wid)
            continue

        # Create new work row
        work_id = f"work_{uuid.uuid4().hex}"
        title = resolve_work_title(row, item_dict)
        styles, layout = extract_generation_styles_and_layout(conn, row, item_dict)
        ratio = str((item_dict.get("ratio") if item_dict else "") or "3:4")

        conn.execute(
            """
            INSERT INTO works (
                id, author_username, author_name, title, images_json, styles_json,
                layout_code, sc021_type, color_code, tone_code, ratio, mode,
                shoot_type, mood, price, prompt, notes, prompt_has_secret,
                status, featured, is_new_release, pioneer_rewarded, cheers,
                likes, favorites, forks, tips, views, stamp_counts_json,
                published_at_ms, created_label, created_at, updated_at,
                origin, request_id, forked_from_id, subject
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, '', 'C-15', 'T-01', ?, ?,
                '', '治愈', 0, ?, '', ?,
                'published', 0, 1, 0, 0,
                0, 0, 0, 0, 0, '{}',
                ?, '刚刚', ?, ?,
                'generation', '', ?, ?
            )
            """,
            (
                work_id,
                author_username,
                author_name,
                title,
                json.dumps([image_url], ensure_ascii=False),
                json.dumps(styles, ensure_ascii=False),
                layout,
                ratio,
                mode,
                safe_prompt,
                prompt_has_secret,
                published_at_ms,
                created_at_iso,
                created_at_iso,
                fork_work_id,
                subject,
            ),
        )

        conn.execute(
            """
            INSERT INTO generation_works (generation_id, item_key, work_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (gen_id, item_key, work_id, utc_now_iso()),
        )
        projected_work_ids.append(work_id)

    return projected_work_ids


def sync_generation_visibility(
    conn: sqlite3.Connection,
    generation_id: str,
    new_visibility: str,
    *,
    is_deleted: bool = False,
) -> None:
    """Synchronize generation visibility and deletion state to projected works."""
    from .services import set_work_visibility, utc_now_iso

    rows = conn.execute(
        "SELECT work_id FROM generation_works WHERE generation_id = ?",
        (generation_id,),
    ).fetchall()

    now_iso = utc_now_iso()

    if new_visibility != "public" or is_deleted:
        for r in rows:
            wid = str(r["work_id"])
            set_work_visibility(
                conn,
                wid,
                "hidden",
                now_iso,
                source="generation",
                reason="关联生成记录已设为私密或删除",
                automated=True,
            )
    else:
        # Became public
        project_generation_to_works(conn, generation_id, force_visibility="public")


def backfill_historical_generations(
    conn: sqlite3.Connection,
    *,
    batch_size: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Batch-backfill existing public generations into works idempotently.

    Supports resumption with cursor and returns detailed counts.
    """
    query = """
        SELECT *
        FROM studio_generations
        WHERE status = 'success'
          AND visibility = 'public'
          AND COALESCE(deleted_at, '') = ''
          AND items_json IS NOT NULL
          AND items_json != ''
          AND items_json != '[]'
          AND engine != 'demo'
    """
    params: list[Any] = []
    if cursor:
        query += " AND (created_at < ? OR (created_at = ? AND id < ?))"
        # cursor format: iso_time:id
        parts = cursor.split("::", 1)
        if len(parts) == 2:
            params.extend([parts[0], parts[0], parts[1]])

    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(batch_size + 1)

    rows = conn.execute(query, params).fetchall()

    has_more = len(rows) > batch_size
    batch_rows = rows[:batch_size]

    total_scanned = len(batch_rows)
    projected_count = 0
    next_cursor = None

    for row in batch_rows:
        wids = project_generation_to_works(conn, row)
        projected_count += len(wids)

    if has_more and batch_rows:
        last = batch_rows[-1]
        next_cursor = f"{last['created_at']}::{last['id']}"

    return {
        "ok": True,
        "scanned": total_scanned,
        "projected": projected_count,
        "hasMore": has_more,
        "nextCursor": next_cursor,
    }


def get_work_generation_provenance(conn: sqlite3.Connection, work_id: str) -> dict[str, Any] | None:
    """Return generation mapping provenance for a work if it originated from a generation."""
    row = conn.execute(
        """
        SELECT gw.generation_id, gw.item_key, gw.created_at, sg.subject, sg.mode, sg.engine
        FROM generation_works gw
        LEFT JOIN studio_generations sg ON sg.id = gw.generation_id
        WHERE gw.work_id = ?
        """,
        (work_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "generationId": row["generation_id"],
        "itemKey": row["item_key"],
        "createdAt": row["created_at"],
        "subject": row["subject"] or "",
        "mode": row["mode"] or "",
        "engine": row["engine"] or "",
    }
