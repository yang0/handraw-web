"""Cross-process Redis lease for durable generation reconciliation.

Only one process should reconcile a gateway task at a time. Redis stores
*coordination*, not generation history or wallet truth. A lost lease stops
processing additional tasks, and a compare-and-delete Lua script prevents a
former leader from unlocking a newer leader's lease.
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import secrets
import threading
from dataclasses import dataclass, field
from typing import Iterator

logger = logging.getLogger("handraw.jobs.lease")

_RENEW = """
if redis.call('GET',KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE',KEYS[1],tonumber(ARGV[2]))
end
return 0
"""
_UNLOCK = """
if redis.call('GET',KEYS[1]) == ARGV[1] then
  return redis.call('DEL',KEYS[1])
end
return 0
"""


@dataclass
class Lease:
    acquired: bool = False
    lost: threading.Event = field(default_factory=threading.Event)

    def valid(self) -> bool:
        return self.acquired and not self.lost.is_set()


@contextlib.contextmanager
def generation_reconcile_lease(ttl_seconds: int = 90) -> Iterator[Lease]:
    """An automatically renewed lease. Empty Redis config = single-process dev."""
    ttl_seconds = max(30, int(ttl_seconds))
    lease = Lease()
    url = os.environ.get("HANDRAW_REDIS_URL", "").strip()
    required = os.environ.get("HANDRAW_REDIS_REQUIRED", "").strip().lower() in {
        "1", "true", "yes",
    }
    if not url:
        if required:
            logger.error("Redis is required but unavailable; reconciliation skipped")
            yield lease
        else:
            lease.acquired = True
            yield lease
        return

    import redis
    prefix = os.environ.get("HANDRAW_REDIS_PREFIX", "handraw:prod").strip()
    if not re.fullmatch(r"[a-zA-Z0-9:_-]{1,100}", prefix):
        raise RuntimeError("Unsafe Redis coordination namespace")
    key = prefix + ":lease:generation-reconciler"
    token = secrets.token_hex(24)
    client = redis.Redis.from_url(
        url, socket_connect_timeout=3, socket_timeout=5, decode_responses=True,
    )
    try:
        lease.acquired = bool(client.set(key, token, nx=True, ex=ttl_seconds))
    except redis.RedisError:
        logger.exception("Redis lease acquisition failed; reconciliation skipped")
        yield lease
        return

    if not lease.acquired:
        yield lease
        return

    stopped = threading.Event()

    def heartbeat():
        while not stopped.wait(max(5, ttl_seconds // 3)):
            try:
                if int(client.eval(_RENEW, 1, key, token, ttl_seconds)) != 1:
                    lease.lost.set()
                    logger.warning("Reconciler lost Redis leadership")
                    return
            except redis.RedisError:
                lease.lost.set()
                logger.exception("Redis lease refresh failed; stop future tasks")
                return

    thread = threading.Thread(
        target=heartbeat, name="handraw-reconcile-lease", daemon=True,
    )
    thread.start()
    try:
        yield lease
    finally:
        stopped.set()
        thread.join(timeout=5)
        try:
            client.eval(_UNLOCK, 1, key, token)
        except redis.RedisError:
            logger.warning("Could not release Redis reconcile lease", exc_info=True)
