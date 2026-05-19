"""Tests for domain value-object enumerations."""

import json

import pytest

from app.domain.value_objects.enums import (
    BackupType,
    CollectionBackupStatus,
    JobStatus,
    TopicType,
    UserRole,
)


class TestUserRole:
    def test_members(self) -> None:
        assert UserRole.ADMIN == "ADMIN"
        assert UserRole.DBA == "DBA"
        assert UserRole.OPERATOR == "OPERATOR"
        assert UserRole.READONLY == "READONLY"

    def test_string_comparability(self) -> None:
        assert UserRole.ADMIN == "ADMIN"

    def test_json_serializable(self) -> None:
        assert json.dumps(UserRole.ADMIN) == '"ADMIN"'

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            UserRole("INVALID")

    def test_is_str_instance(self) -> None:
        assert isinstance(UserRole.ADMIN, str)


class TestBackupType:
    def test_members(self) -> None:
        assert BackupType.FULL == "FULL"
        assert BackupType.CUSTOM == "CUSTOM"

    def test_json_serializable(self) -> None:
        assert json.dumps(BackupType.FULL) == '"FULL"'


class TestJobStatus:
    def test_members(self) -> None:
        assert JobStatus.PENDING == "PENDING"
        assert JobStatus.QUEUED == "QUEUED"
        assert JobStatus.RUNNING == "RUNNING"
        assert JobStatus.SUCCESS == "SUCCESS"
        assert JobStatus.FAILED == "FAILED"
        assert JobStatus.PARTIAL_SUCCESS == "PARTIAL_SUCCESS"
        assert JobStatus.CANCELLED == "CANCELLED"

    def test_terminal_states(self) -> None:
        terminal = {JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.CANCELLED}
        assert JobStatus.SUCCESS in terminal
        assert JobStatus.RUNNING not in terminal

    def test_is_str_instance(self) -> None:
        assert isinstance(JobStatus.SUCCESS, str)


class TestCollectionBackupStatus:
    def test_members(self) -> None:
        assert CollectionBackupStatus.PENDING == "PENDING"
        assert CollectionBackupStatus.RUNNING == "RUNNING"
        assert CollectionBackupStatus.SUCCESS == "SUCCESS"
        assert CollectionBackupStatus.FAILED == "FAILED"
        assert CollectionBackupStatus.SKIPPED == "SKIPPED"

    def test_json_serializable(self) -> None:
        assert json.dumps(CollectionBackupStatus.SKIPPED) == '"SKIPPED"'


class TestTopicType:
    def test_members(self) -> None:
        assert TopicType.BACKUP_REQUESTS == "BACKUP_REQUESTS"
        assert TopicType.SIZE_ASK == "SIZE_ASK"
        assert TopicType.EXECUTION_ERRORS == "EXECUTION_ERRORS"
        assert TopicType.ADMIN == "ADMIN"

    def test_is_str_instance(self) -> None:
        assert isinstance(TopicType.ADMIN, str)
