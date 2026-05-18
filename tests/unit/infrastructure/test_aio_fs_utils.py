"""Unit tests for AioFsUtils."""

import tarfile
from pathlib import Path

import pytest

from app.infrastructure.filesystem.aio_fs_utils import AioFsUtils


@pytest.fixture
def fs() -> AioFsUtils:
    return AioFsUtils()


class TestPathValidation:
    async def test_rejects_path_outside_base(
        self,
        tmp_path: Path,
    ) -> None:
        fs = AioFsUtils(base_path=tmp_path / "safe")
        evil = tmp_path / ".." / "evil.txt"

        with pytest.raises(ValueError, match="outside the authorized base path"):
            await fs.ensure_dir(evil)

    async def test_rejects_traversal_with_dotdot(
        self,
        tmp_path: Path,
    ) -> None:
        safe_base = tmp_path / "safe"
        safe_base.mkdir()
        fs = AioFsUtils(base_path=safe_base)
        evil = safe_base / "subdir" / ".." / ".." / "etc" / "passwd"

        with pytest.raises(ValueError, match="outside the authorized base path"):
            await fs.ensure_dir(evil)

    async def test_rejects_traversal_in_compressed_source(
        self,
        tmp_path: Path,
    ) -> None:
        safe_base = tmp_path / "safe"
        safe_base.mkdir()
        fs = AioFsUtils(base_path=safe_base)
        evil_source = safe_base / ".." / "evil"
        dest = safe_base / "out.tar.gz"

        with pytest.raises(ValueError, match="outside the authorized base path"):
            await fs.compress(evil_source, dest)

    async def test_rejects_traversal_in_compressed_destination(
        self,
        tmp_path: Path,
    ) -> None:
        safe_base = tmp_path / "safe"
        safe_base.mkdir()
        fs = AioFsUtils(base_path=safe_base)
        source = safe_base / "data"
        source.mkdir()
        evil_dest = safe_base / ".." / "evil.tar.gz"

        with pytest.raises(ValueError, match="outside the authorized base path"):
            await fs.compress(source, evil_dest)

    async def test_allows_path_inside_base(
        self,
        tmp_path: Path,
    ) -> None:
        safe_base = tmp_path / "safe"
        safe_base.mkdir()
        fs = AioFsUtils(base_path=safe_base)
        target = safe_base / "subdir"

        await fs.ensure_dir(target)
        assert target.is_dir()


class TestEnsureDir:
    async def test_creates_nested_directories(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "a" / "b" / "c"
        await fs.ensure_dir(target)
        assert target.is_dir()

    async def test_idempotent_when_exists(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "existing"
        target.mkdir()
        await fs.ensure_dir(target)
        assert target.is_dir()


class TestWriteText:
    async def test_creates_file_with_content(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "subdir" / "file.txt"
        await fs.write_text(path, "hello world")
        assert path.read_text(encoding="utf-8") == "hello world"


class TestGetFolderSize:
    async def test_returns_zero_for_empty_directory(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        size = await fs.get_folder_size(empty)
        assert size == 0

    async def test_returns_zero_for_missing_path(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        size = await fs.get_folder_size(tmp_path / "missing")
        assert size == 0

    async def test_sums_files_recursively(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        root = tmp_path / "tree"
        root.mkdir()
        (root / "a.txt").write_bytes(b"aaa")
        nested = root / "sub"
        nested.mkdir()
        (nested / "b.txt").write_bytes(b"bb")

        size = await fs.get_folder_size(root)
        assert size == 5

    async def test_returns_file_size_for_file_path(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        file = tmp_path / "single.bin"
        file.write_bytes(b"\x00" * 42)
        size = await fs.get_folder_size(file)
        assert size == 42


class TestGetDiskUsage:
    async def test_returns_three_tuple(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        total, used, free = await fs.get_disk_usage(tmp_path)
        assert isinstance(total, int)
        assert isinstance(used, int)
        assert isinstance(free, int)
        assert total > 0
        assert used >= 0
        assert free >= 0


class TestCompress:
    async def test_creates_tar_gz(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "backup"
        source.mkdir()
        (source / "data.txt").write_text("data")

        dest = tmp_path / "backup.tar.gz"
        await fs.compress(source, dest)

        assert dest.exists()
        assert tarfile.is_tarfile(dest)

    async def test_raises_when_source_missing(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        with pytest.raises(FileNotFoundError, match="Source not found"):
            await fs.compress(tmp_path / "missing", tmp_path / "out.tar.gz")


class TestDelete:
    async def test_removes_file(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "file.txt"
        target.write_text("x")
        await fs.delete(target)
        assert not target.exists()

    async def test_removes_directory_tree(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "tree"
        target.mkdir()
        (target / "nested" / "file.txt").parent.mkdir(parents=True)
        (target / "nested" / "file.txt").write_text("x")
        await fs.delete(target)
        assert not target.exists()

    async def test_idempotent_when_missing(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "missing"
        await fs.delete(target)
        assert not target.exists()


class TestListFiles:
    async def test_returns_matching_files(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.py").write_text("b")

        result = await fs.list_files(tmp_path, "*.txt")
        assert len(result) == 1
        assert result[0].name == "a.txt"

    async def test_returns_empty_for_missing_dir(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        result = await fs.list_files(tmp_path / "missing", "*")
        assert result == []


class TestListFilesRecursive:
    async def test_returns_files_deeply(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "deep.txt").write_text("x")

        result = await fs.list_files_recursive(tmp_path, "**/*.txt")
        assert any(p.name == "deep.txt" for p in result)

    async def test_returns_empty_for_missing_dir(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        result = await fs.list_files_recursive(tmp_path / "missing", "**/*")
        assert result == []


class TestGetModificationTime:
    async def test_returns_utc_datetime(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        from datetime import datetime, timezone

        target = tmp_path / "file.txt"
        target.write_text("x")

        mtime = await fs.get_modification_time(target)
        assert isinstance(mtime, datetime)
        # Ensure it is timezone-aware UTC (as returned by datetime.fromtimestamp with tz).
        assert mtime.tzinfo is not None
        # Roughly recent.
        assert (datetime.now(timezone.utc) - mtime).total_seconds() < 10


class TestMove:
    async def test_moves_file(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "source.txt"
        source.write_text("data")
        dest = tmp_path / "dest.txt"

        await fs.move(source, dest)

        assert not source.exists()
        assert dest.read_text() == "data"

    async def test_moves_directory(
        self,
        fs: AioFsUtils,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "source_dir"
        source.mkdir()
        (source / "file.txt").write_text("data")
        dest = tmp_path / "dest_dir"

        await fs.move(source, dest)

        assert not source.exists()
        assert (dest / "file.txt").read_text() == "data"
