"""Permission-aware search facade and administrator indexing commands."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid

from .search_engine import SearchEngine, index_name
from .search_sources import CHANNELS, entity_documents, identity, resource_map
from .services import ServiceError, record_audit_log


def admin_required(user):
    if not user or user.get('role') != 'admin' or user.get('status','active') != 'active':
        raise ServiceError('只有管理员可以管理搜索索引', 403, 'forbidden')


def request_rebuild(db, channel, user=None):
    if channel != 'all' and channel not in CHANNELS:
        raise ServiceError('无效的搜索频道', 400, 'invalid_search_channel')
    jobs = []
    with db.transaction() as tx:
        for ch in CHANNELS if channel == 'all' else (channel,):
            existing = tx.execute("SELECT id FROM search_jobs WHERE channel=? AND status IN ('queued','running','swapping')", (ch,)).fetchone()
            if existing:
                jobs.append(existing['id'])
                continue
            jid = uuid.uuid4().hex
            row = tx.execute("""INSERT INTO search_jobs(id,channel,requested_by) VALUES(?,?,?)
                ON CONFLICT DO NOTHING RETURNING id""", (jid,ch,user['id'] if user else None)).fetchone()
            if row:
                jobs.append(jid)
        if user:
            record_audit_log(tx, user, 'search_rebuild', 'search', channel, '重建全文索引', {'jobs':jobs})
    return {'ok':True,'jobs':jobs}


def retry_events(db, user):
    admin_required(user)
    with db.transaction() as tx:
        tx.execute("UPDATE search_events SET retry_at=now(),error='' WHERE processed_at IS NULL")
        record_audit_log(tx,user,'search_retry','search','all','重试索引事件',{})
    return {'ok':True}


def status(db):
    conn = db.get_conn()
    channels = [dict(r) for r in conn.execute("""SELECT c.*,
        (SELECT count(*) FROM search_events e WHERE e.channel=c.channel AND e.processed_at IS NULL) AS pending,
        (SELECT count(*) FROM search_events e WHERE e.channel=c.channel AND e.processed_at IS NULL AND e.error<>'') AS failed,
        (SELECT EXTRACT(EPOCH FROM now()-min(created_at)) FROM search_events e WHERE e.channel=c.channel AND e.processed_at IS NULL) AS lag_seconds
        FROM search_channels c ORDER BY channel""").fetchall()]
    jobs = [dict(r) for r in conn.execute('SELECT * FROM search_jobs ORDER BY created_at DESC LIMIT 30').fetchall()]
    for row in [*channels,*jobs]:
        for k,v in list(row.items()):
            if hasattr(v,'isoformat'):
                row[k] = v.isoformat()
            elif k == 'lag_seconds':
                row[k] = float(v or 0)
    try:
        engine = SearchEngine().request('GET','/health',timeout=2)
        health = engine.get('status') == 'available'
    except ServiceError:
        health = False
    return {'ok':True,'available':health,'channels':channels,'jobs':jobs}


def _cursor_key():
    return (os.environ.get('HANDRAW_SEARCH_CURSOR_KEY') or os.environ.get('HANDRAW_SEARCH_KEY') or '').encode()


def _encode_cursor(data):
    body = base64.urlsafe_b64encode(json.dumps(data,separators=(',',':')).encode()).decode().rstrip('=')
    sig = hmac.new(_cursor_key(),body.encode(),hashlib.sha256).hexdigest()
    return body + '.' + sig


def _decode_cursor(value, scope):
    try:
        if len(value) > 100000:
            raise ValueError()
        body, sig = value.rsplit('.',1)
        if not hmac.compare_digest(sig,hmac.new(_cursor_key(),body.encode(),hashlib.sha256).hexdigest()):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body)%4)))
        if data['scope'] != scope or data['expires'] < time.time() or not 0 <= data['offset'] <= 2000:
            raise ValueError()
        return data
    except (ValueError,KeyError,TypeError):
        raise ServiceError('搜索状态已变化，请从第一页重新搜索',400,'invalid_search_cursor') from None


def _parts(value):
    """Return text segments, never HTML from indexed content."""
    pieces = re.split('(\ue000|\ue001)', str(value or ''))
    result, marked = [], False
    for piece in pieces:
        if piece == '\ue000': marked = True
        elif piece == '\ue001': marked = False
        elif piece: result.append({'text':piece,'match':marked})
    return result


def search(db, user, params, engine=None):
    q = str(params.get('q') or '').strip()
    if not q or len(q) > 200:
        raise ServiceError('请输入 1–200 字的搜索内容',400,'invalid_search_query')
    channel = str(params.get('channel') or 'all')
    if channel != 'all' and channel not in CHANNELS:
        raise ServiceError('无效的搜索频道',400,'invalid_search_channel')
    sort = str(params.get('sort') or 'relevance')
    if sort not in ('relevance','newest'):
        raise ServiceError('无效的排序方式',400,'invalid_search_sort')
    try: limit = max(1,min(50,int(params.get('limit') or 24)))
    except (ValueError,TypeError): raise ServiceError('无效的分页数量') from None
    from .forum_boards import list_boards
    conn = db.get_conn()
    boards = list_boards(conn,user)
    generations = [(r['channel'],r['epoch']) for r in conn.execute('SELECT channel,epoch FROM search_channels ORDER BY channel').fetchall()]
    scope = hashlib.sha256(json.dumps([q,channel,sort,limit,(user or {}).get('id'),(user or {}).get('role'),boards,generations],sort_keys=True,default=str).encode()).hexdigest()
    cursor = _decode_cursor(params['cursor'],scope) if params.get('cursor') else {'offset':0,'seen':[]}
    seen, offset = set(cursor['seen']), cursor['offset']
    resources = resource_map(conn)
    cache = {}
    def hydrate(hit):
        key = (hit.get('channel'),hit.get('entity_id'))
        if key[0] not in CHANNELS or (channel != 'all' and key[0] != channel): return None
        if key not in cache:
            cache[key] = {d['id']:d for d in entity_documents(conn,*key,viewer=user,resources=resources)}
        current = cache[key].get(hit.get('id'))
        if not current or current['fingerprint'] != hit.get('fingerprint'): return None
        formatted = hit.get('_formatted') or {}
        title_parts = _parts(formatted.get('title',current['title']))
        snippet_parts = _parts(formatted.get('body',current['body'][:180]))
        return {'id':current['id'],'resultId':current['result_id'],'channel':current['channel'],
            'title':current['title'],'code':current['code'],'author':current['author'],
            'url':current['url'],'image':current['image'], 'publishedAtMs':current['published'],
            'snippet':''.join(p['text'] for p in snippet_parts),
            'titleParts':title_parts,
            'snippetParts':snippet_parts}
    results = []
    # Exact official/current/legacy identifiers are promoted without fuzzy code matches.
    normalized = re.sub(r'[^A-Z0-9]','',q.upper())
    if offset == 0 and sort == 'relevance' and normalized:
        for code,r in resources.items():
            if normalized not in (re.sub(r'[^A-Z0-9]','',code.upper()), str(r.get('legacy','')).upper()): continue
            ch = {'style':'styles','layout':'layouts','color':'colors'}.get(r.get('kind'))
            if ch and (channel == 'all' or ch == channel):
                for doc in entity_documents(conn,ch,code,resources=resources):
                    result = hydrate(doc)
                    if result and result['resultId'] not in seen:
                        results.append(result); seen.add(result['resultId'])
    engine = engine or SearchEngine()
    more = False
    def build_queries(extra=None):
        built = []
        for ch in CHANNELS if channel == 'all' else (channel,):
            query = {'indexUid':index_name(ch),'q':q.lstrip('#'),
                'attributesToHighlight':['title','body'],'attributesToCrop':['body:45'],
                'highlightPreTag':'\ue000','highlightPostTag':'\ue001','matchingStrategy':'all'}
            if sort == 'newest': query['sort'] = ['published:desc']
            if extra: query.update(extra)
            if ch == 'forum':
                if not boards: continue
                query['filter'] = 'board IN ' + json.dumps([b['key'] for b in boards])
            built.append(query)
        return built
    if sort == 'newest':
        batch_end = min(2000, max(64, offset + limit + 64))
        while offset < 2000:
            queries = build_queries({'limit': batch_end, 'offset': 0})
            if not queries: break
            response = engine.request('POST','/multi-search',{'queries':queries},timeout=4)
            per_index = response.get('results') or []
            merged = sorted(
                (h for res in per_index for h in (res.get('hits') or [])),
                key=lambda h: (-int(h.get('published') or 0), str(h.get('id') or '')),
            )
            exhausted = all(len(res.get('hits') or []) < batch_end for res in per_index)
            for hit in merged[offset:]:
                result = hydrate(hit)
                if result and result['resultId'] not in seen:
                    if len(results) >= limit:
                        more = True
                        break
                    results.append(result); seen.add(result['resultId'])
                offset += 1
            if more or exhausted or batch_end >= 2000: break
            batch_end = min(2000, batch_end * 2)
    else:
        while offset < 2000:
            queries = build_queries()
            if not queries: break
            response = engine.request('POST','/multi-search',{'queries':queries,'federation':{'offset':offset,'limit':64}},timeout=4)
            hits = response.get('hits',[])
            if not hits: break
            for hit in hits:
                result = hydrate(hit)
                if result and result['resultId'] not in seen:
                    if len(results) >= limit:
                        more = True
                        break
                    results.append(result); seen.add(result['resultId'])
                offset += 1
            if more or len(hits) < 64: break
    return {'ok':True,'query':q,'channel':channel,'hits':results,'hasMore':more,
        'nextCursor':_encode_cursor({'offset':offset,'seen':sorted(seen),'scope':scope,'expires':time.time()+900}) if more else '',
        'limited':offset >= 2000}
