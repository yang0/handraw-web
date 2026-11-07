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
            SELECT * FROM studio_generations
            WHERE user_id = ? AND batch_id = ? AND status = 'success'
              AND visibility = 'public' AND COALESCE(deleted_at,'') = ''
              AND engine != 'demo'
            ORDER BY batch_index ASC, created_at ASC, id ASC
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

    # One work is linked directly to its canonical run. No separate mapping
    # table is needed; batches and individual requests use the same key.
    from .generation_v3 import _stable_id
    canonical_run_id = _stable_id(
        "run", int(row["user_id"]), "web", batch_id or gen_id,
    )
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
        wid = f"work_{uuid.uuid4().hex}"
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

def backfill_work_topics(conn: sqlite3.Connection, *, batch_size: int = 100) -> dict[str, Any]:
    """Backfill missing topics for all published works (generations, web, legacy) and preserve listed states.

    Idempotent and safe:
      1. Preserves existing topics: ID, replies, moderation status, counters.
      2. Backfills listed_at_ms only if a historical published topic has a published reply.
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
              -- Work discussions become listed only after the first published
              -- reply; do not resurrect empty unlisted topics during backfill.
              AND EXISTS (
                  SELECT 1 FROM forum_replies r
                  WHERE r.topic_id = t.id AND r.status = 'published'
              )
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
