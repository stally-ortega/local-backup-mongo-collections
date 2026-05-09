"""Domain Data Transfer Objects (DTOs) with embedded validation.

These lightweight, immutable objects carry structured data across
layers without exposing ORM internals.
"""

from pydantic import BaseModel, Field, field_validator

from app.domain.value_objects.enums import CollectionBackupStatus


class CollectionTarget(BaseModel):
    """A single MongoDB collection scheduled for backup within a job."""

    model_config = {"frozen": True}

    database: str = Field(..., min_length=1)
    collection: str = Field(..., min_length=1)
    status: CollectionBackupStatus = CollectionBackupStatus.PENDING
    size_bytes: int | None = Field(default=None, ge=0)
    error_message: str | None = None


class JobProgress(BaseModel):
    """Aggregated progress of a running backup job."""

    model_config = {"frozen": True}

    total_collections: int = Field(..., ge=0)
    completed_collections: int = Field(default=0, ge=0)
    failed_collections: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    percent_complete: float = Field(default=0.0, ge=0.0, le=100.0)
    bytes_processed: int = Field(default=0, ge=0)

    @field_validator("percent_complete", mode="after")
    @classmethod
    def _round_percent(cls, value: float) -> float:
        """Store percent with at most two decimal places."""
        return round(value, 2)
