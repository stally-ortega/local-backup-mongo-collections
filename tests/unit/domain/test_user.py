"""Tests for the :class:`~app.domain.entities.user.User` entity."""

import pytest

from app.domain.entities.user import User
from app.domain.value_objects.enums import UserRole


class TestUserCreation:
    def test_create_minimal(self) -> None:
        user = User(telegram_id=123456, role=UserRole.ADMIN)
        assert user.telegram_id == 123456
        assert user.role == UserRole.ADMIN
        assert user.is_active is True
        assert user.username is None

    def test_create_with_username(self) -> None:
        user = User(telegram_id=1, username="admin", role=UserRole.DBA)
        assert user.username == "admin"

    def test_invalid_telegram_id_raises(self) -> None:
        with pytest.raises(ValueError):
            User(telegram_id=0, role=UserRole.ADMIN)


class TestUserImmutability:
    def test_is_active_mutable(self) -> None:
        user = User(telegram_id=1, role=UserRole.OPERATOR)
        user.is_active = False
        assert user.is_active is False

    def test_telegram_id_immutable(self) -> None:
        user = User(telegram_id=1, role=UserRole.OPERATOR)
        with pytest.raises(AttributeError):
            user.telegram_id = 2

    def test_role_immutable(self) -> None:
        user = User(telegram_id=1, role=UserRole.OPERATOR)
        with pytest.raises(AttributeError):
            user.role = UserRole.ADMIN

    def test_username_immutable(self) -> None:
        user = User(telegram_id=1, username="op", role=UserRole.OPERATOR)
        with pytest.raises(AttributeError):
            user.username = "new"


class TestUserHasRole:
    def test_positive(self) -> None:
        user = User(telegram_id=1, role=UserRole.ADMIN)
        assert user.has_role(UserRole.ADMIN) is True

    def test_negative(self) -> None:
        user = User(telegram_id=1, role=UserRole.READONLY)
        assert user.has_role(UserRole.ADMIN) is False


class TestUserCanExecute:
    def test_admin_can_backup(self) -> None:
        user = User(telegram_id=1, role=UserRole.ADMIN)
        assert user.can_execute("BACKUP", "BACKUP_REQUESTS") is True

    def test_readonly_cannot_backup(self) -> None:
        user = User(telegram_id=1, role=UserRole.READONLY)
        assert user.can_execute("BACKUP", "BACKUP_REQUESTS") is False

    def test_readonly_can_size_query(self) -> None:
        user = User(telegram_id=1, role=UserRole.READONLY)
        assert user.can_execute("SIZE_QUERY", "SIZE_ASK") is True

    def test_inactive_user_cannot_execute(self) -> None:
        user = User(telegram_id=1, role=UserRole.ADMIN)
        user.is_active = False
        assert user.can_execute("BACKUP", "BACKUP_REQUESTS") is False

    def test_unknown_command_returns_false(self) -> None:
        user = User(telegram_id=1, role=UserRole.ADMIN)
        assert user.can_execute("UNKNOWN", "BACKUP_REQUESTS") is False

    def test_unknown_topic_returns_false(self) -> None:
        user = User(telegram_id=1, role=UserRole.ADMIN)
        assert user.can_execute("BACKUP", "UNKNOWN") is False

    def test_operator_cannot_access_admin_topic(self) -> None:
        user = User(telegram_id=1, role=UserRole.OPERATOR)
        assert user.can_execute("MANAGE_USERS", "ADMIN") is False
