"""Repository interfaces (ports) for the domain layer.

Implementations live in ``app/infrastructure/persistence/`` and are
injected into application services at runtime.
"""

from datetime import datetime
from typing import Any, Protocol

from app.domain.entities.audit_log import AuditLog
from app.domain.entities.backup_job import BackupJob
from app.domain.entities.user import User
from app.domain.value_objects.enums import JobStatus, UserRole


class IUserRepository(Protocol):
    """Persistence port for :class:`~app.domain.entities.user.User`."""

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        """Fetch a user by their Telegram ID."""
        ...

    async def list_all(self, page: int = 1, page_size: int = 50) -> list[User]:
        """Return a paginated slice of registered users ordered by creation time."""
        ...

    async def count_all(self) -> int:
        """Return the total number of registered users."""
        ...

    async def save(self, user: User) -> None:
        """Persist a new or updated user."""
        ...

    async def update_role(self, telegram_id: int, role: UserRole) -> User | None:
        """Change the role of an existing user."""
        ...

    async def toggle_active(self, telegram_id: int) -> User | None:
        """Flip the ``is_active`` flag of the user identified by *telegram_id*."""
        ...


class IJobRepository(Protocol):
    """Persistence port for :class:`~app.domain.entities.backup_job.BackupJob`."""

    async def get_by_id(self, job_id: str) -> BackupJob | None:
        """Fetch a job by its unique identifier."""
        ...

    async def list_by_user(
        self,
        telegram_id: int,
        status: JobStatus | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[BackupJob]:
        """Return jobs requested by the given Telegram user, optionally filtered by status."""
        ...

    async def list_by_status(
        self, status: JobStatus, page: int = 1, page_size: int = 50
    ) -> list[BackupJob]:
        """Return all jobs in the supplied status."""
        ...

    async def save(self, job: BackupJob) -> None:
        """Persist a new or updated job."""
        ...

    async def commit(self) -> None:
        """Commit the current transaction so the job is durable on disk."""
        ...

    async def clear_session_cache(self) -> None:
        """Discard any in-memory identity map / snapshot so the next query hits the database."""
        ...

    async def get_job_stats(self) -> dict[str, Any]:
        """Return aggregated job statistics.

        Expected keys:
        - ``jobs_today`` (int)
        - ``jobs_week`` (int)
        - ``jobs_month`` (int)
        - ``success_rate_percent`` (float)
        - ``avg_duration_seconds`` (float | None)
        """
        ...


class IAuditRepository(Protocol):
    """Persistence port for :class:`~app.domain.entities.audit_log.AuditLog`."""

    async def log(self, entry: AuditLog) -> None:
        """Persist an audit entry."""
        ...

    async def list_by_user(
        self,
        telegram_id: int,
        page: int = 1,
        page_size: int = 50,
    ) -> list[AuditLog]:
        """Return audit entries for a specific Telegram user."""
        ...

    async def list_by_job(
        self,
        job_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> list[AuditLog]:
        """Return audit entries related to a specific job."""
        ...

    async def list_by_date_range(
        self,
        start: datetime,
        end: datetime,
        page: int = 1,
        page_size: int = 50,
    ) -> list[AuditLog]:
        """Return audit entries whose timestamp falls within [*start*, *end*]."""
        ...


class IRateLimitRepository(Protocol):
    """Persistence port for :class:`~app.domain.entities.rate_limit.RateLimit`."""

    async def check_limit(
        self,
        telegram_id: int,
        action: str,
        max_allowed: int,
        window_seconds: int,
    ) -> bool:
        """Return ``True`` when the user has not exceeded the rate limit."""
        ...

    async def increment(
        self,
        telegram_id: int,
        action: str,
        window_seconds: int,
    ) -> int:
        """Bump the counter and return the new value."""
        ...

    async def reset(self, telegram_id: int, action: str) -> None:
        """Zero out the counter for the given user and action."""
        ...
