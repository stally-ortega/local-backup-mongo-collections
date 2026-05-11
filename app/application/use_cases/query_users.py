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
        """Return every registered user ordered by creation time."""
        users = await self._user_repository.list_all()

        # Manual pagination because list_all returns the full set.
        offset = (dto.page - 1) * dto.page_size
        paginated = users[offset : offset + dto.page_size]

        await self._audit_service.log_action(
            action="LIST_USERS",
            user=dto.user,
            topic=dto.topic,
            command=dto.command,
            result="SUCCESS",
            context={"page": dto.page, "page_size": dto.page_size, "count": len(paginated)},
        )

        return QueryUsersResult(
            users=paginated,
            page=dto.page,
            page_size=dto.page_size,
            total=len(users),
        )
