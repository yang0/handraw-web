"""Forum resource detail, related listing, and comment reads.

Read-only module: no GET creates storage. Pending curation is exposed only via
``curation._safe_preview`` and only when the original topic is public, with
``canUse`` false and no prompt/definition. Hidden DB records never fall back
to static catalog data.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote

from . import services as S
from . import resource_discussions as RD
from . import curation as C
from .skill_prompt import strip_bilingual_definition

_STAFF = ("admin", "operator", "reviewer")
_REL_LIMIT = 36
_COMMENT_LIMIT = 50
_PREVIEW = 4
_ASSET_TABS = {"style": ("works", "layouts", "topics"), "layout": ("works", "styles", "topics")}
_WORK_TABS = ("styles", "layouts", "topics")
_STATIC_FIELDS = (
    "id", "kind", "name", "description", "image", "definition", "layout", "ratio",
    "mode", "styles", "price", "unlockCost", "mood", "color", "tone",
)
_FILTER_BLACKBOX = "[CLOUD_BLACKBOX::"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _loads(value: Any, default):
    try:
        return json.loads(value) if value else default
    except Exception:
        return default


def _norm(kind: str, target: str) -> tuple[str, str]:
    k = (kind or "").strip().lower()
    t = str(target or "").strip()
    if k in ("style", "layout", "asset"):
        t = t.upper().lstrip("#")
    return k, t


def _resolve_kind(conn, kind: str, target: str) -> str | None:
    if kind in ("style", "layout", "work"):
        return kind
    if kind != "asset":
        return None
    row = conn.execute("SELECT kind FROM catalog_assets WHERE code=?", (target,)).fetchone()
    if row:
        return row["kind"]
    item = RD.static_catalog().get(target)
    if not item:
        row=conn.execute('SELECT kind FROM curation_submissions WHERE target_id=? AND kind IN (\'style\',\'layout\')',(target,)).fetchone()
        return row['kind'] if row else None
    return item["kind"] if item and item.get("kind") in ("style", "layout") else None


def _unlocked(db, user) -> set[str]:
    if not user:
        return set()
    rows = db.get_conn().execute(
        "SELECT target_id FROM unlocks WHERE user_id=? AND status='settled'",
        (user.get("id"),),
    ).fetchall()
    return {r["target_id"] for r in rows if r["target_id"]}


def _image_of(images) -> str:
    if not isinstance(images, list) or not images:
        return ""
    first = images[0]
    return _local_image(first.get("url", "") if isinstance(first, dict) else str(first or ""))


def _local_image(url):
    # Match the existing localized catalog endpoint; local preview serves these files.
    prefix='https://img.handraw-style.com/images/'
    return '/images/'+url[len(prefix):] if str(url).startswith(prefix) else url


def _images_public(raw) -> list[str]:
    imgs = _loads(raw, [])
    return [_image_of([i]) for i in imgs if _image_of([i])] if isinstance(imgs, list) else []


def _is_public_work(conn, wid: str) -> bool:
    row = conn.execute("SELECT id FROM works WHERE id=? AND status='published'", (wid,)).fetchone()
    return bool(row) and (S.is_demo_mode() or wid not in S.seed_ids("works"))


def _mapping(db, kind: str, target: str):
    row = db.get_conn().execute(
        "SELECT * FROM curation_resource_topics WHERE kind=? AND (target_id=? OR UPPER(target_id)=?)",
        (kind, target, target),
    ).fetchone()
    return dict(row) if row else None


def _topic(conn, topic_id: str):
    row = conn.execute("SELECT * FROM forum_topics WHERE id=?", (topic_id,)).fetchone()
    return dict(row) if row else None


def _submission(db, kind: str, target: str):
    """Locate submission by (kind,target), not by topic."""
    row = db.get_conn().execute(
        "SELECT * FROM curation_submissions WHERE kind=? AND target_id=? ORDER BY id DESC LIMIT 1",
        (kind, target),
    ).fetchone()
    return dict(row) if row else None


def _payload(db, sub: dict[str, Any]):
    if not sub:
        return None
    row = db.get_conn().execute(
        "SELECT payload_json FROM curation_versions WHERE submission_id=? AND revision=?",
        (sub["id"], sub["current_revision"]),
    ).fetchone()
    return _loads(row["payload_json"], None) if row else None


def _submission_thread_topic(conn, sub: dict[str, Any]):
    """Resolve the original submission topic (published only)."""
    topic = _topic(conn, sub.get("topic_id") or "")
    return topic if topic and topic["status"] == "published" else None


# ---------------------------------------------------------------------------
# Curation / thread
# ---------------------------------------------------------------------------

def _curation_block(db, conn, sub: dict[str, Any] | None, published: bool):
    if not sub:
        return None
    return {
        "id": sub["id"],
        "status": sub["status"],
        "revision": sub["current_revision"],
        "hasPublishedVersion": bool(published),
    }


def _thread_block(conn, topic: dict[str, Any] | None, sub_kind: str, target: str):
    """Return (thread, closed)."""
    if not topic:
        return None, False
    mapping = conn.execute(
        "SELECT origin FROM curation_resource_topics WHERE kind=? AND (target_id=? OR UPPER(target_id)=?)",
        (sub_kind, target, target),
    ).fetchone()
    origin = mapping["origin"] if mapping else None
    # Hidden override: published resource with an unpublished discussion topic.
    if topic["status"] != "published":
        return {"id": topic["id"], "title": "资源讨论", "body": "", "category": topic["category"],
                "closed": True, "origin": origin, "commentCount": 0}, True
    table,where,args='forum_replies','topic_id=?',[topic['id']]
    sf,sp=S._seed_filter('id',table)
    row=conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where} AND status='published' AND {sf}",args+list(sp)).fetchone()
    count = int(row[0]) if row else 0
    body = C.sanitize_html(topic.get("summary") or "") if hasattr(C, "sanitize_html") else (topic.get("summary") or "")
    return {
        "id": topic["id"], "title": topic["title"], "body": body,
        "category": topic["category"], "closed": False,
        "origin": origin, "commentCount": count,
    }, False


# ---------------------------------------------------------------------------
# Resource serialization
# ---------------------------------------------------------------------------

def _static_resource(item: dict[str, Any], kind: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _STATIC_FIELDS:
        if key in item:
            out[key] = item[key]
    out["id"] = item.get("id")
    out["kind"] = kind
    out["author"] = item.get("author", "")
    out["authorName"] = item.get("authorName") or item.get("author") or "官方"
    out["sourceType"] = item.get("sourceType") or "official"
    out["tier"] = item.get("tier", "free")
    out["unlockCost"] = int(item.get("unlockCost") or 0)
    out["price"] = int(item.get("price") or 0)
    out["unlocked"] = True
    out["canUse"] = True
    out["status"] = "published"
    out["publishedAtMs"] = int(item.get("publishedAtMs") or 0)
    out['image']=_local_image(out.get('image',''))
    if kind == "layout" and "definition" in out:
        out["definition"] = strip_bilingual_definition(out["definition"])
    return out


def _asset_resource(row: dict[str, Any], unlocked: set[str], user) -> dict[str, Any]:
    ser = S._serialize_catalog_asset(row, unlocked, user)
    source = row["source_type"]
    definition = ser.get("definition") or ""
    if source == "exclusive" or _FILTER_BLACKBOX in definition:
        definition = ""
    allowed = int(row['unlock_cost'] or 0) <= 0 or row['code'] in unlocked or bool(user and (user.get('role') in _STAFF or user.get('username') == row['author_username']))
    if not allowed:
        definition = ''
    elif ser.get("kind") == "layout" and definition:
        definition = strip_bilingual_definition(definition)
    return {
        "id": ser["id"], "kind": ser["kind"], "name": ser["name"],
        "description": ser["description"], "definition": definition,
        "prompt": "", "image": _local_image(ser["image"]),
        "images": [_local_image(ser["image"])] if ser["image"] else [],
        "author": ser["author"], "authorName": ser["authorName"],
        "sourceType": ser["sourceType"], "tier": ser["tier"],
        "unlockCost": ser["unlockCost"], "unlocked": allowed,
        "canUse": allowed,
        "status": row["status"], "publishedAtMs": int(row["published_at_ms"] or 0),
        "styles": [], "layout": None,
    }


def _work_resource(row: dict[str, Any], unlocked: set[str], user) -> dict[str, Any]:
    ser = S._serialize_work(row, {}, unlocked, user)
    price = int(row["price"] or 0)
    is_staff = bool(user and user.get("role") in _STAFF)
    is_author = bool(user and user.get("username") == row["author_username"])
    is_unlocked = price <= 0 or row["id"] in unlocked or is_staff or is_author
    return {
        "id": ser["id"], "kind": "work", "title": ser["title"], "name": ser["title"],
        "notes": ser["notes"], "description": ser["notes"],
        "prompt": ser["prompt"] if is_unlocked else "",
        "subject": ser.get("subject", ""),
        "image": _image_of(ser["images"]), "images": [_local_image(_image_of([i])) for i in ser["images"]],
        "author": ser["author"], "authorName": ser["authorName"],
        "sourceType": "community", "tier": "paid" if price > 0 else "free",
        "price": price, "unlockCost": price,
        "unlocked": is_unlocked, "canUse": is_unlocked, "reproducible": bool(str(row["prompt"] or "").strip()),
        "promptMasked": bool(ser.get("promptMasked")),
        "status": row["status"], "publishedAtMs": int(row["published_at_ms"] or 0),
        "styles": ser["styles"], "layout": ser["layout"],
        **{key:ser[key] for key in ('ratio','mode','color','tone','mood','sc021Type','shootType') if key in ser},
    }


# ---------------------------------------------------------------------------
# Siblings (same topic submissions)
# ---------------------------------------------------------------------------

def _siblings(db, topic_id: str | None) -> list[dict[str, Any]]:
    if not topic_id:
        return []
    rows = db.get_conn().execute(
        "SELECT id, kind, target_id, status, current_revision FROM curation_submissions WHERE topic_id=? ORDER BY id",
        (topic_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        payload = _payload(db, dict(r)) or {}
        preview = C._safe_preview(payload)
        images = preview.get("images") or []
        out.append({
            "id": r["target_id"], "kind": r["kind"],
            "name": preview.get("name") or preview.get("title") or r["target_id"],
            "image": _image_of(images),
            "status": r["status"],
        })
    return out


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------


def _context(db, user, kind, target):
    kind, target = _norm(kind, target)
    conn = db.get_conn()
    kind = _resolve_kind(conn, kind, target)
    if kind not in ('style','layout','work') or not target:
        raise S.ServiceError('资源不存在或尚未收录', status=404)
    mapping = _mapping(db,kind,target)
    sub = _submission(db,kind,target)
    topic = _topic(conn,mapping['topic_id']) if mapping else None
    raw = RD.resolve_resource(conn,kind,target)
    published = raw is not None
    if published:
        if kind == 'work':
            resource = _work_resource(raw,_unlocked(db,user),user)
        elif 'code' in raw:
            resource = _asset_resource(raw,_unlocked(db,user),user)
        else:
            resource = _static_resource(raw,kind)
    else:
        # A hidden record is an authoritative override, never a static fallback.
        table,key = ('works','id') if kind=='work' else ('catalog_assets','code')
        exists = conn.execute(f'SELECT 1 FROM {table} WHERE {key}=?',(target,)).fetchone()
        if exists or not sub or not topic or topic['status']!='published' or mapping['origin']!='submission':
            raise S.ServiceError('资源不存在或尚未收录',status=404)
        preview = C._safe_preview(_payload(db,sub) or {})
        images = [_image_of([i]) for i in (preview.get('images') or ([preview['image']] if preview.get('image') else []))]
        resource = dict(preview,id=target,kind=kind,status=sub['status'],canUse=False,unlocked=False,
                        definition='',prompt='',images=images,image=_image_of(images),
                        author=sub['owner_username'],authorName=topic['author_name'],sourceType='community')
    return kind,target,resource,published,mapping,sub,topic


def _page(offset,limit,maximum):
    try:
        offset,limit = int(offset),int(limit)
    except (TypeError,ValueError):
        raise S.ServiceError('分页参数无效',status=400)
    if offset<0 or limit<1:
        raise S.ServiceError('分页参数无效',status=400)
    return offset,min(limit,maximum)


def _membership(alias):
    return f"EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid({alias}.styles_json) THEN {alias}.styles_json ELSE '[]' END) j WHERE j.value=?)"


def _sql_page(conn,table,where,args,q,sort,offset,limit,kind):
    alias='w' if table=='works' else 't'
    if q:
        where += f' AND (instr(lower({alias}.title),?)>0 OR instr(lower({alias}.author_name),?)>0 OR instr(lower({alias}.id),?)>0)'
        args += [q,q,q]
    count=int(conn.execute(f'SELECT COUNT(*) FROM {table} {alias} WHERE {where}',args).fetchone()[0])
    # One popularity formula per object type, shared with the rest of the app.
    # View counts are deliberately absent: they have no trusted write path and
    # anonymous deduplication would need cookie or IP fingerprints.
    from .ranking import work_popular_sql, topic_popular_sql, normalize_sort
    popularity = work_popular_sql(alias) if table == 'works' else topic_popular_sql(alias)
    order = popularity if normalize_sort(sort) == 'popular' else f'{alias}.published_at_ms'
    columns=f'{alias}.id,{alias}.title,{alias}.author_name,{alias}.images_json'
    rows=conn.execute(f'SELECT {columns} FROM {table} {alias} WHERE {where} ORDER BY {order} DESC,{alias}.id ASC LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
    return [{'id':r['id'],'kind':kind,'name':r['title'],'image':_image_of(_loads(r['images_json'],[])),'authorName':r['author_name']} for r in rows],count


def _asset_card(conn,kind,code,usage):
    raw=RD.resolve_resource(conn,kind,code)
    if not raw:
        return None
    return {'id':code,'kind':kind,'name':raw.get('name') or code,'description':raw.get('description',''),
            'image':_local_image(raw.get('image_url') or raw.get('image','')),'authorName':raw.get('author_name') or raw.get('authorName') or '官方',
            'usageCount':usage,'publishedAtMs':int(raw.get('published_at_ms') or raw.get('publishedAtMs') or 0)}


def _related_page(db,kind,target,resource,mapping,tab,q,sort,offset,limit):
    conn=db.get_conn()
    if tab=='works':
        sf,sp=S._seed_filter('w.id','works')
        match=_membership('w') if kind=='style' else 'w.layout_code=?'
        return _sql_page(conn,'works',f"w.status='published' AND TRIM(w.prompt)<>'' AND {sf} AND {match}",list(sp)+[target],q,sort,offset,limit,'work')
    if tab=='topics':
        sf,sp=S._seed_filter('t.id','topics')
        match=_membership('t') if kind=='style' else ('t.layout_code=?' if kind=='layout' else 't.work_id=?')
        where=f"t.status='published' AND {sf} AND {match}"
        args=list(sp)+[target]
        if mapping:
            where+=' AND t.id<>?';args.append(mapping['topic_id'])
        return _sql_page(conn,'forum_topics',where,args,q,sort,offset,limit,'topic')
    asset_kind='style' if tab=='styles' else 'layout'
    if kind=='work':
        codes=list(dict.fromkeys(resource.get('styles',[]))) if asset_kind=='style' else [resource.get('layout')]
        grouped=[(code,1) for code in codes if code]
    else:
        sf,sp=S._seed_filter('w.id','works')
        match=_membership('w') if kind=='style' else 'w.layout_code=?'
        if asset_kind=='style':
            sql=f"SELECT j.value code,COUNT(DISTINCT w.id) n FROM works w,json_each(CASE WHEN json_valid(w.styles_json) THEN w.styles_json ELSE '[]' END) j WHERE w.status='published' AND TRIM(w.prompt)<>'' AND {sf} AND {match} GROUP BY j.value"
        else:
            sql=f"SELECT w.layout_code code,COUNT(DISTINCT w.id) n FROM works w WHERE w.status='published' AND TRIM(w.prompt)<>'' AND {sf} AND {match} AND w.layout_code<>'' GROUP BY w.layout_code"
        grouped=[(r['code'],r['n']) for r in conn.execute(sql,list(sp)+[target]).fetchall()]
    # Only grouped catalog IDs are materialized to combine static and DB metadata.
    cards=[]
    for code,n in grouped:
        card=_asset_card(conn,asset_kind,code,n)
        if card and kind=='work':
            card.pop('usageCount',None)
        if card and (not q or q in ' '.join(str(card.get(k,'')) for k in ('id','name','description','authorName')).lower()):
            cards.append(card)
    cards.sort(key=lambda c:(-(c['usageCount'] if sort=='popular' else c['publishedAtMs']),c['id']))
    return cards[offset:offset+limit],len(cards)


def resource_detail(db,user,kind,target):
    kind,target,resource,published,mapping,sub,topic=_context(db,user,kind,target)
    thread,_=_thread_block(db.get_conn(),topic,kind,target)
    tabs=_WORK_TABS if kind=='work' else _ASSET_TABS[kind]
    relations=[]
    if published:
        for tab in tabs:
            items,total=_related_page(db,kind,target,resource,mapping,tab,'','newest',0,4)
            if total:
                relations.append({'tab':tab,'label':{'works':'关联作品','styles':'使用的画风' if kind=='work' else '搭配画风','layouts':'使用的图型' if kind=='work' else '搭配图型','topics':'相关讨论'}[tab],'total':total,'items':items})
    return {'ok':True,'resource':resource,'thread':thread,'curation':_curation_block(db,db.get_conn(),sub,published),
            'siblings':_siblings(db,topic['id']) if topic and topic['status']=='published' else [],'relations':relations}


def related_items(db,user,kind,target,tab,q='',sort='newest',offset=0,limit=24):
    kind,target,resource,published,mapping,_,_=_context(db,user,kind,target)
    tabs=_WORK_TABS if kind=='work' else _ASSET_TABS[kind]
    if tab not in tabs:
        raise S.ServiceError('无效的关联分类',status=400)
    offset,limit=_page(offset,limit,36)
    items,total=_related_page(db,kind,target,resource,mapping,tab,str(q).strip().lower()[:150],sort,offset,limit) if published else ([],0)
    return {'ok':True,'items':items,'total':total,'offset':offset,'limit':limit,'tab':tab}


def _comment_permissions(conn,user,row,ctype,category):
    if not user:
        return False,False
    own=user.get('username')==row['author_username']
    staff=user.get('role') in _STAFF
    mod=ctype=='forum_reply' and bool(conn.execute("SELECT 1 FROM forum_moderators WHERE user_id=? AND category IN ('all',?)",(user['id'],category)).fetchone())
    author=conn.execute('SELECT role FROM users WHERE username=?',(row['author_username'],)).fetchone()
    protected=author and author['role']=='admin' and user.get('role')!='admin' and not own
    manage=bool((staff or mod) and not protected)
    return bool(own or manage),manage


def resource_comments(db,user,kind,target,offset=0,limit=20):
    kind,target,_,_,mapping,_,topic=_context(db,user,kind,target)
    offset,limit=_page(offset,limit,50)
    result={'ok':True,'items':[],'total':0,'offset':offset,'limit':limit}
    if topic and topic['status']!='published':
        return result
    if not mapping or not mapping.get('topic_id'):
        return result
    table,where,args,ctype='forum_replies','topic_id=?',[mapping['topic_id']],'forum_reply'
    sf,sp=S._seed_filter('id',table)
    where+=f" AND status='published' AND {sf}";args+=list(sp)
    conn=db.get_conn()
    result['total']=int(conn.execute(f'SELECT COUNT(*) FROM {table} WHERE {where}',args).fetchone()[0])
    rows=conn.execute(f'SELECT * FROM {table} WHERE {where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',args+[limit,offset]).fetchall()
    for r in rows:
        delete,hide=_comment_permissions(conn,user,r,ctype,topic['category'] if topic else 'assets')
        result['items'].append({'id':r['id'],'user':r['author_username'],'name':r['author_name'],'text':r['text'],'time':r['time_label'],'type':ctype,'canDelete':delete,'canHide':hide})
    return result


def post_comment(db,user,kind,target,text):
    kind,target,_,_,_,_,topic=_context(db,user,kind,target)
    if topic and topic['status']!='published':
        raise S.ServiceError('讨论已暂停',status=409)
    return RD.comment(db,user,kind,target,text)

