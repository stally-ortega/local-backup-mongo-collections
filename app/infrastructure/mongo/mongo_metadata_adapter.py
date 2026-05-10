"""MongoDB metadata adapter implementing :class:`~app.application.ports.ports.IMongoMetadata`.

Uses Motor async commands to introspect databases, collections, and sizes.
Designed for resilience on large clusters: individual collection failures are
logged and skipped rather than aborting the entire report.
"""

import asyncio
import logging
from typing import Any

from app.application.ports.ports import IMongoMetadata
from app.domain.entities.size_report import CollectionSize, DatabaseSize, SizeReport
from app.infrastructure.mongo.mongo_connection import MongoConnection

logger = logging.getLogger(__name__)

# Databases managed by MongoDB itself; excluded from user-visible listings.
_SYSTEM_DATABASES: frozenset[str] = frozenset({"admin", "local", "config"})

# Default per-operation timeout when gathering stats on large clusters.
_DEFAULT_STAT_TIMEOUT_S: float = 15.0


class MongoMetadataAdapter(IMongoMetadata):
    """Async adapter for MongoDB metadata and size introspection.

    Parameters
    ----------
    connection:
        An open :class:`~app.infrastructure.mongo.mongo_connection.MongoConnection`.
    stat_timeout_seconds:
        Maximum wall-clock time allowed for each ``dbStats`` / ``collStats``
        command before asyncio cancels it.
    """

    def __init__(
        self,
        connection: MongoConnection,
        *,
        stat_timeout_seconds: float = _DEFAULT_STAT_TIMEOUT_S,
    ) -> None:
        self._connection = connection
        self._stat_timeout = stat_timeout_seconds

    # ------------------------------------------------------------------
    # IMongoMetadata implementation
    # ------------------------------------------------------------------

    async def list_databases(self, cluster_uri_hash: str) -> list[str]:
        """Return non-system database names sorted alphabetically."""
        client = self._connection.client
        names: list[str] = await client.list_database_names()
        return sorted(n for n in names if n not in _SYSTEM_DATABASES)

    async def list_collections(
        self,
        cluster_uri_hash: str,
        database: str,
    ) -> list[str]:
        """Return collection names inside *database*, sorted."""
        client = self._connection.client
        names: list[str] = await client[database].list_collection_names()
        return sorted(names)

    async def get_size_stats(self, cluster_uri_hash: str) -> SizeReport:
        """Build a complete :class:`SizeReport` for the cluster.

        The method iterates database-by-database and collection-by-collection.
        If an individual ``collStats`` command times out or raises, the error is
        logged and that collection is skipped so the rest of the report can
        still be produced.
        """
        client = self._connection.client
        databases: list[DatabaseSize] = []
        collections: list[CollectionSize] = []

        db_names = await self.list_databases(cluster_uri_hash)

        for db_name in db_names:
            try:
                db_stats, col_names = await asyncio.gather(
                    self._db_stats(client, db_name),
                    self._list_collections_safe(client, db_name),
                )
            except Exception as exc:
                logger.warning(
                    "Skipping database '%s' due to error: %s",
                    db_name,
                    exc,
                    extra={"cluster_uri_hash": cluster_uri_hash},
                )
                continue

            databases.append(db_stats)

            for col_name in col_names:
                try:
                    col_size = await self._collection_stats(client, db_name, col_name)
                    collections.append(col_size)
                except asyncio.TimeoutError:
                    logger.warning(
                        "collStats timed out for %s.%s; skipping",
                        db_name,
                        col_name,
                        extra={"cluster_uri_hash": cluster_uri_hash},
                    )
                except Exception as exc:
                    logger.warning(
                        "collStats failed for %s.%s: %s",
                        db_name,
                        col_name,
                        exc,
                        extra={"cluster_uri_hash": cluster_uri_hash},
                    )

        return SizeReport(
            cluster_uri_hash=cluster_uri_hash,
            databases=databases,
            collections=collections,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _db_stats(
        self,
        client: Any,
        database: str,
    ) -> DatabaseSize:
        """Execute ``dbStats`` and map the result to :class:`DatabaseSize`."""
        db = client[database]
        stats: dict[str, Any] = await asyncio.wait_for(
            db.command("dbStats"),
            timeout=self._stat_timeout,
        )
        return DatabaseSize(
            database=database,
            size_bytes=stats.get("dataSize", 0),
            collection_count=stats.get("collections", 0),
        )

    async def _list_collections_safe(
        self,
        client: Any,
        database: str,
    ) -> list[str]:
        """Return collection names with a defensive timeout."""
        names: list[str] = await asyncio.wait_for(
            client[database].list_collection_names(),
            timeout=self._stat_timeout,
        )
        return names

    async def _collection_stats(
        self,
        client: Any,
        database: str,
        collection: str,
    ) -> CollectionSize:
        """Execute ``collStats`` and map the result to :class:`CollectionSize`."""
        db = client[database]
        stats: dict[str, Any] = await asyncio.wait_for(
            db.command("collStats", collection),
            timeout=self._stat_timeout,
        )
        return CollectionSize(
            database=database,
            collection=collection,
            size_bytes=stats.get("size", 0),
            document_count=stats.get("count", 0),
        )
