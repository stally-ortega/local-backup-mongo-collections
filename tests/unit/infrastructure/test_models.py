"""Unit tests for SQLAlchemy ORM models."""

import os
from collections.abc import AsyncGenerator
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AppConfig
from app.infrastructure.persistence.database import (
    create_engine,
    create_session_factory,
    dispose_engine,
    init_database,
)
from app.infrastructure.persistence.models import (
    AuditLogORM,
    JobORM,
    RateLimitORM,
    UserORM,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("MONGO_OPS_"):
            monkeypatch.delenv(key, raising=False)


def _config() -> AppConfig:
    return AppConfig(
        telegram_bot_token="t",
        telegram_chat_id="-100",
        mongodb_uri="mongodb://localhost:27017",
        database_url="sqlite+aiosqlite:///:memory:",
    )


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    cfg = _config()
    engine = await create_engine(cfg)
    await init_database(engine)
    factory = await create_session_factory(engine)

    async with factory() as sess:
        yield sess

    await dispose_engine(engine)


class TestUserORM:
    async def test_create_and_fetch(self, session: AsyncSession) -> None:
        user = UserORM(
            telegram_id=123456789,
            username="test_user",
            role="ADMIN",
        )
        session.add(user)
        await session.commit()

        result = await session.execute(select(UserORM).where(UserORM.telegram_id == 123456789))
        fetched = result.scalar_one()

        assert fetched.telegram_id == 123456789
        assert fetched.username == "test_user"
        assert fetched.role == "ADMIN"
        assert fetched.is_active is True
        assert isinstance(fetched.created_at, datetime)

    async def test_unique_telegram_id(self, session: AsyncSession) -> None:
        session.add(UserORM(telegram_id=111, role="DBA"))
        await session.commit()

        session.add(UserORM(telegram_id=111, role="OPERATOR"))
        with pytest.raises(IntegrityError):
            await session.commit()


class TestJobORM:
    async def test_create_and_fetch(self, session: AsyncSession) -> None:
        job_id = str(uuid4())
        job = JobORM(
            id=job_id,
            requester_telegram_id=123,
            backup_type="FULL",
            status="PENDING",
            cluster_uri_hash="a" * 64,
            target_databases=["db1", "db2"],
        )
        session.add(job)
        await session.commit()

        result = await session.execute(select(JobORM).where(JobORM.id == job_id))
        fetched = result.scalar_one()

        assert fetched.id == job_id
        assert fetched.status == "PENDING"
        assert fetched.target_databases == ["db1", "db2"]
        assert fetched.retry_count == 0
        assert fetched.bytes_processed == 0


class TestAuditLogORM:
    async def test_create_and_fetch(self, session: AsyncSession) -> None:
        log = AuditLogORM(
            telegram_id=123,
            action="BACKUP_REQUESTED",
            topic="BACKUP_REQUESTS",
            command="/backup",
            result="SUCCESS",
            duration_ms=1500,
        )
        session.add(log)
        await session.commit()

        result = await session.execute(
            select(AuditLogORM).where(AuditLogORM.action == "BACKUP_REQUESTED")
        )
        fetched = result.scalar_one()

        assert fetched.telegram_id == 123
        assert fetched.result == "SUCCESS"
        assert isinstance(fetched.timestamp, datetime)


class TestRateLimitORM:
    async def test_create_and_fetch(self, session: AsyncSession) -> None:
        rl = RateLimitORM(
            telegram_id=123,
            action="BACKUP",
            window_start=datetime.utcnow(),
            count=3,
        )
        session.add(rl)
        await session.commit()

        result = await session.execute(select(RateLimitORM).where(RateLimitORM.action == "BACKUP"))
        fetched = result.scalar_one()

        assert fetched.telegram_id == 123
        assert fetched.count == 3


class TestTableExistence:
    async def test_all_model_tables_created(self) -> None:
        cfg = _config()
        engine = await create_engine(cfg)
        await init_database(engine)

        async with engine.connect() as conn:
            result = await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
            )
            tables = {row[0] for row in result}

        assert "users" in tables
        assert "jobs" in tables
        assert "audit_logs" in tables
        assert "rate_limits" in tables

        await dispose_engine(engine)
