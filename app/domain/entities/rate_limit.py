"""Rate-limit domain entity."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class RateLimit(BaseModel):
    """Tracks action counts inside a sliding time window per user."""

    model_config = {"frozen": True}

    id: int | None = None
    telegram_id: int = Field(..., gt=0)
    action: str = Field(..., min_length=1)
    window_start: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    count: int = Field(default=1, ge=0)
