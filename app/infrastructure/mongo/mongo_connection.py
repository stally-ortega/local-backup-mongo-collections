"""Async MongoDB connection manager using Motor.

Wraps :class:`motor.motor_asyncio.AsyncIOMotorClient` with configurable
timeouts, lifecycle management, and a lightweight health-check.
"""

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import AppConfig

logger = logging.getLogger(__name__)


class MongoConnection:
    """Injectable wrapper around a single ``AsyncIOMotorClient`` instance.

    Parameters
    ----------
    uri:
        MongoDB connection string (``mongodb://`` or ``mongodb+srv://``).
    server_selection_timeout_ms:
        Maximum time (ms) to wait for server selection before raising.
    connect_timeout_ms:
        Maximum time (ms) to establish a TCP connection.
    socket_timeout_ms:
        Maximum time (ms) for individual socket operations.
    max_pool_size:
        Maximum number of connections in the pool.
    """

    def __init__(
        self,
        uri: str,
        *,
        server_selection_timeout_ms: int = 5_000,
        connect_timeout_ms: int = 5_000,
        socket_timeout_ms: int = 10_000,
        max_pool_size: int = 50,
    ) -> None:
        self._uri = uri
        self._server_selection_timeout_ms = server_selection_timeout_ms
        self._connect_timeout_ms = connect_timeout_ms
        self._socket_timeout_ms = socket_timeout_ms
        self._max_pool_size = max_pool_size
        self._client: AsyncIOMotorClient[Any] | None = None

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: AppConfig) -> "MongoConnection":
        """Build a connection from validated application settings."""
        return cls(
            uri=config.mongodb_uri,
            server_selection_timeout_ms=5_000,
            connect_timeout_ms=5_000,
            socket_timeout_ms=10_000,
            max_pool_size=50,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Create the underlying ``AsyncIOMotorClient``.

        Idempotent: calling twice replaces the client with a fresh one.
        """
        if self._client is not None:
            logger.warning("MongoConnection already open; recreating client")
            self.close()

        self._client = AsyncIOMotorClient(
            self._uri,
            serverSelectionTimeoutMS=self._server_selection_timeout_ms,
            connectTimeoutMS=self._connect_timeout_ms,
            socketTimeoutMS=self._socket_timeout_ms,
            maxPoolSize=self._max_pool_size,
        )
        logger.debug("AsyncIOMotorClient created for %s", self._uri_masked)

    def close(self) -> None:
        """Close the client and release the connection pool."""
        if self._client is not None:
            self._client.close()
            self._client = None
            logger.debug("AsyncIOMotorClient closed")

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def client(self) -> AsyncIOMotorClient[Any]:
        """Return the active Motor client.

        Raises
        ------
        RuntimeError
            When :meth:`connect` has not been called.
        """
        if self._client is None:
            raise RuntimeError("MongoConnection not open; call connect() first")
        return self._client

    @property
    def is_open(self) -> bool:
        """Return ``True`` when the client has been created."""
        return self._client is not None

    @property
    def _uri_masked(self) -> str:
        """Obfuscate credentials for safe logging."""
        # Simple mask: keep only scheme and host.
        try:
            from urllib.parse import urlparse

            parsed = urlparse(self._uri)
            scheme = parsed.scheme or "mongodb"
            host = parsed.hostname or "unknown"
            return f"{scheme}://***@{host}"
        except Exception:
            return "mongodb://***"

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def ping(self) -> bool:
        """Send ``{ping: 1}`` to the admin database.

        Returns ``True`` on success, ``False`` on any failure.
        """
        if self._client is None:
            return False
        try:
            await self._client.admin.command("ping")
            return True
        except Exception as exc:
            logger.warning("MongoDB ping failed: %s", exc)
            return False
