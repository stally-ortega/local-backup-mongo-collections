"""Unit tests for BackupCompressor."""

import tarfile
from pathlib import Path

import pytest

from app.infrastructure.backup.compressor import BackupCompressor


@pytest.fixture
def compressor() -> BackupCompressor:
    return BackupCompressor()


class TestCompressDirectory:
    async def test_creates_tar_gz_archive(
        self,
        compressor: BackupCompressor,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "backup_2024"
        source.mkdir()
        (source / "file1.txt").write_text("hello")
        nested = source / "subdir"
        nested.mkdir()
        (nested / "file2.txt").write_text("world")

        dest = tmp_path / "backup_2024.tar.gz"
        await compressor.compress_directory(source, dest)

        assert dest.exists()
        assert tarfile.is_tarfile(dest)

        with tarfile.open(dest, "r:gz") as tar:
            names = tar.getnames()
            assert any("file1.txt" in n for n in names)
            assert any("file2.txt" in n for n in names)

    async def test_raises_when_source_missing(
        self,
        compressor: BackupCompressor,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "nonexistent"
        dest = tmp_path / "out.tar.gz"

        with pytest.raises(FileNotFoundError, match="Source directory not found"):
            await compressor.compress_directory(source, dest)

    async def test_overwrites_existing_archive(
        self,
        compressor: BackupCompressor,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "backup"
        source.mkdir()
        (source / "a.txt").write_text("a")

        dest = tmp_path / "backup.tar.gz"
        dest.write_bytes(b"old content")

        await compressor.compress_directory(source, dest)

        assert dest.exists()
        assert tarfile.is_tarfile(dest)


class TestVerifyArchive:
    async def test_returns_true_for_valid_archive(
        self,
        compressor: BackupCompressor,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "backup"
        source.mkdir()
        (source / "data.txt").write_text("data")

        archive = tmp_path / "backup.tar.gz"
        await compressor.compress_directory(source, archive)

        result = await compressor.verify_archive(archive)
        assert result is True

    async def test_returns_false_for_corrupted_file(
        self,
        compressor: BackupCompressor,
        tmp_path: Path,
    ) -> None:
        bad_file = tmp_path / "fake.tar.gz"
        bad_file.write_bytes(b"not a tar file")

        result = await compressor.verify_archive(bad_file)
        assert result is False

    async def test_returns_false_for_missing_file(
        self,
        compressor: BackupCompressor,
        tmp_path: Path,
    ) -> None:
        missing = tmp_path / "missing.tar.gz"

        result = await compressor.verify_archive(missing)
        assert result is False
