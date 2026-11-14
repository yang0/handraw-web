"""Cross-process Redis rate limiting for production authentication endpoints.

Fixed-window rate limits are stricter than the legacy in-process token buckets.
Secrets, raw IP addresses, and usernames never appear in Redis keys.
Redis unavailability fails CLOSED in production to prevent bypassing a shared
authentication limiter. Local development can explicitly use the process limiter.
"""
from __future__ import annotations

import hashlib
import os
from functools import lru_cache


_LIMITS = {
    "fulltext-search": (120, 60),
    "planning": (12, 60),
    "client_error": (20, 60),
    "login": (8, 300),
    "register": (5, 900),
    "reset": (5, 900),
    "verification": (5, 900),
    "oauth": (8, 300),
    "oauth_callback": (12, 300),
    "oauth_unlink": (5, 900),
    "funnel": (100, 60),
    "device": (10, 300),
    "skill_token": (1200, 3600),
}

# Redis executes the increment + expiry decision atomically.
# An expired key is recreated with its full TTL; no races between workers.
_RATE_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return count <= tonumber(ARGV[2]) and 1 or 0
"""


def redis_required() -> bool:
    return os.environ.get("HANDRAW_REDIS_REQUIRED", "").strip().lower() in {"1", "true", "yes"}


@lru_cache(maxsize=8)
def _connect(url: str):
    import redis
    client = redis.Redis.from_url(
        url, socket_timeout=1.0, socket_connect_timeout=1.0,
        retry_on_timeout=False, decode_responses=True,
        health_check_interval=30,
    )
    client.ping()
    return client


def ping() -> bool:
    url = os.environ.get("HANDRAW_REDIS_URL", "").strip()
    if not url:
        return not redis_required()
    try:
        return bool(_connect(url).ping())
    except Exception:
        return False


def check_limit(scope: str, subject: str) -> bool | None:
    """True/False with Redis; None means use existing local limiter.

    When HANDRAW_REDIS_REQUIRED=1, both a missing URL and a transient Redis
    outage deny authentication writes. Never silently fall back to per-worker
    memory in production.
    """
    url = os.environ.get("HANDRAW_REDIS_URL", "").strip()
    if not url:
        return False if redis_required() else None
    cap, window = _LIMITS.get(scope, _LIMITS["login"])
    namespace = os.environ.get("HANDRAW_REDIS_PREFIX", "handraw:prod").strip()
    if not namespace or len(namespace) > 60 or not all(
        c.isascii() and (c.isalnum() or c in ":-_") for c in namespace
    ):
        return False
    digest = hashlib.sha256((scope + ":" + subject).encode("utf-8")).hexdigest()
    key = namespace + ":rate:" + scope + ":" + digest
    try:
        client = _connect(url)
        return bool(int(client.eval(_RATE_LUA, 1, key, window, cap)))
    except Exception:
        # Redis is the security boundary for multi-worker authentication.
        return False


def ensure_ready() -> None:
    """Fail startup when production has explicitly requested Redis security."""
    if redis_required() and not ping():
        raise RuntimeError("生产认证限流要求 Redis 可用；请检查 HANDRAW_REDIS_URL 和访问权限")
