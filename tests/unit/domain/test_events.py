"""Tests for domain events."""

from datetime import datetime
from typing import cast

from app.domain.events.domain_events import (
    BackupCompletedPayload,
    BackupFailedPayload,
    BackupRequestedPayload,
    BackupStartedPayload,
    CollectionBackupCompletedPayload,
    DomainEvent,
    JobCancelledPayload,
    SizeQueriedPayload,
)
from app.domain.value_objects.dtos import CollectionTarget
from app.domain.value_objects.enums import BackupType, CollectionBackupStatus, JobStatus


class TestBackupRequested:
    def test_event(self) -> None:
        payload = BackupRequestedPayload(
            job_id="j1",
            requester_telegram_id=123,
            backup_type=BackupType.FULL,
            cluster_uri_hash="h" * 64,
        )
        event = DomainEvent.backup_requested(payload, correlation_id="c1")
        assert event.event_type == "BACKUP_REQUESTED"
        assert event.correlation_id == "c1"
        assert event.payload == payload
        assert isinstance(event.occurred_on, datetime)


class TestBackupStarted:
    def test_event(self) -> None:
        payload = BackupStartedPayload(job_id="j1")
        event = DomainEvent.backup_started(payload)
        assert event.event_type == "BACKUP_STARTED"
        started = cast(BackupStartedPayload, event.payload)
        assert started.job_id == "j1"
        assert event.correlation_id is None


class TestCollectionBackupCompleted:
    def test_event(self) -> None:
        target = CollectionTarget(
            database="db",
            collection="col",
            status=CollectionBackupStatus.SUCCESS,
        )
        payload = CollectionBackupCompletedPayload(job_id="j1", result=target)
        event = DomainEvent.collection_backup_completed(payload)
        assert event.event_type == "COLLECTION_BACKUP_COMPLETED"
        coll = cast(CollectionBackupCompletedPayload, event.payload)
        assert coll.result.status == CollectionBackupStatus.SUCCESS


class TestBackupCompleted:
    def test_event(self) -> None:
        payload = BackupCompletedPayload(job_id="j1", status=JobStatus.SUCCESS)
        event = DomainEvent.backup_completed(payload)
        assert event.event_type == "BACKUP_COMPLETED"
        completed = cast(BackupCompletedPayload, event.payload)
        assert completed.status == JobStatus.SUCCESS


class TestBackupFailed:
    def test_event(self) -> None:
        payload = BackupFailedPayload(job_id="j1", error_log="disk full")
        event = DomainEvent.backup_failed(payload)
        assert event.event_type == "BACKUP_FAILED"
        failed = cast(BackupFailedPayload, event.payload)
        assert failed.error_log == "disk full"


class TestJobCancelled:
    def test_event(self) -> None:
        payload = JobCancelledPayload(job_id="j1", cancelled_by=999)
        event = DomainEvent.job_cancelled(payload)
        assert event.event_type == "JOB_CANCELLED"
        cancelled = cast(JobCancelledPayload, event.payload)
        assert cancelled.cancelled_by == 999


class TestSizeQueried:
    def test_event(self) -> None:
        payload = SizeQueriedPayload(
            cluster_uri_hash="h" * 64,
            requester_telegram_id=123,
        )
        event = DomainEvent.size_queried(payload, correlation_id="c2")
        assert event.event_type == "SIZE_QUERIED"
        assert event.correlation_id == "c2"
