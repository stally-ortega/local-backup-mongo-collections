"""Unit tests for RedisLockManager."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.infrastructure.queue.redis_connection import RedisConnection
from app.infrastructure.queue.redis_lock_manager import RedisLockManager


@pytest.fixture
def redis_conn() -> Any:
    conn = RedisConnection("redis://localhost:6379/0")
    conn._client = MagicMock()
    return conn


@pytest.fixture
def manager(redis_conn: Any) -> RedisLockManager:
    return RedisLockManager(redis_conn)


class TestAcquire:
    async def test_returns_token_when_set_succeeds(
        self,
        manager: RedisLockManager,
        redis_conn: Any,
    ) -> None:
        redis_conn.client.set.return_value = True

        token = await manager.acquire("backup:global", ttl_seconds=120)

        assert token is not None
        assert len(token) == 36  # UUID
        redis_conn.client.set.assert_called_once()
        call_kwargs = redis_conn.client.set.call_args.kwargs
        assert call_kwargs.get("nx") is True
        assert call_kwargs.get("ex") == 120

    async def test_returns_none_when_lock_held(
        self,
        manager: RedisLockManager,
        redis_conn: Any,
    ) -> None:
        redis_conn.client.set.return_value = None

        token = await manager.acquire("backup:global")

        assert token is None


class TestRelease:
    async def test_returns_true_when_token_matches(
        self,
        manager: RedisLockManager,
        redis_conn: Any,
    ) -> None:
        redis_conn.client.eval.return_value = 1

        result = await manager.release("backup:global", "token-123")

        assert result is True
        redis_conn.client.eval.assert_called_once()

    async def test_returns_false_when_token_mismatch(
        self,
        manager: RedisLockManager,
        redis_conn: Any,
    ) -> None:
        redis_conn.client.eval.return_value = 0

        result = await manager.release("backup:global", "token-123")

        assert result is False

    async def test_returns_false_on_exception(
        self,
        manager: RedisLockManager,
        redis_conn: Any,
    ) -> None:
        redis_conn.client.eval.side_effect = ConnectionError("redis down")

        result = await manager.release("backup:global", "token-123")

        assert result is False


class TestIsLocked:
    async def test_returns_true_when_key_exists(
        self,
        manager: RedisLockManager,
        redis_conn: Any,
    ) -> None:
        redis_conn.client.exists.return_value = 1

        result = await manager.is_locked("backup:global")

        assert result is True

    async def test_returns_false_when_key_missing(
        self,
        manager: RedisLockManager,
        redis_conn: Any,
    ) -> None:
        redis_conn.client.exists.return_value = 0

        result = await manager.is_locked("backup:global")

        assert result is False

    async def test_returns_false_on_exception(
        self,
        manager: RedisLockManager,
        redis_conn: Any,
    ) -> None:
        redis_conn.client.exists.side_effect = ConnectionError("redis down")

        result = await manager.is_locked("backup:global")

        assert result is False
