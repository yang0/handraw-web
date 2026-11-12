"""Cache the ordered work IDs for a browsing session."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass

from .redis_cache import redis_cache_client


logger = logging.getLogger("handraw.works_feed")
_TTL_SECONDS = 1800
_MAX_SESSIONS = 128
_LOCAL_LOCK = threading.Lock()
_LOCAL_SESSIONS: dict[tuple, tuple[float, PopularSession]] = {}

# The index stores expiry times. The payload hash and expiry index use one
# Redis slot and are pruned together before each write.
_READ = """
local now = tonumber(redis.call('TIME')[1])
local expiry = redis.call('ZSCORE', KEYS[2], ARGV[1])
if not expiry or tonumber(expiry) <= now then
    return false
end
return redis.call('HGET', KEYS[1], ARGV[1])
"""
_WRITE = """
local now = tonumber(ARGV[5])
local expired = redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', now)
for _, session in ipairs(expired) do
    redis.call('HDEL', KEYS[1], session)
    redis.call('ZREM', KEYS[2], session)
end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
redis.call('ZADD', KEYS[2], now + tonumber(ARGV[3]), ARGV[1])
local overflow = redis.call('ZCARD', KEYS[2]) - tonumber(ARGV[4])
if overflow > 0 then
    local oldest = redis.call('ZRANGE', KEYS[2], 0, overflow - 1)
    for _, session in ipairs(oldest) do
        redis.call('HDEL', KEYS[1], session)
        redis.call('ZREM', KEYS[2], session)
    end
end
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('EXPIRE', KEYS[2], ARGV[3])
return 1
"""


@dataclass(frozen=True)
class PopularSession:
    filter_key: str
    ordered_ids: tuple[str, ...]


def session_filter_key(user_id: int | None, filters: tuple, demo: bool) -> str:
    data = json.dumps((user_id, filters, demo), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class PopularSessions:
    def __init__(self, db, conn):
        url = os.environ.get("HANDRAW_REDIS_URL", "").strip()
        prefix = os.environ.get("HANDRAW_REDIS_PREFIX", "handraw:prod").strip()
        scope = getattr(conn, "cache_scope", None)
        self.local_scope = (url, prefix, scope or db)
        self.redis_url = url
        self.redis_keys = None
        if url and scope and re.fullmatch(r"[a-zA-Z0-9:_-]{1,100}", prefix):
            namespace = f"{prefix}:popular-works:v1:{{{scope}}}"
            self.redis_keys = (namespace + ":payloads", namespace + ":expires")

    def get(self, session_id: str) -> PopularSession | None:
        if self.redis_keys:
            try:
                raw = redis_cache_client(self.redis_url).eval(
                    _READ, 2, *self.redis_keys, session_id,
                )
                if raw:
                    filter_key, ids = json.loads(raw)
                    if isinstance(filter_key, str) and isinstance(ids, list) and all(
                        isinstance(item, str) for item in ids
                    ):
                        return PopularSession(filter_key, tuple(ids))
            except (TypeError, ValueError):
                pass  # Treat an invalid cache value as expired.
            except Exception:
                logger.warning("Popular works session cache unavailable")
        key = (*self.local_scope, session_id)
        with _LOCAL_LOCK:
            value = _LOCAL_SESSIONS.get(key)
            if value:
                expiry, session = value
                if expiry > time.monotonic():
                    return session
                _LOCAL_SESSIONS.pop(key, None)
        return None

    def put(self, session_id: str, session: PopularSession) -> None:
        key = (*self.local_scope, session_id)
        if self.redis_keys:
            try:
                data = json.dumps((session.filter_key, session.ordered_ids), separators=(",", ":"))
                client = redis_cache_client(self.redis_url)
                seconds, microseconds = client.time()
                client.eval(
                    _WRITE, 2, *self.redis_keys, session_id, data, _TTL_SECONDS, _MAX_SESSIONS,
                    seconds + microseconds / 1_000_000,
                )
            except Exception:
                logger.warning("Popular works session cache write failed; keeping the session locally")
            else:
                with _LOCAL_LOCK:
                    _LOCAL_SESSIONS.pop(key, None)
                return
        with _LOCAL_LOCK:
            now = time.monotonic()
            for expired in [entry for entry, (expiry, _) in _LOCAL_SESSIONS.items() if expiry <= now]:
                _LOCAL_SESSIONS.pop(expired, None)
            _LOCAL_SESSIONS.pop(key, None)
            while len(_LOCAL_SESSIONS) >= _MAX_SESSIONS:
                _LOCAL_SESSIONS.pop(next(iter(_LOCAL_SESSIONS)))
            _LOCAL_SESSIONS[key] = (now + _TTL_SECONDS, session)
