"""Import the original fictional launch pack, with backups and internal provenance.

Default is a read-only preview. --apply imports; --pause --apply hides the pack's
posts and replies. No user is deleted, logged in, or given credits.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.db import Database
from backend.security import hash_password

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


def registry(conn):
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cold_start_registry'").fetchone()
    return {(r[0], r[1]): r[2] for r in conn.execute('SELECT kind,item_id,pack_id FROM cold_start_registry')} if exists else {}


def plan(conn, rows):
    registered = registry(conn)
    pending, skipped = [], Counter()
    for kind, key, item, parent in rows:
        table, column = {'user': ('users', 'username'), 'topic': ('forum_topics', 'id'), 'reply': ('forum_replies', 'id')}[kind]
        exists = conn.execute(f'SELECT 1 FROM {table} WHERE {column}=?', (key,)).fetchone()
        owner = registered.get((kind, key))
        if owner is not None and owner != PACK_ID or exists and owner != PACK_ID:
            raise ValueError(f'Existing {kind} conflicts with launch pack: {key}')
        if exists:
            skipped[kind] += 1
        else:
            pending.append((kind, key, item, parent))
    return pending, skipped


def stats(conn):
    registered = registry(conn)
    counts = Counter(k for (k, _), p in registered.items() if p == PACK_ID)
    users = {key for (kind, key) in registered if kind == 'user'}
    topics = {key for (kind, key) in registered if kind == 'topic'}
    return {'pack_id': PACK_ID, 'pack': dict(counts),
            'other_users': sum(r[0] not in users for r in conn.execute('SELECT username FROM users')),
            'other_topics': sum(r[0] not in topics for r in conn.execute('SELECT id FROM forum_topics'))}


def backup(path):
    folder = path.parent / 'backups'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ('coldstart-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.db')
    with target.open('xb'):
        pass
    source, destination = sqlite3.connect(str(path)), sqlite3.connect(str(target))
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()
    return target


def apply_pack(path, rows, pause=False):
    backup_path = backup(path)
    db = Database(path)
    changed = Counter()
    try:
        with db.transaction() as tx:
            pending, _ = plan(tx, rows)  # Recheck under the write transaction.
            tx.execute('CREATE TABLE IF NOT EXISTS cold_start_registry (pack_id TEXT NOT NULL,kind TEXT NOT NULL,item_id TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(kind,item_id))')
            if pause:
                for kind, table, status in [('topic', 'forum_topics', 'paused'), ('reply', 'forum_replies', 'hidden')]:
                    cur = tx.execute(f'UPDATE {table} SET status=? WHERE id IN (SELECT item_id FROM cold_start_registry WHERE pack_id=? AND kind=?)', (status, PACK_ID, kind))
                    changed[kind] = cur.rowcount
            else:
                now = datetime.now(timezone.utc)
                iso, ms = now.strftime('%Y-%m-%dT%H:%M:%SZ'), int(now.timestamp() * 1000)
                names = {u['username']: u['display_name'] for u in USERS}
                for kind, key, item, parent in pending:
                    if kind == 'user':
                        cur = tx.execute('INSERT INTO users (username,display_name,email,password_hash,role,status,bio,invite_code,created_at) VALUES (?,?,?,?,?,?,?,?,?)', (key, item['display_name'], key + '@example.invalid', hash_password(secrets.token_urlsafe(40)), 'user', 'active', item['bio'], secrets.token_urlsafe(24), iso))
                        tx.execute('INSERT INTO wallets(user_id,balance,updated_at) VALUES (?,0,?)', (cur.lastrowid, iso))
                    elif kind == 'topic':
                        from backend.server import load_localized_json
                        catalog = {r['id']: r for r in json.loads(load_localized_json('catalog.json'))['resources']}
                        styles = item.get('styles', [])
                        if any(code not in catalog or catalog[code].get('kind') != 'style' for code in styles):
                            raise ValueError('Unknown style reference in launch pack')
                        if styles and '配图是站内画风参考' not in item['body']:
                            raise ValueError('Style preview requires a source description')
                        images = [{'url': catalog[code]['image'], 'tag': '画风参考 ' + code} for code in styles]
                        tx.execute('INSERT INTO forum_topics (id,category,category_label,title,author_username,author_name,summary,status,published_at_ms,created_label,created_at,updated_at,images_json,styles_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (key, item['category'], LABELS[item['category']], item['title'], parent['username'], parent['display_name'], item['body'], 'published', ms, '', iso, iso, json.dumps(images, ensure_ascii=False), json.dumps(styles)))
                    else:
                        tx.execute('INSERT INTO forum_replies (id,topic_id,author_username,author_name,text,status,time_label,created_at) VALUES (?,?,?,?,?,?,?,?)', (key, parent, item['username'], names[item['username']], item['text'], 'published', '', iso))
                    tx.execute('INSERT OR IGNORE INTO cold_start_registry (pack_id,kind,item_id,created_at) VALUES (?,?,?,?)', (PACK_ID, kind, key, iso))
                    changed[kind] += 1
        return {'changed': dict(changed), 'backup': str(backup_path)}
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--stats', action='store_true')
    parser.add_argument('--pause', action='store_true')
    args = parser.parse_args()
    path = args.db.resolve()
    if not path.is_file():
        parser.error('Target must be an existing initialized database')
    if args.pause and not args.apply or args.stats and (args.apply or args.pause):
        parser.error('--pause requires --apply; --stats must be read-only')
    rows = records()
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        if args.stats:
            print(json.dumps(stats(conn), ensure_ascii=False))
            return
        pending, skipped = plan(conn, rows)
        print(json.dumps({'pack_id': PACK_ID, 'create': dict(Counter(r[0] for r in pending)), 'skip': dict(skipped)}, ensure_ascii=False))
    finally:
        conn.close()
    if args.apply:
        print(json.dumps(apply_pack(path, rows, args.pause), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, sqlite3.Error) as error:
        print('Cold-start import failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
