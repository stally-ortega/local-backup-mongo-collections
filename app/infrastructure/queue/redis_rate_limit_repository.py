"""Redis-backed implementation of :class:`~app.domain.repositories.repositories.IRateLimitRepository`.

Uses a Redis sorted set per ``(telegram_id, action)`` to implement a true
sliding-window rate limiter.  Each request is stored as a member with the
current timestamp (in milliseconds) as its score.  Old entries outside the
window are trimmed automatically, and the cardinality of the remaining set is
the current counter.

The key itself is given a TTL so that inactive windows auto-expire and do
not bloat Redis memory.
"""

import time
import uuid

from app.domain.repositories.repositories import IRateLimitRepository
from app.infrastructure.queue.redis_connection import RedisConnection


class RedisRateLimitRepository(IRateLimitRepository):
    """Sliding-window rate limiter backed by Redis sorted sets.

    Parameters
    ----------
    redis_connection:
        An open :class:`~app.infrastructure.queue.redis_connection.RedisConnection`.
    """

    def __init__(self, redis_connection: RedisConnection) -> None:
        self._redis = redis_connection

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

        client = self._redis.client
        # Remove entries older than the sliding window.
        await client.zremrangebyscore(key, 0, window_start_ms)
        current = int(await client.zcard(key))
        return current < max_allowed

    async def increment(
        self,
        telegram_id: int,
        action: str,
        window_seconds: int,
    ) -> int:
        """Bump the counter and return the new value.

        Adds the current timestamp to the sorted set and refreshes the key TTL.
        """
        key = self._key(telegram_id, action)
        now_ms = int(time.time() * 1000)
        window_start_ms = now_ms - (window_seconds * 1000)

        client = self._redis.client
        # Trim old entries before counting.
        await client.zremrangebyscore(key, 0, window_start_ms)
        # Add current request with a unique member so that collisions within
        # the same millisecond do not overwrite previous entries.
        unique_member = f"{now_ms}:{uuid.uuid4().hex[:8]}"
        await client.zadd(key, {unique_member: now_ms})
        # Ensure the key expires after the full window has passed.
        await client.expire(key, window_seconds)

        return int(await client.zcard(key))

    async def reset(self, telegram_id: int, action: str) -> None:
        """Zero out the counter for the given user and action."""
        await self._redis.client.delete(self._key(telegram_id, action))
