"""Unit tests for :class:`~app.application.use_cases.add_user.AddUserUseCase`."""

from unittest.mock import AsyncMock

import pytest

from app.application.dtos import AddUserDto, AddUserResult
from app.application.services.audit_service import AuditService
from app.application.services.permission_service import PermissionService
from app.application.use_cases.add_user import AddUserUseCase
from app.domain.entities.user import User
from app.domain.exceptions.domain_errors import DomainPermissionError, UserAlreadyExistsError
from app.domain.repositories.repositories import IUserRepository
from app.domain.value_objects.enums import UserRole


@pytest.fixture
def mock_user_repo() -> AsyncMock:
    return AsyncMock(spec=IUserRepository)


@pytest.fixture
def mock_audit_service() -> AsyncMock:
    return AsyncMock(spec=AuditService)


@pytest.fixture
def perms() -> PermissionService:
    return PermissionService()


@pytest.fixture
def use_case(
    mock_user_repo: AsyncMock,
    mock_audit_service: AsyncMock,
    perms: PermissionService,
) -> AddUserUseCase:
    return AddUserUseCase(
        user_repository=mock_user_repo,
        permission_service=perms,
        audit_service=mock_audit_service,
    )


class TestAddUserUseCaseExecute:
    @pytest.mark.asyncio
    async def test_admin_can_add_new_user(
        self,
        use_case: AddUserUseCase,
        mock_user_repo: AsyncMock,
        mock_audit_service: AsyncMock,
    ) -> None:
        mock_user_repo.get_by_telegram_id.return_value = None
        mock_user_repo.save = AsyncMock()

        admin = User(telegram_id=1, username="admin", role=UserRole.ADMIN)
        dto = AddUserDto(
            requester=admin,
            telegram_id=99,
            username="alice",
            role=UserRole.OPERATOR,
        )

        result = await use_case.execute(dto)

        assert isinstance(result, AddUserResult)
        assert result.telegram_id == 99
        assert result.username == "alice"
        assert result.role == UserRole.OPERATOR
        assert result.is_new is True

        mock_user_repo.save.assert_awaited_once()
        mock_audit_service.log_action.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_admin_cannot_overwrite_existing_user(
        self,
        use_case: AddUserUseCase,
        mock_user_repo: AsyncMock,
        mock_audit_service: AsyncMock,
    ) -> None:
        existing = User(telegram_id=99, username="alice", role=UserRole.READONLY)
        mock_user_repo.get_by_telegram_id.return_value = existing

        admin = User(telegram_id=1, username="admin", role=UserRole.ADMIN)
        dto = AddUserDto(
            requester=admin,
            telegram_id=99,
            username="alice_new",
            role=UserRole.DBA,
        )

        with pytest.raises(UserAlreadyExistsError, match="already exists"):
            await use_case.execute(dto)

        mock_user_repo.save.assert_not_called()
        mock_audit_service.log_action.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_admin_cannot_add_user(
        self,
        use_case: AddUserUseCase,
        mock_user_repo: AsyncMock,
    ) -> None:
        operator = User(telegram_id=1, username="bob", role=UserRole.OPERATOR)
        dto = AddUserDto(
            requester=operator,
            telegram_id=99,
            username="alice",
            role=UserRole.OPERATOR,
        )

        with pytest.raises(DomainPermissionError, match="Only ADMIN"):
            await use_case.execute(dto)

        mock_user_repo.get_by_telegram_id.assert_not_called()
