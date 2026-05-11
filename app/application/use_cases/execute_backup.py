"""Use case: execute a previously queued backup job.

Orchestrates the actual backup run: state transitions, per-collection
execution via the backup engine, progress tracking, cancellation checks,
retention enforcement, and user notification.
"""

from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from app.application.dtos import ExecuteBackupDto, ExecuteBackupResult
from app.application.ports.ports import (
    IBackupEngine,
    IFsUtils,
    ILockManager,
    IMongoMetadata,
    INotifier,
    IRetentionManager,
)
from app.application.services.audit_service import AuditService
from app.domain.entities.backup_job import BackupJob
from app.domain.exceptions.domain_errors import (
    BackupEngineError,
    JobAlreadyRunningError,
    JobNotFoundError,
)
from app.domain.repositories.repositories import IJobRepository
from app.domain.value_objects.dtos import CollectionTarget, JobProgress
from app.domain.value_objects.enums import BackupType, CollectionBackupStatus, JobStatus

CancelCheck = Callable[[], Awaitable[bool]] | None


class ExecuteBackupUseCase:
    """Coordinates the end-to-end execution of a backup job.

    Parameters
    ----------
    job_repository:
        Persistence port for :class:`~app.domain.entities.backup_job.BackupJob`.
    backup_engine:
        Port that performs the actual ``mongodump``-style collection backup.
    mongo_metadata:
        Port that lists databases and collections for ``FULL`` backups.
    audit_service:
        Structured audit logger.
    notifier:
        Notification channel adapter (Telegram, email, etc.).
    retention_manager:
        Service that applies post-backup retention policies.
    fs_utils:
        Async filesystem adapter.
    backup_base_path:
        Root directory where per-job backup outputs are stored.
    """

    _CLUSTER_LOCK_PREFIX: str = "backup:cluster"
    _LOCK_TTL: int = 3600  # 1 hour

    def __init__(
        self,
        *,
        job_repository: IJobRepository,
        backup_engine: IBackupEngine,
        mongo_metadata: IMongoMetadata,
        audit_service: AuditService,
        notifier: INotifier,
        retention_manager: IRetentionManager,
        fs_utils: IFsUtils,
        lock_manager: ILockManager | None = None,
        backup_base_path: Path,
    ) -> None:
        self._job_repository = job_repository
        self._backup_engine = backup_engine
        self._mongo_metadata = mongo_metadata
        self._audit_service = audit_service
        self._notifier = notifier
        self._retention_manager = retention_manager
        self._fs_utils = fs_utils
        self._lock_manager = lock_manager
        self._backup_base_path = backup_base_path

    async def execute(
        self,
        dto: ExecuteBackupDto,
        *,
        cancel_check: CancelCheck = None,
    ) -> ExecuteBackupResult:
        """Run the complete backup execution pipeline.

        Parameters
        ----------
        dto:
            Execution payload containing the job identifier.
        cancel_check:
            Optional async callable invoked before every collection backup.
            When it returns ``True`` the loop aborts and the job is marked
            ``CANCELLED``.

        Raises
        ------
        JobNotFoundError
            When the referenced job does not exist.
        InvalidStateTransitionError
            When the job is in a state that cannot transition to ``RUNNING``.
        """
        job = await self._job_repository.get_by_id(dto.job_id)
        if job is None:
            raise JobNotFoundError(
                message=f"Job {dto.job_id} not found",
                details={"job_id": dto.job_id},
            )

        # Acquire cluster-scoped lock before transitioning to RUNNING.
        lock_token: str | None = None
        if self._lock_manager is not None:
            lock_name = f"{self._CLUSTER_LOCK_PREFIX}:{job.cluster_uri_hash}"
            lock_token = await self._lock_manager.acquire(
                lock_name,
                ttl_seconds=self._LOCK_TTL,
            )
            if lock_token is None:
                raise JobAlreadyRunningError(
                    message="Another backup is already running for this cluster",
                    details={"job_id": dto.job_id, "cluster_hash": job.cluster_uri_hash},
                )

        try:
            job.mark_running()

            output_dir = self._backup_base_path / job.cluster_uri_hash / job.id
            await self._fs_utils.ensure_dir(output_dir)
            job.output_path = output_dir
            await self._job_repository.save(job)

            targets = await self._resolve_targets(job)
            total = len(targets)

            started_at = datetime.utcnow()
            await self._audit_service.log_job_event(
                job_id=job.id,
                event="BACKUP_STARTED",
                requester_telegram_id=job.requester_telegram_id,
                details={"total_collections": total},
            )

            completed = 0
            failed = 0
            bytes_processed = 0
            collection_results: list[CollectionTarget] = []
            was_cancelled = False

            for target in targets:
                if cancel_check is not None and await cancel_check():
                    was_cancelled = True
                    break

                result = await self._backup_single_collection(
                    job=job,
                    target=target,
                    output_dir=output_dir,
                )
                collection_results.append(result)

                if result.status == CollectionBackupStatus.SUCCESS:
                    completed += 1
                    bytes_processed += result.size_bytes or 0
                else:
                    failed += 1

                percent = round(((completed + failed) / total) * 100, 2) if total else 0.0
                job.update_progress(
                    JobProgress(
                        total_collections=total,
                        completed_collections=completed,
                        failed_collections=failed,
                        percent_complete=percent,
                        bytes_processed=bytes_processed,
                    )
                )
                job.target_collections = collection_results
                await self._job_repository.save(job)

            final_status = self._finalize_job(
                job=job,
                was_cancelled=was_cancelled,
                total=total,
                failed=failed,
                collection_results=collection_results,
            )
            await self._job_repository.save(job)

            duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
            await self._audit_service.log_job_event(
                job_id=job.id,
                event=self._event_name(final_status),
                requester_telegram_id=job.requester_telegram_id,
                result=final_status.value,
                details={
                    "completed_collections": completed,
                    "failed_collections": failed,
                    "total_collections": total,
                    "bytes_processed": bytes_processed,
                    "duration_ms": duration_ms,
                },
            )

            await self._notify(job, final_status, completed, failed, total, bytes_processed)
            await self._apply_retention(final_status)

            return ExecuteBackupResult(
                job_id=job.id,
                status=final_status,
                completed_collections=completed,
                failed_collections=failed,
                total_collections=total,
                bytes_processed=bytes_processed,
                error_log=job.error_log,
            )
        finally:
            if self._lock_manager is not None and lock_token is not None:
                lock_name = f"{self._CLUSTER_LOCK_PREFIX}:{job.cluster_uri_hash}"
                with suppress(Exception):
                    await self._lock_manager.release(lock_name, lock_token)

    async def _resolve_targets(self, job: BackupJob) -> list[CollectionTarget]:
        """Return the list of collections to back up for *job*."""
        if job.backup_type == BackupType.CUSTOM:
            return [
                CollectionTarget(
                    database=t.database,
                    collection=t.collection,
                    status=CollectionBackupStatus.PENDING,
                )
                for t in job.target_collections
            ]

        targets: list[CollectionTarget] = []
        databases = await self._mongo_metadata.list_databases(job.cluster_uri_hash)
        for database in databases:
            collections = await self._mongo_metadata.list_collections(
                job.cluster_uri_hash, database
            )
            for collection in collections:
                targets.append(
                    CollectionTarget(
                        database=database,
                        collection=collection,
                        status=CollectionBackupStatus.PENDING,
                    )
                )
        return targets

    async def _backup_single_collection(
        self,
        *,
        job: BackupJob,
        target: CollectionTarget,
        output_dir: Path,
    ) -> CollectionTarget:
        """Back up a single collection and return its result descriptor.

        Failures at the collection level are caught so that the overall job
        can continue and finish as ``PARTIAL_SUCCESS`` rather than aborting.
        """
        try:
            return await self._backup_engine.backup_collection(
                database=target.database,
                collection=target.collection,
                output_path=output_dir,
            )
        except BackupEngineError as exc:
            return CollectionTarget(
                database=target.database,
                collection=target.collection,
                status=CollectionBackupStatus.FAILED,
                error_message=exc.message,
            )

    def _finalize_job(
        self,
        *,
        job: BackupJob,
        was_cancelled: bool,
        total: int,
        failed: int,
        collection_results: list[CollectionTarget],
    ) -> JobStatus:
        """Transition the job to its terminal state based on execution outcome."""
        if was_cancelled:
            job.mark_cancelled(by_telegram_id=0)
            return JobStatus.CANCELLED

        if total > 0 and failed == total:
            error_log = "\n".join(r.error_message for r in collection_results if r.error_message)
            job.mark_failed(error_log=error_log or "All collections failed")
            return JobStatus.FAILED

        if failed > 0:
            job.mark_partial_success()
            return JobStatus.PARTIAL_SUCCESS

        job.mark_success()
        return JobStatus.SUCCESS

    @staticmethod
    def _event_name(status: JobStatus) -> str:
        """Map a terminal job status to its audit event name."""
        mapping = {
            JobStatus.SUCCESS: "BACKUP_COMPLETED",
            JobStatus.PARTIAL_SUCCESS: "BACKUP_PARTIAL",
            JobStatus.FAILED: "BACKUP_FAILED",
            JobStatus.CANCELLED: "BACKUP_CANCELLED",
        }
        return mapping.get(status, "BACKUP_FINISHED")

    async def _notify(
        self,
        job: BackupJob,
        status: JobStatus,
        completed: int,
        failed: int,
        total: int,
        bytes_processed: int,
    ) -> None:
        """Send a best-effort completion notification to the job requester.

        Notification failures are intentionally **not** raised so that a
        transient Telegram outage does not flip a successfully backed-up job
        into ``FAILED``.
        """
        summary = (
            f"Backup job #{job.id} finished with status {status.value}.\n"
            f"Collections: {completed}/{total} succeeded"
        )
        if failed:
            summary += f", {failed} failed"
        summary += "."
        if bytes_processed:
            summary += f"\nTotal size: {bytes_processed} bytes."

        with suppress(Exception):
            await self._notifier.send_message(
                chat_id=job.requester_telegram_id,
                text=summary,
            )

    async def _apply_retention(self, status: JobStatus) -> None:
        """Trigger retention cleanup for successful backups.

        Retention failures are treated as non-fatal so that a corrupted
        archive from an earlier run cannot block new backups.
        """
        if status not in {JobStatus.SUCCESS, JobStatus.PARTIAL_SUCCESS}:
            return

        with suppress(Exception):
            await self._retention_manager.apply_policy()
