"""SQLAlchemy implementation of :class:`~app.domain.repositories.repositories.IJobRepository`.

Maps between :class:`~app.domain.entities.backup_job.BackupJob` (domain entity) and
:class:`~app.infrastructure.persistence.models.job.JobORM` (SQLAlchemy model).
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.backup_job import BackupJob
from app.domain.repositories.repositories import IJobRepository
from app.domain.value_objects.dtos import CollectionTarget, JobProgress
from app.domain.value_objects.enums import BackupType, JobStatus
from app.infrastructure.persistence.models.job import JobORM


class SQLJobRepository(IJobRepository):
    """Async SQLAlchemy adapter for backup-job persistence.

    Parameters
    ----------
    session:
        An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.  The caller is
        responsible for commit/rollback lifecycle.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get_by_id(self, job_id: str) -> BackupJob | None:
        """Fetch a job by its unique identifier."""
        orm = await self._session.get(JobORM, job_id)
        return self._to_entity(orm) if orm else None

    async def list_by_user(
        self,
        telegram_id: int,
        status: JobStatus | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[BackupJob]:
        """Return jobs requested by the given Telegram user, optionally filtered by status."""
        offset = (page - 1) * page_size
        stmt = (
            select(JobORM)
            .where(JobORM.requester_telegram_id == telegram_id)
            .order_by(JobORM.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        if status is not None:
            stmt = stmt.where(JobORM.status == status.value)
        result = await self._session.execute(stmt)
        return [self._to_entity(row) for row in result.scalars().all()]

    async def list_by_status(
        self,
        status: JobStatus,
        page: int = 1,
        page_size: int = 50,
    ) -> list[BackupJob]:
        """Return all jobs in the supplied status."""
        offset = (page - 1) * page_size
        result = await self._session.execute(
            select(JobORM)
            .where(JobORM.status == status.value)
            .order_by(JobORM.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        return [self._to_entity(row) for row in result.scalars().all()]

    async def save(self, job: BackupJob) -> None:
        """Persist *job*, inserting or updating depending on existence."""
        existing = await self._session.execute(select(JobORM).where(JobORM.id == job.id))
        orm = existing.scalar_one_or_none()

        if orm is None:
            orm = self._to_orm(job)
            self._session.add(orm)
        else:
            self._update_orm(orm, job)
            await self._session.flush()
            await self._session.refresh(orm)
        await self._session.commit()

    async def clear_session_cache(self) -> None:
        """Rollback the current transaction to discard the identity map."""
        await self._session.rollback()

    async def get_job_stats(self) -> dict[str, Any]:
        """Return aggregated job statistics computed via SQLAlchemy."""
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        month_start = now - timedelta(days=30)

        today_count = await self._session.scalar(
            select(func.count()).select_from(JobORM).where(JobORM.created_at >= today_start)
        )
        week_count = await self._session.scalar(
            select(func.count()).select_from(JobORM).where(JobORM.created_at >= week_start)
        )
        month_count = await self._session.scalar(
            select(func.count()).select_from(JobORM).where(JobORM.created_at >= month_start)
        )

        completed_statuses = [
            JobStatus.SUCCESS.value,
            JobStatus.PARTIAL_SUCCESS.value,
            JobStatus.FAILED.value,
        ]
        total_completed = await self._session.scalar(
            select(func.count()).select_from(JobORM).where(JobORM.status.in_(completed_statuses))
        )
        successful = await self._session.scalar(
            select(func.count())
            .select_from(JobORM)
            .where(JobORM.status.in_([JobStatus.SUCCESS.value, JobStatus.PARTIAL_SUCCESS.value]))
        )

        success_rate = 0.0
        if total_completed and total_completed > 0:
            success_rate = round((successful or 0) / total_completed * 100, 2)

        # Average duration via Python to keep SQL portable across SQLite/PostgreSQL.
        result = await self._session.execute(
            select(JobORM.started_at, JobORM.completed_at)
            .where(JobORM.started_at.is_not(None))
            .where(JobORM.completed_at.is_not(None))
        )
        durations: list[float] = []
        for started, completed in result.all():
            if started and completed:
                durations.append((completed - started).total_seconds())
        avg_duration = round(sum(durations) / len(durations), 2) if durations else None

        return {
            "jobs_today": today_count or 0,
            "jobs_week": week_count or 0,
            "jobs_month": month_count or 0,
            "success_rate_percent": success_rate,
            "avg_duration_seconds": avg_duration,
        }

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_entity(orm: JobORM) -> BackupJob:
        """Map an ORM row to the domain :class:`BackupJob`."""
        progress = None
        if orm.total_collections is not None:
            percent = 0.0
            if orm.total_collections > 0:
                percent = round((orm.completed_collections / orm.total_collections) * 100, 2)
            progress = JobProgress(
                total_collections=orm.total_collections,
                completed_collections=orm.completed_collections,
                failed_collections=orm.failed_collections,
                retry_count=orm.retry_count,
                percent_complete=percent,
                bytes_processed=orm.bytes_processed,
            )

        collections = []
        if orm.target_collections:
            for item in orm.target_collections:
                collections.append(CollectionTarget(**item))

        return BackupJob(
            id=orm.id,
            requester_telegram_id=orm.requester_telegram_id,
            chat_id=orm.chat_id,
            topic_id=orm.topic_id,
            status_message_id=orm.status_message_id,
            backup_type=BackupType(orm.backup_type),
            status=JobStatus(orm.status),
            cluster_uri_hash=orm.cluster_uri_hash,
            target_collections=collections,
            progress=progress,
            output_path=Path(orm.output_path) if orm.output_path else None,
            error_log=orm.error_log,
            started_at=orm.started_at,
            completed_at=orm.completed_at,
            cancelled_by=orm.cancelled_by,
            queue_job_id=orm.queue_job_id,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def _to_orm(job: BackupJob) -> JobORM:
        """Map a domain :class:`BackupJob` to a new ORM row."""
        target_collections = [tc.model_dump(mode="json") for tc in job.target_collections]

        target_databases = None
        if job.target_collections:
            target_databases = sorted({tc.database for tc in job.target_collections})

        progress_kwargs = {}
        if job.progress:
            progress_kwargs = {
                "total_collections": job.progress.total_collections,
                "completed_collections": job.progress.completed_collections,
                "failed_collections": job.progress.failed_collections,
                "retry_count": job.progress.retry_count,
                "bytes_processed": job.progress.bytes_processed,
            }

        return JobORM(
            id=job.id,
            requester_telegram_id=job.requester_telegram_id,
            chat_id=job.chat_id,
            topic_id=job.topic_id,
            status_message_id=job.status_message_id,
            backup_type=job.backup_type.value,
            status=job.status.value,
            cluster_uri_hash=job.cluster_uri_hash,
            target_databases=target_databases,
            target_collections=target_collections or None,
            output_path=str(job.output_path) if job.output_path else None,
            error_log=job.error_log,
            started_at=job.started_at,
            completed_at=job.completed_at,
            cancelled_by=job.cancelled_by,
            queue_job_id=job.queue_job_id,
            created_at=job.created_at,
            updated_at=job.updated_at,
            **progress_kwargs,
        )

    @staticmethod
    def _update_orm(orm: JobORM, job: BackupJob) -> None:
        """Refresh an existing ORM row with values from *job*."""
        orm.requester_telegram_id = job.requester_telegram_id
        orm.chat_id = job.chat_id
        orm.topic_id = job.topic_id
        orm.status_message_id = job.status_message_id
        orm.backup_type = job.backup_type.value
        orm.status = job.status.value
        orm.cluster_uri_hash = job.cluster_uri_hash
        orm.target_collections = [
            tc.model_dump(mode="json") for tc in job.target_collections
        ] or None
        orm.target_databases = (
            sorted({tc.database for tc in job.target_collections})
            if job.target_collections
            else None
        )
        orm.output_path = str(job.output_path) if job.output_path else None
        orm.error_log = job.error_log
        orm.started_at = job.started_at
        orm.completed_at = job.completed_at
        orm.cancelled_by = job.cancelled_by
        orm.queue_job_id = job.queue_job_id
        orm.updated_at = job.updated_at

        if job.progress:
            orm.total_collections = job.progress.total_collections
            orm.completed_collections = job.progress.completed_collections
            orm.failed_collections = job.progress.failed_collections
            orm.retry_count = job.progress.retry_count
            orm.bytes_processed = job.progress.bytes_processed
