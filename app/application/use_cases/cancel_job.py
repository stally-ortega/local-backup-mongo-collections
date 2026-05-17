"""Use case: cancel a running or queued backup job.

Orchestrates permission validation, job state transition, queue
cancellation, and audit logging by delegating to
:class:`~app.application.services.job_manager.JobManager`.
"""

from app.application.dtos import CancelJobDto, CancelJobResult
from app.application.services.audit_service import AuditService
from app.application.services.job_manager import JobManager


class CancelJobUseCase:
    """Coordinates job cancellation with RBAC and audit.

    Parameters
    ----------
    job_manager:
        Application service that encapsulates job lifecycle operations.
    audit_service:
        Structured audit logger.
    """

    def __init__(
        self,
        *,
        job_manager: JobManager,
        audit_service: AuditService,
    ) -> None:
        self._job_manager = job_manager
        self._audit_service = audit_service

    async def execute(self, dto: CancelJobDto) -> CancelJobResult:
        """Cancel the identified job after validating that *user* has the right.

        Parameters
        ----------
        dto:
            Cancellation payload containing job identifier and principal.

        Raises
        ------
        DomainPermissionError
            When the user lacks the required role.
        JobError
            When the referenced job does not exist.
        InvalidStateTransitionError
            When the job is in a terminal state.
        """
        job = await self._job_manager.cancel_job(dto.job_id, dto.user)

        await self._audit_service.log_action(
            action="CANCEL_REQUESTED",
            user=dto.user,
            topic=dto.topic,
            command=dto.command,
            result="SUCCESS",
            context={"job_id": job.id},
        )

        return CancelJobResult(
            job_id=job.id,
            status=job.status,
            cancelled_by=job.cancelled_by or dto.user.telegram_id,
        )
