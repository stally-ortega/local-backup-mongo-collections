"""Application service for RBAC permission checks.

Encapsulates the policy decision so that rules can evolve without
modifying domain entities directly.
"""

from app.domain.entities.backup_job import BackupJob
from app.domain.entities.user import User
from app.domain.value_objects.enums import TopicType, UserRole


class PermissionService:
    """Evaluates whether a user may perform commands, topics, or job actions.

    An optional custom RBAC matrix can be injected at construction time;
    when absent, the service delegates to the domain rules embedded in
    :class:`~app.domain.entities.user.User`.
    """

    def __init__(
        self,
        *,
        command_permissions: dict[str, set[UserRole]] | None = None,
        topic_permissions: dict[TopicType, set[UserRole]] | None = None,
    ) -> None:
        self._command_permissions = command_permissions
        self._topic_permissions = topic_permissions

    def can_execute(self, user: User, command: str, topic: str) -> bool:
        """Return ``True`` when *user* may execute *command* inside *topic*."""
        if not user.is_active:
            return False

        if self._command_permissions is not None:
            allowed = self._command_permissions.get(command, set())
            if user.role not in allowed:
                return False
        else:
            return user.can_execute(command, topic)

        try:
            topic_enum = TopicType(topic)
        except ValueError:
            return False

        if self._topic_permissions is not None:
            allowed = self._topic_permissions.get(topic_enum, set())
            return user.role in allowed

        # If we reach here, command_permissions was custom but topic_permissions
        # was not, which is a partial configuration. Fall back to entity default.
        return user.can_execute(command, topic)

    def can_cancel(self, user: User, job: BackupJob) -> bool:
        """Return ``True`` when *user* may cancel *job*."""
        return job.can_be_cancelled_by(user)
