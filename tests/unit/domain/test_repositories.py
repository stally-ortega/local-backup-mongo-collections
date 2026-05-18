"""Tests verifying repository protocol shapes and fake implementations."""

from datetime import datetime
from typing import Any

import pytest

from app.domain.entities.audit_log import AuditLog
from app.domain.entities.backup_job import BackupJob
from app.domain.entities.user import User
from app.domain.repositories.repositories import (  # noqa: TCH001
    IAuditRepository,
    IJobRepository,
    IRateLimitRepository,
    IUserRepository,
)
from app.domain.value_objects.enums import JobStatus, UserRole


class _FakeUserRepo:
    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return User(telegram_id=telegram_id, role=UserRole.ADMIN)

    async def list_all(self, page: int = 1, page_size: int = 50) -> list[User]:
        return []

    async def count_all(self) -> int:
        return 0

    async def save(self, user: User) -> None:
        pass

    async def update_role(self, telegram_id: int, role: UserRole) -> User | None:
        return User(telegram_id=telegram_id, role=role)

    async def toggle_active(self, telegram_id: int) -> User | None:
        return User(telegram_id=telegram_id, role=UserRole.ADMIN)


class _FakeJobRepo:
    async def get_by_id(self, job_id: str) -> BackupJob | None:
        return BackupJob.create_full(job_id, 1, "a" * 64)

    async def list_by_user(
        self,
        telegram_id: int,
        status: JobStatus | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[BackupJob]:
        return []

    async def list_by_status(
        self, status: JobStatus | None = None, page: int = 1, page_size: int = 50
    ) -> list[BackupJob]:
        return []

    async def count_by_status(self, status: JobStatus) -> int:
        return 0

    async def save(self, job: BackupJob) -> None:
        pass

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
    async def log(self, entry: AuditLog) -> None:
        pass

    async def list_by_user(
        self, telegram_id: int, page: int = 1, page_size: int = 50
    ) -> list[AuditLog]:
        return []

    async def list_by_job(self, job_id: str, page: int = 1, page_size: int = 50) -> list[AuditLog]:
        return []

    async def list_by_date_range(
        self, start: datetime, end: datetime, page: int = 1, page_size: int = 50
    ) -> list[AuditLog]:
        return []


class _FakeRateLimitRepo:
    async def check_limit(
        self, telegram_id: int, action: str, max_allowed: int, window_seconds: int
    ) -> bool:
        return True

    async def increment(self, telegram_id: int, action: str, window_seconds: int) -> int:
        return 1

    async def reset(self, telegram_id: int, action: str) -> None:
        pass


class TestUserRepositoryProtocol:
    def test_fake_implements_protocol(self) -> None:
        repo: IUserRepository = _FakeUserRepo()
        assert repo is not None

    @pytest.mark.asyncio
    async def test_get_by_telegram_id(self) -> None:
        repo: IUserRepository = _FakeUserRepo()
        user = await repo.get_by_telegram_id(123)
        assert user is not None
        assert user.telegram_id == 123

    @pytest.mark.asyncio
    async def test_update_role(self) -> None:
        repo: IUserRepository = _FakeUserRepo()
        user = await repo.update_role(1, UserRole.DBA)
        assert user is not None
        assert user.role == UserRole.DBA


class TestJobRepositoryProtocol:
    def test_fake_implements_protocol(self) -> None:
        repo: IJobRepository = _FakeJobRepo()
        assert repo is not None

    @pytest.mark.asyncio
    async def test_get_by_id(self) -> None:
        repo: IJobRepository = _FakeJobRepo()
        job = await repo.get_by_id("j1")
        assert job is not None
        assert job.id == "j1"

    @pytest.mark.asyncio
    async def test_list_by_status(self) -> None:
        repo: IJobRepository = _FakeJobRepo()
        jobs = await repo.list_by_status(JobStatus.PENDING)
        assert jobs == []

    @pytest.mark.asyncio
    async def test_count_by_status(self) -> None:
        repo: IJobRepository = _FakeJobRepo()
        count = await repo.count_by_status(JobStatus.RUNNING)
        assert count == 0


class TestAuditRepositoryProtocol:
    def test_fake_implements_protocol(self) -> None:
        repo: IAuditRepository = _FakeAuditRepo()
        assert repo is not None

    @pytest.mark.asyncio
    async def test_log(self) -> None:
        repo: IAuditRepository = _FakeAuditRepo()
        entry = AuditLog(
            telegram_id=123,
            action="BACKUP",
            topic="BACKUP_REQUESTS",
            result="SUCCESS",
        )
        await repo.log(entry)


class TestRateLimitRepositoryProtocol:
    def test_fake_implements_protocol(self) -> None:
        repo: IRateLimitRepository = _FakeRateLimitRepo()
        assert repo is not None

    @pytest.mark.asyncio
    async def test_check_limit(self) -> None:
        repo: IRateLimitRepository = _FakeRateLimitRepo()
        ok = await repo.check_limit(123, "BACKUP", 5, 60)
        assert ok is True

    @pytest.mark.asyncio
    async def test_increment(self) -> None:
        repo: IRateLimitRepository = _FakeRateLimitRepo()
        count = await repo.increment(123, "BACKUP", 60)
        assert count == 1

    @pytest.mark.asyncio
    async def test_reset(self) -> None:
        repo: IRateLimitRepository = _FakeRateLimitRepo()
        await repo.reset(123, "BACKUP")
