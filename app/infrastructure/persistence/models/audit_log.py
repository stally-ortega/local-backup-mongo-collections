"""Audit log ORM model for operational traceability and compliance."""

from datetime import datetime

from sqlalchemy import BigInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.database import Base


class AuditLogORM(Base):
    """Immutable record of every significant action performed via the platform."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Canonical action name, e.g. BACKUP_REQUESTED, SIZE_QUERIED",
    )
    topic: Mapped[str | None] = mapped_column(String(50))
    command: Mapped[str | None] = mapped_column(String(100))
    job_id: Mapped[str | None] = mapped_column(String(36))
    cluster_uri_hash: Mapped[str | None] = mapped_column(
        String(64),
        comment="SHA-256 hash of the cluster URI at the time of the action",
    )
    databases: Mapped[str | None] = mapped_column(
        Text,
        comment="JSON string of databases involved",
    )
    collections: Mapped[str | None] = mapped_column(
        Text,
        comment="JSON string of collections involved",
    )
    result: Mapped[str | None] = mapped_column(String(20))
    duration_ms: Mapped[int | None]
    timestamp: Mapped[datetime] = mapped_column(
        default=func.now(),
        nullable=False,
        index=True,
        comment="Indexed for time-range queries",
    )
    details: Mapped[str | None] = mapped_column(
        Text,
        comment="Flexible JSON blob for extended context",
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        comment="IPv4 or IPv6 address of the client",
    )
    user_agent: Mapped[str | None] = mapped_column(
        Text,
        comment="Client user-agent string",
    )
