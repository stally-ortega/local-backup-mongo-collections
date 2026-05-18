"""Redis-backed implementation of :class:`~app.domain.repositories.repositories.IRateLimitRepository`.

Uses a Redis sorted set per ``(telegram_id, action)`` to implement a true
sliding-window rate limiter.  Each request is stored as a member with the
current timestamp (in milliseconds) as its score.  Old entries outside the
window are trimmed automatically, and the cardinality of the remaining set is
the current counter.

The key itself is given a TTL so that inactive windows auto-expire and do
not bloat Redis memory.

All write operations are executed atomically via Lua scripts to prevent
race conditions between trim, add, and count.
"""

import time
import uuid

import redis.asyncio as aioredis

from app.domain.repositories.repositories import IRateLimitRepository

# Atomic Lua script: trim old entries, add the current one, refresh TTL,
# and return the final cardinality of the sorted set.
_INCREMENT_SCRIPT = """
local key = KEYS[1]
local window_start_ms = tonumber(ARGV[1])
local unique_member = ARGV[2]
local now_ms = tonumber(ARGV[3])
local window_seconds = tonumber(ARGV[4])

redis.call('ZREMRANGEBYSCORE', key, 0, window_start_ms)
redis.call('ZADD', key, now_ms, unique_member)
redis.call('EXPIRE', key, window_seconds)
return redis.call('ZCARD', key)
"""

# Atomic Lua script: trim old entries and return the current cardinality.
_CHECK_SCRIPT = """
local key = KEYS[1]
local window_start_ms = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', key, 0, window_start_ms)
return redis.call('ZCARD', key)
"""


class RedisRateLimitRepository(IRateLimitRepository):
    """Sliding-window rate limiter backed by Redis sorted sets.

    Parameters
    ----------
    redis_client:
        An active ``redis.asyncio.Redis`` client.
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._client = redis_client

    @staticmethod
    def _key(telegram_id: int, action: str) -> str:
        return f"rate_limit:{telegram_id}:{action}"

    async def check_limit(
        self,
        telegram_id: int,
        action: str,
        max_allowed: int,
        window_seconds: int,
    ) -> bool:
        """Return ``True`` when the user has not exceeded the rate limit."""
        key = self._key(telegram_id, action)
        now_ms = int(time.time() * 1000)
        window_start_ms = now_ms - (window_seconds * 1000)

        current = await self._client.eval(
            _CHECK_SCRIPT,
            1,
            key,
            str(window_start_ms),
        )  # type: ignore[misc]
        return int(current) < max_allowed

    async def increment(
        self,
        telegram_id: int,
        action: str,
        window_seconds: int,
    ) -> int:
        """Bump the counter and return the new value.

        Executes trim, add, expire, and count atomically inside a Lua script
        so concurrent callers cannot observe stale cardinalities.
        """
        key = self._key(telegram_id, action)
        now_ms = int(time.time() * 1000)
        window_start_ms = now_ms - (window_seconds * 1000)
        unique_member = f"{now_ms}:{uuid.uuid4().hex[:8]}"

        count = await self._client.eval(
            _INCREMENT_SCRIPT,
            1,
            key,
            str(window_start_ms),
            unique_member,
            str(now_ms),
            str(window_seconds),
        )  # type: ignore[misc]
        return int(count)

    async def reset(self, telegram_id: int, action: str) -> None:
        """Zero out the counter for the given user and action."""
        await self._client.delete(self._key(telegram_id, action))
