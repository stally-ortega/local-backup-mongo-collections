"""Unit tests for RQJobQueue."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from rq.exceptions import NoSuchJobError

from app.domain.value_objects.enums import JobStatus
from app.infrastructure.queue.redis_connection import RedisConnection
from app.infrastructure.queue.rq_job_queue import RQJobQueue


@pytest.fixture
def redis_conn() -> RedisConnection:
    return RedisConnection("redis://localhost:6379/0")


@pytest.fixture
def queue(redis_conn: RedisConnection) -> RQJobQueue:
    redis_conn._client = MagicMock()
    return RQJobQueue(redis_conn, queue_name="test-queue")


class TestEnqueue:
    @patch("app.infrastructure.queue.rq_job_queue.rq.Queue.enqueue_in")
    async def test_enqueues_worker_fn(
        self,
        mock_enqueue_in: MagicMock,
        queue: RQJobQueue,
    ) -> None:
        mock_job = MagicMock()
        mock_job.id = "rq-job-123"
        mock_enqueue_in.return_value = mock_job

        result = await queue.enqueue(
            job_id="platform-job-1",
            job_type="backup",
            payload={"key": "value"},
            priority="normal",
        )

        assert result == "rq-job-123"
        mock_enqueue_in.assert_called_once()
        call_args = mock_enqueue_in.call_args
        assert call_args.args[0] == timedelta(seconds=2)
        call_kwargs = call_args.kwargs
        assert call_kwargs["job_id"] == "platform-job-1"
        assert call_kwargs["at_front"] is False

    @patch("app.infrastructure.queue.rq_job_queue.rq.Queue.enqueue_in")
    async def test_high_priority_sets_at_front(
        self,
        mock_enqueue_in: MagicMock,
        queue: RQJobQueue,
    ) -> None:
        mock_job = MagicMock()
        mock_job.id = "rq-job-456"
        mock_enqueue_in.return_value = mock_job

        await queue.enqueue(
            job_id="platform-job-2",
            job_type="backup",
            payload={},
            priority="high",
        )

        call_kwargs = mock_enqueue_in.call_args.kwargs
        assert call_kwargs["at_front"] is True


class TestGetStatus:
    @patch("app.infrastructure.queue.rq_job_queue.RQJob.fetch")
    async def test_maps_rq_status_to_domain(
        self,
        mock_fetch: MagicMock,
        queue: RQJobQueue,
    ) -> None:
        mock_job = MagicMock()
        mock_job.get_status.return_value = "started"
        mock_fetch.return_value = mock_job

        status = await queue.get_status("rq-job-1")
        assert status == JobStatus.RUNNING.value

    @patch("app.infrastructure.queue.rq_job_queue.RQJob.fetch")
    async def test_returns_none_when_job_missing(
        self,
        mock_fetch: MagicMock,
        queue: RQJobQueue,
    ) -> None:
        mock_fetch.side_effect = NoSuchJobError("rq-job-missing")

        status = await queue.get_status("rq-job-missing")
        assert status is None

    @patch("app.infrastructure.queue.rq_job_queue.RQJob.fetch")
    async def test_returns_raw_status_when_unmapped(
        self,
        mock_fetch: MagicMock,
        queue: RQJobQueue,
    ) -> None:
        mock_job = MagicMock()
        mock_job.get_status.return_value = "unknown-status"
        mock_fetch.return_value = mock_job

        status = await queue.get_status("rq-job-2")
        assert status == "unknown-status"


class TestCancelJob:
    @patch("app.infrastructure.queue.rq_job_queue.RQJob.fetch")
    async def test_cancels_existing_job(
        self,
        mock_fetch: MagicMock,
        queue: RQJobQueue,
    ) -> None:
        mock_job = MagicMock()
        mock_fetch.return_value = mock_job

        result = await queue.cancel_job("rq-job-3")

        assert result is True
        mock_job.cancel.assert_called_once()

    @patch("app.infrastructure.queue.rq_job_queue.RQJob.fetch")
    async def test_returns_false_when_job_missing(
        self,
        mock_fetch: MagicMock,
        queue: RQJobQueue,
    ) -> None:
        mock_fetch.side_effect = NoSuchJobError("rq-job-missing")

        result = await queue.cancel_job("rq-job-missing")
        assert result is False

    @patch("app.infrastructure.queue.rq_job_queue.RQJob.fetch")
    async def test_returns_false_on_exception(
        self,
        mock_fetch: MagicMock,
        queue: RQJobQueue,
    ) -> None:
        mock_fetch.side_effect = NoSuchJobError("rq-job-4")

        result = await queue.cancel_job("rq-job-4")
        assert result is False


class TestRetryJob:
    @patch("app.infrastructure.queue.rq_job_queue.RQJob.fetch")
    async def test_requeues_with_incremented_retry_count(
        self,
        mock_fetch: MagicMock,
        queue: RQJobQueue,
    ) -> None:
        mock_job = MagicMock()
        mock_job.meta = {"retry_count": 2}
        mock_job.get_meta.return_value = mock_job.meta
        mock_new_job = MagicMock()
        mock_new_job.id = "rq-job-retry"
        mock_job.requeue.return_value = mock_new_job
        mock_fetch.return_value = mock_job

        result = await queue.retry_job("rq-job-5")

        assert result == "rq-job-retry"
        mock_job.save_meta.assert_called_once()
        # save_meta stores the updated meta on the job instance.
        assert mock_job.meta["retry_count"] == 3
        mock_job.requeue.assert_called_once()

    @patch("app.infrastructure.queue.rq_job_queue.RQJob.fetch")
    async def test_returns_none_when_job_missing(
        self,
        mock_fetch: MagicMock,
        queue: RQJobQueue,
    ) -> None:
        mock_fetch.side_effect = NoSuchJobError("rq-job-missing")

        result = await queue.retry_job("rq-job-missing")
        assert result is None

    @patch("app.infrastructure.queue.rq_job_queue.RQJob.fetch")
    async def test_returns_none_on_exception(
        self,
        mock_fetch: MagicMock,
        queue: RQJobQueue,
    ) -> None:
        mock_fetch.side_effect = NoSuchJobError("rq-job-6")

        result = await queue.retry_job("rq-job-6")
        assert result is None
