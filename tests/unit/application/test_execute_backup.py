"""Unit tests for ExecuteBackupUseCase."""

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app.application.dtos import ExecuteBackupDto, ExecuteBackupResult
from app.application.services.audit_service import AuditService
from app.application.use_cases.execute_backup import ExecuteBackupUseCase
from app.domain.entities.audit_log import AuditLog
from app.domain.entities.backup_job import BackupJob
from app.domain.entities.user import User
from app.domain.exceptions.domain_errors import (
    BackupEngineError,
    InvalidStateTransitionError,
    JobNotFoundError,
)
from app.domain.repositories.repositories import IAuditRepository, IJobRepository
from app.domain.value_objects.dtos import CollectionTarget
from app.domain.value_objects.enums import (
    BackupType,
    CollectionBackupStatus,
    JobStatus,
    UserRole,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


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


class _FakeBackupEngine:
    def __init__(
        self,
        *,
        fail_collections: set[tuple[str, str]] | None = None,
    ) -> None:
        self._fail_collections = fail_collections or set()

    async def backup_collection(
        self,
        database: str,
        collection: str,
        output_path: Path,
    ) -> CollectionTarget:
        if (database, collection) in self._fail_collections:
            raise BackupEngineError(
                message=f"dump failed for {database}.{collection}",
                details={"database": database, "collection": collection},
            )
        return CollectionTarget(
            database=database,
            collection=collection,
            status=CollectionBackupStatus.SUCCESS,
            size_bytes=1024,
        )

    async def get_version(self) -> str:
        return "1.0.0"

    async def validate_connection(self, cluster_uri_hash: str) -> bool:
        return True


class _FakeMongoMetadata:
    def __init__(self, databases: dict[str, list[str]] | None = None) -> None:
        self._databases = databases or {"db1": ["col1", "col2"], "db2": ["col3"]}

    async def list_databases(self, cluster_uri_hash: str) -> list[str]:
        return list(self._databases.keys())

    async def list_collections(self, cluster_uri_hash: str, database: str) -> list[str]:
        return self._databases.get(database, [])

    async def get_size_stats(self, cluster_uri_hash: str) -> Any:
        return None


class _FakeNotifier:
    def __init__(self, *, raise_on_send: bool = False) -> None:
        self.messages: list[tuple[int, str]] = []
        self._raise_on_send = raise_on_send

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        topic_id: int | None = None,
        correlation_id: str | None = None,
    ) -> None:
        if self._raise_on_send:
            raise RuntimeError("Notifier down")
        self.messages.append((chat_id, text))

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        correlation_id: str | None = None,
    ) -> None:
        pass

    async def send_document(
        self,
        chat_id: int,
        file_path: Path,
        *,
        caption: str | None = None,
        topic_id: int | None = None,
        correlation_id: str | None = None,
    ) -> None:
        pass


class _FakeFsUtils:
    async def ensure_dir(self, path: Path) -> None:
        pass

    async def write_text(self, path: Path, content: str) -> None:
        pass

    async def get_folder_size(self, path: Path) -> int:
        return 0

    async def get_disk_usage(self, path: Path) -> tuple[int, int, int]:
        return (100_000_000_000, 50_000_000_000, 50_000_000_000)

    async def compress(self, source: Path, destination: Path) -> None:
        pass

    async def delete(self, path: Path) -> None:
        pass

    async def list_files(self, path: Path, pattern: str = "*") -> list[Path]:
        return []

    async def list_files_recursive(self, path: Path, pattern: str = "**/*") -> list[Path]:
        return []

    async def get_modification_time(self, path: Path) -> Any:
        from datetime import datetime

        return datetime.utcnow()


class _FakeRetentionManager:
    def __init__(self, *, raise_on_apply: bool = False) -> None:
        self.applied = False
        self._raise_on_apply = raise_on_apply

    async def apply_policy(self) -> dict[str, Any]:
        if self._raise_on_apply:
            raise RuntimeError("Retention failed")
        self.applied = True
        return {"deleted_count": 0, "reclaimed_bytes": 0, "errors": []}

    async def get_storage_stats(self) -> dict[str, Any]:
        return {}


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


class _CancelAfterN:
    """Async callable that returns ``True`` after *n* invocations."""

    def __init__(self, n: int) -> None:
        self._count = 0
        self._n = n

    async def __call__(self) -> bool:
        self._count += 1
        return self._count > self._n


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def job_repo() -> IJobRepository:
    return _FakeJobRepo()


@pytest.fixture
def backup_engine() -> _FakeBackupEngine:
    return _FakeBackupEngine()


@pytest.fixture
def mongo_metadata() -> _FakeMongoMetadata:
    return _FakeMongoMetadata()


@pytest.fixture
def audit_repo() -> IAuditRepository:
    return _FakeAuditRepo()


@pytest.fixture
def audit_service(audit_repo: IAuditRepository) -> AuditService:
    return AuditService(repository=audit_repo)


@pytest.fixture
def notifier() -> _FakeNotifier:
    return _FakeNotifier()


@pytest.fixture
def fs_utils() -> _FakeFsUtils:
    return _FakeFsUtils()


@pytest.fixture
def retention_manager(fs_utils: _FakeFsUtils) -> _FakeRetentionManager:
    return _FakeRetentionManager()


@pytest.fixture
def use_case(
    job_repo: _FakeJobRepo,
    backup_engine: _FakeBackupEngine,
    mongo_metadata: _FakeMongoMetadata,
    audit_service: AuditService,
    notifier: _FakeNotifier,
    retention_manager: _FakeRetentionManager,
    fs_utils: _FakeFsUtils,
) -> ExecuteBackupUseCase:
    return ExecuteBackupUseCase(
        job_repository=job_repo,
        backup_engine=backup_engine,
        mongo_metadata=mongo_metadata,
        audit_service=audit_service,
        notifier=notifier,
        retention_manager=retention_manager,
        fs_utils=fs_utils,
        backup_base_path=Path("/backups"),
    )


@pytest.fixture
def admin_user() -> User:
    return User(telegram_id=1, role=UserRole.ADMIN)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _store_queued_job(
    repo: _FakeJobRepo,
    *,
    backup_type: BackupType = BackupType.FULL,
    targets: list[CollectionTarget] | None = None,
) -> BackupJob:
    job = (
        BackupJob.create_full("job-001", 1, "hash123")
        if backup_type == BackupType.FULL
        else BackupJob.create_custom("job-001", 1, "hash123", targets or [])
    )
    job.mark_queued()
    await repo.save(job)
    return job


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestExecuteBackupHappyPath:
    @pytest.mark.asyncio
    async def test_full_backup_all_collections_succeed(
        self,
        use_case: ExecuteBackupUseCase,
        job_repo: _FakeJobRepo,
    ) -> None:
        job = await _store_queued_job(job_repo)
        dto = ExecuteBackupDto(job_id=job.id)

        result = await use_case.execute(dto)

        assert isinstance(result, ExecuteBackupResult)
        assert result.status == JobStatus.SUCCESS
        assert result.total_collections == 3  # db1:2 + db2:1
        assert result.completed_collections == 3
        assert result.failed_collections == 0
        assert result.bytes_processed == 3 * 1024

    @pytest.mark.asyncio
    async def test_custom_backup_all_collections_succeed(
        self,
        use_case: ExecuteBackupUseCase,
        job_repo: _FakeJobRepo,
    ) -> None:
        targets = [
            CollectionTarget(database="db1", collection="col1"),
            CollectionTarget(database="db1", collection="col2"),
        ]
        job = await _store_queued_job(job_repo, backup_type=BackupType.CUSTOM, targets=targets)
        dto = ExecuteBackupDto(job_id=job.id)

        result = await use_case.execute(dto)

        assert result.status == JobStatus.SUCCESS
        assert result.total_collections == 2
        assert result.completed_collections == 2
        assert result.failed_collections == 0

    @pytest.mark.asyncio
    async def test_job_marked_running_then_success(
        self,
        use_case: ExecuteBackupUseCase,
        job_repo: _FakeJobRepo,
    ) -> None:
        job = await _store_queued_job(job_repo)
        dto = ExecuteBackupDto(job_id=job.id)

        await use_case.execute(dto)

        stored = await job_repo.get_by_id(job.id)
        assert stored is not None
        assert stored.status == JobStatus.SUCCESS
        assert stored.started_at is not None
        assert stored.completed_at is not None
        assert stored.output_path is not None

    @pytest.mark.asyncio
    async def test_progress_updated_after_each_collection(
        self,
        use_case: ExecuteBackupUseCase,
        job_repo: _FakeJobRepo,
    ) -> None:
        targets = [
            CollectionTarget(database="db1", collection="col1"),
            CollectionTarget(database="db1", collection="col2"),
        ]
        job = await _store_queued_job(job_repo, backup_type=BackupType.CUSTOM, targets=targets)
        dto = ExecuteBackupDto(job_id=job.id)

        await use_case.execute(dto)

        stored = await job_repo.get_by_id(job.id)
        assert stored is not None
        assert stored.progress is not None
        assert stored.progress.total_collections == 2
        assert stored.progress.completed_collections == 2
        assert stored.progress.percent_complete == 100.0

    @pytest.mark.asyncio
    async def test_target_collections_replaced_without_duplicates(
        self,
        use_case: ExecuteBackupUseCase,
        job_repo: _FakeJobRepo,
    ) -> None:
        targets = [
            CollectionTarget(database="db1", collection="col1"),
            CollectionTarget(database="db1", collection="col2"),
        ]
        job = await _store_queued_job(job_repo, backup_type=BackupType.CUSTOM, targets=targets)
        dto = ExecuteBackupDto(job_id=job.id)

        await use_case.execute(dto)

        stored = await job_repo.get_by_id(job.id)
        assert stored is not None
        assert len(stored.target_collections) == 2
        assert all(t.status == CollectionBackupStatus.SUCCESS for t in stored.target_collections)

    @pytest.mark.asyncio
    async def test_audit_events_logged(
        self,
        use_case: ExecuteBackupUseCase,
        job_repo: _FakeJobRepo,
        audit_repo: _FakeAuditRepo,
    ) -> None:
        job = await _store_queued_job(job_repo)
        dto = ExecuteBackupDto(job_id=job.id)

        await use_case.execute(dto)

        events = [e.action for e in audit_repo.entries]
        assert "BACKUP_STARTED" in events
        assert "BACKUP_COMPLETED" in events

    @pytest.mark.asyncio
    async def test_notification_sent_to_requester(
        self,
        use_case: ExecuteBackupUseCase,
        job_repo: _FakeJobRepo,
        notifier: _FakeNotifier,
    ) -> None:
        job = await _store_queued_job(job_repo)
        dto = ExecuteBackupDto(job_id=job.id)

        await use_case.execute(dto)

        assert len(notifier.messages) == 1
        assert notifier.messages[0][0] == job.requester_telegram_id
        assert JobStatus.SUCCESS.value in notifier.messages[0][1]

    @pytest.mark.asyncio
    async def test_retention_applied_on_success(
        self,
        use_case: ExecuteBackupUseCase,
        job_repo: _FakeJobRepo,
        retention_manager: _FakeRetentionManager,
    ) -> None:
        job = await _store_queued_job(job_repo)
        dto = ExecuteBackupDto(job_id=job.id)

        await use_case.execute(dto)

        assert retention_manager.applied is True


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestExecuteBackupErrors:
    @pytest.mark.asyncio
    async def test_job_not_found_raises(
        self,
        use_case: ExecuteBackupUseCase,
    ) -> None:
        dto = ExecuteBackupDto(job_id="missing-job")

        with pytest.raises(JobNotFoundError) as exc_info:
            await use_case.execute(dto)
        assert exc_info.value.code == "JOB_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_invalid_state_transition_propagates(
        self,
        use_case: ExecuteBackupUseCase,
        job_repo: _FakeJobRepo,
    ) -> None:
        job = BackupJob.create_full("job-002", 1, "hash")
        job.mark_queued()
        job.mark_running()
        job.mark_success()
        await job_repo.save(job)

        dto = ExecuteBackupDto(job_id=job.id)
        with pytest.raises(InvalidStateTransitionError):
            await use_case.execute(dto)

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_fail_backup(
        self,
        job_repo: _FakeJobRepo,
        backup_engine: _FakeBackupEngine,
        mongo_metadata: _FakeMongoMetadata,
        audit_service: AuditService,
        retention_manager: _FakeRetentionManager,
        fs_utils: _FakeFsUtils,
    ) -> None:
        failing_notifier = _FakeNotifier(raise_on_send=True)
        use_case = ExecuteBackupUseCase(
            job_repository=job_repo,
            backup_engine=backup_engine,
            mongo_metadata=mongo_metadata,
            audit_service=audit_service,
            notifier=failing_notifier,
            retention_manager=retention_manager,
            fs_utils=fs_utils,
            backup_base_path=Path("/backups"),
        )
        job = await _store_queued_job(job_repo)
        dto = ExecuteBackupDto(job_id=job.id)

        result = await use_case.execute(dto)

        assert result.status == JobStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_retention_failure_does_not_fail_backup(
        self,
        job_repo: _FakeJobRepo,
        backup_engine: _FakeBackupEngine,
        mongo_metadata: _FakeMongoMetadata,
        audit_service: AuditService,
        notifier: _FakeNotifier,
        fs_utils: _FakeFsUtils,
    ) -> None:
        failing_retention = _FakeRetentionManager(raise_on_apply=True)
        use_case = ExecuteBackupUseCase(
            job_repository=job_repo,
            backup_engine=backup_engine,
            mongo_metadata=mongo_metadata,
            audit_service=audit_service,
            notifier=notifier,
            retention_manager=failing_retention,
            fs_utils=fs_utils,
            backup_base_path=Path("/backups"),
        )
        job = await _store_queued_job(job_repo)
        dto = ExecuteBackupDto(job_id=job.id)

        result = await use_case.execute(dto)

        assert result.status == JobStatus.SUCCESS


# ---------------------------------------------------------------------------
# Partial / total failure
# ---------------------------------------------------------------------------


class TestExecuteBackupPartialAndTotalFailure:
    @pytest.mark.asyncio
    async def test_partial_success_when_some_collections_fail(
        self,
        job_repo: _FakeJobRepo,
        mongo_metadata: _FakeMongoMetadata,
        audit_service: AuditService,
        notifier: _FakeNotifier,
        retention_manager: _FakeRetentionManager,
        fs_utils: _FakeFsUtils,
    ) -> None:
        targets = [
            CollectionTarget(database="db1", collection="col1"),
            CollectionTarget(database="db1", collection="col2"),
            CollectionTarget(database="db2", collection="col3"),
        ]
        engine = _FakeBackupEngine(fail_collections={("db1", "col2")})
        use_case = ExecuteBackupUseCase(
            job_repository=job_repo,
            backup_engine=engine,
            mongo_metadata=mongo_metadata,
            audit_service=audit_service,
            notifier=notifier,
            retention_manager=retention_manager,
            fs_utils=fs_utils,
            backup_base_path=Path("/backups"),
        )
        job = await _store_queued_job(job_repo, backup_type=BackupType.CUSTOM, targets=targets)
        dto = ExecuteBackupDto(job_id=job.id)

        result = await use_case.execute(dto)

        assert result.status == JobStatus.PARTIAL_SUCCESS
        assert result.completed_collections == 2
        assert result.failed_collections == 1
        assert result.bytes_processed == 2 * 1024

        stored = await job_repo.get_by_id(job.id)
        assert stored is not None
        failed = [t for t in stored.target_collections if t.status == CollectionBackupStatus.FAILED]
        assert len(failed) == 1
        assert failed[0].error_message is not None

    @pytest.mark.asyncio
    async def test_failed_when_all_collections_fail(
        self,
        job_repo: _FakeJobRepo,
        mongo_metadata: _FakeMongoMetadata,
        audit_service: AuditService,
        notifier: _FakeNotifier,
        retention_manager: _FakeRetentionManager,
        fs_utils: _FakeFsUtils,
    ) -> None:
        targets = [
            CollectionTarget(database="db1", collection="col1"),
            CollectionTarget(database="db1", collection="col2"),
        ]
        engine = _FakeBackupEngine(fail_collections={("db1", "col1"), ("db1", "col2")})
        use_case = ExecuteBackupUseCase(
            job_repository=job_repo,
            backup_engine=engine,
            mongo_metadata=mongo_metadata,
            audit_service=audit_service,
            notifier=notifier,
            retention_manager=retention_manager,
            fs_utils=fs_utils,
            backup_base_path=Path("/backups"),
        )
        job = await _store_queued_job(job_repo, backup_type=BackupType.CUSTOM, targets=targets)
        dto = ExecuteBackupDto(job_id=job.id)

        result = await use_case.execute(dto)

        assert result.status == JobStatus.FAILED
        assert result.completed_collections == 0
        assert result.failed_collections == 2
        assert result.error_log is not None


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class TestExecuteBackupCancellation:
    @pytest.mark.asyncio
    async def test_cancelled_mid_execution(
        self,
        job_repo: _FakeJobRepo,
        backup_engine: _FakeBackupEngine,
        mongo_metadata: _FakeMongoMetadata,
        audit_service: AuditService,
        notifier: _FakeNotifier,
        retention_manager: _FakeRetentionManager,
        fs_utils: _FakeFsUtils,
    ) -> None:
        targets = [
            CollectionTarget(database="db1", collection="col1"),
            CollectionTarget(database="db1", collection="col2"),
            CollectionTarget(database="db2", collection="col3"),
        ]
        use_case = ExecuteBackupUseCase(
            job_repository=job_repo,
            backup_engine=backup_engine,
            mongo_metadata=mongo_metadata,
            audit_service=audit_service,
            notifier=notifier,
            retention_manager=retention_manager,
            fs_utils=fs_utils,
            backup_base_path=Path("/backups"),
        )
        job = await _store_queued_job(job_repo, backup_type=BackupType.CUSTOM, targets=targets)
        dto = ExecuteBackupDto(job_id=job.id)

        result = await use_case.execute(dto, cancel_check=_CancelAfterN(1))

        assert result.status == JobStatus.CANCELLED
        assert result.completed_collections == 1
        assert result.failed_collections == 0

        stored = await job_repo.get_by_id(job.id)
        assert stored is not None
        assert stored.status == JobStatus.CANCELLED
        assert stored.cancelled_by == 0

    @pytest.mark.asyncio
    async def test_retention_not_applied_when_cancelled(
        self,
        job_repo: _FakeJobRepo,
        backup_engine: _FakeBackupEngine,
        mongo_metadata: _FakeMongoMetadata,
        audit_service: AuditService,
        notifier: _FakeNotifier,
        retention_manager: _FakeRetentionManager,
        fs_utils: _FakeFsUtils,
    ) -> None:
        targets = [
            CollectionTarget(database="db1", collection="col1"),
            CollectionTarget(database="db1", collection="col2"),
        ]
        use_case = ExecuteBackupUseCase(
            job_repository=job_repo,
            backup_engine=backup_engine,
            mongo_metadata=mongo_metadata,
            audit_service=audit_service,
            notifier=notifier,
            retention_manager=retention_manager,
            fs_utils=fs_utils,
            backup_base_path=Path("/backups"),
        )
        job = await _store_queued_job(job_repo, backup_type=BackupType.CUSTOM, targets=targets)
        dto = ExecuteBackupDto(job_id=job.id)

        await use_case.execute(dto, cancel_check=_CancelAfterN(0))

        assert retention_manager.applied is False
