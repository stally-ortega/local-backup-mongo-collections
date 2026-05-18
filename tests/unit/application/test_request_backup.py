"""Unit tests for RequestBackupUseCase."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.application.dtos import RequestBackupDto, RequestBackupResult, UserPrincipalDto
from app.application.services.audit_service import AuditService
from app.application.services.job_manager import JobManager
from app.application.services.permission_service import PermissionService
from app.application.use_cases.request_backup import RequestBackupUseCase
from app.domain.entities.audit_log import AuditLog
from app.domain.entities.backup_job import BackupJob
from app.domain.entities.user import User
from app.domain.exceptions.domain_errors import (
    DiskSpaceError,
    DomainPermissionError,
    RateLimitError,
)
from app.domain.repositories.repositories import (
    IAuditRepository,
    IJobRepository,
    IRateLimitRepository,
)
from app.domain.value_objects.dtos import CollectionTarget
from app.domain.value_objects.enums import BackupType, JobStatus, UserRole


class _FakeRateLimitRepo:
    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    async def check_limit(
        self,
        telegram_id: int,
        action: str,
        max_allowed: int,
        window_seconds: int,
    ) -> bool:
        key = f"{telegram_id}:{action}"
        return self._counters.get(key, 0) < max_allowed

    async def increment(self, telegram_id: int, action: str, window_seconds: int) -> int:
        key = f"{telegram_id}:{action}"
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]

    async def reset(self, telegram_id: int, action: str) -> None:
        self._counters.pop(f"{telegram_id}:{action}", None)


class _FakeFsUtils:
    def __init__(self, *, free_bytes: int = 10_000_000_000) -> None:
        self._free_bytes = free_bytes

    async def ensure_dir(self, path: Path) -> None:
        pass

    async def write_text(self, path: Path, content: str) -> None:
        pass

    async def get_folder_size(self, path: Path) -> int:
        return 0

    async def get_disk_usage(self, path: Path) -> tuple[int, int, int]:
        return (100_000_000_000, 90_000_000_000, self._free_bytes)

    async def compress(self, source: Path, destination: Path) -> None:
        pass

    async def delete(self, path: Path) -> None:
        pass

    async def list_files(self, path: Path, pattern: str = "*") -> list[Path]:
        return []

    async def list_files_recursive(self, path: Path, pattern: str = "**/*") -> list[Path]:
        return []

    async def get_modification_time(self, path: Path) -> datetime:
        return datetime.now(timezone.utc)


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
        self, status: JobStatus, page: int = 1, page_size: int = 50
    ) -> list[BackupJob]:
        return [job for job in self._jobs.values() if job.status == status]

    async def count_by_status(self, status: JobStatus) -> int:
        return len([job for job in self._jobs.values() if job.status == status])

    async def save(self, job: BackupJob) -> None:
        self._jobs[job.id] = job

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


class _FakeJobQueue:
    def __init__(self) -> None:
        self._next_id = 1

    async def enqueue(
        self,
        job_id: str,
        job_type: str,
        payload: dict[str, object],
        *,
        priority: str = "normal",
    ) -> str:
        qid = f"queue-{self._next_id}"
        self._next_id += 1
        return qid

    async def get_status(self, queue_job_id: str) -> str | None:
        return "queued"

    async def cancel_job(self, queue_job_id: str) -> bool:
        return True


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


@pytest.fixture
def permission_service() -> PermissionService:
    return PermissionService()


@pytest.fixture
def rate_limit_repo() -> IRateLimitRepository:
    return _FakeRateLimitRepo()


@pytest.fixture
def fs_utils() -> _FakeFsUtils:
    return _FakeFsUtils()


@pytest.fixture
def job_repo() -> IJobRepository:
    return _FakeJobRepo()


@pytest.fixture
def job_queue() -> _FakeJobQueue:
    return _FakeJobQueue()


@pytest.fixture
def audit_repo() -> IAuditRepository:
    return _FakeAuditRepo()


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
    permission_service: PermissionService,
    rate_limit_repo: IRateLimitRepository,
    fs_utils: _FakeFsUtils,
    job_manager: JobManager,
    audit_service: AuditService,
) -> RequestBackupUseCase:
    return RequestBackupUseCase(
        permission_service=permission_service,
        rate_limit_repo=rate_limit_repo,
        fs_utils=fs_utils,
        job_manager=job_manager,
        audit_service=audit_service,
        backup_base_path=Path("/backups"),
        max_backup_rate=2,
        backup_rate_window=60,
        min_free_disk_bytes=1_000_000,
    )


@pytest.fixture
def admin_user() -> User:
    return User(telegram_id=1, role=UserRole.ADMIN)


@pytest.fixture
def readonly_user() -> User:
    return User(telegram_id=2, role=UserRole.READONLY)


@pytest.fixture
def dto_full(admin_user: User) -> RequestBackupDto:
    return RequestBackupDto(
        user=UserPrincipalDto.from_user(admin_user),
        backup_type=BackupType.FULL,
        cluster_uri_hash="hash123",
    )


class TestRequestBackupHappyPath:
    @pytest.mark.asyncio
    async def test_returns_job_id_and_status(
        self,
        use_case: RequestBackupUseCase,
        dto_full: RequestBackupDto,
    ) -> None:
        result = await use_case.execute(dto_full)

        assert isinstance(result, RequestBackupResult)
        assert len(result.job_id) > 0
        assert result.status == JobStatus.QUEUED

    @pytest.mark.asyncio
    async def test_creates_job_in_repository(
        self,
        use_case: RequestBackupUseCase,
        dto_full: RequestBackupDto,
        job_repo: _FakeJobRepo,
    ) -> None:
        result = await use_case.execute(dto_full)

        stored = await job_repo.get_by_id(result.job_id)
        assert stored is not None
        assert stored.backup_type == BackupType.FULL
        assert stored.requester_telegram_id == dto_full.user.telegram_id

    @pytest.mark.asyncio
    async def test_logs_audit_backup_requested(
        self,
        use_case: RequestBackupUseCase,
        dto_full: RequestBackupDto,
        audit_repo: _FakeAuditRepo,
    ) -> None:
        await use_case.execute(dto_full)

        audit = [e for e in audit_repo.entries if e.action == "BACKUP_REQUESTED"]
        assert len(audit) == 1
        assert audit[0].telegram_id == dto_full.user.telegram_id
        assert audit[0].topic == "BACKUP_REQUESTS"

    @pytest.mark.asyncio
    async def test_logs_audit_job_queued(
        self,
        use_case: RequestBackupUseCase,
        dto_full: RequestBackupDto,
        audit_repo: _FakeAuditRepo,
    ) -> None:
        await use_case.execute(dto_full)

        audit = [e for e in audit_repo.entries if e.action == "JOB_QUEUED"]
        assert len(audit) == 1

    @pytest.mark.asyncio
    async def test_increments_rate_limit(
        self,
        use_case: RequestBackupUseCase,
        dto_full: RequestBackupDto,
        rate_limit_repo: _FakeRateLimitRepo,
    ) -> None:
        await use_case.execute(dto_full)

        count = await rate_limit_repo.increment(dto_full.user.telegram_id, "BACKUP", 60)
        # Fake increment always adds; original request bumped it to 1,
        # so this second call makes it 2.
        assert count == 2


class TestRequestBackupPermissionError:
    @pytest.mark.asyncio
    async def test_readonly_user_denied(
        self,
        use_case: RequestBackupUseCase,
        readonly_user: User,
    ) -> None:
        dto = RequestBackupDto(
            user=UserPrincipalDto.from_user(readonly_user),
            backup_type=BackupType.FULL,
            cluster_uri_hash="hash123",
        )
        with pytest.raises(DomainPermissionError) as exc_info:
            await use_case.execute(dto)
        assert exc_info.value.code == "PERMISSION_DENIED"


class TestRequestBackupRateLimitError:
    @pytest.mark.asyncio
    async def test_exceeded_rate_limit_raises(
        self,
        use_case: RequestBackupUseCase,
        dto_full: RequestBackupDto,
        rate_limit_repo: _FakeRateLimitRepo,
    ) -> None:
        # Exhaust the rate limit (max = 2).
        await rate_limit_repo.increment(dto_full.user.telegram_id, "BACKUP", 60)
        await rate_limit_repo.increment(dto_full.user.telegram_id, "BACKUP", 60)

        with pytest.raises(RateLimitError) as exc_info:
            await use_case.execute(dto_full)
        assert exc_info.value.code == "RATE_LIMIT_EXCEEDED"

    @pytest.mark.asyncio
    async def test_no_job_created_when_rate_limited(
        self,
        use_case: RequestBackupUseCase,
        dto_full: RequestBackupDto,
        rate_limit_repo: _FakeRateLimitRepo,
        job_repo: _FakeJobRepo,
    ) -> None:
        await rate_limit_repo.increment(dto_full.user.telegram_id, "BACKUP", 60)
        await rate_limit_repo.increment(dto_full.user.telegram_id, "BACKUP", 60)

        with pytest.raises(RateLimitError):
            await use_case.execute(dto_full)

        jobs = await job_repo.list_by_user(dto_full.user.telegram_id)
        assert len(jobs) == 0


class TestRequestBackupDiskSpaceError:
    @pytest.mark.asyncio
    async def test_insufficient_disk_space_raises(
        self,
        permission_service: PermissionService,
        rate_limit_repo: IRateLimitRepository,
        job_manager: JobManager,
        audit_service: AuditService,
        dto_full: RequestBackupDto,
    ) -> None:
        fs = _FakeFsUtils(free_bytes=500_000)  # below 1 MB threshold
        use_case = RequestBackupUseCase(
            permission_service=permission_service,
            rate_limit_repo=rate_limit_repo,
            fs_utils=fs,
            job_manager=job_manager,
            audit_service=audit_service,
            backup_base_path=Path("/backups"),
            min_free_disk_bytes=1_000_000,
        )

        with pytest.raises(DiskSpaceError) as exc_info:
            await use_case.execute(dto_full)
        assert exc_info.value.code == "DISK_SPACE_ERROR"

    @pytest.mark.asyncio
    async def test_no_job_created_when_disk_full(
        self,
        permission_service: PermissionService,
        rate_limit_repo: IRateLimitRepository,
        job_manager: JobManager,
        audit_service: AuditService,
        dto_full: RequestBackupDto,
        job_repo: _FakeJobRepo,
    ) -> None:
        fs = _FakeFsUtils(free_bytes=500_000)
        use_case = RequestBackupUseCase(
            permission_service=permission_service,
            rate_limit_repo=rate_limit_repo,
            fs_utils=fs,
            job_manager=job_manager,
            audit_service=audit_service,
            backup_base_path=Path("/backups"),
            min_free_disk_bytes=1_000_000,
        )

        with pytest.raises(DiskSpaceError):
            await use_case.execute(dto_full)

        jobs = await job_repo.list_by_user(dto_full.user.telegram_id)
        assert len(jobs) == 0


class TestRequestBackupCustomCollections:
    @pytest.mark.asyncio
    async def test_custom_backup_with_targets(
        self,
        use_case: RequestBackupUseCase,
        admin_user: User,
        job_repo: _FakeJobRepo,
    ) -> None:
        targets = [
            CollectionTarget(database="db1", collection="col1"),
            CollectionTarget(database="db1", collection="col2"),
        ]
        dto = RequestBackupDto(
            user=UserPrincipalDto.from_user(admin_user),
            backup_type=BackupType.CUSTOM,
            cluster_uri_hash="hash456",
            target_collections=targets,
        )

        result = await use_case.execute(dto)

        stored = await job_repo.get_by_id(result.job_id)
        assert stored is not None
        assert stored.backup_type == BackupType.CUSTOM
        assert len(stored.target_collections) == 2
