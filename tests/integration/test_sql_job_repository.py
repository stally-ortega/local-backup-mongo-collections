"""Integration tests for SQLJobRepository using an in-memory SQLite database."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.domain.entities.backup_job import BackupJob
from app.domain.value_objects.dtos import CollectionTarget, JobProgress
from app.domain.value_objects.enums import CollectionBackupStatus, JobStatus
from app.infrastructure.persistence.database import init_database
from app.infrastructure.persistence.sql_job_repository import SQLJobRepository


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
def repo(db_session: AsyncSession) -> SQLJobRepository:
    return SQLJobRepository(session=db_session)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    job_id: str = "job-001",
    requester_telegram_id: int = 1,
    status: JobStatus = JobStatus.PENDING,
    target_collections: list[CollectionTarget] | None = None,
    progress: JobProgress | None = None,
) -> BackupJob:
    job = BackupJob.create_full(job_id, requester_telegram_id, "hash123")
    job.status = status
    if target_collections:
        job.target_collections = target_collections
    if progress:
        job.progress = progress
    return job


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


class TestSQLJobRepositoryGetById:
    @pytest.mark.asyncio
    async def test_returns_job_when_found(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        job = _make_job(job_id="job-found", status=JobStatus.QUEUED)
        await repo.save(job)
        await db_session.commit()

        found = await repo.get_by_id("job-found")

        assert found is not None
        assert found.id == "job-found"
        assert found.status == JobStatus.QUEUED
        assert found.requester_telegram_id == 1

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(
        self,
        repo: SQLJobRepository,
    ) -> None:
        result = await repo.get_by_id("missing-job")
        assert result is None


# ---------------------------------------------------------------------------
# list_by_user
# ---------------------------------------------------------------------------


class TestSQLJobRepositoryListByUser:
    @pytest.mark.asyncio
    async def test_returns_jobs_for_requester(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.save(_make_job(job_id="a", requester_telegram_id=1))
        await repo.save(_make_job(job_id="b", requester_telegram_id=1))
        await repo.save(_make_job(job_id="c", requester_telegram_id=2))
        await db_session.commit()

        jobs = await repo.list_by_user(1)

        assert len(jobs) == 2
        assert {j.id for j in jobs} == {"a", "b"}

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_jobs(
        self,
        repo: SQLJobRepository,
    ) -> None:
        jobs = await repo.list_by_user(99)
        assert jobs == []

    @pytest.mark.asyncio
    async def test_paginates_results(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        for i in range(1, 4):
            await repo.save(_make_job(job_id=f"job-{i}", requester_telegram_id=5))
        await db_session.commit()

        page = await repo.list_by_user(5, page=1, page_size=2)
        assert len(page) == 2

        page = await repo.list_by_user(5, page=2, page_size=2)
        assert len(page) == 1

    @pytest.mark.asyncio
    async def test_filters_by_status(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.save(_make_job(job_id="q1", requester_telegram_id=3, status=JobStatus.QUEUED))
        await repo.save(_make_job(job_id="q2", requester_telegram_id=3, status=JobStatus.QUEUED))
        await repo.save(_make_job(job_id="r1", requester_telegram_id=3, status=JobStatus.RUNNING))
        await db_session.commit()

        queued = await repo.list_by_user(3, status=JobStatus.QUEUED)
        assert len(queued) == 2
        assert all(j.status == JobStatus.QUEUED for j in queued)

        running = await repo.list_by_user(3, status=JobStatus.RUNNING)
        assert len(running) == 1
        assert running[0].id == "r1"


# ---------------------------------------------------------------------------
# list_by_status
# ---------------------------------------------------------------------------


class TestSQLJobRepositoryListByStatus:
    @pytest.mark.asyncio
    async def test_returns_jobs_with_matching_status(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.save(_make_job(job_id="q1", status=JobStatus.QUEUED))
        await repo.save(_make_job(job_id="q2", status=JobStatus.QUEUED))
        await repo.save(_make_job(job_id="r1", status=JobStatus.RUNNING))
        await db_session.commit()

        queued = await repo.list_by_status(JobStatus.QUEUED)
        assert len(queued) == 2
        assert all(j.status == JobStatus.QUEUED for j in queued)

    @pytest.mark.asyncio
    async def test_returns_all_jobs_when_no_status_filter(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.save(_make_job(job_id="q1", status=JobStatus.QUEUED))
        await repo.save(_make_job(job_id="r1", status=JobStatus.RUNNING))
        await db_session.commit()

        all_jobs = await repo.list_by_status()
        assert len(all_jobs) == 2

    @pytest.mark.asyncio
    async def test_paginates_by_status(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        for i in range(1, 6):
            await repo.save(_make_job(job_id=f"q{i}", status=JobStatus.QUEUED))
        await db_session.commit()

        page = await repo.list_by_status(JobStatus.QUEUED, page=1, page_size=3)
        assert len(page) == 3


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestSQLJobRepositoryCountByStatus:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_jobs_match(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.save(_make_job(job_id="q1", status=JobStatus.QUEUED))
        await db_session.commit()

        count = await repo.count_by_status(JobStatus.RUNNING)
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_correct_count(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        await repo.save(_make_job(job_id="r1", status=JobStatus.RUNNING))
        await repo.save(_make_job(job_id="r2", status=JobStatus.RUNNING))
        await repo.save(_make_job(job_id="q1", status=JobStatus.QUEUED))
        await db_session.commit()

        count = await repo.count_by_status(JobStatus.RUNNING)
        assert count == 2


class TestSQLJobRepositorySave:
    @pytest.mark.asyncio
    async def test_inserts_new_job(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        job = _make_job(job_id="new-job", status=JobStatus.PENDING)
        await repo.save(job)
        await db_session.commit()

        found = await repo.get_by_id("new-job")
        assert found is not None
        assert found.status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_updates_existing_job(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        job = _make_job(job_id="upd-job", status=JobStatus.PENDING)
        await repo.save(job)
        await db_session.commit()

        job.mark_queued()
        await repo.save(job)
        await db_session.commit()

        found = await repo.get_by_id("upd-job")
        assert found is not None
        assert found.status == JobStatus.QUEUED

    @pytest.mark.asyncio
    async def test_round_trips_target_collections(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        targets = [
            CollectionTarget(
                database="db1",
                collection="col1",
                status=CollectionBackupStatus.SUCCESS,
                size_bytes=1024,
            ),
            CollectionTarget(
                database="db1",
                collection="col2",
                status=CollectionBackupStatus.FAILED,
                error_message="timeout",
            ),
        ]
        job = BackupJob.create_custom("custom-job", 1, "hash456", targets)
        await repo.save(job)
        await db_session.commit()

        found = await repo.get_by_id("custom-job")
        assert found is not None
        assert len(found.target_collections) == 2
        assert found.target_collections[0].collection == "col1"
        assert found.target_collections[0].size_bytes == 1024
        assert found.target_collections[1].error_message == "timeout"

    @pytest.mark.asyncio
    async def test_round_trips_progress(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        job = _make_job(job_id="prog-job")
        job.progress = JobProgress(
            total_collections=10,
            completed_collections=7,
            failed_collections=1,
            retry_count=2,
            percent_complete=70.0,
            bytes_processed=1_048_576,
        )
        await repo.save(job)
        await db_session.commit()

        found = await repo.get_by_id("prog-job")
        assert found is not None
        assert found.progress is not None
        assert found.progress.total_collections == 10
        assert found.progress.completed_collections == 7
        assert found.progress.failed_collections == 1
        assert found.progress.retry_count == 2
        assert found.progress.bytes_processed == 1_048_576

    @pytest.mark.asyncio
    async def test_round_trips_output_path(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        from pathlib import Path

        job = _make_job(job_id="path-job")
        job.output_path = Path("/tmp/backup/archive")
        await repo.save(job)
        await db_session.commit()

        found = await repo.get_by_id("path-job")
        assert found is not None
        assert found.output_path is not None
        assert found.output_path.name == "archive"
        assert found.output_path.parent.name == "backup"

    @pytest.mark.asyncio
    async def test_round_trips_queue_job_id(
        self,
        repo: SQLJobRepository,
        db_session: AsyncSession,
    ) -> None:
        job = _make_job(job_id="queue-job")
        job.queue_job_id = "rq-abc-123"
        await repo.save(job)
        await db_session.commit()

        found = await repo.get_by_id("queue-job")
        assert found is not None
        assert found.queue_job_id == "rq-abc-123"
