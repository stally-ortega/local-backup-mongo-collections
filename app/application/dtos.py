"""Application-level Data Transfer Objects (DTOs).

These objects carry data from the interface layer into application services
without exposing domain internals directly.
"""

from pydantic import BaseModel, Field

from app.domain.entities.user import User
from app.domain.value_objects.dtos import CollectionTarget
from app.domain.value_objects.enums import BackupType, JobStatus


class CreateJobRequest(BaseModel):
    """Payload required to instantiate a new :class:`~app.domain.entities.backup_job.BackupJob`."""

    requester_telegram_id: int = Field(..., gt=0)
    backup_type: BackupType
    cluster_uri_hash: str = Field(..., min_length=1)
    target_collections: list[CollectionTarget] | None = None


class RequestBackupDto(BaseModel):
    """Input payload for the backup request use case."""

    user: User
    backup_type: BackupType
    cluster_uri_hash: str = Field(..., min_length=1)
    target_collections: list[CollectionTarget] | None = None
    topic: str = "BACKUP_REQUESTS"
    command: str | None = None


class RequestBackupResult(BaseModel):
    """Outcome of a successful backup request."""

    job_id: str = Field(..., min_length=1)
    status: JobStatus
