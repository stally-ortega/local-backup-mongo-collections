"""Unit tests for :class:`~app.infrastructure.queue.redis_rate_limit_repository.RedisRateLimitRepository`.

Uses a ``fakeredis``-style mock so that no real Redis server is required.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.queue.redis_rate_limit_repository import RedisRateLimitRepository


@pytest.fixture
def mock_redis_client() -> MagicMock:
    """Return a fake Redis client with sorted-set semantics in memory."""
    client = MagicMock()
    _store: dict[str, dict[str, float]] = {}

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

    client.zremrangebyscore = _zremrangebyscore
    client.zcard = _zcard
    client.zadd = _zadd
    client.expire = _expire
    client.delete = _delete

    return client


@pytest.fixture
def repo(mock_redis_client: MagicMock) -> RedisRateLimitRepository:
    with patch(
        "app.infrastructure.queue.redis_rate_limit_repository.RedisConnection"
    ) as mock_conn_cls:
        mock_conn = mock_conn_cls.return_value
        mock_conn.client = mock_redis_client
        return RedisRateLimitRepository(mock_conn)


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
