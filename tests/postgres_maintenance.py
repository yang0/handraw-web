"""Native PostgreSQL fixtures for historical data maintenance regressions."""
from __future__ import annotations
import json
from typing import Any
from backend.postgres_db import PgConnection


def deduplicate_generation_history(conn: PgConnection, user_id: int | None = None) -> int:
    """Clean duplicate studio_generations records idempotently.

    1. Match by (user_id, request_id): when multiple active rows share the same user and non-empty request_id,
       keep the server record (preferring gen_ prefix or live engine), and soft-delete duplicate hist_ rows.
    2. Match by (user_id, complete image set): for rows of the same user with identical complete image sets,
       match hist_/gen_ pairs, keep the server/gen_ record, and soft-delete the duplicate hist_ record.
    3. Backfill subject / recipe_summary onto the kept record if missing.
    4. Never touches wallets, transactions, or accounting ledgers.
    """
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    count_deleted = 0

    in_tx = getattr(conn, "in_transaction", False)
    if not in_tx:
        conn.execute("BEGIN;")

    try:
        user_clause = "AND user_id = ?" if user_id is not None else ""
        user_args: tuple[Any, ...] = (user_id,) if user_id is not None else ()

        # 1. Deduplicate by (user_id, request_id)
        dup_reqs = conn.execute(
            f"""
            SELECT user_id, request_id, COUNT(*) as cnt
            FROM studio_generations
            WHERE COALESCE(deleted_at, '') = ''
              AND request_id IS NOT NULL AND request_id != ''
              {user_clause}
            GROUP BY user_id, request_id
            HAVING COUNT(*) > 1
            """,
            user_args,
        ).fetchall()

        for d_row in dup_reqs:
            u_id = d_row["user_id"]
            r_id = d_row["request_id"]
            group_rows = conn.execute(
                """
                SELECT * FROM studio_generations
                WHERE user_id = ? AND request_id = ? AND COALESCE(deleted_at, '') = ''
                ORDER BY
                  CASE WHEN id NOT LIKE 'hist_%' AND engine != 'sample' THEN 0
                       WHEN id NOT LIKE 'hist_%' THEN 1
                       WHEN engine != 'sample' THEN 2
                       ELSE 3 END,
                  created_at ASC,
                  id ASC
                """,
                (u_id, r_id),
            ).fetchall()
            if len(group_rows) <= 1:
                continue
            primary = group_rows[0]
            updates = []
            update_vals = []
            for dup in group_rows[1:]:
                if "subject = ?" not in updates and not primary["subject"] and dup["subject"]:
                    updates.append("subject = ?")
                    update_vals.append(dup["subject"])
                if "recipe_summary = ?" not in updates and not primary["recipe_summary"] and dup["recipe_summary"]:
                    updates.append("recipe_summary = ?")
                    update_vals.append(dup["recipe_summary"])
                conn.execute(
                    "UPDATE studio_generations SET deleted_at = ?, request_id = '' WHERE id = ? AND COALESCE(deleted_at, '') = ''",
                    (now_iso, dup["id"]),
                )
                count_deleted += 1
            if updates:
                update_vals.append(primary["id"])
                conn.execute(
                    f"UPDATE studio_generations SET {', '.join(updates)} WHERE id = ?",
                    tuple(update_vals),
                )

        # 2. Deduplicate by identical complete image set for same user
        cand_rows = conn.execute(
            f"""
            SELECT id, user_id, engine, subject, recipe_summary, items_json, created_at, request_id
            FROM studio_generations
            WHERE COALESCE(deleted_at, '') = ''
              AND status = 'success'
              AND items_json IS NOT NULL AND items_json != '' AND items_json != '[]'
              {user_clause}
            ORDER BY user_id, created_at ASC, id ASC
            """,
            user_args,
        ).fetchall()

        def _extract_urls(items_json_str: str) -> tuple[str, ...]:
            try:
                items = json.loads(items_json_str or "[]")
            except Exception:
                return ()
            urls: list[str] = []
            for it in (items if isinstance(items, list) else []):
                if isinstance(it, str) and it.strip():
                    urls.append(it.strip())
                elif isinstance(it, dict) and it.get("imageUrl"):
                    urls.append(str(it["imageUrl"]).strip())
            return tuple(sorted(urls))

        user_image_map: dict[tuple[int, tuple[str, ...]], list[Any]] = {}
        for r in cand_rows:
            urls = _extract_urls(r["items_json"])
            if not urls:
                continue
            key = (int(r["user_id"]), urls)
            user_image_map.setdefault(key, []).append(r)

        for (u_id, urls), rows_with_same_images in user_image_map.items():
            if len(rows_with_same_images) <= 1:
                continue

            server_rows = [r for r in rows_with_same_images if not str(r["id"]).startswith("hist_") and str(r["engine"]) != "sample"]
            client_rows = [r for r in rows_with_same_images if str(r["id"]).startswith("hist_") or str(r["engine"]) == "sample"]

            if server_rows and client_rows:
                primary = server_rows[0]
                updates = []
                update_vals = []
                for client_row in client_rows:
                    # Never merge distinct requests with different non-empty request IDs
                    client_req = str(client_row["request_id"] or "").strip()
                    primary_req = str(primary["request_id"] or "").strip()
                    if client_req and primary_req and client_req != primary_req:
                        continue

                    if "subject = ?" not in updates and not primary["subject"] and client_row["subject"]:
                        updates.append("subject = ?")
                        update_vals.append(client_row["subject"])
                    if "recipe_summary = ?" not in updates and not primary["recipe_summary"] and client_row["recipe_summary"]:
                        updates.append("recipe_summary = ?")
                        update_vals.append(client_row["recipe_summary"])
                    conn.execute(
                        "UPDATE studio_generations SET deleted_at = ? WHERE id = ? AND COALESCE(deleted_at, '') = ''",
                        (now_iso, client_row["id"]),
                    )
                    count_deleted += 1
                if updates:
                    update_vals.append(primary["id"])
                    conn.execute(
                        f"UPDATE studio_generations SET {', '.join(updates)} WHERE id = ?",
                        tuple(update_vals),
                    )

        if not in_tx:
            conn.execute("COMMIT;")
    except Exception:
        if not in_tx and getattr(conn, "in_transaction", False):
            conn.execute("ROLLBACK;")
        raise

    return count_deleted
