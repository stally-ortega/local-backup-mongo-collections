"""Use case: request a new backup job.

Orchestrates permission checks, rate limiting, disk-space validation,
job creation, audit logging, and queue enqueueing.
"""

from contextlib import suppress
from pathlib import Path

from app.application.dtos import CreateJobRequest, RequestBackupDto, RequestBackupResult
from app.application.ports.ports import IFsUtils, ILockManager
from app.application.services.audit_service import AuditService
from app.application.services.job_manager import JobManager
from app.application.services.permission_service import PermissionService
from app.domain.exceptions.domain_errors import (
    DiskSpaceError,
    JobAlreadyRunningError,
    PermissionError,
    RateLimitError,
)
from app.domain.repositories.repositories import IRateLimitRepository


class RequestBackupUseCase:
    """Coordinates the backup request flow from validation to enqueueing.

    Parameters
    ----------
    permission_service:
        RBAC evaluator.
    rate_limit_repo:
        Persistence port for rate-limit counters.
    fs_utils:
        Async filesystem adapter for disk-space checks.
    job_manager:
        Orchestrator for :class:`~app.domain.entities.backup_job.BackupJob`
        creation and enqueueing.
    audit_service:
        Structured audit logger.
    backup_base_path:
        Directory whose volume is inspected for free space.
    max_backup_rate:
        Maximum backup requests allowed per user within the rate window.
    backup_rate_window:
        Rate-limit window in seconds.
    min_free_disk_bytes:
        Minimum free bytes required on the backup volume.
    """

    _GLOBAL_LOCK: str = "backup:global"
    _LOCK_TTL: int = 3600  # 1 hour

    def __init__(
        self,
        *,
        permission_service: PermissionService,
        rate_limit_repo: IRateLimitRepository,
        fs_utils: IFsUtils,
        job_manager: JobManager,
        audit_service: AuditService,
        lock_manager: ILockManager | None = None,
        backup_base_path: Path,
        max_backup_rate: int = 1,
        backup_rate_window: int = 60,
        min_free_disk_bytes: int = 1_073_741_824,  # 1 GB
    ) -> None:
        self._permission_service = permission_service
        self._rate_limit_repo = rate_limit_repo
        self._fs_utils = fs_utils
        self._job_manager = job_manager
        self._audit_service = audit_service
        self._lock_manager = lock_manager
        self._backup_base_path = backup_base_path
        self._max_backup_rate = max_backup_rate
        self._backup_rate_window = backup_rate_window
        self._min_free_disk_bytes = min_free_disk_bytes

    async def execute(self, dto: RequestBackupDto) -> RequestBackupResult:
        """Run the complete backup request pipeline.

        Raises
        ------
        PermissionError
            When the user lacks the required role.
        RateLimitError
            When the user has exceeded the backup request rate limit.
        DiskSpaceError
            When the backup volume has less than ``min_free_disk_bytes`` free.
        """
        # 1. RBAC guard
        if not self._permission_service.can_execute(dto.user, "BACKUP", dto.topic):
            raise PermissionError(
                message="User is not authorised to request backups",
                details={
                    "user_id": dto.user.telegram_id,
                    "topic": dto.topic,
                },
            )

        # 2. Rate-limit guard
        allowed = await self._rate_limit_repo.check_limit(
            telegram_id=dto.user.telegram_id,
            action="BACKUP",
            max_allowed=self._max_backup_rate,
            window_seconds=self._backup_rate_window,
        )
        if not allowed:
            raise RateLimitError(
                message="Backup rate limit exceeded. Please wait before retrying.",
                details={
                    "user_id": dto.user.telegram_id,
                    "window_seconds": self._backup_rate_window,
                },
            )

        # 3. Distributed lock guard (global backup lock)
        lock_token: str | None = None
        if self._lock_manager is not None:
            lock_token = await self._lock_manager.acquire(
                self._GLOBAL_LOCK,
                ttl_seconds=self._LOCK_TTL,
            )
            if lock_token is None:
                raise JobAlreadyRunningError(
                    message="Another backup is currently in progress. Please wait and retry.",
                    details={"user_id": dto.user.telegram_id},
                )

        try:
            # 4. Disk-space guard
            total_bytes, used_bytes, free_bytes = await self._fs_utils.get_disk_usage(
                self._backup_base_path
            )
            if free_bytes < self._min_free_disk_bytes:
                raise DiskSpaceError(
                    message=(
                        f"Insufficient disk space: {free_bytes} bytes free, "
                        f"{self._min_free_disk_bytes} bytes required"
                    ),
                    details={
                        "free_bytes": free_bytes,
                        "required_bytes": self._min_free_disk_bytes,
                        "total_bytes": total_bytes,
                        "used_bytes": used_bytes,
                    },
                )

            # 5. Create job
            create_req = CreateJobRequest(
                requester_telegram_id=dto.user.telegram_id,
                chat_id=dto.chat_id,
                topic_id=dto.topic_id,
                backup_type=dto.backup_type,
                cluster_uri_hash=dto.cluster_uri_hash,
                target_collections=dto.target_collections,
            )
            job = await self._job_manager.create_job(create_req)

            # 6. Commit immediately so the worker sees the row in SQLite
            await self._job_manager.commit()

            # 7. Audit the user action
            await self._audit_service.log_action(
                action="BACKUP_REQUESTED",
                user=dto.user,
                topic=dto.topic,
                command=dto.command,
                result="SUCCESS",
            )

            # 8. Enqueue for execution
            await self._job_manager.enqueue_job(job.id)

            # 8. Increment rate-limit counter
            await self._rate_limit_repo.increment(
                telegram_id=dto.user.telegram_id,
                action="BACKUP",
                window_seconds=self._backup_rate_window,
            )

            return RequestBackupResult(
                job_id=job.id,
                status=job.status,
            )
        finally:
            if self._lock_manager is not None and lock_token is not None:
                with suppress(Exception):
                    await self._lock_manager.release(self._GLOBAL_LOCK, lock_token)
