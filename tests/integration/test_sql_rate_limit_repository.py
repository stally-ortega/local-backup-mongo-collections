"""Integration tests for SQLRateLimitRepository using an in-memory SQLite database."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.persistence.database import init_database
from app.infrastructure.persistence.sql_rate_limit_repository import SQLRateLimitRepository


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session bound to a fresh in-memory SQLite database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_database(engine)

    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


@pytest.fixture
def repo(db_session: AsyncSession) -> SQLRateLimitRepository:
    return SQLRateLimitRepository(session=db_session)


# ---------------------------------------------------------------------------
# check_limit
# ---------------------------------------------------------------------------


class TestSQLRateLimitRepositoryCheckLimit:
    @pytest.mark.asyncio
    async def test_returns_true_when_no_record(
        self,
        repo: SQLRateLimitRepository,
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
        repo: SQLRateLimitRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.increment(1, "BACKUP", window_seconds=60)
        await db_session.commit()

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
        repo: SQLRateLimitRepository,
        db_session: AsyncSession,
    ) -> None:
        for _ in range(5):
            await repo.increment(1, "BACKUP", window_seconds=60)
        await db_session.commit()

        assert (
            await repo.check_limit(
                telegram_id=1,
                action="BACKUP",
                max_allowed=5,
                window_seconds=60,
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_resets_after_window_expires(
        self,
        repo: SQLRateLimitRepository,
        db_session: AsyncSession,
    ) -> None:
        for _ in range(5):
            await repo.increment(1, "BACKUP", window_seconds=60)
        await db_session.commit()

        # Simulating window expiry by using a very small window
        assert (
            await repo.check_limit(
                telegram_id=1,
                action="BACKUP",
                max_allowed=5,
                window_seconds=0,
            )
            is True
        )


# ---------------------------------------------------------------------------
# increment
# ---------------------------------------------------------------------------


class TestSQLRateLimitRepositoryIncrement:
    @pytest.mark.asyncio
    async def test_creates_new_record(
        self,
        repo: SQLRateLimitRepository,
        db_session: AsyncSession,
    ) -> None:
        count = await repo.increment(1, "BACKUP", window_seconds=60)
        await db_session.commit()

        assert count == 1

    @pytest.mark.asyncio
    async def test_increments_existing_record(
        self,
        repo: SQLRateLimitRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.increment(1, "BACKUP", window_seconds=60)
        count = await repo.increment(1, "BACKUP", window_seconds=60)
        await db_session.commit()

        assert count == 2

    @pytest.mark.asyncio
    async def test_creates_separate_windows_per_action(
        self,
        repo: SQLRateLimitRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.increment(1, "BACKUP", window_seconds=60)
        count = await repo.increment(1, "SIZE_QUERY", window_seconds=60)
        await db_session.commit()

        assert count == 1

    @pytest.mark.asyncio
    async def test_creates_separate_windows_per_user(
        self,
        repo: SQLRateLimitRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.increment(1, "BACKUP", window_seconds=60)
        count = await repo.increment(2, "BACKUP", window_seconds=60)
        await db_session.commit()

        assert count == 1


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestSQLRateLimitRepositoryReset:
    @pytest.mark.asyncio
    async def test_removes_existing_records(
        self,
        repo: SQLRateLimitRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.increment(1, "BACKUP", window_seconds=60)
        await db_session.commit()

        await repo.reset(1, "BACKUP")
        await db_session.commit()

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
        repo: SQLRateLimitRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.reset(999, "BACKUP")
        await db_session.commit()

        assert (
            await repo.check_limit(
                telegram_id=999,
                action="BACKUP",
                max_allowed=5,
                window_seconds=60,
            )
            is True
        )
