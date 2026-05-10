"""Redis connection manager with connection pooling and lifecycle hooks.

Wraps ``redis.Redis`` with configurable timeouts, health checks, and an
injectable design that mirrors :class:`~app.infrastructure.mongo.mongo_connection.MongoConnection`.
"""

import logging

import redis

from app.config import AppConfig

logger = logging.getLogger(__name__)

# Default connection-pool and socket parameters.
_DEFAULT_SOCKET_TIMEOUT_S: int = 5
_DEFAULT_SOCKET_CONNECT_TIMEOUT_S: int = 5
_DEFAULT_MAX_CONNECTIONS: int = 50


class RedisConnection:
    """Injectable wrapper around a single ``redis.Redis`` instance.

    Parameters
    ----------
    redis_url:
        Redis connection URL (``redis://`` or ``rediss://``).
    socket_timeout:
        Socket read timeout in seconds.
    socket_connect_timeout:
        Socket connection timeout in seconds.
    max_connections:
        Maximum number of connections in the pool.
    """

    def __init__(
        self,
        redis_url: str,
        *,
        socket_timeout: int = _DEFAULT_SOCKET_TIMEOUT_S,
        socket_connect_timeout: int = _DEFAULT_SOCKET_CONNECT_TIMEOUT_S,
        max_connections: int = _DEFAULT_MAX_CONNECTIONS,
    ) -> None:
        self._redis_url = redis_url
        self._socket_timeout = socket_timeout
        self._socket_connect_timeout = socket_connect_timeout
        self._max_connections = max_connections
        self._client: redis.Redis | None = None

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: AppConfig) -> "RedisConnection":
        """Build a connection from validated application settings."""
        return cls(
            redis_url=config.redis_url,
            socket_timeout=_DEFAULT_SOCKET_TIMEOUT_S,
            socket_connect_timeout=_DEFAULT_SOCKET_CONNECT_TIMEOUT_S,
            max_connections=_DEFAULT_MAX_CONNECTIONS,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Create the underlying ``redis.Redis`` client with a connection pool.

        Idempotent: calling twice replaces the client with a fresh one.
        """
        if self._client is not None:
            logger.warning("RedisConnection already open; recreating client")
            self.close()

        pool = redis.ConnectionPool.from_url(
            self._redis_url,
            max_connections=self._max_connections,
            socket_timeout=self._socket_timeout,
            socket_connect_timeout=self._socket_connect_timeout,
            decode_responses=True,
        )
        self._client = redis.Redis(connection_pool=pool)
        logger.debug("Redis client created for %s", self._redis_url)

    def close(self) -> None:
        """Close the client and release the connection pool."""
        if self._client is not None:
            self._client.close()
            self._client = None
            logger.debug("Redis client closed")

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def client(self) -> redis.Redis:
        """Return the active Redis client.

        Raises
        ------
        RuntimeError
            When :meth:`connect` has not been called.
        """
        if self._client is None:
            raise RuntimeError("RedisConnection not open; call connect() first")
        return self._client

    @property
    def is_open(self) -> bool:
        """Return ``True`` when the client has been created."""
        return self._client is not None

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def ping(self) -> bool:
        """Send ``PING`` to Redis.

        Returns ``True`` on success, ``False`` on any failure.
        """
        if self._client is None:
            return False
        try:
            return bool(self._client.ping())
        except Exception as exc:
            logger.warning("Redis ping failed: %s", exc)
            return False
