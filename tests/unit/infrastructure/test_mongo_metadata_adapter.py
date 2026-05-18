"""Unit tests for MongoMetadataAdapter."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.entities.size_report import CollectionSize, DatabaseSize, SizeReport
from app.infrastructure.mongo.mongo_connection import MongoConnection
from app.infrastructure.mongo.mongo_metadata_adapter import MongoMetadataAdapter


@pytest.fixture
def connection() -> MongoConnection:
    return MongoConnection("mongodb://localhost:27017")


@pytest.fixture
def adapter(connection: MongoConnection) -> MongoMetadataAdapter:
    return MongoMetadataAdapter(connection, stat_timeout_seconds=5.0)


class TestListDatabases:
    async def test_filters_system_databases_and_sorts(
        self,
        connection: MongoConnection,
        adapter: MongoMetadataAdapter,
    ) -> None:
        mock_client = MagicMock()
        mock_client.list_database_names = AsyncMock(
            return_value=["config", "mydb", "admin", "local", "another"]
        )
        connection._client = mock_client

        result = await adapter.list_databases("hash123")

        assert result == ["another", "mydb"]

    async def test_empty_when_only_system_databases(
        self,
        connection: MongoConnection,
        adapter: MongoMetadataAdapter,
    ) -> None:
        mock_client = MagicMock()
        mock_client.list_database_names = AsyncMock(return_value=["admin", "local"])
        connection._client = mock_client

        result = await adapter.list_databases("hash123")
        assert result == []


class TestListCollections:
    async def test_returns_sorted_collection_names(
        self,
        connection: MongoConnection,
        adapter: MongoMetadataAdapter,
    ) -> None:
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_db.list_collection_names = AsyncMock(return_value=["z", "a", "m"])
        mock_client.__getitem__ = lambda _self, key: mock_db if key == "mydb" else MagicMock()
        connection._client = mock_client

        result = await adapter.list_collections("hash123", "mydb")
        assert result == ["a", "m", "z"]


class TestGetSizeStats:
    async def test_builds_complete_size_report(
        self,
        connection: MongoConnection,
        adapter: MongoMetadataAdapter,
    ) -> None:
        mock_client = MagicMock()
        mock_db = MagicMock()

        mock_db.list_collection_names = AsyncMock(return_value=["col1", "col2"])
        mock_db.command = AsyncMock(
            side_effect=[
                {"dataSize": 1_000, "collections": 2},  # dbStats
                {"size": 500, "count": 10},  # collStats col1
                {"size": 300, "count": 5},  # collStats col2
            ]
        )
        mock_client.list_database_names = AsyncMock(return_value=["mydb"])
        mock_client.__getitem__ = lambda _self, key: mock_db if key == "mydb" else MagicMock()

        connection._client = mock_client

        report = await adapter.get_size_stats(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        assert isinstance(report, SizeReport)
        assert (
            report.cluster_uri_hash
            == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        assert len(report.databases) == 1
        assert report.databases[0] == DatabaseSize(
            database="mydb", size_bytes=1_000, collection_count=2
        )
        assert len(report.collections) == 2
        assert report.collections[0] == CollectionSize(
            database="mydb", collection="col1", size_bytes=500, document_count=10
        )
        assert report.collections[1] == CollectionSize(
            database="mydb", collection="col2", size_bytes=300, document_count=5
        )

    async def test_skips_collection_on_timeout(
        self,
        connection: MongoConnection,
        adapter: MongoMetadataAdapter,
    ) -> None:
        mock_client = MagicMock()
        mock_db = MagicMock()

        async def _cmd(*args: object, **_: object) -> dict[str, object]:
            if args == ("collStats", "bad_col"):
                raise asyncio.TimeoutError()
            return (
                {"dataSize": 100, "collections": 1}
                if args == ("dbStats",)
                else {"size": 50, "count": 1}
            )

        mock_db.list_collection_names = AsyncMock(return_value=["good_col", "bad_col"])
        mock_db.command = _cmd
        mock_client.list_database_names = AsyncMock(return_value=["mydb"])
        mock_client.__getitem__ = lambda _self, key: mock_db if key == "mydb" else MagicMock()

        connection._client = mock_client

        report = await adapter.get_size_stats(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        assert len(report.databases) == 1
        assert len(report.collections) == 1
        assert report.collections[0].collection == "good_col"

    async def test_skips_collection_on_generic_exception(
        self,
        connection: MongoConnection,
        adapter: MongoMetadataAdapter,
    ) -> None:
        mock_client = MagicMock()
        mock_db = MagicMock()

        async def _cmd(*args: object, **_: object) -> dict[str, object]:
            if args == ("collStats", "bad_col"):
                raise RuntimeError("boom")
            return (
                {"dataSize": 100, "collections": 1}
                if args == ("dbStats",)
                else {"size": 50, "count": 1}
            )

        mock_db.list_collection_names = AsyncMock(return_value=["bad_col", "good_col"])
        mock_db.command = _cmd
        mock_client.list_database_names = AsyncMock(return_value=["mydb"])
        mock_client.__getitem__ = lambda _self, key: mock_db if key == "mydb" else MagicMock()

        connection._client = mock_client

        report = await adapter.get_size_stats(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        assert len(report.collections) == 1
        assert report.collections[0].collection == "good_col"

    async def test_skips_database_on_exception(
        self,
        connection: MongoConnection,
        adapter: MongoMetadataAdapter,
    ) -> None:
        mock_client = MagicMock()
        mock_db = MagicMock()

        async def _cmd(*args: object, **_: object) -> dict[str, object]:
            if args == ("dbStats",):
                raise RuntimeError("db down")
            return {"size": 50, "count": 1}

        mock_db.list_collection_names = AsyncMock(return_value=["col1"])
        mock_db.command = _cmd
        mock_client.list_database_names = AsyncMock(return_value=["mydb"])
        mock_client.__getitem__ = lambda _self, key: mock_db if key == "mydb" else MagicMock()

        connection._client = mock_client

        report = await adapter.get_size_stats(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        assert len(report.databases) == 0
        assert len(report.collections) == 0

    async def test_defaults_missing_stats_to_zero(
        self,
        connection: MongoConnection,
        adapter: MongoMetadataAdapter,
    ) -> None:
        mock_client = MagicMock()
        mock_db = MagicMock()

        mock_db.list_collection_names = AsyncMock(return_value=["col1"])
        mock_db.command = AsyncMock(return_value={})  # empty stats
        mock_client.list_database_names = AsyncMock(return_value=["mydb"])
        mock_client.__getitem__ = lambda _self, key: mock_db if key == "mydb" else MagicMock()

        connection._client = mock_client

        report = await adapter.get_size_stats(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )

        assert report.databases[0].size_bytes == 0
        assert report.databases[0].collection_count == 0
        assert report.collections[0].size_bytes == 0
        assert report.collections[0].document_count == 0
