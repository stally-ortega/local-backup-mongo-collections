"""Tests verifying application port protocol shapes and fake adapters."""

from pathlib import Path

import pytest

from app.application.ports.ports import (  # noqa: TCH001
    IBackupEngine,
    IFsUtils,
    IJobQueue,
    ILockManager,
    IMongoMetadata,
    INotifier,
)
from app.domain.entities.size_report import CollectionSize, DatabaseSize, SizeReport
from app.domain.value_objects.dtos import CollectionTarget
from app.domain.value_objects.enums import CollectionBackupStatus


class _FakeBackupEngine:
    async def backup_collection(
        self, database: str, collection: str, output_path: Path
    ) -> CollectionTarget:
        return CollectionTarget(
            database=database,
            collection=collection,
            status=CollectionBackupStatus.SUCCESS,
            size_bytes=1024,
        )

    async def get_version(self) -> str:
        return "1.0.0"

    async def validate_connection(self, cluster_uri_hash: str) -> bool:
        return True


class _FakeNotifier:
    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        topic_id: int | None = None,
        correlation_id: str | None = None,
    ) -> None:
        pass

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        correlation_id: str | None = None,
    ) -> None:
        pass

    async def send_document(
        self,
        chat_id: int,
        file_path: Path,
        *,
        caption: str | None = None,
        topic_id: int | None = None,
        correlation_id: str | None = None,
    ) -> None:
        pass


class _FakeJobQueue:
    async def enqueue(
        self,
        job_id: str,
        job_type: str,
        payload: dict[str, object],
        *,
        priority: str = "normal",
    ) -> str:
        return "queue-id-123"

    async def get_status(self, queue_job_id: str) -> str | None:
        return "queued"

    async def cancel_job(self, queue_job_id: str) -> bool:
        return True


class _FakeLockManager:
    async def acquire(self, resource: str, *, ttl_seconds: int = 60) -> str | None:
        return "token-abc"

    async def release(self, resource: str, token: str) -> bool:
        return True

    async def is_locked(self, resource: str) -> bool:
        return False


class _FakeFsUtils:
    async def ensure_dir(self, path: Path) -> None:
        pass

    async def write_text(self, path: Path, content: str) -> None:
        pass

    async def get_folder_size(self, path: Path) -> int:
        return 0

    async def get_disk_usage(self, path: Path) -> tuple[int, int, int]:
        return (100_000, 50_000, 50_000)

    async def compress(self, source: Path, destination: Path) -> None:
        pass

    async def delete(self, path: Path) -> None:
        pass


class _FakeMongoMetadata:
    async def list_databases(self, cluster_uri_hash: str) -> list[str]:
        return ["db1", "db2"]

    async def list_collections(self, cluster_uri_hash: str, database: str) -> list[str]:
        return ["col1", "col2"]

    async def get_size_stats(self, cluster_uri_hash: str) -> SizeReport:
        return SizeReport(
            cluster_uri_hash=cluster_uri_hash,
            databases=[
                DatabaseSize(database="db1", size_bytes=1000, collection_count=2),
            ],
            collections=[
                CollectionSize(
                    database="db1",
                    collection="col1",
                    size_bytes=500,
                    document_count=10,
                ),
            ],
        )


class TestBackupEnginePort:
    def test_fake_implements_protocol(self) -> None:
        engine: IBackupEngine = _FakeBackupEngine()
        assert engine is not None

    @pytest.mark.asyncio
    async def test_backup_collection(self) -> None:
        engine: IBackupEngine = _FakeBackupEngine()
        result = await engine.backup_collection("db", "col", Path("/tmp"))
        assert result.status == CollectionBackupStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_validate_connection(self) -> None:
        engine: IBackupEngine = _FakeBackupEngine()
        ok = await engine.validate_connection("hash")
        assert ok is True


class TestNotifierPort:
    def test_fake_implements_protocol(self) -> None:
        notifier: INotifier = _FakeNotifier()
        assert notifier is not None

    @pytest.mark.asyncio
    async def test_send_message(self) -> None:
        notifier: INotifier = _FakeNotifier()
        await notifier.send_message(123, "hello")

    @pytest.mark.asyncio
    async def test_send_document(self) -> None:
        notifier: INotifier = _FakeNotifier()
        await notifier.send_document(123, Path("/tmp/file.txt"))


class TestJobQueuePort:
    def test_fake_implements_protocol(self) -> None:
        queue: IJobQueue = _FakeJobQueue()
        assert queue is not None

    @pytest.mark.asyncio
    async def test_enqueue(self) -> None:
        queue: IJobQueue = _FakeJobQueue()
        qid = await queue.enqueue("j1", "backup", {})
        assert qid == "queue-id-123"

    @pytest.mark.asyncio
    async def test_cancel_job(self) -> None:
        queue: IJobQueue = _FakeJobQueue()
        ok = await queue.cancel_job("q1")
        assert ok is True


class TestLockManagerPort:
    def test_fake_implements_protocol(self) -> None:
        lock: ILockManager = _FakeLockManager()
        assert lock is not None

    @pytest.mark.asyncio
    async def test_acquire_and_release(self) -> None:
        lock: ILockManager = _FakeLockManager()
        token = await lock.acquire("resource")
        assert token == "token-abc"
        released = await lock.release("resource", token)
        assert released is True

    @pytest.mark.asyncio
    async def test_is_locked(self) -> None:
        lock: ILockManager = _FakeLockManager()
        assert await lock.is_locked("resource") is False


class TestFsUtilsPort:
    def test_fake_implements_protocol(self) -> None:
        fs: IFsUtils = _FakeFsUtils()
        assert fs is not None

    @pytest.mark.asyncio
    async def test_get_disk_usage(self) -> None:
        fs: IFsUtils = _FakeFsUtils()
        total, used, free = await fs.get_disk_usage(Path("/tmp"))
        assert total == 100_000
        assert used == 50_000
        assert free == 50_000

    @pytest.mark.asyncio
    async def test_get_folder_size(self) -> None:
        fs: IFsUtils = _FakeFsUtils()
        size = await fs.get_folder_size(Path("/tmp"))
        assert size == 0


class TestMongoMetadataPort:
    def test_fake_implements_protocol(self) -> None:
        meta: IMongoMetadata = _FakeMongoMetadata()
        assert meta is not None

    @pytest.mark.asyncio
    async def test_list_databases(self) -> None:
        meta: IMongoMetadata = _FakeMongoMetadata()
        dbs = await meta.list_databases("hash")
        assert dbs == ["db1", "db2"]

    @pytest.mark.asyncio
    async def test_get_size_stats(self) -> None:
        meta: IMongoMetadata = _FakeMongoMetadata()
        report = await meta.get_size_stats("hash")
        assert report.cluster_uri_hash == "hash"
        assert report.total_size_bytes() == 1000
