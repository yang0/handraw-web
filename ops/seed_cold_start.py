"""Import the original fictional launch pack, with backups and internal provenance.

Default is a read-only preview. --apply imports; --pause --apply hides the pack's
posts and replies. No user is deleted, logged in, or given credits.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.resource_discussions import static_catalog
from backend.security import hash_password
from ops.postgres_maintenance import backup_before_change, maintenance_parser, maintenance_transaction

# The cold-start content pack ships separately; importing this script must not
# fail on a checkout that does not include it.
try:
    from backend.cold_start_content import PACK_ID, USERS
except ImportError:  # pragma: no cover - content pack not installed
    PACK_ID = ""
    USERS: list = []

LABELS = {'tuning': '作品求改进', 'experience': '创作经验', 'assets': '画风与图型', 'tools': '工具与问答'}


def records():
    names = [u['username'] for u in USERS]
    if len(names) != len(set(names)) or not all(re.fullmatch(r'[a-z0-9_]{3,40}', n) for n in names):
        raise ValueError('Invalid or duplicate usernames')
    if not re.fullmatch(r'[a-z0-9_-]{1,24}', PACK_ID):
        raise ValueError('Invalid pack id')
    output = [('user', u['username'], u, None) for u in USERS]
    keys = set()
    for user in USERS:
        if not user['display_name'].strip() or not user['bio'].strip():
            raise ValueError('Profile cannot be empty')
        for topic in user['topics']:
            key = topic['key']
            if key in keys or not re.fullmatch(r'[a-z0-9_]{1,32}', key):
                raise ValueError('Invalid or duplicate topic key')
            keys.add(key)
            if topic['category'] not in LABELS or not topic['title'].strip() or not topic['body'].strip():
                raise ValueError('Invalid topic')
            tid = f'cs_{PACK_ID}_{key}'
            if len(tid) > 64:
                raise ValueError('Topic id too long')
            output.append(('topic', tid, topic, user))
            for index, reply in enumerate(topic['replies']):
                rid = f'csr_{PACK_ID}_{key}_{index}'
                if len(rid) > 64 or reply['username'] not in names or reply['username'] == user['username'] or not reply['text'].strip():
                    raise ValueError('Invalid reply')
                output.append(('reply', rid, reply, tid))
    return output


_TARGETS = {
    "user": ("users", "username"),
    "topic": ("forum_topics", "id"),
    "reply": ("forum_replies", "id"),
}


def registry(conn):
    return {(row[0], row[1]): row[2] for row in conn.execute(
        "SELECT kind, item_id, pack_id FROM cold_start_registry"
    )}


def plan(conn, rows):
    registered = registry(conn)
    existing = set()
    for kind, (table, column) in _TARGETS.items():
        keys = [key for row_kind, key, _, _ in rows if row_kind == kind]
        if keys:
            existing.update((kind, row[0]) for row in conn.execute(
                f"SELECT {column} FROM {table} WHERE {column} = ANY(?)", (keys,),
            ))
    pending, skipped = [], Counter()
    for kind, key, item, parent in rows:
        exists = (kind, key) in existing
        owner = registered.get((kind, key))
        if (owner is not None or exists) and owner != PACK_ID:
            raise ValueError(f"Existing {kind} conflicts with launch pack: {key}")
        if exists:
            skipped[kind] += 1
        else:
            pending.append((kind, key, item, parent))
    return pending, skipped


def stats(conn):
    counts = dict((row[0], row[1]) for row in conn.execute(
        "SELECT kind, COUNT(*) FROM cold_start_registry WHERE pack_id = ? GROUP BY kind", (PACK_ID,),
    ))
    others = {}
    for kind in ("user", "topic"):
        table, column = _TARGETS[kind]
        others[table] = conn.execute(f"""
            SELECT COUNT(*) FROM {table} AS t
            WHERE NOT EXISTS (
                SELECT 1 FROM cold_start_registry AS r
                WHERE r.kind = ? AND r.item_id = t.{column}
            )
        """, (kind,)).fetchone()[0]
    return {"pack_id": PACK_ID, "pack": counts, "other_users": others["users"], "other_topics": others["forum_topics"]}


def pause_pack(conn):
    changed = {}
    for kind, table, status in (("topic", "forum_topics", "paused"), ("reply", "forum_replies", "hidden")):
        result = conn.execute(f"""
            UPDATE {table} SET status = ?
            WHERE status <> ? AND id IN (
                SELECT item_id FROM cold_start_registry WHERE pack_id = ? AND kind = ?
            )
        """, (status, status, PACK_ID, kind))
        changed[kind] = result.rowcount
    return changed


def apply_pack(conn, pending):
    now = datetime.now(timezone.utc)
    iso, ms = now.strftime("%Y-%m-%dT%H:%M:%SZ"), int(now.timestamp() * 1000)
    names = {u["username"]: u["display_name"] for u in USERS}
    catalog = static_catalog()
    changed = Counter()
    for kind, key, item, parent in pending:
        if kind == "user":
            user_id = conn.execute("""
                INSERT INTO users (username, display_name, email, password_hash, role, status, bio, invite_code, created_at)
                VALUES (?, ?, ?, ?, 'user', 'active', ?, ?, ?) RETURNING id
            """, (
                key, item["display_name"], key + "@example.invalid", hash_password(secrets.token_urlsafe(40)),
                item["bio"], secrets.token_urlsafe(24), iso,
            )).fetchone()[0]
            conn.execute("INSERT INTO wallets (user_id, balance, updated_at) VALUES (?, 0, ?)", (user_id, iso))
        elif kind == "topic":
            styles = item.get("styles", [])
            if any(code not in catalog or catalog[code].get("kind") != "style" for code in styles):
                raise ValueError("Unknown style reference in launch pack")
            if styles and "配图是站内画风参考" not in item["body"]:
                raise ValueError("Style preview requires a source description")
            images = [{"url": catalog[code]["image"], "tag": "画风参考 " + code} for code in styles]
            conn.execute("""
                INSERT INTO forum_topics (
                    id, category, category_label, title, author_username, author_name, summary,
                    status, published_at_ms, created_label, created_at, updated_at, images_json, styles_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'published', ?, '', ?, ?, ?, ?)
            """, (
                key, item["category"], LABELS[item["category"]], item["title"], parent["username"],
                parent["display_name"], item["body"], ms, iso, iso, json.dumps(images, ensure_ascii=False), json.dumps(styles),
            ))
        else:
            conn.execute("""
                INSERT INTO forum_replies (id, topic_id, author_username, author_name, text, status, time_label, created_at)
                VALUES (?, ?, ?, ?, ?, 'published', '', ?)
            """, (key, parent, item["username"], names[item["username"]], item["text"], iso))
        conn.execute("""
            INSERT INTO cold_start_registry (pack_id, kind, item_id, created_at)
            VALUES (?, ?, ?, ?) ON CONFLICT (kind, item_id) DO NOTHING
        """, (PACK_ID, kind, key, iso))
        changed[kind] += 1
    return dict(changed)


def main(argv=None):
    parser = maintenance_parser(__doc__)
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--pause", action="store_true")
    args = parser.parse_args(argv)
    if (args.pause and not args.apply) or (args.stats and args.apply):
        parser.error("--pause requires --apply; --stats must be read-only")
    with maintenance_transaction(parser, write=args.apply) as (conn, dsn):
        if args.stats:
            print(json.dumps(stats(conn), ensure_ascii=False))
            return 0
        if args.pause:
            registered = conn.execute(
                "SELECT 1 FROM cold_start_registry WHERE pack_id = ? LIMIT 1", (PACK_ID,),
            ).fetchone()
            if not registered:
                return 0
        else:
            pending, skipped = plan(conn, records())
            print(json.dumps({
                "pack_id": PACK_ID, "create": dict(Counter(row[0] for row in pending)), "skip": dict(skipped),
            }, ensure_ascii=False))
            if not args.apply or not pending:
                return 0
        backup = backup_before_change(conn, dsn, args.backup_dir, "cold-start-before")
        changed = pause_pack(conn) if args.pause else apply_pack(conn, pending)
    print(json.dumps({"changed": changed, "backup": str(backup)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print("Cold-start import failed: " + str(error), file=sys.stderr)
        raise SystemExit(1) from error
