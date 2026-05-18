"""Unit tests for :class:`~app.infrastructure.queue.redis_rate_limit_repository.RedisRateLimitRepository`.

Uses a ``fakeredis``-style mock so that no real Redis server is required.
"""

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.infrastructure.queue.redis_rate_limit_repository import RedisRateLimitRepository


@pytest.fixture
def mock_redis_client() -> MagicMock:
    """Return a fake Redis client with sorted-set semantics in memory."""
    client = MagicMock()
    _store: dict[str, dict[str, float]] = {}

    async def _eval(script: str, numkeys: int, key: str, *args: Any) -> int:
        """Simulate Lua script execution for trim-and-count operations."""
        window_start_ms = float(args[0]) if args else 0

        # Trim old entries
        if key in _store:
            _store[key] = {
                member: score for member, score in _store[key].items() if score > window_start_ms
            }

        # If this is the increment script, there are extra args:
        # [unique_member, now_ms, window_seconds]
        if len(args) >= 3:
            unique_member = args[1]
            now_ms_arg = float(args[2])
            if key not in _store:
                _store[key] = {}
            _store[key][unique_member] = now_ms_arg

        return len(_store.get(key, {}))

    async def _zremrangebyscore(key: str, min_score: float, max_score: float) -> None:
        if key in _store:
            _store[key] = {
                member: score
                for member, score in _store[key].items()
                if score < min_score or score > max_score
            }

    async def _zcard(key: str) -> int:
        return len(_store.get(key, {}))

    async def _zadd(key: str, mapping: dict[str, float]) -> None:
        if key not in _store:
            _store[key] = {}
        for member, score in mapping.items():
            _store[key][member] = score

    async def _expire(key: str, ttl: int) -> None:
        pass

    async def _delete(key: str) -> None:
        _store.pop(key, None)

    client.eval = _eval
    client.zremrangebyscore = _zremrangebyscore
    client.zcard = _zcard
    client.zadd = _zadd
    client.expire = _expire
    client.delete = _delete

    return client


@pytest.fixture
def repo(mock_redis_client: MagicMock) -> RedisRateLimitRepository:
    return RedisRateLimitRepository(mock_redis_client)


class TestCheckLimit:
    @pytest.mark.asyncio
    async def test_returns_true_when_no_record(
        self,
        repo: RedisRateLimitRepository,
    ) -> None:
        assert (
            await repo.check_limit(
                telegram_id=1,
                action="BACKUP",
                max_allowed=5,
                window_seconds=60,
            )
            is True
        )

    @pytest.mark.asyncio
    async def test_returns_true_when_under_limit(
        self,
        repo: RedisRateLimitRepository,
    ) -> None:
        await repo.increment(1, "BACKUP", window_seconds=60)
        assert (
            await repo.check_limit(
                telegram_id=1,
                action="BACKUP",
                max_allowed=5,
                window_seconds=60,
            )
            is True
        )

    @pytest.mark.asyncio
    async def test_returns_false_when_at_limit(
        self,
        repo: RedisRateLimitRepository,
    ) -> None:
        for _ in range(5):
            await repo.increment(1, "BACKUP", window_seconds=60)
        assert (
            await repo.check_limit(
                telegram_id=1,
                action="BACKUP",
                max_allowed=5,
                window_seconds=60,
            )
            is False
        )


class TestIncrement:
    @pytest.mark.asyncio
    async def test_creates_new_record(
        self,
        repo: RedisRateLimitRepository,
    ) -> None:
        count = await repo.increment(1, "BACKUP", window_seconds=60)
        assert count == 1

    @pytest.mark.asyncio
    async def test_increments_existing_record(
        self,
        repo: RedisRateLimitRepository,
    ) -> None:
        await repo.increment(1, "BACKUP", window_seconds=60)
        count = await repo.increment(1, "BACKUP", window_seconds=60)
        assert count == 2

    @pytest.mark.asyncio
    async def test_creates_separate_windows_per_action(
        self,
        repo: RedisRateLimitRepository,
    ) -> None:
        await repo.increment(1, "BACKUP", window_seconds=60)
        count = await repo.increment(1, "SIZE_QUERY", window_seconds=60)
        assert count == 1

    @pytest.mark.asyncio
    async def test_creates_separate_windows_per_user(
        self,
        repo: RedisRateLimitRepository,
    ) -> None:
        await repo.increment(1, "BACKUP", window_seconds=60)
        count = await repo.increment(2, "BACKUP", window_seconds=60)
        assert count == 1


class TestReset:
    @pytest.mark.asyncio
    async def test_removes_existing_records(
        self,
        repo: RedisRateLimitRepository,
    ) -> None:
        await repo.increment(1, "BACKUP", window_seconds=60)
        await repo.reset(1, "BACKUP")
        assert (
            await repo.check_limit(
                telegram_id=1,
                action="BACKUP",
                max_allowed=5,
                window_seconds=60,
            )
            is True
        )

    @pytest.mark.asyncio
    async def test_is_idempotent_for_missing_records(
        self,
        repo: RedisRateLimitRepository,
    ) -> None:
        await repo.reset(999, "BACKUP")
        assert (
            await repo.check_limit(
                telegram_id=999,
                action="BACKUP",
                max_allowed=5,
                window_seconds=60,
            )
            is True
        )


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_increments_remain_atomic(
        self,
        repo: RedisRateLimitRepository,
    ) -> None:
        """Simulate a race: many coroutines increment the same key concurrently.

        The Lua-script mock is synchronous, so the final count must equal
        the number of coroutines exactly (no lost updates).
        """
        coros = [repo.increment(1, "BACKUP", window_seconds=60) for _ in range(50)]
        results = await asyncio.gather(*coros)
        assert results[-1] == 50
        assert max(results) == 50
