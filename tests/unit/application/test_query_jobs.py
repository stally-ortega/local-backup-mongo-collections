"""Unit tests for QueryJobsUseCase."""

from typing import Any

import pytest

from app.application.dtos import QueryJobsDto, QueryJobsResult, UserPrincipalDto
from app.application.services.audit_service import AuditService
from app.application.use_cases.query_jobs import QueryJobsUseCase
from app.domain.entities.backup_job import BackupJob
from app.domain.entities.user import User
from app.domain.repositories.repositories import IJobRepository
from app.domain.value_objects.enums import JobStatus, UserRole


class _FakeJobRepo(IJobRepository):
    def __init__(self, jobs: list[BackupJob] | None = None) -> None:
        self._jobs = jobs or []

    async def get_by_id(self, job_id: str) -> BackupJob | None:
        for job in self._jobs:
            if job.id == job_id:
                return job
        return None

    async def list_by_user(
        self,
        telegram_id: int,
        status: JobStatus | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[BackupJob]:
        jobs = [j for j in self._jobs if j.requester_telegram_id == telegram_id]
        if status is not None:
            jobs = [j for j in jobs if j.status == status]
        return jobs

    async def list_by_status(
        self, status: JobStatus, page: int = 1, page_size: int = 50
    ) -> list[BackupJob]:
        return [j for j in self._jobs if j.status == status]

    async def save(self, job: BackupJob) -> None:
        pass

    async def clear_session_cache(self) -> None:
        pass

    async def get_job_stats(self) -> dict[str, object]:
        return {}


class _FakeAuditService(AuditService):
    def __init__(self) -> None:
        pass

    async def log_action(
        self,
        action: str,
        user: User | UserPrincipalDto,
        *,
        topic: str = "",
        command: str | None = None,
        result: str = "",
        duration_ms: int | None = None,
        cluster_uri_hash: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        pass


@pytest.fixture
def use_case() -> QueryJobsUseCase:
    return QueryJobsUseCase(
        job_repository=_FakeJobRepo(),
        audit_service=_FakeAuditService(),
    )


class TestQueryJobsUseCase:
    @pytest.mark.asyncio
    async def test_admin_uses_list_by_status(self, use_case: QueryJobsUseCase) -> None:
        admin = User(telegram_id=1, role=UserRole.ADMIN)
        dto = QueryJobsDto(user=UserPrincipalDto.from_user(admin), filter_status=JobStatus.QUEUED)

        job = BackupJob.create_full("j1", 2, "hash")
        job.status = JobStatus.QUEUED
        use_case._job_repository = _FakeJobRepo([job])

        result = await use_case.execute(dto)
        assert isinstance(result, QueryJobsResult)
        assert len(result.jobs) == 1
        assert result.jobs[0].id == "j1"

    @pytest.mark.asyncio
    async def test_non_admin_uses_list_by_user_with_status(
        self, use_case: QueryJobsUseCase
    ) -> None:
        user = User(telegram_id=2, role=UserRole.OPERATOR)
        dto = QueryJobsDto(user=UserPrincipalDto.from_user(user), filter_status=JobStatus.RUNNING)

        job = BackupJob.create_full("j2", 2, "hash")
        job.status = JobStatus.RUNNING
        use_case._job_repository = _FakeJobRepo([job])

        result = await use_case.execute(dto)
        assert isinstance(result, QueryJobsResult)
        assert len(result.jobs) == 1
        assert result.jobs[0].id == "j2"

    @pytest.mark.asyncio
    async def test_non_admin_sees_only_own_jobs(self, use_case: QueryJobsUseCase) -> None:
        user = User(telegram_id=2, role=UserRole.OPERATOR)
        dto = QueryJobsDto(user=UserPrincipalDto.from_user(user), filter_status=JobStatus.QUEUED)

        own_job = BackupJob.create_full("own", 2, "hash")
        own_job.status = JobStatus.QUEUED
        other_job = BackupJob.create_full("other", 3, "hash")
        other_job.status = JobStatus.QUEUED
        use_case._job_repository = _FakeJobRepo([own_job, other_job])

        result = await use_case.execute(dto)
        assert len(result.jobs) == 1
        assert result.jobs[0].id == "own"
