"""Unit tests for AuditService."""

from datetime import datetime

import pytest

from app.application.services.audit_service import AuditService
from app.domain.entities.audit_log import AuditLog
from app.domain.entities.user import User
from app.domain.value_objects.enums import UserRole


class _FakeAuditRepository:
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
def fake_repo() -> _FakeAuditRepository:
    return _FakeAuditRepository()


@pytest.fixture
def service(fake_repo: _FakeAuditRepository) -> AuditService:
    return AuditService(repository=fake_repo)


@pytest.fixture
def user() -> User:
    return User(telegram_id=42, role=UserRole.OPERATOR)


class TestAuditServiceLogAction:
    @pytest.mark.asyncio
    async def test_log_action_defaults(
        self, service: AuditService, user: User, fake_repo: _FakeAuditRepository
    ) -> None:
        await service.log_action("BACKUP_REQUESTED", user)

        assert len(fake_repo.entries) == 1
        entry = fake_repo.entries[0]
        assert entry.telegram_id == 42
        assert entry.action == "BACKUP_REQUESTED"
        assert entry.topic == "GENERAL"
        assert entry.result == "SUCCESS"
        assert entry.command is None
        assert entry.duration_ms is None
        assert isinstance(entry.timestamp, datetime)

    @pytest.mark.asyncio
    async def test_log_action_with_options(
        self, service: AuditService, user: User, fake_repo: _FakeAuditRepository
    ) -> None:
        await service.log_action(
            "SIZE_QUERY",
            user,
            topic="SIZE_ASK",
            command="/size",
            result="FAILED",
            duration_ms=150,
            cluster_uri_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            context={"db": "production"},
        )

        assert len(fake_repo.entries) == 1
        entry = fake_repo.entries[0]
        assert entry.action == "SIZE_QUERY"
        assert entry.topic == "SIZE_ASK"
        assert entry.command == "/size"
        assert entry.result == "FAILED"
        assert entry.duration_ms == 150
        assert (
            entry.cluster_uri_hash
            == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        assert entry.details == {"db": "production"}

    @pytest.mark.asyncio
    async def test_log_action_for_inactive_user(
        self, service: AuditService, fake_repo: _FakeAuditRepository
    ) -> None:
        inactive = User(telegram_id=99, role=UserRole.READONLY, is_active=False)
        await service.log_action("LIST_JOBS", inactive)

        assert len(fake_repo.entries) == 1
        assert fake_repo.entries[0].telegram_id == 99


class TestAuditServiceLogJobEvent:
    @pytest.mark.asyncio
    async def test_log_job_event_defaults(
        self, service: AuditService, fake_repo: _FakeAuditRepository
    ) -> None:
        await service.log_job_event(
            job_id="job-123",
            event="JOB_QUEUED",
            requester_telegram_id=42,
        )

        assert len(fake_repo.entries) == 1
        entry = fake_repo.entries[0]
        assert entry.telegram_id == 42
        assert entry.action == "JOB_QUEUED"
        assert entry.topic == "JOB_EVENTS"
        assert entry.command is None
        assert entry.result == "SUCCESS"
        assert entry.duration_ms is None

    @pytest.mark.asyncio
    async def test_log_job_event_with_details(
        self, service: AuditService, fake_repo: _FakeAuditRepository
    ) -> None:
        await service.log_job_event(
            job_id="job-456",
            event="JOB_FAILED",
            requester_telegram_id=7,
            details={"error": "disk full"},
            result="FAILED",
        )

        assert len(fake_repo.entries) == 1
        entry = fake_repo.entries[0]
        assert entry.action == "JOB_FAILED"
        assert entry.result == "FAILED"
        assert entry.telegram_id == 7
        assert entry.job_id == "job-456"
        assert entry.details == {"error": "disk full"}
