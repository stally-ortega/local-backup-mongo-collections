"""Size-report aggregate for MongoDB storage analytics."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class CollectionSize(BaseModel):
    """Size metrics for a single collection."""

    model_config = {"frozen": True}

    database: str = Field(..., min_length=1)
    collection: str = Field(..., min_length=1)
    size_bytes: int = Field(..., ge=0)
    document_count: int = Field(..., ge=0)


class DatabaseSize(BaseModel):
    """Aggregated size for an entire logical database."""

    model_config = {"frozen": True}

    database: str = Field(..., min_length=1)
    size_bytes: int = Field(..., ge=0)
    collection_count: int = Field(..., ge=0)


class SizeReport(BaseModel):
    """Aggregate root containing a complete cluster size snapshot."""

    model_config = {"frozen": True}

    cluster_uri_hash: str = Field(..., min_length=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    databases: list[DatabaseSize] = Field(default_factory=list)
    collections: list[CollectionSize] = Field(default_factory=list)

    def total_size_bytes(self) -> int:
        """Return the sum of all database sizes."""
        return sum(db.size_bytes for db in self.databases)

    def total_document_count(self) -> int:
        """Return the sum of all collection document counts."""
        return sum(col.document_count for col in self.collections)

    def collection_count(self) -> int:
        """Return the total number of collections reported."""
        return len(self.collections)

    def database_count(self) -> int:
        """Return the total number of databases reported."""
        return len(self.databases)
