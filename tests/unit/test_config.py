"""Unit tests for the application configuration layer."""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import AppConfig


class TestAppConfigValidation:
    """Validate AppConfig field parsing and custom validators."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Remove MONGO_OPS_ variables so each test starts from a blank slate."""
        for key in list(os.environ):
            if key.startswith("MONGO_OPS_"):
                monkeypatch.delenv(key, raising=False)

    def _set_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONGO_OPS_TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("MONGO_OPS_TELEGRAM_CHAT_ID", "-100123456789")
        monkeypatch.setenv("MONGO_OPS_MONGODB_URI", "mongodb+srv://u:p@cluster.mongodb.net/")

    @staticmethod
    def _load() -> AppConfig:
        """Factory helper: mypy cannot see env-var resolution inside BaseSettings.

        Pydantic ``BaseSettings`` reads required fields from ``os.environ`` at
        runtime. Static analysis (mypy) only sees the constructor signature and
        therefore flags ``AppConfig()`` as missing arguments. We centralise the
        ``# type: ignore`` here so that every test method remains clean.
        """
        return AppConfig()  # type: ignore[call-arg]

    def test_valid_minimal_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A minimal valid configuration loads successfully."""
        self._set_required(monkeypatch)
        cfg = self._load()

        assert cfg.telegram_bot_token == "test-token"
        assert cfg.telegram_chat_id == "-100123456789"
        assert cfg.mongodb_uri == "mongodb+srv://u:p@cluster.mongodb.net/"

    def test_defaults_when_optional_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Optional fields fall back to documented defaults."""
        self._set_required(monkeypatch)
        cfg = self._load()

        assert cfg.redis_url == "redis://localhost:6379/0"
        assert cfg.database_url == "sqlite+aiosqlite:///./mongo_ops.db"
        assert cfg.retention_full_weeks == 4
        assert cfg.retention_custom_weeks == 2
        assert cfg.retention_max_gb == 50
        assert cfg.log_level == "INFO"
        assert cfg.max_concurrent_backups == 3
        assert cfg.topic_backup_requests == 1
        assert cfg.topic_size_ask == 2
        assert cfg.topic_execution_errors == 3
        assert cfg.topic_admin == 4

    def test_backup_path_created_when_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """backup_base_path is created automatically if it does not exist."""
        self._set_required(monkeypatch)
        missing_dir = tmp_path / "new_backups"
        monkeypatch.setenv("MONGO_OPS_BACKUP_BASE_PATH", str(missing_dir))

        cfg = self._load()
        assert cfg.backup_base_path == missing_dir.resolve()
        assert missing_dir.exists()
        assert missing_dir.is_dir()

    def test_backup_path_rejects_existing_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """backup_base_path must not point to an existing file."""
        self._set_required(monkeypatch)
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("data")
        monkeypatch.setenv("MONGO_OPS_BACKUP_BASE_PATH", str(file_path))

        with pytest.raises(ValidationError) as exc_info:
            self._load()
        assert "backup_base_path must be a directory" in str(exc_info.value)

    def test_mongodb_uri_rejects_invalid_scheme(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only 'mongodb' and 'mongodb+srv' schemes are accepted."""
        self._set_required(monkeypatch)
        monkeypatch.setenv("MONGO_OPS_MONGODB_URI", "http://invalid.com")

        with pytest.raises(ValidationError) as exc_info:
            self._load()
        assert "mongodb+srv" in str(exc_info.value)

    def test_mongodb_uri_rejects_missing_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A URI without a host is rejected."""
        self._set_required(monkeypatch)
        monkeypatch.setenv("MONGO_OPS_MONGODB_URI", "mongodb://")

        with pytest.raises(ValidationError) as exc_info:
            self._load()
        assert "valid scheme and host" in str(exc_info.value)

    def test_log_level_rejects_invalid_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only standard logging levels are accepted."""
        self._set_required(monkeypatch)
        monkeypatch.setenv("MONGO_OPS_LOG_LEVEL", "VERBOSE")

        with pytest.raises(ValidationError) as exc_info:
            self._load()
        assert "log_level must be one of" in str(exc_info.value)

    def test_log_level_normalizes_case(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Log levels are upper-cased automatically."""
        self._set_required(monkeypatch)
        monkeypatch.setenv("MONGO_OPS_LOG_LEVEL", "debug")

        cfg = self._load()
        assert cfg.log_level == "DEBUG"

    def test_max_concurrent_backups_rejects_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Zero concurrent backups is not allowed."""
        self._set_required(monkeypatch)
        monkeypatch.setenv("MONGO_OPS_MAX_CONCURRENT_BACKUPS", "0")

        with pytest.raises(ValidationError) as exc_info:
            self._load()
        assert "max_concurrent_backups" in str(exc_info.value)

    def test_max_concurrent_backups_rejects_too_high(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """More than 20 concurrent backups is not allowed."""
        self._set_required(monkeypatch)
        monkeypatch.setenv("MONGO_OPS_MAX_CONCURRENT_BACKUPS", "25")

        with pytest.raises(ValidationError) as exc_info:
            self._load()
        assert "max_concurrent_backups" in str(exc_info.value)

    def test_telegram_chat_id_rejects_non_numeric(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Telegram chat IDs must be numeric strings."""
        self._set_required(monkeypatch)
        monkeypatch.setenv("MONGO_OPS_TELEGRAM_CHAT_ID", "not_a_number")

        with pytest.raises(ValidationError) as exc_info:
            self._load()
        assert "telegram_chat_id" in str(exc_info.value)

    def test_telegram_bot_token_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing required field raises ValidationError."""
        monkeypatch.setenv("MONGO_OPS_TELEGRAM_CHAT_ID", "-100123456789")
        monkeypatch.setenv("MONGO_OPS_MONGODB_URI", "mongodb://localhost:27017")

        with pytest.raises(ValidationError) as exc_info:
            self._load()
        assert "telegram_bot_token" in str(exc_info.value)

    def test_env_prefix_isolation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Variables without the MONGO_OPS_ prefix are ignored."""
        self._set_required(monkeypatch)
        monkeypatch.setenv("UNRELATED_VAR", "should_be_ignored")

        cfg = self._load()
        assert cfg.telegram_bot_token == "test-token"
