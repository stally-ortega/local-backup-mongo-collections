"""Tests for the :class:`~app.domain.entities.size_report.SizeReport` aggregate."""

from app.domain.entities.size_report import CollectionSize, DatabaseSize, SizeReport


class TestCollectionSize:
    def test_create(self) -> None:
        cs = CollectionSize(
            database="db1",
            collection="users",
            size_bytes=1024,
            document_count=100,
        )
        assert cs.size_bytes == 1024
        assert cs.document_count == 100


class TestDatabaseSize:
    def test_create(self) -> None:
        ds = DatabaseSize(database="db1", size_bytes=2048, collection_count=3)
        assert ds.size_bytes == 2048
        assert ds.collection_count == 3


class TestSizeReport:
    def test_empty_report(self) -> None:
        report = SizeReport(cluster_uri_hash="hash")
        assert report.total_size_bytes() == 0
        assert report.total_document_count() == 0
        assert report.collection_count() == 0
        assert report.database_count() == 0

    def test_with_data(self) -> None:
        report = SizeReport(
            cluster_uri_hash="hash",
            databases=[
                DatabaseSize(database="db1", size_bytes=1000, collection_count=2),
                DatabaseSize(database="db2", size_bytes=2000, collection_count=1),
            ],
            collections=[
                CollectionSize(
                    database="db1",
                    collection="users",
                    size_bytes=600,
                    document_count=50,
                ),
                CollectionSize(
                    database="db1",
                    collection="orders",
                    size_bytes=400,
                    document_count=30,
                ),
                CollectionSize(
                    database="db2",
                    collection="logs",
                    size_bytes=2000,
                    document_count=100,
                ),
            ],
        )
        assert report.total_size_bytes() == 3000
        assert report.total_document_count() == 180
        assert report.collection_count() == 3
        assert report.database_count() == 2
