"""Redis-backed implementation of :class:`~app.application.ports.ports.ILockManager`.

Uses ``SET resource token NX EX ttl`` for atomic acquire and a Lua script
for safe check-and-release to avoid dropping locks owned by other processes.
"""

import logging
import uuid

import redis.asyncio as aioredis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Lua script: delete the key only when the stored value matches the token.
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class RedisLockManager:
    """Distributed lock manager backed by a single Redis instance.

    Parameters
    ----------
    redis_client:
        An active ``redis.asyncio.Redis`` client.
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._client = redis_client

    async def acquire(
        self,
        resource: str,
        *,
        ttl_seconds: int = 60,
    ) -> str | None:
        """Attempt to acquire a lock on *resource*.

        Returns
        -------
        A unique token on success, or ``None`` when the lock is already held.
        """
        token = str(uuid.uuid4())
        # ``nx=True`` → set only if key does not exist.
        # ``ex=ttl_seconds`` → auto-expire to avoid dead locks.
        acquired = await self._client.set(resource, token, nx=True, ex=ttl_seconds)
        if acquired is True:
            logger.debug("Lock acquired %s (token=%s)", resource, token)
            return token
        logger.debug("Lock not acquired %s", resource)
        return None

    async def release(self, resource: str, token: str) -> bool:
        """Release a lock previously acquired with *token*.

        Returns
        -------
        ``True`` when the lock existed and the token matched, ``False`` otherwise.
        """
        try:
            result = await self._client.eval(_RELEASE_SCRIPT, 1, resource, token)  # type: ignore[misc]
            released = bool(result)
            if released:
                logger.debug("Lock released %s", resource)
            else:
                logger.warning(
                    "Lock release failed %s (token mismatch or expired)",
                    resource,
                )
            return released
        except RedisError as exc:
            logger.warning("Lock release error %s: %s", resource, exc)
            return False

    async def is_locked(self, resource: str) -> bool:
        """Return ``True`` when *resource* currently holds a lock."""
        try:
            return bool(await self._client.exists(resource))
        except RedisError as exc:
            logger.warning("Lock check error %s: %s", resource, exc)
            return False
