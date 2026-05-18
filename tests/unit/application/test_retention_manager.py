"""Unit tests for RetentionManager."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from app.application.services.retention_manager import RetentionManager
from app.domain.entities.backup_job import BackupJob
from app.domain.repositories.repositories import IJobRepository
from app.domain.value_objects.enums import JobStatus


class _FakeFsUtils:
    """In-memory filesystem fake for retention tests."""

    def __init__(self) -> None:
        self._files: dict[Path, dict[str, Any]] = {}
        self._deleted: set[Path] = set()

    def seed_file(self, path: Path, size: int, mtime: datetime) -> None:
        self._files[path] = {"size": size, "mtime": mtime}

    async def ensure_dir(self, path: Path) -> None:
        pass

    async def write_text(self, path: Path, content: str) -> None:
        pass

    async def get_folder_size(self, path: Path) -> int:
        if path in self._files:
            return cast("int", self._files[path]["size"])
        total = 0
        for p, meta in self._files.items():
            # Simple prefix match for directory contents.
            try:
                p.relative_to(path)
                total += meta["size"]
            except ValueError:
                pass
        return total

    async def get_disk_usage(self, path: Path) -> tuple[int, int, int]:
        return (100_000_000_000, 10_000_000_000, 90_000_000_000)

    async def compress(self, source: Path, destination: Path) -> None:
        pass

    async def delete(self, path: Path) -> None:
        self._deleted.add(path)
        self._files.pop(path, None)

    async def list_files(self, path: Path, pattern: str = "*") -> list[Path]:
        return [p for p in self._files if p.parent == path]

    async def list_files_recursive(self, path: Path, pattern: str = "**/*") -> list[Path]:
        results: list[Path] = []
        for p in self._files:
            try:
                p.relative_to(path)
                if pattern == "backup_*.tar.gz":
                    if p.name.startswith("backup_") and p.name.endswith(".tar.gz"):
                        results.append(p)
                else:
                    results.append(p)
            except ValueError:
                pass
        return results

    async def get_modification_time(self, path: Path) -> datetime:
        return cast("datetime", self._files[path]["mtime"])


class _FakeJobRepo(IJobRepository):
    def __init__(self, jobs: list[BackupJob] | None = None) -> None:
        self._jobs = jobs or []

    async def get_by_id(self, job_id: str) -> BackupJob | None:
        for job in self._jobs:
            if job.id == job_id:
                return job
        return None

    async def list_by_user(
        self,
        telegram_id: int,
        status: JobStatus | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[BackupJob]:
        jobs = [j for j in self._jobs if j.requester_telegram_id == telegram_id]
        if status is not None:
            jobs = [j for j in jobs if j.status == status]
        return jobs

    async def list_by_status(
        self, status: JobStatus, page: int = 1, page_size: int = 50
    ) -> list[BackupJob]:
        return [j for j in self._jobs if j.status == status]

    async def save(self, job: BackupJob) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def clear_session_cache(self) -> None:
        pass

    async def get_job_stats(self) -> dict[str, Any]:
        return {}


@pytest.fixture
def fs() -> _FakeFsUtils:
    return _FakeFsUtils()


@pytest.fixture
def base_path() -> Path:
    return Path("/backups")


@pytest.fixture
def manager(fs: _FakeFsUtils, base_path: Path) -> RetentionManager:
    return RetentionManager(
        fs_utils=fs,
        backup_base_path=base_path,
        retention_full_weeks=4,
        retention_custom_weeks=2,
        retention_max_gb=1,  # 1 GB = small cap for easy testing
    )


class TestRetentionManagerStorageStats:
    @pytest.mark.asyncio
    async def test_get_storage_stats_empty(
        self, manager: RetentionManager, fs: _FakeFsUtils
    ) -> None:
        stats = await manager.get_storage_stats()
        assert stats["backup_file_count"] == 0
        assert stats["backup_size_bytes"] == 0
        assert stats["disk_total_bytes"] == 100_000_000_000

    @pytest.mark.asyncio
    async def test_get_storage_stats_with_files(
        self, manager: RetentionManager, fs: _FakeFsUtils, base_path: Path
    ) -> None:
        fs.seed_file(
            base_path / "backup_full_20260101_120000.tar.gz",
            size=100,
            mtime=datetime.utcnow(),
        )
        fs.seed_file(
            base_path / "backup_custom_20260102_120000.tar.gz",
            size=200,
            mtime=datetime.utcnow(),
        )
        stats = await manager.get_storage_stats()
        assert stats["backup_file_count"] == 2
        assert stats["backup_size_bytes"] == 300


class TestRetentionManagerApplyPolicy:
    @pytest.mark.asyncio
    async def test_empty_directory(self, manager: RetentionManager) -> None:
        result = await manager.apply_policy()
        assert result["deleted_count"] == 0
        assert result["reclaimed_bytes"] == 0

    @pytest.mark.asyncio
    async def test_age_pruning_deletes_old_backups(
        self,
        manager: RetentionManager,
        fs: _FakeFsUtils,
        base_path: Path,
    ) -> None:
        now = datetime.utcnow()
        # Recent backups (should survive).
        fs.seed_file(
            base_path / "backup_full_20260115_120000.tar.gz",
            size=100,
            mtime=now,
        )
        fs.seed_file(
            base_path / "backup_custom_20260115_120000.tar.gz",
            size=100,
            mtime=now,
        )
        # Old backups (should be deleted).
        fs.seed_file(
            base_path / "backup_full_20251001_120000.tar.gz",
            size=50,
            mtime=now - timedelta(weeks=10),
        )
        fs.seed_file(
            base_path / "backup_custom_20251001_120000.tar.gz",
            size=50,
            mtime=now - timedelta(weeks=5),
        )

        result = await manager.apply_policy()

        assert result["deleted_count"] == 2
        assert result["reclaimed_bytes"] == 100
        assert (base_path / "backup_full_20251001_120000.tar.gz") in fs._deleted
        assert (base_path / "backup_custom_20251001_120000.tar.gz") in fs._deleted

    @pytest.mark.asyncio
    async def test_respects_minimum_one_per_type(
        self,
        manager: RetentionManager,
        fs: _FakeFsUtils,
        base_path: Path,
    ) -> None:
        now = datetime.utcnow()
        # Only one full backup, very old.
        fs.seed_file(
            base_path / "backup_full_20250101_120000.tar.gz",
            size=100,
            mtime=now - timedelta(weeks=52),
        )
        # Only one custom backup, very old.
        fs.seed_file(
            base_path / "backup_custom_20250101_120000.tar.gz",
            size=100,
            mtime=now - timedelta(weeks=52),
        )

        result = await manager.apply_policy()

        # Minimum-one rule prevents deletion.
        assert result["deleted_count"] == 0
        assert result["reclaimed_bytes"] == 0

    @pytest.mark.asyncio
    async def test_size_pruning_when_over_cap(
        self,
        manager: RetentionManager,
        fs: _FakeFsUtils,
        base_path: Path,
    ) -> None:
        now = datetime.utcnow()
        # Create several backups totalling > 1 GB cap.
        for i in range(5):
            fs.seed_file(
                base_path / f"backup_full_2026010{i}_120000.tar.gz",
                size=300_000_000,  # 300 MB each
                mtime=now - timedelta(days=i),
            )

        result = await manager.apply_policy()

        # Total = 1.5 GB; cap = 1 GB → need to reclaim ~500 MB.
        # Oldest backups removed first, respecting minimum-one.
        assert result["deleted_count"] >= 1
        assert result["reclaimed_bytes"] > 0
        # The newest full backup must survive (minimum-one).
        newest = base_path / "backup_full_20260100_120000.tar.gz"
        assert newest not in fs._deleted

    @pytest.mark.asyncio
    async def test_size_pruning_keeps_one_per_type_minimum(
        self,
        manager: RetentionManager,
        fs: _FakeFsUtils,
        base_path: Path,
    ) -> None:
        now = datetime.utcnow()
        # Two full backups, very large.
        fs.seed_file(
            base_path / "backup_full_20260101_120000.tar.gz",
            size=600_000_000,
            mtime=now - timedelta(days=2),
        )
        fs.seed_file(
            base_path / "backup_full_20260102_120000.tar.gz",
            size=600_000_000,
            mtime=now - timedelta(days=1),
        )
        # One custom backup, very large.
        fs.seed_file(
            base_path / "backup_custom_20260101_120000.tar.gz",
            size=600_000_000,
            mtime=now - timedelta(days=1),
        )

        await manager.apply_policy()

        # Total = 1.8 GB; cap = 1 GB.
        # Must remove at least 800 MB, but keep 1 full + 1 custom.
        remaining_full = [p for p in fs._files if "full" in p.name]
        remaining_custom = [p for p in fs._files if "custom" in p.name]
        assert len(remaining_full) >= 1
        assert len(remaining_custom) >= 1


class TestRetentionManagerClassify:
    def test_from_filename(self) -> None:
        assert RetentionManager._classify_type(Path("backup_full_xxx.tar.gz")) == "full"
        assert RetentionManager._classify_type(Path("backup_custom_xxx.tar.gz")) == "custom"

    def test_from_parent_directory(self) -> None:
        assert (
            RetentionManager._classify_type(Path("/backups/cluster/2026/01/full/backup_xxx.tar.gz"))
            == "full"
        )
        assert (
            RetentionManager._classify_type(
                Path("/backups/cluster/2026/01/custom/backup_xxx.tar.gz")
            )
            == "custom"
        )

    def test_unknown(self) -> None:
        assert RetentionManager._classify_type(Path("backup_unknown_xxx.tar.gz")) == "unknown"

    def test_substring_in_name_is_not_misclassified(self) -> None:
        # A file with "full" or "custom" embedded but not at the strict prefix.
        assert RetentionManager._classify_type(Path("my_full_backup.tar.gz")) == "unknown"
        assert RetentionManager._classify_type(Path("report_custom_final.tar.gz")) == "unknown"

    def test_prefix_ambiguity_resolved_by_prefix(self) -> None:
        # Prefix determines type unambiguously.
        assert RetentionManager._classify_type(Path("backup_full_custom_report.tar.gz")) == "full"
        assert RetentionManager._classify_type(Path("backup_custom_full_report.tar.gz")) == "custom"


class TestCleanupOldBackups:
    @pytest.mark.asyncio
    async def test_empty_directory(self, manager: RetentionManager) -> None:
        result = await manager.cleanup_old_backups()
        assert result["deleted_count"] == 0
        assert result["reclaimed_bytes"] == 0

    @pytest.mark.asyncio
    async def test_deletes_old_full_and_custom(
        self,
        manager: RetentionManager,
        fs: _FakeFsUtils,
        base_path: Path,
    ) -> None:
        now = datetime.utcnow()
        # Recent backups (should survive).
        fs.seed_file(
            base_path / "backup_full_20260115_120000.tar.gz",
            size=100,
            mtime=now,
        )
        fs.seed_file(
            base_path / "backup_custom_20260115_120000.tar.gz",
            size=100,
            mtime=now,
        )
        # Old backups (should be deleted).
        fs.seed_file(
            base_path / "backup_full_20251001_120000.tar.gz",
            size=50,
            mtime=now - timedelta(weeks=10),
        )
        fs.seed_file(
            base_path / "backup_custom_20251001_120000.tar.gz",
            size=50,
            mtime=now - timedelta(weeks=5),
        )

        result = await manager.cleanup_old_backups()

        assert result["deleted_count"] == 2
        assert result["reclaimed_bytes"] == 100
        assert (base_path / "backup_full_20251001_120000.tar.gz") in fs._deleted
        assert (base_path / "backup_custom_20251001_120000.tar.gz") in fs._deleted

    @pytest.mark.asyncio
    async def test_respects_minimum_one_per_type(
        self,
        manager: RetentionManager,
        fs: _FakeFsUtils,
        base_path: Path,
    ) -> None:
        now = datetime.utcnow()
        fs.seed_file(
            base_path / "backup_full_20250101_120000.tar.gz",
            size=100,
            mtime=now - timedelta(weeks=52),
        )
        fs.seed_file(
            base_path / "backup_custom_20250101_120000.tar.gz",
            size=100,
            mtime=now - timedelta(weeks=52),
        )

        result = await manager.cleanup_old_backups()

        assert result["deleted_count"] == 0
        assert result["reclaimed_bytes"] == 0


class TestEnforceMaxStorage:
    @pytest.mark.asyncio
    async def test_empty_directory(self, manager: RetentionManager) -> None:
        result = await manager.enforce_max_storage()
        assert result["deleted_count"] == 0
        assert result["reclaimed_bytes"] == 0

    @pytest.mark.asyncio
    async def test_no_action_when_under_cap(
        self,
        manager: RetentionManager,
        fs: _FakeFsUtils,
        base_path: Path,
    ) -> None:
        now = datetime.utcnow()
        fs.seed_file(
            base_path / "backup_full_20260101_120000.tar.gz",
            size=100,
            mtime=now,
        )

        result = await manager.enforce_max_storage()

        assert result["deleted_count"] == 0
        assert result["reclaimed_bytes"] == 0

    @pytest.mark.asyncio
    async def test_removes_oldest_when_over_cap(
        self,
        manager: RetentionManager,
        fs: _FakeFsUtils,
        base_path: Path,
    ) -> None:
        now = datetime.utcnow()
        for i in range(5):
            fs.seed_file(
                base_path / f"backup_full_2026010{i}_120000.tar.gz",
                size=300_000_000,
                mtime=now - timedelta(days=i),
            )

        result = await manager.enforce_max_storage()

        assert result["deleted_count"] >= 1
        assert result["reclaimed_bytes"] > 0
        newest = base_path / "backup_full_20260100_120000.tar.gz"
        assert newest not in fs._deleted

    @pytest.mark.asyncio
    async def test_keeps_one_per_type_minimum(
        self,
        manager: RetentionManager,
        fs: _FakeFsUtils,
        base_path: Path,
    ) -> None:
        now = datetime.utcnow()
        fs.seed_file(
            base_path / "backup_full_20260101_120000.tar.gz",
            size=600_000_000,
            mtime=now - timedelta(days=2),
        )
        fs.seed_file(
            base_path / "backup_full_20260102_120000.tar.gz",
            size=600_000_000,
            mtime=now - timedelta(days=1),
        )
        fs.seed_file(
            base_path / "backup_custom_20260101_120000.tar.gz",
            size=600_000_000,
            mtime=now - timedelta(days=1),
        )

        await manager.enforce_max_storage()

        remaining_full = [p for p in fs._files if "full" in p.name]
        remaining_custom = [p for p in fs._files if "custom" in p.name]
        assert len(remaining_full) >= 1
        assert len(remaining_custom) >= 1


class TestRetentionManagerSkipInUse:
    @pytest.mark.asyncio
    async def test_skips_file_inside_running_job_output_path(
        self,
        fs: _FakeFsUtils,
        base_path: Path,
    ) -> None:
        now = datetime.utcnow()
        # Old backup inside a running job's output directory.
        old_file = base_path / "hash" / "job-123" / "backup_full_20250101_120000.tar.gz"
        fs.seed_file(old_file, size=100, mtime=now - timedelta(weeks=10))
        # Recent backup outside so minimum_keep allows deletion of the old one.
        recent_file = base_path / "backup_full_20260101_120000.tar.gz"
        fs.seed_file(recent_file, size=100, mtime=now)

        running_job = BackupJob.create_full("job-123", 1, "hash")
        running_job.mark_queued()
        running_job.mark_running()
        running_job.output_path = base_path / "hash" / "job-123"

        job_repo = _FakeJobRepo([running_job])
        manager = RetentionManager(
            fs_utils=fs,
            backup_base_path=base_path,
            retention_full_weeks=4,
            retention_custom_weeks=2,
            retention_max_gb=1,
            job_repository=job_repo,
        )

        result = await manager.cleanup_old_backups()

        assert old_file not in fs._deleted
        assert recent_file not in fs._deleted
        assert any("Skipped deletion" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_deletes_file_when_job_not_running(
        self,
        fs: _FakeFsUtils,
        base_path: Path,
    ) -> None:
        now = datetime.utcnow()
        old_file = base_path / "hash" / "job-456" / "backup_full_20250101_120000.tar.gz"
        fs.seed_file(old_file, size=100, mtime=now - timedelta(weeks=10))
        recent_file = base_path / "backup_full_20260101_120000.tar.gz"
        fs.seed_file(recent_file, size=100, mtime=now)

        success_job = BackupJob.create_full("job-456", 1, "hash")
        success_job.mark_queued()
        success_job.mark_running()
        success_job.mark_success()
        success_job.output_path = base_path / "hash" / "job-456"

        job_repo = _FakeJobRepo([success_job])
        manager = RetentionManager(
            fs_utils=fs,
            backup_base_path=base_path,
            retention_full_weeks=4,
            retention_custom_weeks=2,
            retention_max_gb=1,
            job_repository=job_repo,
        )

        await manager.cleanup_old_backups()

        assert old_file in fs._deleted
        assert recent_file not in fs._deleted

    @pytest.mark.asyncio
    async def test_deletes_file_when_no_job_repository(
        self,
        fs: _FakeFsUtils,
        base_path: Path,
    ) -> None:
        now = datetime.utcnow()
        old_file = base_path / "backup_full_20250101_120000.tar.gz"
        fs.seed_file(old_file, size=100, mtime=now - timedelta(weeks=10))
        recent_file = base_path / "backup_full_20260101_120000.tar.gz"
        fs.seed_file(recent_file, size=100, mtime=now)

        manager = RetentionManager(
            fs_utils=fs,
            backup_base_path=base_path,
            retention_full_weeks=4,
            retention_custom_weeks=2,
            retention_max_gb=1,
        )

        await manager.cleanup_old_backups()

        assert old_file in fs._deleted
        assert recent_file not in fs._deleted
