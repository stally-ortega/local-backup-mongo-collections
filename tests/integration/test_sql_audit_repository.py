"""Integration tests for SQLAuditRepository using an in-memory SQLite database."""

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.domain.entities.audit_log import AuditLog
from app.infrastructure.persistence.database import init_database
from app.infrastructure.persistence.sql_audit_repository import SQLAuditRepository


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
def repo(db_session: AsyncSession) -> SQLAuditRepository:
    return SQLAuditRepository(session=db_session)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_audit(
    telegram_id: int = 1,
    action: str = "TEST_ACTION",
    topic: str = "TEST_TOPIC",
    timestamp: datetime | None = None,
) -> AuditLog:
    return AuditLog(
        telegram_id=telegram_id,
        action=action,
        topic=topic,
        result="SUCCESS",
        timestamp=timestamp or datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------


class TestSQLAuditRepositoryLog:
    @pytest.mark.asyncio
    async def test_persists_entry(
        self,
        repo: SQLAuditRepository,
        db_session: AsyncSession,
    ) -> None:
        entry = _make_audit(telegram_id=42, action="BACKUP_REQUESTED")
        await repo.log(entry)
        await db_session.commit()

        found = await repo.list_by_user(42)
        assert len(found) == 1
        assert found[0].action == "BACKUP_REQUESTED"

    @pytest.mark.asyncio
    async def test_assigns_auto_increment_id(
        self,
        repo: SQLAuditRepository,
        db_session: AsyncSession,
    ) -> None:
        entry = _make_audit()
        await repo.log(entry)
        await db_session.commit()

        # AuditLog is frozen; we verify persistence via query instead of mutating entry.id.
        found = await repo.list_by_user(entry.telegram_id)
        assert len(found) == 1
        assert isinstance(found[0].id, int)

    @pytest.mark.asyncio
    async def test_round_trips_json_fields(
        self,
        repo: SQLAuditRepository,
        db_session: AsyncSession,
    ) -> None:
        entry = AuditLog(
            telegram_id=99,
            action="BACKUP_REQUESTED",
            topic="BACKUP_REQUESTS",
            job_id="job-abc",
            cluster_uri_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            databases=["db1", "db2"],
            collections=["col1", "col2"],
            result="SUCCESS",
            details={"size": 1024},
            timestamp=datetime.now(timezone.utc),
        )
        await repo.log(entry)
        await db_session.commit()

        found = await repo.list_by_user(99)
        assert len(found) == 1
        assert found[0].job_id == "job-abc"
        assert (
            found[0].cluster_uri_hash
            == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        assert found[0].databases == ["db1", "db2"]
        assert found[0].collections == ["col1", "col2"]
        assert found[0].details == {"size": 1024}


# ---------------------------------------------------------------------------
# list_by_user
# ---------------------------------------------------------------------------


class TestSQLAuditRepositoryListByUser:
    @pytest.mark.asyncio
    async def test_returns_entries_for_user(
        self,
        repo: SQLAuditRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.log(_make_audit(telegram_id=1, action="A1"))
        await repo.log(_make_audit(telegram_id=1, action="A2"))
        await repo.log(_make_audit(telegram_id=2, action="A3"))
        await db_session.commit()

        entries = await repo.list_by_user(1)
        assert len(entries) == 2
        assert {e.action for e in entries} == {"A1", "A2"}

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_entries(
        self,
        repo: SQLAuditRepository,
    ) -> None:
        entries = await repo.list_by_user(99)
        assert entries == []

    @pytest.mark.asyncio
    async def test_orders_by_timestamp_descending(
        self,
        repo: SQLAuditRepository,
        db_session: AsyncSession,
    ) -> None:
        now = datetime.now(timezone.utc)
        await repo.log(_make_audit(telegram_id=5, action="OLD", timestamp=now - timedelta(hours=1)))
        await repo.log(_make_audit(telegram_id=5, action="NEW", timestamp=now))
        await db_session.commit()

        entries = await repo.list_by_user(5)
        assert entries[0].action == "NEW"
        assert entries[1].action == "OLD"

    @pytest.mark.asyncio
    async def test_paginates_results(
        self, repo: SQLAuditRepository, db_session: AsyncSession
    ) -> None:
        now = datetime.now(timezone.utc)
        for i in range(5):
            await repo.log(
                _make_audit(telegram_id=7, action=f"A{i}", timestamp=now - timedelta(minutes=i))
            )
        await db_session.commit()

        page1 = await repo.list_by_user(7, page=1, page_size=2)
        assert len(page1) == 2
        assert page1[0].action == "A0"
        assert page1[1].action == "A1"

        page2 = await repo.list_by_user(7, page=2, page_size=2)
        assert len(page2) == 2
        assert page2[0].action == "A2"
        assert page2[1].action == "A3"

        page3 = await repo.list_by_user(7, page=3, page_size=2)
        assert len(page3) == 1
        assert page3[0].action == "A4"


# ---------------------------------------------------------------------------
# list_by_job
# ---------------------------------------------------------------------------


class TestSQLAuditRepositoryListByJob:
    @pytest.mark.asyncio
    async def test_returns_entries_for_job(
        self,
        repo: SQLAuditRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.log(
            AuditLog(
                telegram_id=1,
                action="JOB_QUEUED",
                topic="JOB_EVENTS",
                job_id="job-001",
                result="SUCCESS",
                timestamp=datetime.now(timezone.utc),
            )
        )
        await repo.log(
            AuditLog(
                telegram_id=1,
                action="JOB_STARTED",
                topic="JOB_EVENTS",
                job_id="job-001",
                result="SUCCESS",
                timestamp=datetime.now(timezone.utc),
            )
        )
        await repo.log(
            AuditLog(
                telegram_id=1,
                action="JOB_QUEUED",
                topic="JOB_EVENTS",
                job_id="job-002",
                result="SUCCESS",
                timestamp=datetime.now(timezone.utc),
            )
        )
        await db_session.commit()

        entries = await repo.list_by_job("job-001")
        assert len(entries) == 2
        assert all(e.job_id == "job-001" for e in entries)

    @pytest.mark.asyncio
    async def test_paginates_results(
        self, repo: SQLAuditRepository, db_session: AsyncSession
    ) -> None:
        now = datetime.now(timezone.utc)
        for i in range(4):
            await repo.log(
                AuditLog(
                    telegram_id=1,
                    action=f"A{i}",
                    topic="JOB_EVENTS",
                    job_id="job-pag",
                    result="SUCCESS",
                    timestamp=now - timedelta(minutes=i),
                )
            )
        await db_session.commit()

        page1 = await repo.list_by_job("job-pag", page=1, page_size=2)
        assert len(page1) == 2
        assert page1[0].action == "A0"

        page2 = await repo.list_by_job("job-pag", page=2, page_size=2)
        assert len(page2) == 2
        assert page2[0].action == "A2"


# ---------------------------------------------------------------------------
# list_by_date_range
# ---------------------------------------------------------------------------


class TestSQLAuditRepositoryListByDateRange:
    @pytest.mark.asyncio
    async def test_returns_entries_within_range(
        self,
        repo: SQLAuditRepository,
        db_session: AsyncSession,
    ) -> None:
        now = datetime.now(timezone.utc)
        await repo.log(_make_audit(timestamp=now - timedelta(days=2)))
        await repo.log(_make_audit(timestamp=now - timedelta(days=1)))
        await repo.log(_make_audit(timestamp=now))
        await db_session.commit()

        entries = await repo.list_by_date_range(
            start=now - timedelta(days=1, hours=12),
            end=now + timedelta(hours=1),
        )
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_matches(
        self,
        repo: SQLAuditRepository,
        db_session: AsyncSession,
    ) -> None:
        now = datetime.now(timezone.utc)
        await repo.log(_make_audit(timestamp=now - timedelta(days=10)))
        await db_session.commit()

        entries = await repo.list_by_date_range(
            start=now - timedelta(days=5),
            end=now - timedelta(days=3),
        )
        assert entries == []

    @pytest.mark.asyncio
    async def test_orders_by_timestamp_descending(
        self,
        repo: SQLAuditRepository,
        db_session: AsyncSession,
    ) -> None:
        now = datetime.now(timezone.utc)
        await repo.log(_make_audit(timestamp=now - timedelta(hours=2), action="OLD"))
        await repo.log(_make_audit(timestamp=now, action="NEW"))
        await db_session.commit()

        entries = await repo.list_by_date_range(
            start=now - timedelta(days=1),
            end=now + timedelta(hours=1),
        )
        assert entries[0].action == "NEW"
        assert entries[1].action == "OLD"

    @pytest.mark.asyncio
    async def test_paginates_results(
        self, repo: SQLAuditRepository, db_session: AsyncSession
    ) -> None:
        now = datetime.now(timezone.utc)
        for i in range(5):
            await repo.log(_make_audit(timestamp=now - timedelta(hours=i), action=f"A{i}"))
        await db_session.commit()

        page1 = await repo.list_by_date_range(
            start=now - timedelta(days=1),
            end=now + timedelta(hours=1),
            page=1,
            page_size=2,
        )
        assert len(page1) == 2
        assert page1[0].action == "A0"
        assert page1[1].action == "A1"

        page2 = await repo.list_by_date_range(
            start=now - timedelta(days=1),
            end=now + timedelta(hours=1),
            page=2,
            page_size=2,
        )
        assert len(page2) == 2
        assert page2[0].action == "A2"
        assert page2[1].action == "A3"
