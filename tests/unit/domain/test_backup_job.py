"""Tests for the :class:`~app.domain.entities.backup_job.BackupJob` entity."""

import pytest

from app.domain.entities.backup_job import BackupJob
from app.domain.entities.user import User
from app.domain.exceptions.domain_errors import InvalidStateTransitionError
from app.domain.value_objects.dtos import CollectionTarget, JobProgress
from app.domain.value_objects.enums import BackupType, CollectionBackupStatus, JobStatus, UserRole


@pytest.fixture
def pending_job() -> BackupJob:
    return BackupJob.create_full(
        job_id="job-001",
        requester_telegram_id=123,
        cluster_uri_hash="a" * 64,
    )


class TestFactoryMethods:
    def test_create_full(self) -> None:
        job = BackupJob.create_full("id", 1, "hash")
        assert job.backup_type == BackupType.FULL
        assert job.status == JobStatus.PENDING
        assert job.target_collections == []

    def test_create_custom(self) -> None:
        targets = [CollectionTarget(database="db", collection="col")]
        job = BackupJob.create_custom("id", 1, "hash", targets)
        assert job.backup_type == BackupType.CUSTOM
        assert job.target_collections == targets


class TestValidTransitions:
    def test_pending_to_queued(self, pending_job: BackupJob) -> None:
        pending_job.mark_queued()
        assert pending_job.status == JobStatus.QUEUED

    def test_queued_to_running(self, pending_job: BackupJob) -> None:
        pending_job.mark_queued()
        pending_job.mark_running()
        assert pending_job.status == JobStatus.RUNNING
        assert pending_job.started_at is not None

    def test_running_to_success(self, pending_job: BackupJob) -> None:
        pending_job.mark_queued()
        pending_job.mark_running()
        pending_job.mark_success()
        assert pending_job.status == JobStatus.SUCCESS
        assert pending_job.completed_at is not None

    def test_running_to_failed(self, pending_job: BackupJob) -> None:
        pending_job.mark_queued()
        pending_job.mark_running()
        pending_job.mark_failed("disk full")
        assert pending_job.status == JobStatus.FAILED
        assert pending_job.error_log == "disk full"

    def test_running_to_partial(self, pending_job: BackupJob) -> None:
        pending_job.mark_queued()
        pending_job.mark_running()
        pending_job._transition(JobStatus.PARTIAL_SUCCESS)
        assert pending_job.status == JobStatus.PARTIAL_SUCCESS

    def test_pending_to_cancelled(self, pending_job: BackupJob) -> None:
        pending_job.mark_cancelled(999)
        assert pending_job.status == JobStatus.CANCELLED
        assert pending_job.cancelled_by == 999


class TestInvalidTransitions:
    def test_success_to_failed_raises(self, pending_job: BackupJob) -> None:
        pending_job.mark_queued()
        pending_job.mark_running()
        pending_job.mark_success()
        with pytest.raises(InvalidStateTransitionError):
            pending_job.mark_failed()

    def test_failed_to_success_raises(self, pending_job: BackupJob) -> None:
        pending_job.mark_queued()
        pending_job.mark_running()
        pending_job.mark_failed()
        with pytest.raises(InvalidStateTransitionError):
            pending_job.mark_success()

    def test_success_to_cancelled_raises(self, pending_job: BackupJob) -> None:
        pending_job.mark_queued()
        pending_job.mark_running()
        pending_job.mark_success()
        with pytest.raises(InvalidStateTransitionError):
            pending_job.mark_cancelled(1)

    def test_pending_directly_to_success_raises(self, pending_job: BackupJob) -> None:
        with pytest.raises(InvalidStateTransitionError):
            pending_job.mark_success()

    def test_pending_directly_to_failed_raises(self, pending_job: BackupJob) -> None:
        with pytest.raises(InvalidStateTransitionError):
            pending_job.mark_failed()


class TestProgress:
    def test_update_progress(self, pending_job: BackupJob) -> None:
        progress = JobProgress(total_collections=5, completed_collections=2)
        pending_job.update_progress(progress)
        assert pending_job.progress == progress


class TestCollectionResult:
    def test_add_collection_result(self, pending_job: BackupJob) -> None:
        result = CollectionTarget(
            database="db",
            collection="col",
            status=CollectionBackupStatus.SUCCESS,
        )
        pending_job.add_collection_result(result)
        assert len(pending_job.target_collections) == 1
        assert pending_job.target_collections[0].status == CollectionBackupStatus.SUCCESS


class TestCanBeCancelledBy:
    def test_admin_can_cancel(self, pending_job: BackupJob) -> None:
        admin = User(telegram_id=999, role=UserRole.ADMIN)
        assert pending_job.can_be_cancelled_by(admin) is True

    def test_requester_can_cancel(self, pending_job: BackupJob) -> None:
        requester = User(telegram_id=123, role=UserRole.OPERATOR)
        assert pending_job.can_be_cancelled_by(requester) is True

    def test_other_operator_cannot_cancel(self, pending_job: BackupJob) -> None:
        other = User(telegram_id=456, role=UserRole.OPERATOR)
        assert pending_job.can_be_cancelled_by(other) is False

    def test_inactive_user_cannot_cancel(self, pending_job: BackupJob) -> None:
        inactive = User(telegram_id=123, role=UserRole.OPERATOR)
        inactive.is_active = False
        assert pending_job.can_be_cancelled_by(inactive) is False

    def test_cannot_cancel_successful_job(self, pending_job: BackupJob) -> None:
        pending_job.mark_queued()
        pending_job.mark_running()
        pending_job.mark_success()
        admin = User(telegram_id=1, role=UserRole.ADMIN)
        assert pending_job.can_be_cancelled_by(admin) is False

    def test_cannot_cancel_failed_job(self, pending_job: BackupJob) -> None:
        pending_job.mark_queued()
        pending_job.mark_running()
        pending_job.mark_failed()
        admin = User(telegram_id=1, role=UserRole.ADMIN)
        assert pending_job.can_be_cancelled_by(admin) is False
