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


def project_generation_to_works(
    conn: sqlite3.Connection,
    generation_id_or_row: str | sqlite3.Row | dict[str, Any],
    *,
    force_visibility: str | None = None,
) -> list[str]:
    """Atomically project one logical run regardless of the caller's context.

    A SAVEPOINT works both inside a surrounding DB.transaction() and when a
    maintenance/test caller invokes the projector directly on an autocommit
    connection. Partial published works/media/grants cannot escape on failure.
    """
    sp = f"v3_project_{uuid.uuid4().hex[:12]}"
    conn.execute(f"SAVEPOINT {sp}")
    try:
        result = _project_generation_impl(
            conn, generation_id_or_row, force_visibility=force_visibility,
        )
        conn.execute(f"RELEASE SAVEPOINT {sp}")
        return result
    except BaseException:
        conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
        conn.execute(f"RELEASE SAVEPOINT {sp}")
        raise


def _project_generation_impl(
    conn: sqlite3.Connection,
    generation_id_or_row: str | sqlite3.Row | dict[str, Any],
    *,
    force_visibility: str | None = None,
) -> list[str]:
    """Persist one public work per logical generation batch, with all its images.

    A generation is the work's identity, not an individual image. One mapping
    row (item_key='__run__') is stored for the entire run. Both the work and
    every media grant are written in the caller's database transaction.
    """
    if isinstance(generation_id_or_row, str):
        row = conn.execute(
            "SELECT * FROM studio_generations WHERE id = ?", (generation_id_or_row,)
        ).fetchone()
    else:
        row = generation_id_or_row
    if not row:
        return []

    keys = row.keys() if hasattr(row, "keys") else row
    gen_id = str(row["id"])
    if "deleted_at" in keys and row["deleted_at"]:
        sync_generation_visibility(conn, gen_id, "private", is_deleted=True)
        return []
    vis = force_visibility or (
        str(row["visibility"] or "public") if "visibility" in keys else "public"
    )
    if vis != "public":
        sync_generation_visibility(conn, gen_id, "private")
        return []
    if str(row["status"] or "") != "success":
        return []
    if "engine" in keys and str(row["engine"] or "") == "demo":
        return []

    batch_id = str(row["batch_id"] or "").strip() if "batch_id" in keys else ""
    # Every cloud request is an execution slot; batch_id names the logical run.
    # Gather completed siblings in stable requested slot order (not completion
    # order), so the cover can be the first successful planned result.
    if batch_id:
        source_rows = conn.execute(
            """
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY batch_index
                    ORDER BY created_at DESC, id DESC
                ) AS attempt_rank
                FROM studio_generations
                WHERE user_id=? AND batch_id=? AND status='success'
                  AND visibility='public' AND COALESCE(deleted_at,'')=''
                  AND engine!='demo'
            )
            SELECT * FROM ranked WHERE attempt_rank=1
            ORDER BY batch_index ASC
            """,
            (int(row["user_id"]), batch_id),
        ).fetchall()
    else:
        source_rows = [row]

    valid_items: list[tuple[dict[str, Any] | None, str, str]] = []
    seen_urls: set[str] = set()
    for source in source_rows:
        try:
            raw_items = json.loads(source["items_json"] or "[]")
        except (ValueError, TypeError):
            raw_items = []
        if not isinstance(raw_items, list):
            continue
        for idx, raw in enumerate(raw_items):
            # A failed slot with stale media data is not a published image.
            if isinstance(raw, dict) and str(raw.get("status") or "").lower() in (
                "failed", "error", "refunded", "cancelled",
            ):
                continue
            _, url = derive_item_key(raw, idx)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            valid_items.append((raw if isinstance(raw, dict) else None, url, str(source["id"])))
    if not valid_items:
        return []

    from .services import get_generation_visible_prompt, check_text_has_secret
    visible_prompt, was_masked = get_generation_visible_prompt(row)
    try:
        has_secret = check_text_has_secret(visible_prompt, conn)
    except Exception:
        has_secret = True  # Do not expose a prompt when safety inspection fails.
    prompt_has_secret = bool(was_masked or has_secret)
    safe_prompt = "" if prompt_has_secret else visible_prompt

    now = utc_now_iso()
    created_at = str(row["created_at"] or now)
    try:
        published_at_ms = int(
            datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp() * 1000
        )
    except (ValueError, TypeError):
        published_at_ms = int(time.time() * 1000)

    author_username = str(row["username"] or "")
    author = conn.execute(
        "SELECT display_name FROM users WHERE username = ?", (author_username,)
    ).fetchone()
    author_name = str(author["display_name"]) if author and author["display_name"] else author_username
    first_item = valid_items[0][0]
    urls = [url for _, url, _ in valid_items]
    images_json = json.dumps(urls, ensure_ascii=False)

    # Reserve and lock the logical run before looking for its work. Two
    # out-of-order gateway callbacks must never race into two new works.
    from .generation_v3 import ensure_run
    canonical_run_id = ensure_run(
        conn, user_id=int(row["user_id"]), source="web",
        external_run_id=batch_id or gen_id,
        expected_count=int(row["batch_total"] or 1) if batch_id else 1,
    )
    if getattr(conn, "dialect", "") == "postgresql":
        conn.execute(
            "SELECT id FROM generation_runs WHERE id=? FOR UPDATE",
            (canonical_run_id,),
        ).fetchone()
    # The author/admin may have deleted this work after a successful run.
    # Never resurrect it on gateway retries, even when the original work row
    # was physically removed and no longer has a moderation status.
    tombstone = conn.execute(
        "SELECT publication_deleted_at FROM generation_runs WHERE id=?",
        (canonical_run_id,),
    ).fetchone()
    if tombstone and str(tombstone["publication_deleted_at"] or ""):
        return []
    mapping = conn.execute(
        "SELECT id AS work_id FROM works WHERE run_id=?",
        (canonical_run_id,),
    ).fetchone()
    if mapping:
        wid = str(mapping["work_id"])
        work = conn.execute(
            "SELECT status,status_source FROM works WHERE id = ?", (wid,)
        ).fetchone()
        if not work:
            raise RuntimeError(f"Generation {gen_id} has a dangling work link {wid}")
        source = str(work["status_source"] or "")
        status = str(work["status"] or "")
        if status != "published" and source in ("moderator", "admin", "report"):
            return [wid]  # Never override an administrator's moderation decision.
        if status != "published" and source == "generation":
            from .services import set_work_visibility
            set_work_visibility(conn, wid, "published", now, automated=True)
        # The V3 media persistence below atomically refreshes work_media and
        # its denormalized feed cache. Do not update images_json in advance:
        # the DB guard rejects a cache that disagrees with the linked media.
    else:
        # Stable work ID makes an interrupted callback safe to retry and
        # prevents duplicate gallery identities even across worker restarts.
        from .generation_v3 import _stable_id
        wid = _stable_id("work", canonical_run_id)
        title = resolve_work_title(row, first_item)
        styles, layout = extract_generation_styles_and_layout(conn, row, first_item)
        ratio = str((first_item.get("ratio") if first_item else "") or "3:4")
        mode = str(row["mode"] or "graphic-text") if "mode" in keys else "graphic-text"
        subject = str(row["subject"] or "") if "subject" in keys else ""
        fork_id = str(row["fork_work_id"] or "") if "fork_work_id" in keys else ""
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
                wid, author_username, author_name, title, images_json,
                json.dumps(styles, ensure_ascii=False), layout, ratio, mode,
                safe_prompt, int(prompt_has_secret), published_at_ms,
                created_at, created_at, fork_id, subject,
            ),
        )

    # Canonical V3 persistence: the gateway's subrequest rows are only
    # execution/billing events; the logical batch owns exactly one run and work.
    # This is in the same DB transaction as the media grants and work update.
    from .generation_v3 import record_public_work
    normalized_images = []
    by_source = {str(s["id"]): s for s in source_rows}
    per_source_count = {}
    for _, url, owner_generation_id in valid_items:
        source_row = by_source[owner_generation_id]
        source_index = int(source_row["batch_index"] or 0) if batch_id else 0
        subindex = per_source_count.get(owner_generation_id, 0)
        per_source_count[owner_generation_id] = subindex + 1
        normalized_images.append((source_index * 1000 + subindex, url, ""))
    record_public_work(
        conn, user_id=int(row["user_id"]), source="web",
        external_run_id=batch_id or gen_id, work_id=wid,
        ordered_images=normalized_images,
        expected_count=int(row["batch_total"] or 1) if batch_id else 1,
    )

    # The work's images are all publicly readable; their source library remains
    # independently permissioned. Create media grants for every linked image.
    for _, url, owner_generation_id in valid_items:
        _grant_work_media(conn, url, author_username, owner_generation_id, wid)

    from .resource_discussions import ensure_topic
    current = conn.execute("SELECT * FROM works WHERE id = ?", (wid,)).fetchone()
    if current and str(current["status"]) == "published":
        ensure_topic(conn, "work", wid, dict(current), initial_origin="generation")
    return [wid]


def sync_generation_visibility(
    conn: sqlite3.Connection,
    generation_id: str,
    new_visibility: str,
    *,
    is_deleted: bool = False,
) -> None:
    """Refresh the single work of a logical run when a slot is hidden/deleted."""
    from .services import set_work_visibility
    from .generation_v3 import _stable_id

    source = conn.execute(
        "SELECT user_id,batch_id FROM studio_generations WHERE id=?",
        (generation_id,),
    ).fetchone()
    if not source or source["user_id"] is None:
        return
    owner_id = int(source["user_id"])
    batch_id = str(source["batch_id"] or "")
    external_id = batch_id or generation_id
    run_id = _stable_id("run", owner_id, "web", external_id)
    work = conn.execute(
        "SELECT id,status,status_source FROM works WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if new_visibility == "public" and not is_deleted:
        project_generation_to_works(conn, generation_id, force_visibility="public")
        return
    if batch_id:
        # Preserve the work if any other successful image slot survives.
        remaining = conn.execute(
            """
            SELECT id FROM studio_generations
            WHERE user_id=? AND batch_id=? AND id<>? AND status='success'
              AND visibility='public' AND COALESCE(deleted_at,'')=''
              AND engine!='demo'
            ORDER BY batch_index ASC,created_at ASC,id ASC LIMIT 1
            """,
            (owner_id, batch_id, generation_id),
        ).fetchone()
        if remaining:
            project_generation_to_works(conn, str(remaining["id"]))
            return
    if work and str(work["status_source"] or "") not in (
        "admin", "moderator", "report",
    ):
        set_work_visibility(
            conn, str(work["id"]), "hidden", utc_now_iso(),
            source="generation", reason="此任务没有可公开的生成图片",
            automated=True,
        )

def get_work_generation_provenance(
    conn: sqlite3.Connection, work_id: str,
) -> dict[str, Any] | None:
    """The work's direct run FK is its authoritative provenance."""
    row = conn.execute(
        """
        SELECT r.id, r.external_run_id, r.source, r.created_at,
               r.original_request
        FROM works w JOIN generation_runs r ON r.id=w.run_id
        WHERE w.id=?
        """,
        (work_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "generationId": row["external_run_id"],
        "runId": row["id"],
        "itemKey": "__run__",
        "createdAt": row["created_at"],
        "subject": row["original_request"] or "",
        "mode": row["source"],
        "engine": row["source"],
    }

def reconcile_work_topics(conn: sqlite3.Connection, *, batch_size: int = 100) -> dict[str, Any]:
    """Repair missing discussion links for current published works only.

    Fresh V3 has no historical topic migration. Each new work creates its
    discussion in the publication transaction; this optional operator action
    only fixes an interrupted current-generation linking operation. It never
    modifies existing topic moderation, listing timestamps or replies.
    Works under PostgreSQL and SQLite, including when called inside a write
    transaction.
    """
    from .resource_discussions import ensure_topic
    limit = max(1, min(1000, int(batch_size)))
    rows = conn.execute(
        """SELECT w.* FROM works w
           WHERE w.status='published' AND NOT EXISTS (
               SELECT 1 FROM forum_topics t WHERE t.work_id=w.id
           ) ORDER BY w.created_at,w.id LIMIT ?""",
        (limit,),
    ).fetchall()
    savepoint = f"v3_topics_{uuid.uuid4().hex[:12]}"
    conn.execute(f"SAVEPOINT {savepoint}")
    created: list[dict[str, str]] = []
    try:
        for work in rows:
            work_id = str(work["id"])
            topic_id = ensure_topic(
                conn, "work", work_id, dict(work),
                initial_origin="generation" if work["run_id"] else "submission",
            )
            created.append({"work_id": work_id, "topic_id": str(topic_id)})
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    except BaseException:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
    return {"ok": True, "created_topics_count": len(created),
            "created_manifest": created, "hasMore": len(rows) >= limit}


