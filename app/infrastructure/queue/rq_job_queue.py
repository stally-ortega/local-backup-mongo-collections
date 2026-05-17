"""RQ-backed implementation of :class:`~app.application.ports.ports.IJobQueue`.

Uses ``redis`` for persistence and ``rq.Queue`` for job management.
RQ status strings are mapped to the project's :class:`JobStatus` enum.
"""

import logging
from datetime import timedelta

import rq
from rq.job import Job as RQJob
from rq.serializers import JSONSerializer

from app.application.ports.ports import IJobQueue
from app.domain.value_objects.enums import JobStatus
from app.infrastructure.queue.redis_connection import RedisConnection

logger = logging.getLogger(__name__)

_DEFAULT_QUEUE_NAME: str = "default"

# Mapping from RQ status strings to domain JobStatus.
# RQ 2.8.0 statuses: created, queued, finished, failed, started,
# deferred, scheduled, stopped, canceled.
_RQ_TO_DOMAIN_STATUS: dict[str, JobStatus] = {
    "created": JobStatus.PENDING,
    "queued": JobStatus.QUEUED,
    "deferred": JobStatus.QUEUED,
    "scheduled": JobStatus.QUEUED,
    "started": JobStatus.RUNNING,
    "finished": JobStatus.SUCCESS,
    "failed": JobStatus.FAILED,
    "stopped": JobStatus.CANCELLED,
    "canceled": JobStatus.CANCELLED,
}


class RQJobQueue(IJobQueue):
    """Concrete adapter that delegates job-queue operations to RQ.

    Parameters
    ----------
    redis_connection:
        An open :class:`~app.infrastructure.queue.redis_connection.RedisConnection`.
    queue_name:
        Name of the RQ queue to use.
    """

    def __init__(
        self,
        redis_connection: RedisConnection,
        *,
        queue_name: str = _DEFAULT_QUEUE_NAME,
    ) -> None:
        self._redis = redis_connection
        self._queue = rq.Queue(
            name=queue_name,
            connection=redis_connection.client,
            serializer=JSONSerializer,
        )

    # ------------------------------------------------------------------
    # IJobQueue implementation
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        job_id: str,
        job_type: str,
        payload: dict[str, object],
        *,
        priority: str = "normal",
    ) -> str:
        """Enqueue a job and return its RQ-assigned identifier.

        The actual worker function and its wiring live in
        :mod:`app.workers.backup_worker`.
        """
        from app.workers.backup_worker import _backup_worker_fn

        # RQ does not have a native ``priority`` string; we use ``at_front``
        # as a coarse approximation for ``high`` priority.
        at_front = priority == "high"

        # Delay execution by 2 seconds so the Bot request can finish its
        # DB commit before the Worker tries to read the job row.
        rq_job: RQJob = self._queue.enqueue_in(
            timedelta(seconds=2),
            _backup_worker_fn,
            job_id,
            job_type=job_type,
            payload=payload,
            job_id=job_id,
            at_front=at_front,
        )
        logger.info(
            "Enqueued job %s (type=%s, priority=%s) -> RQ id=%s",
            job_id,
            job_type,
            priority,
            rq_job.id,
        )
        return str(rq_job.id)

    async def get_status(self, queue_job_id: str) -> str | None:
        """Fetch the RQ job and map its status to a domain ``JobStatus``."""
        try:
            job = RQJob.fetch(queue_job_id, connection=self._redis.client)
            rq_status = job.get_status()
            domain_status = _RQ_TO_DOMAIN_STATUS.get(rq_status)
            if domain_status is None:
                logger.warning(
                    "Unmapped RQ status '%s' for job %s",
                    rq_status,
                    queue_job_id,
                )
                return rq_status
            return domain_status.value
        except Exception:
            return None

    async def cancel_job(self, queue_job_id: str) -> bool:
        """Cancel the RQ job.

        In RQ 2.8.0 this is achieved via :meth:`rq.job.Job.cancel`.
        """
        try:
            job = RQJob.fetch(queue_job_id, connection=self._redis.client)
            job.cancel()
            logger.info("Cancelled RQ job %s", queue_job_id)
            return True
        except Exception as exc:
            logger.warning("Failed to cancel RQ job %s: %s", queue_job_id, exc)
            return False

    # ------------------------------------------------------------------
    # Extended API (not part of IJobQueue)
    # ------------------------------------------------------------------

    async def retry_job(self, queue_job_id: str) -> str | None:
        """Re-enqueue a failed or stopped job, incrementing its retry count.

        Returns the new RQ job identifier, or ``None`` on failure.
        """
        try:
            job = RQJob.fetch(queue_job_id, connection=self._redis.client)
            meta = job.get_meta()
            retry_count = meta.get("retry_count", 0) + 1
            meta["retry_count"] = retry_count
            job.save_meta()  # type: ignore[no-untyped-call]

            new_job = job.requeue()
            logger.info(
                "Retried RQ job %s -> %s (retry_count=%d)",
                queue_job_id,
                new_job.id,
                retry_count,
            )
            return str(new_job.id)
        except Exception as exc:
            logger.warning("Failed to retry RQ job %s: %s", queue_job_id, exc)
            return None
