"""BackupJob entity with finite-state-machine lifecycle guards."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.domain.entities.user import User
from app.domain.exceptions.domain_errors import InvalidStateTransitionError
from app.domain.value_objects.dtos import CollectionTarget, JobProgress
from app.domain.value_objects.enums import BackupType, JobStatus, UserRole


class BackupJob(BaseModel):
    """Represents a backup job and enforces valid state transitions."""

    model_config = {"validate_assignment": True}

    id: str = Field(..., min_length=1)
    requester_telegram_id: int = Field(..., gt=0)
    backup_type: BackupType
    status: JobStatus = JobStatus.PENDING
    cluster_uri_hash: str = Field(..., min_length=1)
    target_collections: list[CollectionTarget] = Field(default_factory=list)
    progress: JobProgress | None = None
    output_path: Path | None = None
    error_log: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_by: int | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Finite-state-machine adjacency list.
    _VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
        JobStatus.PENDING: {JobStatus.QUEUED, JobStatus.CANCELLED},
        JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED},
        JobStatus.RUNNING: {
            JobStatus.SUCCESS,
            JobStatus.FAILED,
            JobStatus.PARTIAL_SUCCESS,
            JobStatus.CANCELLED,
        },
        JobStatus.RETRYING: {JobStatus.RUNNING, JobStatus.CANCELLED},
        JobStatus.SUCCESS: set(),
        JobStatus.FAILED: set(),
        JobStatus.PARTIAL_SUCCESS: set(),
        JobStatus.CANCELLED: set(),
    }

    @classmethod
    def create_full(
        cls,
        job_id: str,
        requester_telegram_id: int,
        cluster_uri_hash: str,
    ) -> "BackupJob":
        """Factory for a full-cluster backup job."""
        return cls(
            id=job_id,
            requester_telegram_id=requester_telegram_id,
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
    ) -> "BackupJob":
        """Factory for a custom (selected collections) backup job."""
        return cls(
            id=job_id,
            requester_telegram_id=requester_telegram_id,
            backup_type=BackupType.CUSTOM,
            cluster_uri_hash=cluster_uri_hash,
            target_collections=target_collections,
        )

    def _transition(self, new_status: JobStatus) -> None:
        """Validate and apply a state transition, updating timestamps."""
        if new_status not in self._VALID_TRANSITIONS.get(self.status, set()):
            raise InvalidStateTransitionError(
                f"Illegal transition from {self.status.value} to {new_status.value}"
            )
        self.status = new_status
        self.updated_at = datetime.utcnow()

    def mark_queued(self) -> None:
        """Move job from ``PENDING`` to ``QUEUED``."""
        self._transition(JobStatus.QUEUED)

    def mark_running(self) -> None:
        """Move job from ``QUEUED`` or ``RETRYING`` to ``RUNNING``."""
        self._transition(JobStatus.RUNNING)
        if self.started_at is None:
            self.started_at = datetime.utcnow()

    def mark_success(self) -> None:
        """Move job from ``RUNNING`` to ``SUCCESS``."""
        self._transition(JobStatus.SUCCESS)
        self.completed_at = datetime.utcnow()

    def mark_failed(self, error_log: str | None = None) -> None:
        """Move job from ``RUNNING`` or ``RETRYING`` to ``FAILED``."""
        self._transition(JobStatus.FAILED)
        if error_log:
            self.error_log = error_log
        self.completed_at = datetime.utcnow()

    def mark_cancelled(self, by_telegram_id: int) -> None:
        """Move job to ``CANCELLED`` if it is not already terminal."""
        self._transition(JobStatus.CANCELLED)
        self.cancelled_by = by_telegram_id
        self.completed_at = datetime.utcnow()

    def update_progress(self, progress: JobProgress) -> None:
        """Replace the current progress snapshot."""
        self.progress = progress
        self.updated_at = datetime.utcnow()

    def add_collection_result(self, result: CollectionTarget) -> None:
        """Append a completed collection target to the job."""
        self.target_collections.append(result)
        self.updated_at = datetime.utcnow()

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
