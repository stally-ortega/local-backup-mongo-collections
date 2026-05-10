"""Integration tests for MongoMetadataAdapter.

These tests require a live MongoDB instance. They are skipped automatically
when no server is reachable on the default localhost port.
"""

import os
from collections.abc import AsyncGenerator
from typing import Any

import pymongo
import pytest

from app.infrastructure.mongo.mongo_connection import MongoConnection
from app.infrastructure.mongo.mongo_metadata_adapter import MongoMetadataAdapter


def _mongo_available() -> bool:
    uri = os.environ.get("MONGO_OPS_TEST_MONGODB_URI", "mongodb://localhost:27017")
    try:
        client: Any = pymongo.MongoClient(uri, serverSelectionTimeoutMS=2_000)
        client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    os.environ.get("MONGO_OPS_SKIP_MONGO_INTEGRATION") == "1" or not _mongo_available(),
    reason="MongoDB not available or MONGO_OPS_SKIP_MONGO_INTEGRATION is set",
)
class TestMongoMetadataAdapterIntegration:
    @pytest.fixture(scope="class")
    async def adapter(self) -> AsyncGenerator[MongoMetadataAdapter, None]:
        uri = os.environ.get("MONGO_OPS_TEST_MONGODB_URI", "mongodb://localhost:27017")
        conn = MongoConnection(uri)
        conn.connect()

        adapter = MongoMetadataAdapter(conn, stat_timeout_seconds=10.0)
        yield adapter
        conn.close()

    async def test_list_databases_excludes_system(self, adapter: MongoMetadataAdapter) -> None:
        dbs = await adapter.list_databases("integration-test")
        system = {"admin", "local", "config"}
        assert not (set(dbs) & system)

    async def test_list_collections_returns_names(self, adapter: MongoMetadataAdapter) -> None:
        dbs = await adapter.list_databases("integration-test")
        if not dbs:
            pytest.skip("No user databases to inspect")

        cols = await adapter.list_collections("integration-test", dbs[0])
        assert isinstance(cols, list)

    async def test_get_size_stats_returns_report(self, adapter: MongoMetadataAdapter) -> None:
        report = await adapter.get_size_stats("integration-test")
        assert report.cluster_uri_hash == "integration-test"
        assert isinstance(report.databases, list)
        assert isinstance(report.collections, list)
