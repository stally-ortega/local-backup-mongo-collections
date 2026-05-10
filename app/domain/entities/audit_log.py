"""Audit log domain entity."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditLog(BaseModel):
    """Represents a single auditable action performed by a Telegram user."""

    model_config = {"frozen": True}

    id: int | None = None
    telegram_id: int = Field(..., gt=0)
    action: str = Field(..., min_length=1)
    topic: str = Field(..., min_length=1)
    command: str | None = None
    job_id: str | None = None
    cluster_uri_hash: str | None = None
    databases: list[str] | None = None
    collections: list[str] | None = None
    result: str = Field(..., min_length=1)
    duration_ms: int | None = Field(default=None, ge=0)
    ip_address: str | None = None
    user_agent: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: dict[str, Any] | None = None
