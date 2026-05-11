"""Use case: query aggregated backup job metrics.

Computes counts, success rates, and storage consumption for admin dashboards.
"""

from pathlib import Path

from app.application.dtos import QueryMetricsDto, QueryMetricsResult
from app.application.ports.ports import IFsUtils
from app.domain.repositories.repositories import IJobRepository


class QueryMetricsUseCase:
    """Coordinates metrics collection from the job repository and filesystem.

    Parameters
    ----------
    job_repository:
        Persistence port for :class:`~app.domain.entities.backup_job.BackupJob`.
    fs_utils:
        Async filesystem adapter.
    backup_base_path:
        Directory whose size is measured as total backup storage.
    """

    def __init__(
        self,
        *,
        job_repository: IJobRepository,
        fs_utils: IFsUtils,
        backup_base_path: Path,
    ) -> None:
        self._job_repo = job_repository
        self._fs = fs_utils
        self._base_path = backup_base_path

    async def execute(self, dto: QueryMetricsDto) -> QueryMetricsResult:
        """Fetch job statistics and backup storage size.

        Parameters
        ----------
        dto:
            Request metadata (user, topic, command).

        Returns
        -------
        QueryMetricsResult
            Aggregated metrics ready for display.
        """
        stats = await self._job_repo.get_job_stats()
        storage = await self._fs.get_folder_size(self._base_path)

        return QueryMetricsResult(
            jobs_today=stats.get("jobs_today", 0),
            jobs_week=stats.get("jobs_week", 0),
            jobs_month=stats.get("jobs_month", 0),
            success_rate_percent=stats.get("success_rate_percent", 0.0),
            avg_duration_seconds=stats.get("avg_duration_seconds"),
            storage_bytes=storage,
        )
