"""Tests for the domain exception hierarchy."""

from app.domain.exceptions.domain_errors import (
    BackupEngineError,
    ConfigurationError,
    DomainError,
    DomainPermissionError,
    InvalidStateTransitionError,
    JobError,
    MongoOpsError,
    NotificationError,
    PermissionDeniedError,
    RepositoryError,
)


class TestMongoOpsError:
    def test_attributes(self) -> None:
        exc = MongoOpsError(code="TEST", message="msg", details={"k": "v"})
        assert exc.code == "TEST"
        assert exc.message == "msg"
        assert exc.details == {"k": "v"}

    def test_default_details(self) -> None:
        exc = MongoOpsError(code="X", message="m")
        assert exc.details == {}

    def test_str(self) -> None:
        exc = MongoOpsError(code="X", message="m")
        assert str(exc) == "m"


class TestDomainError:
    def test_is_mongo_ops_error(self) -> None:
        exc = DomainError("domain issue")
        assert isinstance(exc, MongoOpsError)
        assert exc.code == "DOMAIN_ERROR"


class TestConfigurationError:
    def test_code(self) -> None:
        exc = ConfigurationError("bad config")
        assert exc.code == "CONFIG_INVALID"
        assert isinstance(exc, MongoOpsError)


class TestPermissionError:
    def test_code(self) -> None:
        exc = DomainPermissionError("nope")
        assert exc.code == "PERMISSION_DENIED"
        assert isinstance(exc, MongoOpsError)


class TestBackupEngineError:
    def test_code(self) -> None:
        exc = BackupEngineError("dump failed")
        assert exc.code == "BACKUP_ENGINE_ERROR"


class TestJobError:
    def test_code(self) -> None:
        exc = JobError("job broke")
        assert exc.code == "JOB_ERROR"


class TestNotificationError:
    def test_code(self) -> None:
        exc = NotificationError("telegram down")
        assert exc.code == "NOTIFICATION_ERROR"


class TestRepositoryError:
    def test_code(self) -> None:
        exc = RepositoryError("db timeout")
        assert exc.code == "REPOSITORY_ERROR"


class TestInvalidStateTransitionError:
    def test_is_job_error(self) -> None:
        exc = InvalidStateTransitionError("bad move")
        assert isinstance(exc, JobError)
        assert exc.code == "INVALID_STATE_TRANSITION"


class TestPermissionDeniedError:
    def test_is_permission_error(self) -> None:
        exc = PermissionDeniedError("no access")
        assert isinstance(exc, DomainPermissionError)
