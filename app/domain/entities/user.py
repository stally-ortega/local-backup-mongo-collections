"""User entity representing a Telegram operator in the platform."""

from datetime import datetime, timezone
from types import MappingProxyType
from typing import ClassVar

from pydantic import BaseModel, Field

from app.domain.value_objects.enums import TopicType, UserRole


class User(BaseModel):
    """Platform user with RBAC controls.

    All fields except ``is_active`` are immutable after creation to preserve
    identity and audit consistency.
    """

    model_config = {"validate_assignment": True}

    telegram_id: int = Field(..., gt=0)
    username: str | None = None
    role: UserRole
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Role-to-command mapping (extendable without code changes).
    _COMMAND_PERMISSIONS: ClassVar[MappingProxyType[str, frozenset[UserRole]]] = MappingProxyType(
        {
            "BACKUP": frozenset({UserRole.ADMIN, UserRole.DBA, UserRole.OPERATOR}),
            "SIZE_QUERY": frozenset(
                {UserRole.ADMIN, UserRole.DBA, UserRole.OPERATOR, UserRole.READONLY}
            ),
            "CANCEL_JOB": frozenset({UserRole.ADMIN, UserRole.DBA, UserRole.OPERATOR}),
            "LIST_JOBS": frozenset(
                {UserRole.ADMIN, UserRole.DBA, UserRole.OPERATOR, UserRole.READONLY}
            ),
            "MANAGE_USERS": frozenset({UserRole.ADMIN}),
        }
    )

    _TOPIC_PERMISSIONS: ClassVar[MappingProxyType[TopicType, frozenset[UserRole]]] = (
        MappingProxyType(
            {
                TopicType.BACKUP_REQUESTS: frozenset(
                    {UserRole.ADMIN, UserRole.DBA, UserRole.OPERATOR}
                ),
                TopicType.SIZE_ASK: frozenset(
                    {UserRole.ADMIN, UserRole.DBA, UserRole.OPERATOR, UserRole.READONLY}
                ),
                TopicType.EXECUTION_ERRORS: frozenset({UserRole.ADMIN, UserRole.DBA}),
                TopicType.ADMIN: frozenset({UserRole.ADMIN}),
            }
        )
    )

    def model_post_init(self, __context: object) -> None:
        self.__dict__["_initialized"] = True

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_initialized", False) and name not in {"is_active", "_initialized"}:
            raise AttributeError(f"User.{name} is immutable after creation")
        super().__setattr__(name, value)

    def has_role(self, role: UserRole) -> bool:
        """Return ``True`` when the user holds *role*."""
        return self.role == role

    def can_execute(self, command: str, topic: str) -> bool:
        """Check whether the user may execute *command* inside *topic*.

        Both command and topic permissions must be satisfied.
        """
        if not self.is_active:
            return False

        allowed_roles = self._COMMAND_PERMISSIONS.get(command, frozenset())
        if self.role not in allowed_roles:
            return False

        try:
            topic_enum = TopicType(topic)
        except ValueError:
            return False

        allowed_topic_roles = self._TOPIC_PERMISSIONS.get(topic_enum, frozenset())
        return self.role in allowed_topic_roles
