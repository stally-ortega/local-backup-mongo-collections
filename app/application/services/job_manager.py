"""Application service that orchestrates the backup job lifecycle.

Coordinates creation, enqueueing, cancellation, and querying of
:class:`~app.domain.entities.backup_job.BackupJob` instances while keeping
the domain layer free of queue and persistence concerns.
"""

from typing import Any

from app.application.dtos import CreateJobRequest
from app.application.ports.ports import IJobQueue
from app.application.services.audit_service import AuditService
from app.application.services.permission_service import PermissionService
from app.domain.entities.backup_job import BackupJob
from app.domain.entities.user import User
from app.domain.exceptions.domain_errors import JobError, PermissionError
from app.domain.repositories.repositories import IJobRepository
from app.domain.value_objects.enums import BackupType, JobStatus


class JobManager:
    """Orchestrates job creation, enqueueing, cancellation, and status queries.

    Parameters
    ----------
    job_repository:
        Persistence port for :class:`~app.domain.entities.backup_job.BackupJob`.
    job_queue:
        Infrastructure port for the job-queue backend.
    permission_service:
        RBAC evaluator used to guard cancellation attempts.
    audit_service:
        Structured audit logger for job lifecycle events.
    """

    def __init__(
        self,
        *,
        job_repository: IJobRepository,
        job_queue: IJobQueue,
        permission_service: PermissionService,
        audit_service: AuditService,
    ) -> None:
        self._job_repository = job_repository
        self._job_queue = job_queue
        self._permission_service = permission_service
        self._audit_service = audit_service
        # In-memory mapping of local job_id → queue_job_id.
        # NOTE: This is transient. Production deployments should persist the
        # mapping (e.g. as a column on BackupJob) to survive restarts.
        self._job_id_to_queue_id: dict[str, str] = {}

    async def create_job(self, request: CreateJobRequest) -> BackupJob:
        """Persist a new backup job and return the created entity."""
        job_id = _generate_job_id()

        if request.backup_type == BackupType.FULL:
            job = BackupJob.create_full(
                job_id=job_id,
                requester_telegram_id=request.requester_telegram_id,
                cluster_uri_hash=request.cluster_uri_hash,
                chat_id=request.chat_id,
                topic_id=request.topic_id,
            )
        else:
            job = BackupJob.create_custom(
                job_id=job_id,
                requester_telegram_id=request.requester_telegram_id,
                cluster_uri_hash=request.cluster_uri_hash,
                target_collections=request.target_collections or [],
                chat_id=request.chat_id,
                topic_id=request.topic_id,
            )

        await self._job_repository.save(job)
        return job

    async def commit(self) -> None:
        """Commit the current transaction so the job is durable on disk."""
        await self._job_repository.commit()

    async def enqueue_job(self, job_id: str) -> str:
        """Queue an existing job for execution and transition it to ``QUEUED``.

        Returns the queue-assigned identifier so that callers can track the
        job in the external queue system.
        """
        job = await self._job_repository.get_by_id(job_id)
        if job is None:
            raise JobError(
                message=f"Job {job_id} not found",
                details={"job_id": job_id},
            )

        payload: dict[str, Any] = {
            "requester_telegram_id": job.requester_telegram_id,
            "chat_id": job.chat_id,
            "topic_id": job.topic_id,
            "status_message_id": job.status_message_id,
            "backup_type": job.backup_type.value,
            "cluster_uri_hash": job.cluster_uri_hash,
        }
        if job.target_collections:
            payload["target_collections"] = [t.model_dump() for t in job.target_collections]

        queue_job_id = await self._job_queue.enqueue(
            job_id=job_id,
            job_type="backup",
            payload=payload,
            priority="normal",
        )

        job.mark_queued()
        await self._job_repository.save(job)

        self._job_id_to_queue_id[job_id] = queue_job_id

        await self._audit_service.log_job_event(
            job_id=job_id,
            event="JOB_QUEUED",
            requester_telegram_id=job.requester_telegram_id,
        )

        return queue_job_id

    async def cancel_job(self, job_id: str, user: User) -> BackupJob:
        """Cancel a job after validating that *user* has the right to do so.

        If the job is currently ``QUEUED``, an attempt is made to cancel it in
        the external queue as well.
        """
        job = await self._job_repository.get_by_id(job_id)
        if job is None:
            raise JobError(
                message=f"Job {job_id} not found",
                details={"job_id": job_id},
            )

        if not self._permission_service.can_cancel(user, job):
            raise PermissionError(
                message="User is not allowed to cancel this job",
                details={"job_id": job_id, "user_id": user.telegram_id},
            )

        if job.status == JobStatus.QUEUED:
            queue_job_id = self._job_id_to_queue_id.get(job_id)
            if queue_job_id:
                await self._job_queue.cancel_job(queue_job_id)

        job.mark_cancelled(user.telegram_id)
        await self._job_repository.save(job)

        await self._audit_service.log_job_event(
            job_id=job_id,
            event="JOB_CANCELLED",
            requester_telegram_id=user.telegram_id,
            result="SUCCESS",
            details={"cancelled_by": user.telegram_id},
        )

        return job

    async def get_job_status(self, job_id: str) -> JobStatus:
        """Return the current status of the identified job."""
        job = await self._job_repository.get_by_id(job_id)
        if job is None:
            raise JobError(
                message=f"Job {job_id} not found",
                details={"job_id": job_id},
            )
        return job.status

    async def list_user_jobs(self, user: User) -> list[BackupJob]:
        """Return every job requested by *user*, ordered by recency."""
        return await self._job_repository.list_by_user(user.telegram_id)


def _generate_job_id() -> str:
    """Return a short, URL-safe identifier for a new job."""
    import uuid

    return uuid.uuid4().hex
