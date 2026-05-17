"""Domain-level exception hierarchy.

All exceptions carry ``code``, ``message``, and optional ``details`` so that
upper layers can render user-facing or structured-log friendly errors without
coupling to exception classes.
"""

from typing import Any


class MongoOpsError(Exception):
    """Base exception for every error raised inside the MongoOps platform.

    Attributes
    ----------
    code:
        Machine-readable error identifier (e.g. ``CONFIG_INVALID``).
    message:
        Human-readable description.
    details:
        Arbitrary context useful for debugging or telemetry.
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class ConfigurationError(MongoOpsError):
    """Raised when application configuration is invalid or incomplete."""

    def __init__(
        self,
        message: str = "Invalid configuration",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code="CONFIG_INVALID", message=message, details=details)


class DomainPermissionError(MongoOpsError):
    """Raised when a principal lacks required privileges."""

    def __init__(
        self,
        message: str = "Permission denied",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code="PERMISSION_DENIED", message=message, details=details)


class BackupEngineError(MongoOpsError):
    """Raised when the underlying mongodump / filesystem engine fails."""

    def __init__(
        self,
        message: str = "Backup engine error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code="BACKUP_ENGINE_ERROR", message=message, details=details)


class JobError(MongoOpsError):
    """Raised for errors inside the backup job lifecycle."""

    def __init__(
        self,
        message: str = "Job error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code="JOB_ERROR", message=message, details=details)


class NotificationError(MongoOpsError):
    """Raised when a notification channel (Telegram, email, etc.) fails."""

    def __init__(
        self,
        message: str = "Notification failed",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code="NOTIFICATION_ERROR", message=message, details=details)


class RepositoryError(MongoOpsError):
    """Raised for persistence or data-access failures."""

    def __init__(
        self,
        message: str = "Repository error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code="REPOSITORY_ERROR", message=message, details=details)


class RateLimitError(MongoOpsError):
    """Raised when a user exceeds the allowed rate for an operation."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code="RATE_LIMIT_EXCEEDED", message=message, details=details)


class DiskSpaceError(BackupEngineError):
    """Raised when available disk space is below the configured threshold."""

    def __init__(
        self,
        message: str = "Insufficient disk space",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, details=details)
        self.code = "DISK_SPACE_ERROR"


# ---------------------------------------------------------------------------
# Legacy / fine-grained exceptions kept for backward compatibility.
# They inherit from the categories above so ``isinstance`` checks still work.
# ---------------------------------------------------------------------------


class DomainError(MongoOpsError):
    """Generic domain error (historical base)."""

    def __init__(
        self,
        message: str = "Domain error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code="DOMAIN_ERROR", message=message, details=details)


class JobNotFoundError(JobError):
    """Raised when a referenced backup job does not exist in the repository."""

    def __init__(
        self,
        message: str = "Job not found",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, details=details)
        self.code = "JOB_NOT_FOUND"


class InvalidStateTransitionError(JobError):
    """Raised when a :class:`~app.domain.entities.backup_job.BackupJob` receives
    an illegal state transition.
    """

    def __init__(
        self,
        message: str = "Invalid state transition",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, details=details)
        self.code = "INVALID_STATE_TRANSITION"


class JobAlreadyRunningError(JobError):
    """Raised when a backup cannot start because another one is in progress."""

    def __init__(
        self,
        message: str = "A backup job is already running",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, details=details)
        self.code = "JOB_ALREADY_RUNNING"


class PermissionDeniedError(DomainPermissionError):
    """Raised when a user lacks the required role for an operation."""

    def __init__(
        self,
        message: str = "Permission denied",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, details=details)
