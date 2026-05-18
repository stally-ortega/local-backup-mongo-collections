"""BackupJob entity with finite-state-machine lifecycle guards."""

from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from app.domain.entities.user import User
from app.domain.exceptions.domain_errors import InvalidStateTransitionError
from app.domain.value_objects.dtos import CollectionTarget, JobProgress
from app.domain.value_objects.enums import BackupType, JobStatus, UserRole


class BackupJob(BaseModel):
    """Represents a backup job and enforces valid state transitions."""

    model_config = {"validate_assignment": True}

    # Sentinel value for cancellations initiated by the worker/system.
    SYSTEM_TELEGRAM_ID: ClassVar[int] = -1

    id: str = Field(..., min_length=1)
    requester_telegram_id: int = Field(..., gt=0)
    chat_id: int | None = None
    topic_id: int | None = None
    status_message_id: int | None = None
    backup_type: BackupType
    status: JobStatus = JobStatus.PENDING
    cluster_uri_hash: str = Field(..., min_length=1, pattern=r"^[a-f0-9]{64}$")
    target_collections: list[CollectionTarget] = Field(default_factory=list)
    progress: JobProgress | None = None
    output_path: Path | None = None
    error_log: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_by: int | None = None
    queue_job_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Finite-state-machine adjacency list.
    _VALID_TRANSITIONS: ClassVar[dict[JobStatus, frozenset[JobStatus]]] = {
        JobStatus.PENDING: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
        JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
        JobStatus.RUNNING: frozenset(
            {
                JobStatus.SUCCESS,
                JobStatus.FAILED,
                JobStatus.PARTIAL_SUCCESS,
                JobStatus.CANCELLED,
            }
        ),
        JobStatus.CANCELLED: frozenset(),
        JobStatus.FAILED: frozenset(),
        JobStatus.PARTIAL_SUCCESS: frozenset(),
    }

    @classmethod
    def create_full(
        cls,
        job_id: str,
        requester_telegram_id: int,
        cluster_uri_hash: str,
        chat_id: int | None = None,
        topic_id: int | None = None,
        status_message_id: int | None = None,
    ) -> "BackupJob":
        """Factory for a full-cluster backup job."""
        return cls(
            id=job_id,
            requester_telegram_id=requester_telegram_id,
            chat_id=chat_id,
            topic_id=topic_id,
            status_message_id=status_message_id,
            backup_type=BackupType.FULL,
            cluster_uri_hash=cluster_uri_hash,
        )

    @classmethod
    def create_custom(
        cls,
        job_id: str,
        requester_telegram_id: int,
        cluster_uri_hash: str,
        target_collections: list[CollectionTarget],
        chat_id: int | None = None,
        topic_id: int | None = None,
        status_message_id: int | None = None,
    ) -> "BackupJob":
        """Factory for a custom (selected collections) backup job."""
        return cls(
            id=job_id,
            requester_telegram_id=requester_telegram_id,
            chat_id=chat_id,
            topic_id=topic_id,
            status_message_id=status_message_id,
            backup_type=BackupType.CUSTOM,
            cluster_uri_hash=cluster_uri_hash,
            target_collections=target_collections,
        )

    def _transition(self, new_status: JobStatus) -> None:
        """Validate and apply a state transition, updating timestamps."""
        if new_status not in self._VALID_TRANSITIONS.get(self.status, frozenset()):
            raise InvalidStateTransitionError(
                f"Illegal transition from {self.status.value} to {new_status.value}"
            )
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)

    def mark_queued(self) -> None:
        """Move job from ``PENDING`` to ``QUEUED``."""
        self._transition(JobStatus.QUEUED)

    def mark_running(self) -> None:
        """Move job from ``QUEUED`` to ``RUNNING``."""
        self._transition(JobStatus.RUNNING)
        if self.started_at is None:
            self.started_at = datetime.now(timezone.utc)

    def mark_success(self) -> None:
        """Move job from ``RUNNING`` to ``SUCCESS``."""
        self._transition(JobStatus.SUCCESS)
        self.completed_at = datetime.now(timezone.utc)

    def mark_partial_success(self) -> None:
        """Move job from ``RUNNING`` to ``PARTIAL_SUCCESS``."""
        self._transition(JobStatus.PARTIAL_SUCCESS)
        self.completed_at = datetime.now(timezone.utc)

    def mark_failed(self, error_log: str | None = None) -> None:
        """Move job from ``RUNNING`` to ``FAILED``."""
        self._transition(JobStatus.FAILED)
        if error_log:
            self.error_log = error_log
        self.completed_at = datetime.now(timezone.utc)

    def mark_cancelled(self, by_telegram_id: int) -> None:
        """Move job to ``CANCELLED`` if it is not already terminal."""
        self._transition(JobStatus.CANCELLED)
        self.cancelled_by = by_telegram_id
        self.completed_at = datetime.now(timezone.utc)

    def update_progress(self, progress: JobProgress) -> None:
        """Replace the current progress snapshot."""
        self.progress = progress
        self.updated_at = datetime.now(timezone.utc)

    def add_collection_result(self, result: CollectionTarget) -> None:
        """Append a completed collection target to the job."""
        self.target_collections.append(result)
        self.updated_at = datetime.now(timezone.utc)

    def can_be_cancelled_by(self, user: User) -> bool:
        """Return ``True`` when *user* may cancel this job.

        Rules:
        - Job must not be in a terminal state.
        - User must be active.
        - User must be an ADMIN or the original requester.
        """
        if self.status in {
            JobStatus.SUCCESS,
            JobStatus.FAILED,
            JobStatus.PARTIAL_SUCCESS,
            JobStatus.CANCELLED,
        }:
            return False
        if not user.is_active:
            return False
        if user.has_role(UserRole.ADMIN):
            return True
        return user.telegram_id == self.requester_telegram_id
