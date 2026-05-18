"""Job ORM model for backup job tracking and state persistence."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.database import Base


class JobORM(Base):
    """Represents a single backup job with its lifecycle state."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        comment="UUID v4 as string (SQLite-compatible)",
    )
    requester_telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    topic_id: Mapped[int | None] = mapped_column(BigInteger)
    status_message_id: Mapped[int | None] = mapped_column(BigInteger)
    backup_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="FULL or CUSTOM",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="PENDING, QUEUED, RUNNING, SUCCESS, FAILED, PARTIAL_SUCCESS, CANCELLED",
    )
    cluster_uri_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 hash of the cluster URI; never stores the URI in plain text",
    )
    target_databases: Mapped[list[str] | None] = mapped_column(
        JSON,
        comment="JSON array of database names selected for the backup",
    )
    target_collections: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON,
        comment="JSON array of {database, collection} objects",
    )
    output_path: Mapped[str | None] = mapped_column(Text)
    error_log: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    cancelled_by: Mapped[int | None] = mapped_column(BigInteger)
    queue_job_id: Mapped[str | None] = mapped_column(
        String(36),
        comment="External queue identifier (e.g. RQ job id)",
    )
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    total_collections: Mapped[int | None]
    completed_collections: Mapped[int] = mapped_column(default=0, nullable=False)
    failed_collections: Mapped[int] = mapped_column(default=0, nullable=False)
    bytes_processed: Mapped[int] = mapped_column(default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
