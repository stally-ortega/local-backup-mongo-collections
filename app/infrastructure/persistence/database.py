"""Async SQLAlchemy engine, declarative base, and session factory.

The module is intentionally engine-agnostic: changing the ``database_url``
from ``sqlite+aiosqlite`` to ``postgresql+asyncpg`` requires no code
modification here.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import AppConfig


class Base(DeclarativeBase):
    """Declarative base for all ORM models.

    Inheriting from ``DeclarativeBase`` (SQLAlchemy 2.x) provides full
    typing support and keeps the base class lightweight.
    """


async def create_engine(config: AppConfig) -> AsyncEngine:
    """Create an ``AsyncEngine`` bound to the configured database URL.

    Args:
        config: Application settings containing ``database_url``.

    Returns:
        A SQLAlchemy async engine ready for connection pooling.
    """
    url = str(config.database_url)
    is_sqlite = url.startswith("sqlite")

    engine = create_async_engine(
        url,
        echo=config.log_level == "DEBUG",
        future=True,
        connect_args={"timeout": 15} if is_sqlite else {},
    )

    return engine


async def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Build an async session maker bound to *engine*.

    The returned factory creates sessions with ``expire_on_commit=False``
    so that ORM instances remain usable after a commit in async contexts.

    Args:
        engine: The async engine to bind sessions to.

    Returns:
        A factory callable that produces ``AsyncSession`` instances.
    """
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def init_database(engine: AsyncEngine) -> None:
    """Create all tables registered on ``Base.metadata``.

    Should be called once at application startup (e.g. inside a lifespan
    manager or a dedicated bootstrap script).

    Args:
        engine: The async engine used to execute DDL.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine(engine: AsyncEngine) -> None:
    """Gracefully close the connection pool and dispose of the engine.

    Should be called during application shutdown to avoid leaked
    connections and file descriptors.

    Args:
        engine: The async engine to dispose.
    """
    await engine.dispose()


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a transactional session and commit/rollback automatically.

    Intended for use as a FastAPI dependency or as an async context
    manager in service layers.

    Args:
        session_factory: Async session maker.

    Yields:
        An active ``AsyncSession``.
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
