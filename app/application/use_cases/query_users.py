"""Use case: list registered users with pagination.

Restricted to ADMIN role; orchestrates audit logging.
"""

from app.application.dtos import QueryUsersDto, QueryUsersResult
from app.application.services.audit_service import AuditService
from app.domain.repositories.repositories import IUserRepository


class QueryUsersUseCase:
    """Coordinates paginated user listing for administrative purposes.

    Parameters
    ----------
    user_repository:
        Persistence port for :class:`~app.domain.entities.user.User`.
    audit_service:
        Structured audit logger.
    """

    def __init__(
        self,
        *,
        user_repository: IUserRepository,
        audit_service: AuditService,
    ) -> None:
        self._user_repository = user_repository
        self._audit_service = audit_service

    async def execute(self, dto: QueryUsersDto) -> QueryUsersResult:
        """Return a paginated slice of registered users ordered by creation time."""
        users = await self._user_repository.list_all(
            page=dto.page,
            page_size=dto.page_size,
        )
        total = await self._user_repository.count_all()

        await self._audit_service.log_action(
            action="LIST_USERS",
            user=dto.user,
            topic=dto.topic,
            command=dto.command,
            result="SUCCESS",
            context={"page": dto.page, "page_size": dto.page_size, "count": len(users)},
        )

        return QueryUsersResult(
            users=users,
            page=dto.page,
            page_size=dto.page_size,
            total=total,
        )
