"""Application service for querying MongoDB storage sizes.

Provides paginated and scoped access to cluster, database, and collection
size metrics without exposing raw ``IMongoMetadata`` details to upper layers.
"""

from app.application.ports.ports import IMongoMetadata
from app.domain.entities.size_report import CollectionSize, DatabaseSize, SizeReport


class SizeQueryService:
    """Facade over :class:`~app.application.ports.ports.IMongoMetadata` with
    pagination and filtering helpers."""

    def __init__(self, mongo_metadata: IMongoMetadata) -> None:
        self._mongo_metadata = mongo_metadata

    async def get_cluster_size(self, cluster_uri_hash: str) -> SizeReport:
        """Return a complete size snapshot for the identified cluster."""
        return await self._mongo_metadata.get_size_stats(cluster_uri_hash)

    async def get_database_sizes(self, cluster_uri_hash: str) -> list[DatabaseSize]:
        """Return the size breakdown for every database on the cluster."""
        report = await self._mongo_metadata.get_size_stats(cluster_uri_hash)
        return report.databases

    async def get_collection_sizes(
        self,
        cluster_uri_hash: str,
        database: str | None = None,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> list[CollectionSize]:
        """Return collection-level sizes, optionally filtered and paginated.

        Parameters
        ----------
        cluster_uri_hash:
            SHA-256 hash identifying the target cluster.
        database:
            When supplied, only collections belonging to this database are
            included in the result.
        page:
            1-based page number (must be >= 1).
        page_size:
            Items per page (clamped between 1 and 50).
        """
        report = await self._mongo_metadata.get_size_stats(cluster_uri_hash)
        collections = report.collections

        if database:
            collections = [c for c in collections if c.database == database]

        start = (page - 1) * page_size
        return collections[start : start + page_size]
