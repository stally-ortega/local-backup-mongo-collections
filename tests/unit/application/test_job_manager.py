"""Unit tests for JobManager."""

from datetime import datetime
from typing import Any

import pytest

from app.application.dtos import CreateJobRequest
from app.application.ports.ports import IJobQueue
from app.application.services.audit_service import AuditService
from app.application.services.job_manager import JobManager
from app.application.services.permission_service import PermissionService
from app.domain.entities.audit_log import AuditLog
from app.domain.entities.backup_job import BackupJob
from app.domain.entities.user import User
from app.domain.exceptions.domain_errors import DomainPermissionError, JobError
from app.domain.repositories.repositories import IAuditRepository, IJobRepository
from app.domain.value_objects.dtos import CollectionTarget
from app.domain.value_objects.enums import (
    BackupType,
    CollectionBackupStatus,
    JobStatus,
    UserRole,
)


class _FakeJobRepo:
    def __init__(self) -> None:
        self._jobs: dict[str, BackupJob] = {}

    async def get_by_id(self, job_id: str) -> BackupJob | None:
        return self._jobs.get(job_id)

    async def list_by_user(
        self,
        telegram_id: int,
        status: JobStatus | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[BackupJob]:
        jobs = [job for job in self._jobs.values() if job.requester_telegram_id == telegram_id]
        if status is not None:
            jobs = [job for job in jobs if job.status == status]
        return jobs

    async def list_by_status(
        self, status: JobStatus | None = None, page: int = 1, page_size: int = 50
    ) -> list[BackupJob]:
        if status is None:
            return list(self._jobs.values())
        return [job for job in self._jobs.values() if job.status == status]

    async def count_by_status(self, status: JobStatus) -> int:
        return len([job for job in self._jobs.values() if job.status == status])

    async def save(self, job: BackupJob) -> None:
        self._jobs[job.id] = job

    async def clear_session_cache(self) -> None:
        pass

    async def get_job_stats(self) -> dict[str, Any]:
        return {
            "jobs_today": 0,
            "jobs_week": 0,
            "jobs_month": 0,
            "success_rate_percent": 0.0,
            "avg_duration_seconds": None,
        }


class _FakeAuditRepo:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    async def log(self, entry: AuditLog) -> None:
        self.entries.append(entry)

    async def list_by_user(
        self, telegram_id: int, page: int = 1, page_size: int = 50
    ) -> list[AuditLog]:
        return [e for e in self.entries if e.telegram_id == telegram_id]

    async def list_by_job(self, job_id: str, page: int = 1, page_size: int = 50) -> list[AuditLog]:
        return []

    async def list_by_date_range(
        self, start: datetime, end: datetime, page: int = 1, page_size: int = 50
    ) -> list[AuditLog]:
        return []


class _FakeJobQueue:
    def __init__(self) -> None:
        self._cancellations: set[str] = set()
        self._next_queue_id = 1

    async def enqueue(
        self,
        job_id: str,
        job_type: str,
        payload: dict[str, object],
        *,
        priority: str = "normal",
    ) -> str:
        qid = f"queue-{self._next_queue_id}"
        self._next_queue_id += 1
        return qid

    async def get_status(self, queue_job_id: str) -> str | None:
        return "queued"

    async def cancel_job(self, queue_job_id: str) -> bool:
        self._cancellations.add(queue_job_id)
        return True


@pytest.fixture
def fake_job_repo() -> IJobRepository:
    return _FakeJobRepo()


@pytest.fixture
def fake_audit_repo() -> IAuditRepository:
    return _FakeAuditRepo()


@pytest.fixture
def fake_job_queue() -> IJobQueue:
    return _FakeJobQueue()


@pytest.fixture
def permission_service() -> PermissionService:
    return PermissionService()


@pytest.fixture
def audit_service(fake_audit_repo: IAuditRepository) -> AuditService:
    return AuditService(repository=fake_audit_repo)


@pytest.fixture
def job_manager(
    fake_job_repo: IJobRepository,
    fake_job_queue: IJobQueue,
    permission_service: PermissionService,
    audit_service: AuditService,
) -> JobManager:
    return JobManager(
        job_repository=fake_job_repo,
        job_queue=fake_job_queue,
        permission_service=permission_service,
        audit_service=audit_service,
    )


@pytest.fixture
def owner_user() -> User:
    return User(telegram_id=42, role=UserRole.OPERATOR)


@pytest.fixture
def admin_user() -> User:
    return User(telegram_id=1, role=UserRole.ADMIN)


@pytest.fixture
def other_user() -> User:
    return User(telegram_id=99, role=UserRole.OPERATOR)


class TestJobManagerCreateJob:
    @pytest.mark.asyncio
    async def test_create_full_job(self, job_manager: JobManager) -> None:
        request = CreateJobRequest(
            requester_telegram_id=42,
            backup_type=BackupType.FULL,
            cluster_uri_hash="hash123",
        )
        job = await job_manager.create_job(request)

        assert job.backup_type == BackupType.FULL
        assert job.requester_telegram_id == 42
        assert job.cluster_uri_hash == "hash123"
        assert job.status == JobStatus.PENDING
        assert len(job.id) == 32  # uuid hex

    @pytest.mark.asyncio
    async def test_create_custom_job(self, job_manager: JobManager) -> None:
        targets = [
            CollectionTarget(
                database="db1",
                collection="col1",
                status=CollectionBackupStatus.PENDING,
            ),
        ]
        request = CreateJobRequest(
            requester_telegram_id=7,
            backup_type=BackupType.CUSTOM,
            cluster_uri_hash="hash456",
            target_collections=targets,
        )
        job = await job_manager.create_job(request)

        assert job.backup_type == BackupType.CUSTOM
        assert len(job.target_collections) == 1
        assert job.target_collections[0].database == "db1"

    @pytest.mark.asyncio
    async def test_create_custom_job_without_targets_raises(self, job_manager: JobManager) -> None:
        request = CreateJobRequest(
            requester_telegram_id=7,
            backup_type=BackupType.CUSTOM,
            cluster_uri_hash="hash789",
            target_collections=[],
        )

        with pytest.raises(JobError, match="at least one target collection"):
            await job_manager.create_job(request)


class TestJobManagerEnqueueJob:
    @pytest.mark.asyncio
    async def test_enqueue_transitions_to_queued(
        self,
        job_manager: JobManager,
        fake_job_repo: IJobRepository,
        fake_audit_repo: _FakeAuditRepo,
    ) -> None:
        request = CreateJobRequest(
            requester_telegram_id=42,
            backup_type=BackupType.FULL,
            cluster_uri_hash="hash",
        )
        job = await job_manager.create_job(request)
        await fake_job_repo.save(job)

        queue_id = await job_manager.enqueue_job(job.id)

        assert queue_id.startswith("queue-")
        stored = await fake_job_repo.get_by_id(job.id)
        assert stored is not None
        assert stored.status == JobStatus.QUEUED
        assert stored.queue_job_id == queue_id

        audit = [e for e in fake_audit_repo.entries if e.action == "JOB_QUEUED"]
        assert len(audit) == 1
        assert audit[0].telegram_id == 42

    @pytest.mark.asyncio
    async def test_enqueue_job_not_found(self, job_manager: JobManager) -> None:
        with pytest.raises(JobError):
            await job_manager.enqueue_job("nonexistent")

    @pytest.mark.asyncio
    async def test_enqueue_custom_job_payload(
        self,
        job_manager: JobManager,
        fake_job_repo: IJobRepository,
        fake_job_queue: _FakeJobQueue,
    ) -> None:
        targets = [
            CollectionTarget(database="db1", collection="col1"),
            CollectionTarget(database="db2", collection="col2"),
        ]
        request = CreateJobRequest(
            requester_telegram_id=3,
            backup_type=BackupType.CUSTOM,
            cluster_uri_hash="hash",
            target_collections=targets,
        )
        job = await job_manager.create_job(request)
        await fake_job_repo.save(job)

        await job_manager.enqueue_job(job.id)
        # Queue was invoked; no direct assertion on payload unless we expand
        # the fake, but the operation itself should not raise.


class TestJobManagerCancelJob:
    @pytest.mark.asyncio
    async def test_owner_cancels_own_job(
        self,
        job_manager: JobManager,
        fake_job_repo: IJobRepository,
        owner_user: User,
        fake_audit_repo: _FakeAuditRepo,
        fake_job_queue: _FakeJobQueue,
    ) -> None:
        request = CreateJobRequest(
            requester_telegram_id=owner_user.telegram_id,
            backup_type=BackupType.FULL,
            cluster_uri_hash="hash",
        )
        job = await job_manager.create_job(request)
        await fake_job_repo.save(job)
        await job_manager.enqueue_job(job.id)

        cancelled = await job_manager.cancel_job(job.id, owner_user)

        assert cancelled.status == JobStatus.CANCELLED
        assert cancelled.cancelled_by == owner_user.telegram_id
        assert job.queue_job_id in fake_job_queue._cancellations

        audit = [e for e in fake_audit_repo.entries if e.action == "JOB_CANCELLED"]
        assert len(audit) == 1
        assert audit[0].telegram_id == owner_user.telegram_id

    @pytest.mark.asyncio
    async def test_admin_cancels_foreign_job(
        self,
        job_manager: JobManager,
        fake_job_repo: IJobRepository,
        admin_user: User,
        owner_user: User,
    ) -> None:
        request = CreateJobRequest(
            requester_telegram_id=owner_user.telegram_id,
            backup_type=BackupType.FULL,
            cluster_uri_hash="hash",
        )
        job = await job_manager.create_job(request)
        await fake_job_repo.save(job)
        await job_manager.enqueue_job(job.id)

        cancelled = await job_manager.cancel_job(job.id, admin_user)
        assert cancelled.status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_other_user_cannot_cancel(
        self,
        job_manager: JobManager,
        fake_job_repo: IJobRepository,
        owner_user: User,
        other_user: User,
    ) -> None:
        request = CreateJobRequest(
            requester_telegram_id=owner_user.telegram_id,
            backup_type=BackupType.FULL,
            cluster_uri_hash="hash",
        )
        job = await job_manager.create_job(request)
        await fake_job_repo.save(job)
        await job_manager.enqueue_job(job.id)

        with pytest.raises(DomainPermissionError):
            await job_manager.cancel_job(job.id, other_user)

    @pytest.mark.asyncio
    async def test_cancel_job_not_found(self, job_manager: JobManager, owner_user: User) -> None:
        with pytest.raises(JobError):
            await job_manager.cancel_job("missing", owner_user)

    @pytest.mark.asyncio
    async def test_cannot_cancel_terminal_job(
        self,
        job_manager: JobManager,
        fake_job_repo: IJobRepository,
        owner_user: User,
    ) -> None:
        request = CreateJobRequest(
            requester_telegram_id=owner_user.telegram_id,
            backup_type=BackupType.FULL,
            cluster_uri_hash="hash",
        )
        job = await job_manager.create_job(request)
        await fake_job_repo.save(job)
        await job_manager.enqueue_job(job.id)
        # transition to RUNNING then SUCCESS
        job.mark_running()
        job.mark_success()
        await fake_job_repo.save(job)

        with pytest.raises(DomainPermissionError):
            await job_manager.cancel_job(job.id, owner_user)


class TestJobManagerGetJobStatus:
    @pytest.mark.asyncio
    async def test_returns_status(self, job_manager: JobManager) -> None:
        request = CreateJobRequest(
            requester_telegram_id=1,
            backup_type=BackupType.FULL,
            cluster_uri_hash="hash",
        )
        job = await job_manager.create_job(request)
        # Note: create_job already persists via repo; no need to save again
        # because create_job calls repo.save internally.
        status = await job_manager.get_job_status(job.id)
        assert status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_job_not_found(self, job_manager: JobManager) -> None:
        with pytest.raises(JobError):
            await job_manager.get_job_status("missing")


class TestJobManagerListUserJobs:
    @pytest.mark.asyncio
    async def test_filters_by_telegram_id(
        self,
        job_manager: JobManager,
        owner_user: User,
        other_user: User,
    ) -> None:
        req1 = CreateJobRequest(
            requester_telegram_id=owner_user.telegram_id,
            backup_type=BackupType.FULL,
            cluster_uri_hash="a",
        )
        req2 = CreateJobRequest(
            requester_telegram_id=other_user.telegram_id,
            backup_type=BackupType.FULL,
            cluster_uri_hash="b",
        )
        await job_manager.create_job(req1)
        await job_manager.create_job(req2)

        jobs = await job_manager.list_user_jobs(owner_user)
        assert len(jobs) == 1
        assert jobs[0].requester_telegram_id == owner_user.telegram_id
