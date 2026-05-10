"""Application-level ports (outgoing interfaces) defining contracts for
external adapters.

These protocols live in the **application** layer so that use-case
interactors can declare their dependencies without coupling to concrete
infrastructure (Telegram, mongodump, Redis, RQ, etc.).
"""

from pathlib import Path
from typing import Protocol

from app.domain.entities.size_report import SizeReport
from app.domain.value_objects.dtos import CollectionTarget


class IBackupEngine(Protocol):
    """Port for the backup engine that executes mongodump-style operations."""

    async def backup_collection(
        self,
        database: str,
        collection: str,
        output_path: Path,
    ) -> CollectionTarget:
        """Back up a single collection and return a result descriptor."""
        ...

    async def get_version(self) -> str:
        """Return the backup engine version string."""
        ...

    async def validate_connection(self, cluster_uri_hash: str) -> bool:
        """Verify that the engine can reach the target cluster."""
        ...


class INotifier(Protocol):
    """Port for notification channels (Telegram, email, webhooks, etc.)."""

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        topic_id: int | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Send a plain-text message."""
        ...

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        correlation_id: str | None = None,
    ) -> None:
        """Update an existing message in-place."""
        ...

    async def send_document(
        self,
        chat_id: int,
        file_path: Path,
        *,
        caption: str | None = None,
        topic_id: int | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Send a file attachment."""
        ...


class IJobQueue(Protocol):
    """Port for a job-queue backend (Redis + RQ, Celery, etc.)."""

    async def enqueue(
        self,
        job_id: str,
        job_type: str,
        payload: dict[str, object],
        *,
        priority: str = "normal",
    ) -> str:
        """Queue a job and return its queue-assigned identifier."""
        ...

    async def get_status(self, queue_job_id: str) -> str | None:
        """Return the current status string for a queued job."""
        ...

    async def cancel_job(self, queue_job_id: str) -> bool:
        """Request cancellation and return whether it succeeded."""
        ...


class ILockManager(Protocol):
    """Port for distributed locking (Redis Redlock, PostgreSQL advisory, etc.)."""

    async def acquire(
        self,
        resource: str,
        *,
        ttl_seconds: int = 60,
    ) -> str | None:
        """Attempt to acquire a lock and return a token, or ``None`` on failure."""
        ...

    async def release(self, resource: str, token: str) -> bool:
        """Release a previously acquired lock."""
        ...

    async def is_locked(self, resource: str) -> bool:
        """Check whether *resource* is currently locked."""
        ...


class IFsUtils(Protocol):
    """Port for async-friendly filesystem utilities."""

    async def ensure_dir(self, path: Path) -> None:
        """Create directory tree if it does not already exist."""
        ...

    async def write_text(self, path: Path, content: str) -> None:
        """Write UTF-8 text to *path*."""
        ...

    async def get_folder_size(self, path: Path) -> int:
        """Return total size in bytes of *path* and its descendants."""
        ...

    async def get_disk_usage(self, path: Path) -> tuple[int, int, int]:
        """Return ``(total, used, free)`` bytes for the volume containing *path*."""
        ...

    async def compress(self, source: Path, destination: Path) -> None:
        """Create an archive at *destination* from the contents of *source*."""
        ...

    async def delete(self, path: Path) -> None:
        """Remove *path* (file or directory tree)."""
        ...


class IMongoMetadata(Protocol):
    """Port for MongoDB metadata and size introspection."""

    async def list_databases(self, cluster_uri_hash: str) -> list[str]:
        """Return database names available on the cluster."""
        ...

    async def list_collections(
        self,
        cluster_uri_hash: str,
        database: str,
    ) -> list[str]:
        """Return collection names inside *database*."""
        ...

    async def get_size_stats(
        self,
        cluster_uri_hash: str,
    ) -> SizeReport:
        """Return a complete size snapshot for the cluster."""
        ...
