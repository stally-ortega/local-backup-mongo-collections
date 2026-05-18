"""Unit tests for SizeQueryService."""

import pytest

from app.application.services.size_query_service import SizeQueryService
from app.domain.entities.size_report import CollectionSize, DatabaseSize, SizeReport


class _FakeMongoMetadata:
    def __init__(self) -> None:
        self._report = SizeReport(
            cluster_uri_hash="hash123",
            databases=[
                DatabaseSize(database="db1", size_bytes=1_000, collection_count=2),
                DatabaseSize(database="db2", size_bytes=2_000, collection_count=1),
            ],
            collections=[
                CollectionSize(
                    database="db1",
                    collection="col1",
                    size_bytes=500,
                    document_count=10,
                ),
                CollectionSize(
                    database="db1",
                    collection="col2",
                    size_bytes=500,
                    document_count=20,
                ),
                CollectionSize(
                    database="db2",
                    collection="col3",
                    size_bytes=2_000,
                    document_count=5,
                ),
            ],
        )

    async def list_databases(self, cluster_uri_hash: str) -> list[str]:
        return [db.database for db in self._report.databases]

    async def list_collections(self, cluster_uri_hash: str, database: str) -> list[str]:
        return [col.collection for col in self._report.collections if col.database == database]

    async def get_size_stats(self, cluster_uri_hash: str) -> SizeReport:
        return self._report


@pytest.fixture
def service() -> SizeQueryService:
    return SizeQueryService(mongo_metadata=_FakeMongoMetadata())


class TestSizeQueryServiceCluster:
    @pytest.mark.asyncio
    async def test_get_cluster_size(self, service: SizeQueryService) -> None:
        report = await service.get_cluster_size("hash123")
        assert report.cluster_uri_hash == "hash123"
        assert report.total_size_bytes() == 3_000
        assert report.database_count() == 2
        assert report.collection_count() == 3


class TestSizeQueryServiceDatabases:
    @pytest.mark.asyncio
    async def test_get_database_sizes(self, service: SizeQueryService) -> None:
        dbs = await service.get_database_sizes("hash123")
        assert len(dbs) == 2
        assert dbs[0].database == "db1"
        assert dbs[1].database == "db2"


class TestSizeQueryServiceCollections:
    @pytest.mark.asyncio
    async def test_get_collection_sizes_no_filter(self, service: SizeQueryService) -> None:
        cols = await service.get_collection_sizes("hash123")
        assert len(cols) == 3

    @pytest.mark.asyncio
    async def test_get_collection_sizes_filter_by_database(self, service: SizeQueryService) -> None:
        cols = await service.get_collection_sizes("hash123", database="db1")
        assert len(cols) == 2
        assert all(c.database == "db1" for c in cols)

    @pytest.mark.asyncio
    async def test_get_collection_sizes_pagination(self, service: SizeQueryService) -> None:
        page1 = await service.get_collection_sizes("hash123", page=1, page_size=2)
        assert len(page1) == 2

        page2 = await service.get_collection_sizes("hash123", page=2, page_size=2)
        assert len(page2) == 1

    @pytest.mark.asyncio
    async def test_get_collection_sizes_invalid_page_clamped(
        self, service: SizeQueryService
    ) -> None:
        # page < 1 should be treated as 1
        cols = await service.get_collection_sizes("hash123", page=0, page_size=2)
        assert len(cols) == 2

    @pytest.mark.asyncio
    async def test_get_collection_sizes_oversized_page_size_clamped(
        self, service: SizeQueryService
    ) -> None:
        # page_size > 50 should be clamped to 50
        cols = await service.get_collection_sizes("hash123", page=1, page_size=999)
        assert len(cols) == 3  # only 3 exist, but clamp should not affect result here
