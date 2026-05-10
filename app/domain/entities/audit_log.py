"""Audit log domain entity."""

from datetime import datetime

from pydantic import BaseModel, Field


class AuditLog(BaseModel):
    """Represents a single auditable action performed by a Telegram user."""

    model_config = {"frozen": True}

    id: int | None = None
    telegram_id: int = Field(..., gt=0)
    action: str = Field(..., min_length=1)
    topic: str = Field(..., min_length=1)
    command: str | None = None
    result: str = Field(..., min_length=1)
    duration_ms: int | None = Field(default=None, ge=0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
