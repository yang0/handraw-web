"""Allowlisted search projections. Never serialize protected definitions/recipes."""
from __future__ import annotations

import hashlib
import html
import json
import re
from functools import lru_cache
from html.parser import HTMLParser
from urllib.parse import quote

from .config import CONTENT_DIR

CHANNELS = ('styles', 'layouts', 'colors', 'works', 'forum')
KINDS = {'style': 'styles', 'layout': 'layouts', 'color': 'colors'}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif tag in ('p', 'br', 'div', 'li', 'h1', 'h2', 'h3'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    parser = _Text()
    parser.feed(str(value or ''))
    value = ''.join(parser.parts)
    value = re.sub(r'!\[[^\]]*\]\([^)]*\)', ' ', value)
    value = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', value)
    return re.sub(r'\s+', ' ', html.unescape(value)).strip()


def identity(channel, entity):
    return hashlib.sha256(f'{channel}:{entity}'.encode()).hexdigest()


@lru_cache(maxsize=4)
def _static_catalog(digest):
    return json.loads((CONTENT_DIR / 'catalog.json').read_text(encoding='utf-8')).get('resources', [])


def catalog_digest():
    return hashlib.sha256((CONTENT_DIR / 'catalog.json').read_bytes()).hexdigest()


def resource_map(conn):
    resources = {str(r['id']): dict(r) for r in _static_catalog(catalog_digest())}
    for row in conn.execute('SELECT * FROM catalog_assets').fetchall():
        row = dict(row)
        code = row['code']
        if row['status'] != 'published':
            resources.pop(code, None)
            continue
        original = resources.get(code, {})
        resources[code] = {
            **original, 'id': code, 'kind': row['kind'], 'name': row['name'],
            'description': row['description'], 'group': row['group_name'],
            'image': row['image_url'], 'author': row['author_username'],
            'authorName': row['author_name'], 'publishedAtMs': row['published_at_ms'],
        }
    from .seed import seed_ids
    from .services import is_demo_mode
    excluded = set() if is_demo_mode() else seed_ids('assets')
    return {key: r for key, r in resources.items() if key not in excluded}


def _documents(channel, entity, *, title, bodies, code='', aliases='', author='',
               tags='', image='', url='', board='', published=0):
    """Chunk long bodies without dropping their tail; deduplicate by result_id."""
    root = identity(channel, entity)
    docs = []
    for source, text, anchor in bodies or [('body', '', '')]:
        clean = plain(text)
        for n, start in enumerate(range(0, max(1, len(clean)), 5900)):
            doc = {
                'id': identity(channel, f'{entity}:{source}:{n}'),
                'result_id': root, 'entity_id': str(entity), 'channel': channel,
                'title': plain(title), 'code': code, 'aliases': plain(aliases),
                'author': plain(author), 'tags': plain(tags),
                'body': clean[start:start + 6000], 'board': board,
                'url': url + anchor, 'image': str(image or ''),
                'published': int(published or 0),
            }
            doc['fingerprint'] = hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            docs.append(doc)
    return docs


def _first_image(value):
    try:
        images = json.loads(value or '[]') if isinstance(value, str) else value
        first = (images or [''])[0]
        return first.get('url', '') if isinstance(first, dict) else str(first)
    except (ValueError, TypeError, IndexError):
        return ''


def entity_documents(conn, channel, entity, *, viewer=None, indexing=False, resources=None):
    from .services import _seed_filter, get_work_client_prompt, filter_display_prompt
    if channel in ('styles', 'layouts', 'colors'):
        r = (resources if resources is not None else resource_map(conn)).get(entity)
        if not r or KINDS.get(r.get('kind')) != channel:
            return []
        title = r.get('nameZh') or r.get('name_zh') or r.get('name') or entity
        return _documents(channel, entity, title=title,
            code=entity, aliases=f"{r.get('legacy','')} {r.get('name','')}",
            author=f"{r.get('author','')} {r.get('authorName','')}", tags=r.get('group',''),
            bodies=[('body', r.get('description') or r.get('desc_zh') or '', '')],
            image=r.get('image',''), url=f'/t/{quote(entity)}' if channel != 'colors' else f'/studio/?color={quote(entity)}',
            published=r.get('publishedAtMs',0))
    if channel == 'works':
        sf, sp = _seed_filter('id', 'works')
        row = conn.execute(f"SELECT * FROM works WHERE id=? AND status='published' AND {sf}", (entity,*sp)).fetchone()
        if not row or not _first_image(row['images_json']):
            return []
        prompt, masked = get_work_client_prompt(row)
        # Even a caller with purchase rights searches only the public projection.
        if int(row['price'] or 0) > 0:
            prompt, masked = '', True
        bodies = [('body', f"{row['notes'] or ''} {' ' if masked else row['subject'] or ''} {prompt}", '')]
        cf, cp = _seed_filter('id','work_comments')
        for reply in conn.execute(f"SELECT * FROM work_comments WHERE work_id=? AND status='published' AND {cf}", (entity,*cp)).fetchall():
            bodies.append((reply['id'], reply['text'], '?focus=comment'))
        rf, rp = _seed_filter('r.id', 'forum_replies')
        for reply in conn.execute(
            f"""SELECT r.id, r.text FROM forum_replies r
                WHERE r.status='published' AND {rf}
                  AND r.topic_id IN (
                      SELECT id FROM forum_topics WHERE work_id=? AND status='published'
                      UNION
                      SELECT topic_id FROM curation_resource_topics WHERE kind='work' AND target_id=?
                  )
                ORDER BY r.id""",
            (*rp, entity, entity),
        ).fetchall():
            bodies.append((reply['id'], reply['text'], '?reply=' + quote(reply['id'])))
        return _documents(channel, entity, title=row['title'], bodies=bodies,
            author=f"{row['author_username']} {row['author_name']}",
            tags=f"{row['styles_json']} {row['layout_code']} {row['color_code']} {row['mood']}",
            image=_first_image(row['images_json']), url=f'/t/{quote(entity)}', published=row['published_at_ms'])
    if channel == 'forum':
        sf, sp = _seed_filter('id', 'topics')
        row = conn.execute(f"SELECT * FROM forum_topics WHERE id=? AND status='published' AND {sf}", (entity,*sp)).fetchone()
        if not row:
            return []
        from .forum_boards import can_read_topic
        if indexing:
            allowed = conn.execute("SELECT 1 FROM forum_boards WHERE key=? AND state='open'", (row['category'],)).fetchone()
        else:
            allowed = can_read_topic(conn, entity, viewer)
        if not allowed:
            return []
        if row['work_id']:
            work = conn.execute("SELECT status FROM works WHERE id=?", (row['work_id'],)).fetchone()
            if not work or work['status'] != 'published' or row['listed_at_ms'] is None:
                return []
        raw_summary = str(row['summary'] or '')
        if int(row['price'] or 0) > 0 and 'hw-paywall-divider' in raw_summary:
            raw_summary = re.split(r'<(?:div|hr)[^>]*hw-paywall-divider[^>]*>', raw_summary, maxsplit=1)[0]
        body = filter_display_prompt(raw_summary)
        # Free post content may use locked_body historically; paid bodies are excluded.
        if int(row['price'] or 0) <= 0:
            body += ' ' + filter_display_prompt(row['locked_body'])
        bodies = [('body', body, '')]
        rf, rp = _seed_filter('id','forum_replies')
        for reply in conn.execute(f"SELECT * FROM forum_replies WHERE topic_id=? AND status='published' AND {rf}", (entity,*rp)).fetchall():
            bodies.append((reply['id'], reply['text'], '?reply=' + quote(reply['id'])))
        return _documents(channel, entity, title=row['title'], bodies=bodies,
            author=f"{row['author_username']} {row['author_name']}",
            tags=f"{row['category_label']} {row['styles_json']} {row['layout_code']}", board=row['category'],
            image=_first_image(row['images_json']), url=f'/t/{quote(entity)}', published=row['published_at_ms'])
    return []


def entity_ids(conn, channel):
    if channel in ('styles','layouts','colors'):
        return [key for key,r in resource_map(conn).items() if KINDS.get(r.get('kind')) == channel]
    table = 'works' if channel == 'works' else 'forum_topics'
    return [r['id'] for r in conn.execute(f"SELECT id FROM {table} WHERE status='published' ORDER BY id").fetchall()]
