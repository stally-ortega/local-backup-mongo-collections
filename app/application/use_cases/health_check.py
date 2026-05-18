"""Use case: query system health status.

Pings external dependencies (MongoDB, Redis) and inspects local disk space
without exposing adapter details to the interface layer.
"""

from pathlib import Path

from app.application.dtos import HealthCheckDto, HealthCheckResult
from app.application.ports.ports import IFsUtils, IMongoHealth, IRedisHealth
from app.domain.repositories.repositories import IJobRepository
from app.domain.value_objects.enums import JobStatus


class HealthCheckUseCase:
    """Coordinates health probes across infrastructure adapters.

    Parameters
    ----------
    mongo_health:
        Optional MongoDB health port. When ``None``, the MongoDB check
        always reports ``False``.
    redis_health:
        Optional Redis health port. When ``None``, the Redis check
        always reports ``False``.
    fs_utils:
        Async filesystem adapter for disk-space inspection.
    backup_base_path:
        Directory whose volume is inspected for free space.
    job_repository:
        Optional repository to count currently RUNNING jobs.
    """

    def __init__(
        self,
        *,
        mongo_health: IMongoHealth | None = None,
        redis_health: IRedisHealth | None = None,
        fs_utils: IFsUtils,
        backup_base_path: Path,
        job_repository: IJobRepository | None = None,
    ) -> None:
        self._mongo = mongo_health
        self._redis = redis_health
        self._fs = fs_utils
        self._base_path = backup_base_path
        self._job_repo = job_repository

    async def execute(self, dto: HealthCheckDto) -> HealthCheckResult:
        """Run all configured health probes.

        Parameters
        ----------
        dto:
            Request metadata (user, topic, command).

        Returns
        -------
        HealthCheckResult
            Aggregated status of every probe.
        """
        mongo_ok = await self._ping_mongo()
        redis_ok = await self._ping_redis()
        total_bytes, _, free_bytes = await self._fs.get_disk_usage(self._base_path)
        running = await self._count_running_jobs()

        return HealthCheckResult(
            mongodb=mongo_ok,
            redis=redis_ok,
            disk_free_bytes=free_bytes,
            disk_total_bytes=total_bytes,
            running_jobs=running,
        )

    async def _ping_mongo(self) -> bool:
        if self._mongo is None:
            return False
        return await self._mongo.ping()

    async def _ping_redis(self) -> bool:
        if self._redis is None:
            return False
        return await self._redis.ping()

    async def _count_running_jobs(self) -> int:
        if self._job_repo is None:
            return 0
        return await self._job_repo.count_by_status(JobStatus.RUNNING)
