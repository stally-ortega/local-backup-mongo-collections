"""Domain events raised by the backup and size-reporting subsystems.

Each event is an immutable value object carrying an ``occurred_on`` timestamp,
an optional ``correlation_id`` for distributed tracing, and a strongly typed
``payload``.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.domain.value_objects.dtos import CollectionTarget
from app.domain.value_objects.enums import BackupType, JobStatus


class EventPayload(BaseModel):
    """Marker base for all event payloads."""

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Backup lifecycle events
# ---------------------------------------------------------------------------


class BackupRequestedPayload(EventPayload):
    """Payload for :class:`BackupRequested`."""

    job_id: str = Field(..., min_length=1)
    requester_telegram_id: int = Field(..., gt=0)
    backup_type: BackupType
    cluster_uri_hash: str = Field(..., min_length=1, pattern=r"^[a-f0-9]{64}$")


class BackupStartedPayload(EventPayload):
    """Payload for :class:`BackupStarted`."""

    job_id: str = Field(..., min_length=1)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CollectionBackupCompletedPayload(EventPayload):
    """Payload for :class:`CollectionBackupCompleted`."""

    job_id: str = Field(..., min_length=1)
    result: CollectionTarget


class BackupCompletedPayload(EventPayload):
    """Payload for :class:`BackupCompleted`."""

    job_id: str = Field(..., min_length=1)
    status: JobStatus
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BackupFailedPayload(EventPayload):
    """Payload for :class:`BackupFailed`."""

    job_id: str = Field(..., min_length=1)
    error_log: str | None = None
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JobCancelledPayload(EventPayload):
    """Payload for :class:`JobCancelled`."""

    job_id: str = Field(..., min_length=1)
    cancelled_by: int = Field(..., gt=0)
    cancelled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Size query events
# ---------------------------------------------------------------------------


class SizeQueriedPayload(EventPayload):
    """Payload for :class:`SizeQueried`."""

    cluster_uri_hash: str = Field(..., min_length=1, pattern=r"^[a-f0-9]{64}$")
    requester_telegram_id: int = Field(..., gt=0)


# ---------------------------------------------------------------------------
# Event envelope
# ---------------------------------------------------------------------------


class DomainEvent(BaseModel):
    """Generic envelope for every domain event.

    Attributes
    ----------
    event_type:
        Discriminator string (e.g. ``BACKUP_REQUESTED``).
    occurred_on:
        UTC timestamp when the event was raised.
    correlation_id:
        Optional trace id for distributed logging.
    payload:
        Concrete event data.
    """

    model_config = {"frozen": True}

    event_type: str = Field(..., min_length=1)
    occurred_on: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str | None = None
    payload: EventPayload

    @classmethod
    def backup_requested(
        cls,
        payload: BackupRequestedPayload,
        correlation_id: str | None = None,
    ) -> "DomainEvent":
        return cls(
            event_type="BACKUP_REQUESTED",
            correlation_id=correlation_id,
            payload=payload,
        )

    @classmethod
    def backup_started(
        cls,
        payload: BackupStartedPayload,
        correlation_id: str | None = None,
    ) -> "DomainEvent":
        return cls(
            event_type="BACKUP_STARTED",
            correlation_id=correlation_id,
            payload=payload,
        )

    @classmethod
    def collection_backup_completed(
        cls,
        payload: CollectionBackupCompletedPayload,
        correlation_id: str | None = None,
    ) -> "DomainEvent":
        return cls(
            event_type="COLLECTION_BACKUP_COMPLETED",
            correlation_id=correlation_id,
            payload=payload,
        )

    @classmethod
    def backup_completed(
        cls,
        payload: BackupCompletedPayload,
        correlation_id: str | None = None,
    ) -> "DomainEvent":
        return cls(
            event_type="BACKUP_COMPLETED",
            correlation_id=correlation_id,
            payload=payload,
        )

    @classmethod
    def backup_failed(
        cls,
        payload: BackupFailedPayload,
        correlation_id: str | None = None,
    ) -> "DomainEvent":
        return cls(
            event_type="BACKUP_FAILED",
            correlation_id=correlation_id,
            payload=payload,
        )

    @classmethod
    def job_cancelled(
        cls,
        payload: JobCancelledPayload,
        correlation_id: str | None = None,
    ) -> "DomainEvent":
        return cls(
            event_type="JOB_CANCELLED",
            correlation_id=correlation_id,
            payload=payload,
        )

    @classmethod
    def size_queried(
        cls,
        payload: SizeQueriedPayload,
        correlation_id: str | None = None,
    ) -> "DomainEvent":
        return cls(
            event_type="SIZE_QUERIED",
            correlation_id=correlation_id,
            payload=payload,
        )
