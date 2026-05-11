"""Use case: list recent backup jobs with pagination.

Orchestrates RBAC-aware querying and audit logging.
"""

from app.application.dtos import QueryJobsDto, QueryJobsResult
from app.application.services.audit_service import AuditService
from app.domain.repositories.repositories import IJobRepository


class QueryJobsUseCase:
    """Coordinates paginated job listing with RBAC filtering.

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

    async def execute(self, dto: QueryJobsDto) -> QueryJobsResult:
        """Return the requested page of jobs.

        Admins see every job; other roles see only their own.
        """
        from app.domain.value_objects.enums import UserRole

        if dto.user.has_role(UserRole.ADMIN):
            jobs = await self._job_repository.list_by_status(
                status=dto.filter_status,
                page=dto.page,
                page_size=dto.page_size,
            )
        else:
            jobs = await self._job_repository.list_by_user(
                telegram_id=dto.user.telegram_id,
                page=dto.page,
                page_size=dto.page_size,
            )

        await self._audit_service.log_action(
            action="LIST_JOBS",
            user=dto.user,
            topic=dto.topic,
            command=dto.command,
            result="SUCCESS",
            context={"page": dto.page, "page_size": dto.page_size, "count": len(jobs)},
        )

        return QueryJobsResult(
            jobs=jobs,
            page=dto.page,
            page_size=dto.page_size,
        )
