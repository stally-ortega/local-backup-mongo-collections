"""Unit tests for MongodumpBackupEngine."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pymongo
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
        assert cmd[0] == "/usr/bin/mongodump"
        assert any(arg.startswith("--config=") for arg in cmd)
        assert not any(arg.startswith("--uri=") for arg in cmd)
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
    async def test_empty_dump_file_is_allowed(
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

        result = await engine.backup_collection("mydb", "mycol", tmp_path)

        assert result.status == CollectionBackupStatus.SUCCESS
        assert result.size_bytes == 0


class TestBackupCollectionInjection:
    @patch("app.infrastructure.backup.mongodump_engine.shutil.which")
    @patch("app.infrastructure.backup.mongodump_engine.asyncio.create_subprocess_exec")
    async def test_malicious_names_passed_as_single_arguments(
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
        mock_proc.stdout.read = AsyncMock(return_value=b"stdout")
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"stderr")
        mock_proc.wait = AsyncMock(return_value=0)
        mock_subprocess.return_value = mock_proc

        malicious_db = "mydb --eval db_dropDatabase()"
        malicious_col = "mycol; DROP TABLE users"
        db_dir = tmp_path / malicious_db
        db_dir.mkdir()
        dump_file = db_dir / f"{malicious_col}.bson"
        dump_file.write_bytes(b"fake")

        await engine.backup_collection(malicious_db, malicious_col, tmp_path)

        mock_subprocess.assert_called_once()
        cmd = mock_subprocess.call_args[0]
        assert any(arg == f"--db={malicious_db}" for arg in cmd)
        assert any(arg == f"--collection={malicious_col}" for arg in cmd)
        # Ensure the number of positional args matches exactly 5 (no extra shell splitting).
        # --ssl is omitted for mongodb://localhost because TLS is not required.
        assert len(cmd) == 5


class TestValidateNames:
    async def test_empty_database_name_raises(
        self, engine: MongodumpBackupEngine, tmp_path: Path
    ) -> None:
        with pytest.raises(BackupEngineError, match="database name cannot be empty"):
            await engine.backup_collection("", "mycol", tmp_path)

    async def test_empty_collection_name_raises(
        self, engine: MongodumpBackupEngine, tmp_path: Path
    ) -> None:
        with pytest.raises(BackupEngineError, match="collection name cannot be empty"):
            await engine.backup_collection("mydb", "", tmp_path)

    @pytest.mark.parametrize(
        "bad_name",
        [
            "my/db",
            "my\\db",
            'my"db',
            "my*db",
            "my<db",
            "my>db",
            "my:db",
            "my|db",
            "my?db",
            "my$db",
            "my.db",
        ],
    )
    async def test_database_name_with_forbidden_char_raises(
        self, engine: MongodumpBackupEngine, tmp_path: Path, bad_name: str
    ) -> None:
        with pytest.raises(BackupEngineError, match="forbidden character"):
            await engine.backup_collection(bad_name, "mycol", tmp_path)

    @pytest.mark.parametrize(
        "bad_name",
        [
            "my/col",
            "my\\col",
            'my"col',
            "my*col",
            "my<col",
            "my>col",
            "my:col",
            "my|col",
            "my?col",
            "my$col",
        ],
    )
    async def test_collection_name_with_forbidden_char_raises(
        self, engine: MongodumpBackupEngine, tmp_path: Path, bad_name: str
    ) -> None:
        with pytest.raises(BackupEngineError, match="forbidden character"):
            await engine.backup_collection("mydb", bad_name, tmp_path)

    async def test_system_prefix_database_name_raises(
        self, engine: MongodumpBackupEngine, tmp_path: Path
    ) -> None:
        # Dots are forbidden in database names, so "system.users" is rejected
        # for the dot before the prefix check is reached.
        with pytest.raises(BackupEngineError, match="forbidden character"):
            await engine.backup_collection("system.users", "mycol", tmp_path)

    async def test_system_prefix_collection_name_raises(
        self, engine: MongodumpBackupEngine, tmp_path: Path
    ) -> None:
        # Dots are forbidden in collection names (conservative validation),
        # so "system.indexes" is rejected for the dot before the prefix check.
        with pytest.raises(BackupEngineError, match="forbidden character"):
            await engine.backup_collection("mydb", "system.indexes", tmp_path)

    async def test_database_name_too_long_raises(
        self, engine: MongodumpBackupEngine, tmp_path: Path
    ) -> None:
        long_name = "a" * 65
        with pytest.raises(BackupEngineError, match="exceeds maximum length"):
            await engine.backup_collection(long_name, "mycol", tmp_path)

    async def test_collection_name_too_long_raises(
        self, engine: MongodumpBackupEngine, tmp_path: Path
    ) -> None:
        long_name = "b" * 256
        with pytest.raises(BackupEngineError, match="exceeds maximum length"):
            await engine.backup_collection("mydb", long_name, tmp_path)

    @patch("app.infrastructure.backup.mongodump_engine.shutil.which")
    @patch("app.infrastructure.backup.mongodump_engine.asyncio.create_subprocess_exec")
    async def test_valid_names_proceed_to_subprocess(
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
        dump_file.write_bytes(b"fake")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read = AsyncMock(return_value=b"stdout")
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"stderr")
        mock_proc.wait = AsyncMock(return_value=0)
        mock_subprocess.return_value = mock_proc

        result = await engine.backup_collection("mydb", "mycol", tmp_path)

        assert result.status == CollectionBackupStatus.SUCCESS
        mock_subprocess.assert_called_once()


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
        mock_client.admin.command = MagicMock(
            side_effect=pymongo.errors.ConnectionFailure("refused")
        )
        mock_client_cls.return_value = mock_client

        result = await engine.validate_connection("hash123")

        assert result is False
        mock_client.close.assert_called_once()


class TestConfiguredBinary:
    @patch("app.infrastructure.backup.mongodump_engine.asyncio.create_subprocess_exec")
    async def test_uses_configured_path_when_provided(
        self,
        mock_subprocess: MagicMock,
        tmp_path: Path,
    ) -> None:
        binary = tmp_path / "custom_mongodump.exe"
        binary.write_text("fake")
        engine = MongodumpBackupEngine(
            "mongodb://localhost:27017",
            dump_timeout_seconds=5.0,
            mongodump_path=str(binary),
        )

        db_dir = tmp_path / "mydb"
        db_dir.mkdir()
        dump_file = db_dir / "mycol.bson"
        dump_file.write_bytes(b"fake")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read = AsyncMock(return_value=b"stdout")
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"stderr")
        mock_proc.wait = AsyncMock(return_value=0)
        mock_subprocess.return_value = mock_proc

        await engine.backup_collection("mydb", "mycol", tmp_path)

        mock_subprocess.assert_called_once()
        cmd = mock_subprocess.call_args[0]
        assert cmd[0] == str(binary)

    async def test_raises_when_configured_path_missing(
        self,
        tmp_path: Path,
    ) -> None:
        engine = MongodumpBackupEngine(
            "mongodb://localhost:27017",
            dump_timeout_seconds=5.0,
            mongodump_path="/nonexistent/mongodump",
        )

        with pytest.raises(BackupEngineError, match="mongodump binary not found"):
            await engine.backup_collection("mydb", "mycol", tmp_path)


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
