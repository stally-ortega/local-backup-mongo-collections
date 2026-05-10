"""Application service for audit logging.

Persists structured audit entries via :class:`~app.domain.repositories.repositories.IAuditRepository`.
"""

from typing import Any

from app.domain.entities.audit_log import AuditLog
from app.domain.entities.user import User
from app.domain.repositories.repositories import IAuditRepository


class AuditService:
    """Wraps the audit repository with convenience methods for common events."""

    def __init__(self, repository: IAuditRepository) -> None:
        self._repository = repository

    async def log_action(
        self,
        action: str,
        user: User,
        *,
        topic: str = "GENERAL",
        command: str | None = None,
        result: str = "SUCCESS",
        duration_ms: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Persist a generic user action to the audit trail.

        Parameters
        ----------
        action:
            Domain action name (e.g. ``BACKUP_REQUESTED``).
        user:
            The principal who triggered the action.
        topic:
            Operational topic category.
        command:
            Optional Telegram command text.
        result:
            Outcome string (default ``SUCCESS``).
        duration_ms:
            Optional elapsed time in milliseconds.
        context:
            Extra key-value pairs merged into ``details``.
        """
        entry = AuditLog(
            telegram_id=user.telegram_id,
            action=action,
            topic=topic,
            command=command,
            result=result,
            duration_ms=duration_ms,
        )
        await self._repository.log(entry)

    async def log_job_event(
        self,
        job_id: str,
        event: str,
        *,
        requester_telegram_id: int,
        details: dict[str, Any] | None = None,
        result: str = "SUCCESS",
    ) -> None:
        """Persist a job-centric event to the audit trail.

        Parameters
        ----------
        job_id:
            Identifier of the affected job.
        event:
            Event name (e.g. ``JOB_QUEUED``, ``JOB_FAILED``).
        requester_telegram_id:
            Telegram ID of the user who owns or triggered the job.
        details:
            Extra context (e.g. error message, progress snapshot).
        result:
            Outcome string (default ``SUCCESS``).
        """
        entry = AuditLog(
            telegram_id=requester_telegram_id,
            action=event,
            topic="JOB_EVENTS",
            command=None,
            result=result,
            duration_ms=None,
        )
        await self._repository.log(entry)
