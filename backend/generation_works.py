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


def _grant_work_media(
    conn: sqlite3.Connection,
    image_url: str,
    author_username: str,
    generation_id: str,
    work_id: str,
) -> None:
    """Make a published work's picture readable by anyone who can see the work."""
    url = str(image_url or "").split("?", 1)[0]
    if not url.startswith(("/generated/", "/uploads/")):
        return
    owner = conn.execute(
        "SELECT user_id FROM studio_generations WHERE id = ?", (generation_id,)
    ).fetchone()
    owner_id = int(owner["user_id"]) if owner and owner["user_id"] is not None else None
    if owner_id is None:
        u = conn.execute("SELECT id FROM users WHERE username = ?", (author_username,)).fetchone()
        owner_id = int(u["id"]) if u else None
    if owner_id is None:
        return
    conn.execute(
        """
        INSERT INTO media_public_grants
            (id, media_url, owner_user_id, generation_id, target_type, target_id,
             granted_by_user_id, granted_at, revoked_at)
        VALUES (?, ?, ?, ?, 'work', ?, ?, ?, NULL)
        ON CONFLICT(media_url, target_type, target_id) DO UPDATE SET revoked_at = NULL
        """,
        (
            f"grant_{uuid.uuid4().hex}",
            url,
            owner_id,
            generation_id,
            work_id,
            owner_id,
            utc_now_iso(),
        ),
    )


def _find_work_by_image(conn: sqlite3.Connection, image_url: str, author_username: str) -> str:
    """Return an existing work that already carries this picture, if any.

    Matching on the picture rather than on the generation is deliberate: the
    same file reaches works by two routes -- published from the writing desk and
    projected from history -- and only one of them may exist.
    """
    if not image_url:
        return ""
    rows = conn.execute(
        """
        SELECT id, images_json FROM works
        WHERE author_username = ? AND COALESCE(images_json, '') <> ''
        ORDER BY published_at_ms ASC
        """,
        (author_username,),
    ).fetchall()
    for r in rows:
        try:
            images = json.loads(r["images_json"] or "[]")
        except Exception:
            continue
        for im in images:
            url = im if isinstance(im, str) else (im.get("url") if isinstance(im, dict) else "")
            if url and url == image_url:
                return str(r["id"])
    return ""


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
                    w_status = "published"

                # Pre-build / ensure topic exists for public existing work
                if w_status == "published":
                    from .resource_discussions import ensure_topic
                    w_full = conn.execute("SELECT * FROM works WHERE id = ?", (existing_wid,)).fetchone()
                    if w_full:
                        ensure_topic(conn, "work", existing_wid, dict(w_full), initial_origin="generation")

            projected_work_ids.append(existing_wid)
            continue

        # The picture may already be a work because its author shared it before
        # this projection existed. Adopting that row keeps one picture one work;
        # creating another is exactly how a shared generation showed up twice.
        adopted = _find_work_by_image(conn, image_url, author_username)
        if adopted:
            conn.execute(
                "INSERT OR IGNORE INTO generation_works (generation_id, item_key, work_id, created_at) VALUES (?, ?, ?, ?)",
                (gen_id, item_key, adopted, utc_now_iso()),
            )
            w_full = conn.execute("SELECT * FROM works WHERE id = ?", (adopted,)).fetchone()
            if w_full and str(w_full["status"]) == "published":
                from .resource_discussions import ensure_topic
                ensure_topic(conn, "work", adopted, dict(w_full), initial_origin="generation")
            projected_work_ids.append(adopted)
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

        # Pre-build topic for newly created public work
        from .resource_discussions import ensure_topic
        new_w_full = conn.execute("SELECT * FROM works WHERE id = ?", (work_id,)).fetchone()
        if new_w_full:
            ensure_topic(conn, "work", work_id, dict(new_w_full), initial_origin="generation")

        # The picture is private media owned by its author, served only to them
        # until something grants it to a published target. Publishing the work
        # without granting meant everyone else -- and the author's own gallery
        # when viewed from another account -- got a broken image.
        _grant_work_media(conn, image_url, author_username, gen_id, work_id)

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


def backfill_work_topics(conn: sqlite3.Connection, *, batch_size: int = 100) -> dict[str, Any]:
    """Backfill missing topics for all published works (generations, web, legacy) and preserve listed states.

    Idempotent and safe:
      1. Preserves existing topics: ID, replies, moderation status, counters.
      2. Backfills listed_at_ms for historical published topics (status='published').
         Hidden/archived topics remain unlisted (listed_at_ms = NULL).
      3. Prebuilds unique topics for missing works across all origins with listed_at_ms = NULL.
      4. Records audit events in audit_logs so subsequent runs will never accidentally set listed_at_ms
         on unlisted works.
      5. Second execution produces 0 new topics and 0 listed status mutations.
    """
    from .resource_discussions import ensure_topic

    now_iso = utc_now_iso()
    in_tx = getattr(conn, "in_transaction", False)
    if not in_tx:
        conn.execute("BEGIN IMMEDIATE;")

    try:
        # 1. Backfill listed_at_ms on historical published topics (excluding unlisted prebuilds)
        legacy_candidates = conn.execute(
            """
            SELECT t.id, t.status, t.published_at_ms, t.created_at, t.listed_at_ms, t.work_id,
                   m.target_id AS mapped_work_id
            FROM forum_topics t
            LEFT JOIN curation_resource_topics m ON m.kind = 'work' AND m.topic_id = t.id
            WHERE ((t.work_id IS NOT NULL AND t.work_id <> '') OR m.target_id IS NOT NULL)
              AND t.status = 'published'
              AND t.listed_at_ms IS NULL
              AND t.id NOT IN (
                  SELECT target_id FROM audit_logs WHERE action = 'work.prebuild_unlisted_topic'
              )
            """
        ).fetchall()

        listed_backfilled = 0
        for t in legacy_candidates:
            wid = str(t["work_id"] or t["mapped_work_id"] or "").strip()
            w_cur = conn.execute("SELECT status FROM works WHERE id = ?", (wid,)).fetchone()
            if w_cur and str(w_cur["status"]) == "published":
                pub_ms = int(t["published_at_ms"] or 0)
                if pub_ms <= 0 and t["created_at"]:
                    try:
                        dt = datetime.fromisoformat(str(t["created_at"]).replace("Z", "+00:00"))
                        pub_ms = int(dt.timestamp() * 1000)
                    except Exception:
                        pub_ms = int(time.time() * 1000)
                if pub_ms <= 0:
                    pub_ms = int(time.time() * 1000)

                conn.execute(
                    "UPDATE forum_topics SET listed_at_ms = ? WHERE id = ? AND listed_at_ms IS NULL",
                    (pub_ms, t["id"]),
                )
                listed_backfilled += 1

        # 2. Iterate all published works (from all sources: generation, web, legacy)
        works = conn.execute(
            "SELECT w.* FROM works w WHERE w.status = 'published' ORDER BY w.published_at_ms ASC, w.id ASC"
        ).fetchall()

        created_topics: list[dict[str, Any]] = []
        already_had_topics = 0

        for w in works:
            wid = str(w["id"])
            t_row = conn.execute(
                "SELECT id, status, listed_at_ms FROM forum_topics WHERE work_id = ?",
                (wid,),
            ).fetchone()
            if not t_row:
                m_row = conn.execute(
                    "SELECT topic_id FROM curation_resource_topics WHERE kind = 'work' AND target_id = ?",
                    (wid,),
                ).fetchone()
                if m_row:
                    t_row = conn.execute(
                        "SELECT id, status, listed_at_ms FROM forum_topics WHERE id = ?",
                        (m_row["topic_id"],),
                    ).fetchone()

            if t_row:
                already_had_topics += 1
                conn.execute(
                    "INSERT OR IGNORE INTO curation_resource_topics (kind, target_id, topic_id, origin, created_at) VALUES ('work', ?, ?, 'submission', ?)",
                    (wid, t_row["id"], now_iso),
                )
                conn.execute(
                    "UPDATE forum_topics SET work_id = ? WHERE id = ? AND (work_id IS NULL OR work_id = '')",
                    (wid, t_row["id"]),
                )
            else:
                # Prebuild unlisted topic
                tid = ensure_topic(conn, "work", wid, dict(w), initial_origin="submission", listed_at_ms=None)
                try:
                    conn.execute(
                        """
                        INSERT INTO audit_logs (
                            actor_id, actor_username, actor_role, action, target_type, target_id,
                            reason, details_json, created_at
                        ) VALUES (NULL, 'system', 'system', 'work.prebuild_unlisted_topic', 'topic', ?, ?, ?, ?)
                        """,
                        (
                            tid,
                            f"Prebuilt unlisted topic {tid} for work {wid}",
                            json.dumps({"work_id": wid, "topic_id": tid}, ensure_ascii=False),
                            now_iso,
                        ),
                    )
                except Exception as audit_err:
                    logger.warning("Failed to record audit log for prebuilt topic %s: %s", tid, audit_err)

                created_topics.append(
                    {
                        "work_id": wid,
                        "topic_id": tid,
                        "origin": str(w["origin"] if "origin" in w.keys() else "legacy"),
                        "title": str(w["title"] if "title" in w.keys() else ""),
                    }
                )

        if not in_tx:
            conn.execute("COMMIT;")
    except Exception:
        if not in_tx and getattr(conn, "in_transaction", False):
            conn.execute("ROLLBACK;")
        raise

    return {
        "ok": True,
        "total_published_works": len(works),
        "already_had_topics": already_had_topics,
        "created_topics_count": len(created_topics),
        "listed_backfilled_count": listed_backfilled,
        "created_manifest": created_topics,
    }
