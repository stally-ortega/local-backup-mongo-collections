"""Unit tests for CancelJobUseCase."""

from datetime import datetime
from typing import Any

import pytest

from app.application.dtos import CancelJobDto
from app.application.services.audit_service import AuditService
from app.application.services.job_manager import JobManager
from app.application.services.permission_service import PermissionService
from app.application.use_cases.cancel_job import CancelJobUseCase
from app.domain.entities.audit_log import AuditLog
from app.domain.entities.backup_job import BackupJob
from app.domain.entities.user import User
from app.domain.exceptions.domain_errors import JobError, PermissionError
from app.domain.repositories.repositories import IAuditRepository, IJobRepository
from app.domain.value_objects.enums import JobStatus, UserRole


class _FakeJobRepo:
    def __init__(self) -> None:
        self._jobs: dict[str, BackupJob] = {}

    async def get_by_id(self, job_id: str) -> BackupJob | None:
        return self._jobs.get(job_id)

    async def list_by_user(
        self, telegram_id: int, page: int = 1, page_size: int = 50
    ) -> list[BackupJob]:
        return [j for j in self._jobs.values() if j.requester_telegram_id == telegram_id]

    async def list_by_status(
        self, status: JobStatus, page: int = 1, page_size: int = 50
    ) -> list[BackupJob]:
        return [j for j in self._jobs.values() if j.status == status]

    async def save(self, job: BackupJob) -> None:
        self._jobs[job.id] = job

    async def commit(self) -> None:
        pass

    async def clear_session_cache(self) -> None:
        pass

    async def update_status(self, job_id: str, status: JobStatus) -> BackupJob | None:
        job = self._jobs.get(job_id)
        if job:
            job.status = status
        return job

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

    async def list_by_user(self, telegram_id: int) -> list[AuditLog]:
        return [e for e in self.entries if e.telegram_id == telegram_id]

    async def list_by_job(self, job_id: str) -> list[AuditLog]:
        return []

    async def list_by_date_range(self, start: datetime, end: datetime) -> list[AuditLog]:
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
def job_repo() -> IJobRepository:
    return _FakeJobRepo()


@pytest.fixture
def audit_repo() -> IAuditRepository:
    return _FakeAuditRepo()


@pytest.fixture
def job_queue() -> _FakeJobQueue:
    return _FakeJobQueue()


@pytest.fixture
def permission_service() -> PermissionService:
    return PermissionService()


@pytest.fixture
def audit_service(audit_repo: IAuditRepository) -> AuditService:
    return AuditService(repository=audit_repo)


@pytest.fixture
def job_manager(
    job_repo: IJobRepository,
    job_queue: _FakeJobQueue,
    permission_service: PermissionService,
    audit_service: AuditService,
) -> JobManager:
    return JobManager(
        job_repository=job_repo,
        job_queue=job_queue,
        permission_service=permission_service,
        audit_service=audit_service,
    )


@pytest.fixture
def use_case(
    job_manager: JobManager,
    audit_service: AuditService,
) -> CancelJobUseCase:
    return CancelJobUseCase(
        job_manager=job_manager,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _store_queued_job(repo: _FakeJobRepo, user: User) -> BackupJob:
    job = BackupJob.create_full("job-001", user.telegram_id, "hash123")
    job.mark_queued()
    await repo.save(job)
    return job


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestCancelJobHappyPath:
    @pytest.mark.asyncio
    async def test_owner_cancels_own_job(
        self,
        use_case: CancelJobUseCase,
        job_repo: _FakeJobRepo,
        owner_user: User,
    ) -> None:
        job = await _store_queued_job(job_repo, owner_user)
        dto = CancelJobDto(user=owner_user, job_id=job.id)

        result = await use_case.execute(dto)

        assert result.job_id == job.id
        assert result.status == JobStatus.CANCELLED
        assert result.cancelled_by == owner_user.telegram_id

    @pytest.mark.asyncio
    async def test_admin_cancels_foreign_job(
        self,
        use_case: CancelJobUseCase,
        job_repo: _FakeJobRepo,
        owner_user: User,
        admin_user: User,
    ) -> None:
        job = await _store_queued_job(job_repo, owner_user)
        dto = CancelJobDto(user=admin_user, job_id=job.id)

        result = await use_case.execute(dto)

        assert result.status == JobStatus.CANCELLED
        assert result.cancelled_by == admin_user.telegram_id

    @pytest.mark.asyncio
    async def test_creates_audit_log(
        self,
        use_case: CancelJobUseCase,
        job_repo: _FakeJobRepo,
        owner_user: User,
        audit_repo: _FakeAuditRepo,
    ) -> None:
        job = await _store_queued_job(job_repo, owner_user)
        dto = CancelJobDto(user=owner_user, job_id=job.id)

        await use_case.execute(dto)

        audit = [e for e in audit_repo.entries if e.action == "CANCEL_REQUESTED"]
        assert len(audit) == 1
        assert audit[0].telegram_id == owner_user.telegram_id


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestCancelJobErrors:
    @pytest.mark.asyncio
    async def test_job_not_found_raises(
        self,
        use_case: CancelJobUseCase,
        owner_user: User,
    ) -> None:
        dto = CancelJobDto(user=owner_user, job_id="missing-job")

        with pytest.raises(JobError) as exc_info:
            await use_case.execute(dto)
        assert exc_info.value.code == "JOB_ERROR"

    @pytest.mark.asyncio
    async def test_other_user_cannot_cancel(
        self,
        use_case: CancelJobUseCase,
        job_repo: _FakeJobRepo,
        owner_user: User,
        other_user: User,
    ) -> None:
        job = await _store_queued_job(job_repo, owner_user)
        dto = CancelJobDto(user=other_user, job_id=job.id)

        with pytest.raises(PermissionError) as exc_info:
            await use_case.execute(dto)
        assert exc_info.value.code == "PERMISSION_DENIED"

    @pytest.mark.asyncio
    async def test_cannot_cancel_terminal_job(
        self,
        use_case: CancelJobUseCase,
        job_repo: _FakeJobRepo,
        owner_user: User,
    ) -> None:
        job = BackupJob.create_full("job-002", owner_user.telegram_id, "hash123")
        job.mark_queued()
        job.mark_running()
        job.mark_success()
        await job_repo.save(job)

        dto = CancelJobDto(user=owner_user, job_id=job.id)
        with pytest.raises(PermissionError) as exc_info:
            await use_case.execute(dto)
        assert exc_info.value.code == "PERMISSION_DENIED"
