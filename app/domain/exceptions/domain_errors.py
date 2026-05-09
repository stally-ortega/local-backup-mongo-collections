"""Domain-level exceptions raised by business rules and entity guards."""


class DomainError(Exception):
    """Base exception for all domain-layer errors."""


class InvalidStateTransitionError(DomainError):
    """Raised when a :class:`~app.domain.entities.backup_job.BackupJob` receives
    an illegal state transition.
    """


class PermissionDeniedError(DomainError):
    """Raised when a user lacks the required role for an operation."""
