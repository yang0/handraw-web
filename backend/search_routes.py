"""HTTP boundary for search and administrator-only index operations."""
from . import search_service as service


def handle_get(handler, path, qs):
    if path == '/api/search':
        user = handler._current_user(required=False)
        handler._enforce_auth_rate_limit('fulltext-search', str((user or {}).get('id') or 'guest'))
        handler._send_json(service.search(handler.db,user,{k:v[0] for k,v in qs.items()}))
    elif path == '/api/admin/search':
        service.admin_required(handler._current_user(required=True))
        handler._send_json(service.status(handler.db))
    else:
        return False
    return True


def handle_post(handler,path,body):
    if path not in ('/api/admin/search/rebuild','/api/admin/search/retry'):
        return False
    user = handler._current_user(required=True)
    service.admin_required(user)
    if path.endswith('/rebuild'):
        result = service.request_rebuild(handler.db,str(body.get('channel') or 'all'),user)
    else:
        result = service.retry_events(handler.db,user)
    handler._send_json(result)
    return True
