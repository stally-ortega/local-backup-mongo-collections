"""Use case: add a new user to the platform whitelist.

Validates RBAC, checks for duplicates, persists the user, and logs the
action for audit.
"""

from app.application.dtos import AddUserDto, AddUserResult
from app.application.services.audit_service import AuditService
from app.application.services.permission_service import PermissionService
from app.domain.entities.user import User
from app.domain.exceptions.domain_errors import PermissionError
from app.domain.repositories.repositories import IUserRepository


class AddUserUseCase:
    """Coordinates whitelist user creation with RBAC and audit.

    Parameters
    ----------
    user_repository:
        Persistence port for :class:`~app.domain.entities.user.User`.
    permission_service:
        RBAC evaluator.
    audit_service:
        Structured audit logger.
    """

    def __init__(
        self,
        *,
        user_repository: IUserRepository,
        permission_service: PermissionService,
        audit_service: AuditService,
    ) -> None:
        self._user_repository = user_repository
        self._permission_service = permission_service
        self._audit_service = audit_service

    async def execute(self, dto: AddUserDto) -> AddUserResult:
        """Persist a new whitelist user.

        Raises
        ------
        PermissionError
            When the requesting user is not an ADMIN.
        """
        if not self._permission_service.can_execute(dto.requester, "MANAGE_USERS", dto.topic):
            raise PermissionError(
                message="Only ADMIN can add users to the whitelist",
                details={"requester_id": dto.requester.telegram_id},
            )

        existing = await self._user_repository.get_by_telegram_id(dto.telegram_id)
        is_new = existing is None

        user = User(
            telegram_id=dto.telegram_id,
            username=dto.username,
            role=dto.role,
            is_active=True,
        )
        await self._user_repository.save(user)

        await self._audit_service.log_action(
            action="USER_ADDED",
            user=dto.requester,
            topic=dto.topic,
            command=dto.command,
            result="SUCCESS",
            context={
                "target_telegram_id": dto.telegram_id,
                "target_username": dto.username,
                "target_role": dto.role.value,
                "is_new": is_new,
            },
        )

        return AddUserResult(
            telegram_id=dto.telegram_id,
            username=dto.username,
            role=dto.role,
            is_new=is_new,
        )
