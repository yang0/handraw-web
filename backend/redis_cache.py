"""Shared Redis connection pools for response caches."""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=4)
def redis_cache_client(url: str):
    import redis

    return redis.Redis.from_url(
        url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True,
    )
