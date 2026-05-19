"""Unit tests for RedisConnection."""

from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig
from app.infrastructure.queue.redis_connection import RedisConnection


class TestRedisConnectionLifecycle:
    def test_client_raises_before_connect(self) -> None:
        conn = RedisConnection("redis://localhost:6379/0")
        with pytest.raises(RuntimeError, match="not open"):
            _ = conn.client

    def test_is_open_false_before_connect(self) -> None:
        conn = RedisConnection("redis://localhost:6379/0")
        assert conn.is_open is False

    @patch("app.infrastructure.queue.redis_connection.redis.ConnectionPool.from_url")
    @patch("app.infrastructure.queue.redis_connection.redis.Redis")
    def test_connect_creates_client(
        self,
        mock_redis_cls: MagicMock,
        mock_pool_from_url: MagicMock,
    ) -> None:
        mock_pool = MagicMock()
        mock_pool_from_url.return_value = mock_pool
        mock_instance = MagicMock()
        mock_redis_cls.return_value = mock_instance

        conn = RedisConnection("redis://localhost:6379/0")
        conn.connect()

        assert conn.is_open is True
        assert conn.client is mock_instance
        mock_pool_from_url.assert_called_once()
        mock_redis_cls.assert_called_once_with(connection_pool=mock_pool)

    @patch("app.infrastructure.queue.redis_connection.redis.ConnectionPool.from_url")
    @patch("app.infrastructure.queue.redis_connection.redis.Redis")
    def test_connect_recreates_when_already_open(
        self,
        mock_redis_cls: MagicMock,
        _mock_pool: MagicMock,
    ) -> None:
        first = MagicMock()
        second = MagicMock()
        mock_redis_cls.side_effect = [first, second]

        conn = RedisConnection("redis://localhost:6379/0")
        conn.connect()
        conn.connect()

        assert conn.client is second
        first.close.assert_called_once()
        assert mock_redis_cls.call_count == 2

    @patch("app.infrastructure.queue.redis_connection.redis.ConnectionPool.from_url")
    @patch("app.infrastructure.queue.redis_connection.redis.Redis")
    def test_close_is_idempotent(
        self,
        mock_redis_cls: MagicMock,
        _mock_pool: MagicMock,
    ) -> None:
        mock_instance = MagicMock()
        mock_redis_cls.return_value = mock_instance

        conn = RedisConnection("redis://localhost:6379/0")
        conn.connect()
        conn.close()
        conn.close()

        assert conn.is_open is False
        mock_instance.close.assert_called_once()


class TestRedisConnectionPing:
    @patch("app.infrastructure.queue.redis_connection.redis.ConnectionPool.from_url")
    @patch("app.infrastructure.queue.redis_connection.redis.Redis")
    async def test_ping_returns_true_on_success(
        self,
        mock_redis_cls: MagicMock,
        _mock_pool: MagicMock,
    ) -> None:
        mock_instance = MagicMock()
        mock_instance.ping.return_value = True
        mock_redis_cls.return_value = mock_instance

        conn = RedisConnection("redis://localhost:6379/0")
        conn.connect()
        result = await conn.ping()

        assert result is True
        mock_instance.ping.assert_called_once()

    @patch("app.infrastructure.queue.redis_connection.redis.ConnectionPool.from_url")
    @patch("app.infrastructure.queue.redis_connection.redis.Redis")
    async def test_ping_returns_false_on_exception(
        self,
        mock_redis_cls: MagicMock,
        _mock_pool: MagicMock,
    ) -> None:
        mock_instance = MagicMock()
        mock_instance.ping.side_effect = ConnectionError("refused")
        mock_redis_cls.return_value = mock_instance

        conn = RedisConnection("redis://localhost:6379/0")
        conn.connect()
        result = await conn.ping()

        assert result is False

    async def test_ping_returns_false_when_not_connected(self) -> None:
        conn = RedisConnection("redis://localhost:6379/0")
        result = await conn.ping()
        assert result is False


class TestRedisConnectionFromConfig:
    @patch("app.infrastructure.queue.redis_connection.redis.ConnectionPool.from_url")
    @patch("app.infrastructure.queue.redis_connection.redis.Redis")
    def test_from_config_uses_url(
        self,
        mock_redis_cls: MagicMock,
        mock_pool_from_url: MagicMock,
    ) -> None:
        cfg = AppConfig(
            telegram_bot_token="t",
            telegram_chat_id="-100",
            mongodb_uri="mongodb://localhost:27017",
            database_url="sqlite+aiosqlite:///:memory:",
            redis_url="redis://cache.example.com:6380/1",
        )
        conn = RedisConnection.from_config(cfg)
        conn.connect()

        call_args = mock_pool_from_url.call_args
        assert call_args is not None
        assert call_args.kwargs.get("max_connections") == 50
