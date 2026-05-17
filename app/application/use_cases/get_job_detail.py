"""Use case: retrieve a single backup job by identifier with RBAC checks."""

from app.application.dtos import GetJobDetailDto, GetJobDetailResult
from app.application.services.audit_service import AuditService
from app.domain.exceptions.domain_errors import DomainPermissionError, JobNotFoundError
from app.domain.repositories.repositories import IJobRepository
from app.domain.value_objects.enums import UserRole


class GetJobDetailUseCase:
    """Coordinates job retrieval with RBAC enforcement.

    Parameters
    ----------
    job_repository:
        Persistence port for :class:`~app.domain.entities.backup_job.BackupJob`.
    audit_service:
        Structured audit logger.
    """

    def __init__(
        self,
        *,
        job_repository: IJobRepository,
        audit_service: AuditService,
    ) -> None:
        self._job_repository = job_repository
        self._audit_service = audit_service

    async def execute(self, dto: GetJobDetailDto) -> GetJobDetailResult:
        """Return the identified job after validating access rights.

        Raises
        ------
        JobNotFoundError
            When the referenced job does not exist.
        DomainPermissionError
            When the user is not an ADMIN and does not own the job.
        """
        job = await self._job_repository.get_by_id(dto.job_id)
        if job is None:
            raise JobNotFoundError(
                message=f"Job {dto.job_id} not found",
                details={"job_id": dto.job_id},
            )

        if (
            not dto.user.has_role(UserRole.ADMIN)
            and dto.user.telegram_id != job.requester_telegram_id
        ):
            raise DomainPermissionError(
                message="No tienes permiso para ver este job.",
                details={"job_id": dto.job_id, "user_id": dto.user.telegram_id},
            )

        await self._audit_service.log_action(
            action="GET_JOB_DETAIL",
            user=dto.user,
            topic=dto.topic,
            command=dto.command,
            result="SUCCESS",
            context={"job_id": job.id, "status": job.status.value},
        )

        return GetJobDetailResult(job=job)
