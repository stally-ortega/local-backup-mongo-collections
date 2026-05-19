"""Unit tests for the async SQLAlchemy database layer."""

import os
from pathlib import Path

import pytest
from sqlalchemy import Column, Integer, String, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import AppConfig
from app.infrastructure.persistence.database import (
    Base,
    create_engine,
    create_session_factory,
    dispose_engine,
    init_database,
)


class _TestModel(Base):
    """Transient model used solely to verify DDL creation."""

    __tablename__ = "_test_table"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("MONGO_OPS_"):
            monkeypatch.delenv(key, raising=False)


def _config(database_url: str) -> AppConfig:
    return AppConfig(
        telegram_bot_token="t",
        telegram_chat_id="-100",
        mongodb_uri="mongodb://localhost:27017",
        database_url=database_url,
    )


class TestCreateEngine:
    async def test_creates_valid_async_engine(self) -> None:
        cfg = _config("sqlite+aiosqlite:///:memory:")
        engine = await create_engine(cfg)

        assert isinstance(engine, AsyncEngine)
        assert str(engine.url) == "sqlite+aiosqlite:///:memory:"

        await dispose_engine(engine)

    async def test_echo_disabled_by_default(self) -> None:
        cfg = _config("sqlite+aiosqlite:///:memory:")
        engine = await create_engine(cfg)

        assert engine.echo is False

        await dispose_engine(engine)

    async def test_echo_enabled_when_configured(self) -> None:
        cfg = _config("sqlite+aiosqlite:///:memory:")
        cfg.sqlalchemy_echo = True
        engine = await create_engine(cfg)

        assert engine.echo is True

        await dispose_engine(engine)

    async def test_dispose_idempotent(self) -> None:
        """Disposing an engine multiple times must not raise."""
        cfg = _config("sqlite+aiosqlite:///:memory:")
        engine = await create_engine(cfg)

        await dispose_engine(engine)
        await dispose_engine(engine)  # idempotent


class TestCreateSessionFactory:
    async def test_produces_async_session(self) -> None:
        cfg = _config("sqlite+aiosqlite:///:memory:")
        engine = await create_engine(cfg)
        factory = await create_session_factory(engine)

        async with factory() as session:
            assert isinstance(session, AsyncSession)
            assert session.bind == engine

        await dispose_engine(engine)


class TestInitDatabase:
    async def test_creates_registered_tables(self) -> None:
        cfg = _config("sqlite+aiosqlite:///:memory:")
        engine = await create_engine(cfg)

        await init_database(engine)

        async with engine.connect() as conn:
            result = await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
            )
            tables = {row[0] for row in result}

        assert "_test_table" in tables

        await dispose_engine(engine)


class TestFileDatabasePath:
    async def test_file_database_created_and_cleaned(self, tmp_path: Path) -> None:
        db_file = tmp_path / "test.db"
        cfg = _config(f"sqlite+aiosqlite:///{db_file}")
        engine = await create_engine(cfg)

        await init_database(engine)
        assert db_file.exists()

        await dispose_engine(engine)
