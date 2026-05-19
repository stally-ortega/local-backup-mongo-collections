"""Unit tests for PermissionService."""

import pytest

from app.application.services.permission_service import PermissionService
from app.domain.entities.backup_job import BackupJob
from app.domain.entities.user import User
from app.domain.value_objects.enums import TopicType, UserRole


@pytest.fixture
def admin_user() -> User:
    return User(telegram_id=1, role=UserRole.ADMIN)


@pytest.fixture
def operator_user() -> User:
    return User(telegram_id=2, role=UserRole.OPERATOR)


@pytest.fixture
def readonly_user() -> User:
    return User(telegram_id=3, role=UserRole.READONLY)


@pytest.fixture
def inactive_user() -> User:
    return User(telegram_id=4, role=UserRole.ADMIN, is_active=False)


class TestPermissionServiceCanExecute:
    def test_inactive_user_denied(self, operator_user: User) -> None:
        operator_user.is_active = False
        svc = PermissionService()
        assert svc.can_execute(operator_user, "BACKUP", "BACKUP_REQUESTS") is False

    def test_delegates_to_user_when_no_custom_matrix(
        self, admin_user: User, readonly_user: User
    ) -> None:
        svc = PermissionService()

        assert svc.can_execute(admin_user, "BACKUP", "BACKUP_REQUESTS") is True
        assert svc.can_execute(readonly_user, "BACKUP", "BACKUP_REQUESTS") is False
        assert svc.can_execute(readonly_user, "SIZE_QUERY", "SIZE_ASK") is True

    def test_custom_command_permissions_denied(self, operator_user: User) -> None:
        svc = PermissionService(
            command_permissions={"BACKUP": {UserRole.ADMIN}},
        )
        assert svc.can_execute(operator_user, "BACKUP", "BACKUP_REQUESTS") is False

    def test_custom_command_and_topic_permissions_allowed(self, operator_user: User) -> None:
        svc = PermissionService(
            command_permissions={"BACKUP": {UserRole.OPERATOR}},
            topic_permissions={TopicType.BACKUP_REQUESTS: {UserRole.OPERATOR}},
        )
        assert svc.can_execute(operator_user, "BACKUP", "BACKUP_REQUESTS") is True

    def test_custom_topic_permissions_denied(self, operator_user: User) -> None:
        svc = PermissionService(
            command_permissions={"BACKUP": {UserRole.OPERATOR}},
            topic_permissions={TopicType.BACKUP_REQUESTS: {UserRole.ADMIN}},
        )
        assert svc.can_execute(operator_user, "BACKUP", "BACKUP_REQUESTS") is False

    def test_invalid_topic_returns_false(self, admin_user: User) -> None:
        svc = PermissionService()
        assert svc.can_execute(admin_user, "BACKUP", "INVALID_TOPIC") is False

    def test_partial_config_falls_back_to_entity(self, operator_user: User) -> None:
        svc = PermissionService(
            command_permissions={"BACKUP": {UserRole.OPERATOR}},
            topic_permissions=None,
        )
        assert svc.can_execute(operator_user, "BACKUP", "BACKUP_REQUESTS") is True


class TestPermissionServiceCanCancel:
    def test_delegates_to_job(self, admin_user: User) -> None:
        job = BackupJob.create_full("j1", 1, "a" * 64)
        svc = PermissionService()
        assert svc.can_cancel(admin_user, job) is True

    def test_operator_cannot_cancel_terminal_job(self, operator_user: User) -> None:
        job = BackupJob.create_full("j1", 1, "a" * 64)
        job.mark_queued()
        job.mark_running()
        job.mark_success()
        svc = PermissionService()
        assert svc.can_cancel(operator_user, job) is False

    def test_inactive_user_cannot_cancel(self, inactive_user: User) -> None:
        job = BackupJob.create_full("j1", 1, "a" * 64)
        svc = PermissionService()
        assert svc.can_cancel(inactive_user, job) is False
