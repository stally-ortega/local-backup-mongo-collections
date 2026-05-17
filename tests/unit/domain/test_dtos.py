"""Tests for domain Data Transfer Objects."""

import pytest
from pydantic import ValidationError

from app.domain.value_objects.dtos import CollectionTarget, JobProgress
from app.domain.value_objects.enums import CollectionBackupStatus


class TestCollectionTarget:
    def test_create_minimal(self) -> None:
        target = CollectionTarget(database="mydb", collection="users")
        assert target.database == "mydb"
        assert target.collection == "users"
        assert target.status == CollectionBackupStatus.PENDING
        assert target.size_bytes is None
        assert target.error_message is None

    def test_create_full(self) -> None:
        target = CollectionTarget(
            database="mydb",
            collection="users",
            status=CollectionBackupStatus.RUNNING,
            size_bytes=1024,
            error_message="none",
        )
        assert target.status == CollectionBackupStatus.RUNNING
        assert target.size_bytes == 1024

    def test_empty_database_raises(self) -> None:
        with pytest.raises(ValidationError):
            CollectionTarget(database="", collection="users")

    def test_empty_collection_raises(self) -> None:
        with pytest.raises(ValidationError):
            CollectionTarget(database="mydb", collection="")

    def test_negative_size_bytes_raises(self) -> None:
        with pytest.raises(ValidationError):
            CollectionTarget(database="mydb", collection="users", size_bytes=-1)

    def test_is_immutable(self) -> None:
        target = CollectionTarget(database="mydb", collection="users")
        with pytest.raises(ValidationError):
            target.status = CollectionBackupStatus.SUCCESS  # type: ignore[misc]


class TestJobProgress:
    def test_defaults(self) -> None:
        progress = JobProgress(total_collections=10)
        assert progress.total_collections == 10
        assert progress.completed_collections == 0
        assert progress.failed_collections == 0
        assert progress.retry_count == 0
        assert progress.percent_complete == 0.0
        assert progress.bytes_processed == 0

    def test_percent_complete_rounding(self) -> None:
        progress = JobProgress(total_collections=3, percent_complete=33.33333)
        assert progress.percent_complete == 33.33

    def test_percent_complete_bounds(self) -> None:
        with pytest.raises(ValidationError):
            JobProgress(total_collections=1, percent_complete=-0.1)

        with pytest.raises(ValidationError):
            JobProgress(total_collections=1, percent_complete=100.1)

    def test_retry_count_bounds(self) -> None:
        with pytest.raises(ValidationError):
            JobProgress(total_collections=1, retry_count=-1)

    def test_bytes_processed_bounds(self) -> None:
        with pytest.raises(ValidationError):
            JobProgress(total_collections=1, bytes_processed=-1)

    def test_is_immutable(self) -> None:
        progress = JobProgress(total_collections=5)
        with pytest.raises(ValidationError):
            progress.retry_count = 1  # type: ignore[misc]
