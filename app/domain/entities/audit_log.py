"""Audit log domain entity."""

import ipaddress
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


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
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] | None = None

    @field_validator("ip_address", mode="before")
    @classmethod
    def _validate_ip_address(cls, value: Any) -> Any:
        """Reject values that are not valid IPv4 or IPv6 strings."""
        if value is None:
            return value
        if not isinstance(value, str):
            raise ValueError("ip_address must be a string")
        try:
            ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError(f"invalid IP address: {value}") from exc
        return value
