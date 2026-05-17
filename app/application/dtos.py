"""Application-level Data Transfer Objects (DTOs).

These objects carry data from the interface layer into application services
without exposing domain internals directly.
"""

from pydantic import BaseModel, Field

from app.domain.entities.backup_job import BackupJob
from app.domain.entities.size_report import CollectionSize, DatabaseSize
from app.domain.entities.user import User
from app.domain.value_objects.dtos import CollectionTarget
from app.domain.value_objects.enums import BackupType, JobStatus, UserRole


class CreateJobRequest(BaseModel):
    """Payload required to instantiate a new :class:`~app.domain.entities.backup_job.BackupJob`."""

    requester_telegram_id: int = Field(..., gt=0)
    chat_id: int | None = None
    topic_id: int | None = None
    status_message_id: int | None = None
    backup_type: BackupType
    cluster_uri_hash: str = Field(..., min_length=1)
    target_collections: list[CollectionTarget] | None = None


class RequestBackupDto(BaseModel):
    """Input payload for the backup request use case."""

    user: User
    chat_id: int | None = None
    topic_id: int | None = None
    status_message_id: int | None = None
    backup_type: BackupType
    cluster_uri_hash: str = Field(..., min_length=1)
    target_collections: list[CollectionTarget] | None = None
    topic: str = "BACKUP_REQUESTS"
    command: str | None = None


class RequestBackupResult(BaseModel):
    """Outcome of a successful backup request."""

    job_id: str = Field(..., min_length=1)
    status: JobStatus


class ExecuteBackupDto(BaseModel):
    """Input payload for the backup execution use case.

    When the job row is not yet visible in SQLite (e.g. Docker-for-Windows
    replication lag), the optional fields below let the worker reconstruct
    the job in memory directly from the DTO so execution can continue.
    """

    job_id: str = Field(..., min_length=1)
    requester_telegram_id: int | None = None
    chat_id: int | None = None
    topic_id: int | None = None
    status_message_id: int | None = None
    backup_type: BackupType | None = None
    cluster_uri_hash: str | None = None
    target_collections: list[CollectionTarget] | None = None
    correlation_id: str | None = None


class ExecuteBackupResult(BaseModel):
    """Outcome of a backup execution."""

    job_id: str = Field(..., min_length=1)
    status: JobStatus
    completed_collections: int
    failed_collections: int
    total_collections: int
    bytes_processed: int
    error_log: str | None = None


class QuerySizeDto(BaseModel):
    """Input payload for the size query use case."""

    user: User
    scope: str = Field(..., pattern=r"^(cluster|database|collection)$")
    cluster_uri_hash: str = Field(..., min_length=1)
    database_name: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    topic: str = "SIZE_ASK"
    command: str | None = None


class QuerySizeResult(BaseModel):
    """Outcome of a size query."""

    scope: str
    cluster_uri_hash: str
    database_name: str | None = None
    total_size_bytes: int
    databases: list[DatabaseSize] | None = None
    collections: list[CollectionSize] | None = None


class CancelJobDto(BaseModel):
    """Input payload for the cancel job use case."""

    user: User
    job_id: str = Field(..., min_length=1)
    topic: str = "BACKUP_REQUESTS"
    command: str | None = None


class CancelJobResult(BaseModel):
    """Outcome of a job cancellation."""

    job_id: str = Field(..., min_length=1)
    status: JobStatus
    cancelled_by: int


class QueryJobsDto(BaseModel):
    """Input payload for the list-jobs use case."""

    user: User
    filter_status: JobStatus = JobStatus.QUEUED
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=50)
    topic: str = "ADMIN"
    command: str | None = None


class QueryJobsResult(BaseModel):
    """Outcome of a job-list query."""

    jobs: list[BackupJob]
    page: int
    page_size: int


class QueryUsersDto(BaseModel):
    """Input payload for the list-users use case."""

    user: User
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=50)
    topic: str = "ADMIN"
    command: str | None = None


class QueryUsersResult(BaseModel):
    """Outcome of a user-list query."""

    users: list[User]
    page: int
    page_size: int
    total: int


class AddUserDto(BaseModel):
    """Input payload for the add-user use case."""

    requester: User
    telegram_id: int = Field(..., gt=0)
    username: str = Field(..., min_length=1)
    role: UserRole
    topic: str = "ADMIN"
    command: str | None = None


class AddUserResult(BaseModel):
    """Outcome of adding a user to the whitelist."""

    telegram_id: int
    username: str
    role: UserRole
    is_new: bool


class HealthCheckDto(BaseModel):
    """Input payload for the health-check use case."""

    user: User
    topic: str = "ADMIN"
    command: str | None = None


class HealthCheckResult(BaseModel):
    """Outcome of a system health check."""

    mongodb: bool
    redis: bool
    disk_free_bytes: int
    disk_total_bytes: int
    running_jobs: int


class QueryMetricsDto(BaseModel):
    """Input payload for the metrics query use case."""

    user: User
    topic: str = "ADMIN"
    command: str | None = None


class QueryMetricsResult(BaseModel):
    """Outcome of a job-metrics query."""

    jobs_today: int
    jobs_week: int
    jobs_month: int
    success_rate_percent: float
    avg_duration_seconds: float | None
    storage_bytes: int
