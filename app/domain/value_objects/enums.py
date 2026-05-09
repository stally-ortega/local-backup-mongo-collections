"""Typed domain enumerations used throughout the application.

All enums are ``str``-backed so they serialize naturally to JSON,
compare with plain strings, and remain fully typed.
"""

from enum import Enum


class UserRole(str, Enum):
    """RBAC roles available in the platform."""

    ADMIN = "ADMIN"
    DBA = "DBA"
    OPERATOR = "OPERATOR"
    READONLY = "READONLY"


class BackupType(str, Enum):
    """Scope of a backup operation."""

    FULL = "FULL"
    CUSTOM = "CUSTOM"


class JobStatus(str, Enum):
    """Lifecycle states of a backup job."""

    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    CANCELLED = "CANCELLED"
    RETRYING = "RETRYING"


class CollectionBackupStatus(str, Enum):
    """Outcome of an individual collection backup within a job."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TopicType(str, Enum):
    """Telegram topic categories for operational routing."""

    BACKUP_REQUESTS = "BACKUP_REQUESTS"
    SIZE_ASK = "SIZE_ASK"
    EXECUTION_ERRORS = "EXECUTION_ERRORS"
    ADMIN = "ADMIN"
