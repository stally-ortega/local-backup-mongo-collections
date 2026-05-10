"""Unit tests for MongodumpBackupEngine."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.exceptions.domain_errors import BackupEngineError
from app.domain.value_objects.dtos import CollectionTarget
from app.domain.value_objects.enums import CollectionBackupStatus
from app.infrastructure.backup.mongodump_engine import MongodumpBackupEngine


@pytest.fixture
def engine() -> MongodumpBackupEngine:
    return MongodumpBackupEngine("mongodb://localhost:27017", dump_timeout_seconds=5.0)


class TestBackupCollectionHappyPath:
    @patch("app.infrastructure.backup.mongodump_engine.shutil.which")
    @patch("app.infrastructure.backup.mongodump_engine.asyncio.create_subprocess_exec")
    async def test_successful_dump_returns_target(
        self,
        mock_subprocess: MagicMock,
        mock_which: MagicMock,
        engine: MongodumpBackupEngine,
        tmp_path: Path,
    ) -> None:
        mock_which.return_value = "/usr/bin/mongodump"

        # Create the expected dump file so post-validation passes.
        db_dir = tmp_path / "mydb"
        db_dir.mkdir()
        dump_file = db_dir / "mycol.bson"
        dump_file.write_bytes(b"fake bson data")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read = AsyncMock(return_value=b"stdout")
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"stderr")
        mock_proc.wait = AsyncMock(return_value=0)
        mock_subprocess.return_value = mock_proc

        result = await engine.backup_collection("mydb", "mycol", tmp_path)

        assert isinstance(result, CollectionTarget)
        assert result.database == "mydb"
        assert result.collection == "mycol"
        assert result.status == CollectionBackupStatus.SUCCESS
        assert result.size_bytes == len(b"fake bson data")

        mock_subprocess.assert_called_once()
        cmd = mock_subprocess.call_args[0]
        assert cmd[0] == "mongodump"
        assert "--db=mydb" in cmd
        assert "--collection=mycol" in cmd


class TestBackupCollectionErrors:
    @patch("app.infrastructure.backup.mongodump_engine.shutil.which")
    @patch("app.infrastructure.backup.mongodump_engine.asyncio.create_subprocess_exec")
    async def test_non_zero_exit_raises(
        self,
        mock_subprocess: MagicMock,
        mock_which: MagicMock,
        engine: MongodumpBackupEngine,
        tmp_path: Path,
    ) -> None:
        mock_which.return_value = "/usr/bin/mongodump"

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read = AsyncMock(return_value=b"")
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"connection refused")
        mock_proc.wait = AsyncMock(return_value=1)
        mock_subprocess.return_value = mock_proc

        with pytest.raises(BackupEngineError) as exc_info:
            await engine.backup_collection("mydb", "mycol", tmp_path)

        assert exc_info.value.code == "BACKUP_ENGINE_ERROR"
        assert "connection refused" in str(exc_info.value.details.get("stderr", ""))

    @patch("app.infrastructure.backup.mongodump_engine.shutil.which")
    @patch("app.infrastructure.backup.mongodump_engine.asyncio.create_subprocess_exec")
    async def test_timeout_raises(
        self,
        mock_subprocess: MagicMock,
        mock_which: MagicMock,
        engine: MongodumpBackupEngine,
        tmp_path: Path,
    ) -> None:
        mock_which.return_value = "/usr/bin/mongodump"

        async def _slow_wait() -> int:
            await asyncio.sleep(10)
            return 0

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read = AsyncMock(side_effect=_slow_wait)
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.wait = AsyncMock(side_effect=_slow_wait)
        mock_proc.kill = MagicMock()
        mock_subprocess.return_value = mock_proc

        with pytest.raises(BackupEngineError) as exc_info:
            await engine.backup_collection("mydb", "mycol", tmp_path)

        assert "timed out" in exc_info.value.message.lower()
        mock_proc.kill.assert_called_once()

    @patch("app.infrastructure.backup.mongodump_engine.shutil.which")
    @patch("app.infrastructure.backup.mongodump_engine.asyncio.create_subprocess_exec")
    async def test_missing_dump_file_raises(
        self,
        mock_subprocess: MagicMock,
        mock_which: MagicMock,
        engine: MongodumpBackupEngine,
        tmp_path: Path,
    ) -> None:
        mock_which.return_value = "/usr/bin/mongodump"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read = AsyncMock(return_value=b"done")
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.wait = AsyncMock(return_value=0)
        mock_subprocess.return_value = mock_proc

        with pytest.raises(BackupEngineError) as exc_info:
            await engine.backup_collection("mydb", "mycol", tmp_path)

        assert "missing" in exc_info.value.message.lower()

    @patch("app.infrastructure.backup.mongodump_engine.shutil.which")
    @patch("app.infrastructure.backup.mongodump_engine.asyncio.create_subprocess_exec")
    async def test_empty_dump_file_raises(
        self,
        mock_subprocess: MagicMock,
        mock_which: MagicMock,
        engine: MongodumpBackupEngine,
        tmp_path: Path,
    ) -> None:
        mock_which.return_value = "/usr/bin/mongodump"

        db_dir = tmp_path / "mydb"
        db_dir.mkdir()
        dump_file = db_dir / "mycol.bson"
        dump_file.write_bytes(b"")  # empty file

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read = AsyncMock(return_value=b"done")
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.wait = AsyncMock(return_value=0)
        mock_subprocess.return_value = mock_proc

        with pytest.raises(BackupEngineError) as exc_info:
            await engine.backup_collection("mydb", "mycol", tmp_path)

        assert "empty" in exc_info.value.message.lower()


class TestValidateConnection:
    @patch("app.infrastructure.backup.mongodump_engine.pymongo.MongoClient")
    async def test_returns_true_on_ping_success(
        self,
        mock_client_cls: MagicMock,
        engine: MongodumpBackupEngine,
    ) -> None:
        mock_client = MagicMock()
        mock_client.admin.command = MagicMock(return_value={"ok": 1})
        mock_client_cls.return_value = mock_client

        result = await engine.validate_connection("hash123")

        assert result is True
        mock_client_cls.assert_called_once()
        mock_client.close.assert_called_once()

    @patch("app.infrastructure.backup.mongodump_engine.pymongo.MongoClient")
    async def test_returns_false_on_ping_failure(
        self,
        mock_client_cls: MagicMock,
        engine: MongodumpBackupEngine,
    ) -> None:
        mock_client = MagicMock()
        mock_client.admin.command = MagicMock(side_effect=ConnectionError("refused"))
        mock_client_cls.return_value = mock_client

        result = await engine.validate_connection("hash123")

        assert result is False
        mock_client.close.assert_called_once()


class TestGetVersion:
    @patch("app.infrastructure.backup.mongodump_engine.shutil.which")
    @patch("app.infrastructure.backup.mongodump_engine.asyncio.create_subprocess_exec")
    async def test_parses_first_line(
        self,
        mock_subprocess: MagicMock,
        mock_which: MagicMock,
        engine: MongodumpBackupEngine,
    ) -> None:
        mock_which.return_value = "/usr/bin/mongodump"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read = AsyncMock(return_value=b"mongodump version: 100.9.1\nother")
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.communicate = AsyncMock(return_value=(b"mongodump version: 100.9.1\nother", b""))
        mock_subprocess.return_value = mock_proc

        version = await engine.get_version()

        assert version == "mongodump version: 100.9.1"

    @patch("app.infrastructure.backup.mongodump_engine.shutil.which")
    async def test_returns_unknown_when_binary_missing(
        self,
        mock_which: MagicMock,
        engine: MongodumpBackupEngine,
    ) -> None:
        mock_which.return_value = None

        version = await engine.get_version()

        assert version == "unknown"
