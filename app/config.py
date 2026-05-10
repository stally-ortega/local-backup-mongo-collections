"""Application configuration loaded from environment variables and .env files."""

from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Centralized, typed, and validated application settings.

    Loads from environment variables prefixed with ``MONGO_OPS_``
    and from a ``.env`` file when present. All fields are strictly
    typed and validated at import time.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MONGO_OPS_",
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str = Field(
        ...,
        min_length=1,
        description="Bot token from @BotFather",
    )
    telegram_chat_id: str = Field(
        ...,
        pattern=r"^-?\d+$",
        description="Telegram chat or group ID",
    )

    # Telegram topics
    topic_backup_requests: int = Field(
        default=1,
        ge=1,
        description="Topic ID for backup request commands",
    )
    topic_size_ask: int = Field(
        default=2,
        ge=1,
        description="Topic ID for size queries",
    )
    topic_execution_errors: int = Field(
        default=3,
        ge=1,
        description="Topic ID for execution error reports",
    )
    topic_admin: int = Field(
        default=4,
        ge=1,
        description="Topic ID for admin operations",
    )

    # MongoDB
    mongodb_uri: str = Field(
        ...,
        min_length=1,
        description="MongoDB connection URI",
    )

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        min_length=1,
        description="Redis connection URL",
    )

    # Local database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./mongo_ops.db",
        min_length=1,
        description="SQLAlchemy async database URL",
    )

    # Backup storage
    backup_base_path: Path = Field(
        default=Path("./backups"),
        description="Base directory for backup archives",
    )

    # Retention policy
    retention_full_weeks: int = Field(
        default=4,
        ge=1,
        le=52,
        description="Weeks to retain full backups",
    )
    retention_custom_weeks: int = Field(
        default=2,
        ge=1,
        le=52,
        description="Weeks to retain custom backups",
    )
    retention_max_gb: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Max total backup storage in GB",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Root logging level",
    )

    # Rate limiting
    rate_limit_max_requests: int = Field(
        default=10,
        ge=1,
        description="Maximum requests per user per rate-limit window",
    )
    rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        description="Rate-limit window duration in seconds",
    )

    # Concurrency
    max_concurrent_backups: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Maximum simultaneous backup jobs",
    )

    @field_validator("mongodb_uri", mode="after")
    @classmethod
    def _validate_mongodb_uri(cls, value: str) -> str:
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.hostname:
            raise ValueError("mongodb_uri must contain a valid scheme and host")
        if parsed.scheme not in ("mongodb", "mongodb+srv"):
            raise ValueError("mongodb_uri scheme must be 'mongodb' or 'mongodb+srv'")
        return value

    @field_validator("backup_base_path", mode="after")
    @classmethod
    def _validate_backup_base_path(cls, value: Path) -> Path:
        resolved = value.resolve()
        if resolved.exists() and not resolved.is_dir():
            raise ValueError("backup_base_path must be a directory, not a file")
        if not resolved.exists():
            try:
                resolved.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ValueError(f"backup_base_path '{resolved}' cannot be created: {exc}") from exc
        return resolved

    @field_validator("log_level", mode="after")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}, got '{value}'")
        return upper
