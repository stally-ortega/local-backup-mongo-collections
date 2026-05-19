"""Integration tests for SQLUserRepository using an in-memory SQLite database."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.domain.entities.user import User
from app.domain.value_objects.enums import UserRole
from app.infrastructure.persistence.database import init_database
from app.infrastructure.persistence.sql_user_repository import SQLUserRepository


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
def repo(db_session: AsyncSession) -> SQLUserRepository:
    return SQLUserRepository(session=db_session)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    telegram_id: int = 1,
    username: str = "alice",
    role: UserRole = UserRole.ADMIN,
    is_active: bool = True,
) -> User:
    return User(telegram_id=telegram_id, username=username, role=role, is_active=is_active)


# ---------------------------------------------------------------------------
# get_by_telegram_id
# ---------------------------------------------------------------------------


class TestSQLUserRepositoryGetByTelegramId:
    @pytest.mark.asyncio
    async def test_returns_user_when_found(
        self,
        repo: SQLUserRepository,
        db_session: AsyncSession,
    ) -> None:
        user = _make_user(telegram_id=42, username="bob")
        await repo.save(user)
        await db_session.commit()

        found = await repo.get_by_telegram_id(42)

        assert found is not None
        assert found.telegram_id == 42
        assert found.username == "bob"
        assert found.role == UserRole.ADMIN

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(
        self,
        repo: SQLUserRepository,
    ) -> None:
        result = await repo.get_by_telegram_id(999)
        assert result is None


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------


class TestSQLUserRepositoryListAll:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_users(
        self,
        repo: SQLUserRepository,
    ) -> None:
        users = await repo.list_all()
        assert users == []

    @pytest.mark.asyncio
    async def test_returns_all_users_ordered_by_created_at(
        self,
        repo: SQLUserRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.save(_make_user(telegram_id=1, username="first"))
        await repo.save(_make_user(telegram_id=2, username="second"))
        await db_session.commit()

        users = await repo.list_all()

        assert len(users) == 2
        assert users[0].telegram_id == 1
        assert users[1].telegram_id == 2

    @pytest.mark.asyncio
    async def test_paginates_users(
        self,
        repo: SQLUserRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.save(_make_user(telegram_id=1, username="first"))
        await repo.save(_make_user(telegram_id=2, username="second"))
        await repo.save(_make_user(telegram_id=3, username="third"))
        await db_session.commit()

        page1 = await repo.list_all(page=1, page_size=2)
        assert len(page1) == 2
        assert page1[0].telegram_id == 1
        assert page1[1].telegram_id == 2

        page2 = await repo.list_all(page=2, page_size=2)
        assert len(page2) == 1
        assert page2[0].telegram_id == 3


# ---------------------------------------------------------------------------
# count_all
# ---------------------------------------------------------------------------


class TestSQLUserRepositoryCountAll:
    @pytest.mark.asyncio
    async def test_returns_zero_when_empty(
        self,
        repo: SQLUserRepository,
    ) -> None:
        count = await repo.count_all()
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_total_users(
        self,
        repo: SQLUserRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.save(_make_user(telegram_id=1))
        await repo.save(_make_user(telegram_id=2))
        await db_session.commit()

        count = await repo.count_all()
        assert count == 2


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestSQLUserRepositorySave:
    @pytest.mark.asyncio
    async def test_inserts_new_user(
        self,
        repo: SQLUserRepository,
        db_session: AsyncSession,
    ) -> None:
        user = _make_user(telegram_id=7, username="charlie", role=UserRole.OPERATOR)
        await repo.save(user)
        await db_session.commit()

        found = await repo.get_by_telegram_id(7)
        assert found is not None
        assert found.username == "charlie"
        assert found.role == UserRole.OPERATOR

    @pytest.mark.asyncio
    async def test_updates_existing_user(
        self,
        repo: SQLUserRepository,
        db_session: AsyncSession,
    ) -> None:
        original = _make_user(telegram_id=8, username="dana", role=UserRole.READONLY)
        await repo.save(original)
        await db_session.commit()

        updated = User(
            telegram_id=8,
            username="dana_updated",
            role=UserRole.DBA,
            is_active=False,
        )
        await repo.save(updated)
        await db_session.commit()

        found = await repo.get_by_telegram_id(8)
        assert found is not None
        assert found.username == "dana_updated"
        assert found.role == UserRole.DBA
        assert found.is_active is False


# ---------------------------------------------------------------------------
# update_role
# ---------------------------------------------------------------------------


class TestSQLUserRepositoryUpdateRole:
    @pytest.mark.asyncio
    async def test_changes_role_and_returns_user(
        self,
        repo: SQLUserRepository,
        db_session: AsyncSession,
    ) -> None:
        user = _make_user(telegram_id=9, role=UserRole.OPERATOR)
        await repo.save(user)
        await db_session.commit()

        result = await repo.update_role(9, UserRole.ADMIN)
        await db_session.commit()

        assert result is not None
        assert result.role == UserRole.ADMIN

        found = await repo.get_by_telegram_id(9)
        assert found is not None
        assert found.role == UserRole.ADMIN

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_user(
        self,
        repo: SQLUserRepository,
    ) -> None:
        result = await repo.update_role(999, UserRole.ADMIN)
        assert result is None
