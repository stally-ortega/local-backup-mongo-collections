"""Application service that enforces backup retention policies.

Cleans up expired archives based on age rules and global storage caps
while guaranteeing at least one surviving backup per type.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.application.ports.ports import IFsUtils
from app.domain.entities.backup_job import BackupJob
from app.domain.repositories.repositories import IJobRepository
from app.domain.value_objects.enums import JobStatus


class RetentionManager:
    """Evaluates and applies retention rules on the local backup filesystem.

    Parameters
    ----------
    fs_utils:
        Async filesystem adapter.
    backup_base_path:
        Root directory where backups are stored.
    retention_full_weeks:
        How many weeks to keep ``full`` backups.
    retention_custom_weeks:
        How many weeks to keep ``custom`` backups.
    retention_max_gb:
        Global ceiling in gigabytes. If exceeded, oldest backups are
        removed first (respecting the one-per-type minimum).
    """

    def __init__(
        self,
        *,
        fs_utils: IFsUtils,
        backup_base_path: Path,
        retention_full_weeks: int,
        retention_custom_weeks: int,
        retention_max_gb: int,
        job_repository: IJobRepository | None = None,
    ) -> None:
        self._fs = fs_utils
        self._base_path = backup_base_path
        self._full_weeks = retention_full_weeks
        self._custom_weeks = retention_custom_weeks
        self._max_bytes = retention_max_gb * 1024 * 1024 * 1024
        self._job_repository = job_repository

    async def get_storage_stats(self) -> dict[str, Any]:
        """Return aggregated metrics for the backup storage area."""
        total_bytes, used_bytes, free_bytes = await self._fs.get_disk_usage(self._base_path)
        backup_size = await self._fs.get_folder_size(self._base_path)
        files = await self._fs.list_files_recursive(self._base_path, pattern="backup_*.tar.gz")
        return {
            "disk_total_bytes": total_bytes,
            "disk_used_bytes": used_bytes,
            "disk_free_bytes": free_bytes,
            "backup_size_bytes": backup_size,
            "backup_file_count": len(files),
        }

    async def apply_policy(self) -> dict[str, Any]:
        """Remove backups that violate age or global-size rules.

        Returns a summary dict with counts and bytes reclaimed.
        """
        age_result = await self.cleanup_old_backups()
        size_result = await self.enforce_max_storage()

        return {
            "deleted_count": age_result["deleted_count"] + size_result["deleted_count"],
            "reclaimed_bytes": age_result["reclaimed_bytes"] + size_result["reclaimed_bytes"],
            "errors": age_result["errors"] + size_result["errors"],
        }

    async def cleanup_old_backups(self) -> dict[str, Any]:
        """Remove backups older than the configured retention windows.

        Guarantees at least one surviving backup per known type (``full``,
        ``custom``) even when every file is older than the cutoff.

        Returns a summary dict with counts and bytes reclaimed.
        """
        files = await self._fs.list_files_recursive(self._base_path, pattern="backup_*.tar.gz")
        if not files:
            return {"deleted_count": 0, "reclaimed_bytes": 0, "errors": []}

        now = datetime.now(timezone.utc)
        cutoff_full = now - timedelta(weeks=self._full_weeks)
        cutoff_custom = now - timedelta(weeks=self._custom_weeks)

        backups = await self._build_backup_descriptors(files)

        full_backups = sorted(
            [b for b in backups if b["type"] == "full"],
            key=lambda b: b["mtime"],
        )
        custom_backups = sorted(
            [b for b in backups if b["type"] == "custom"],
            key=lambda b: b["mtime"],
        )

        to_delete: set[Path] = set()
        to_delete.update(self._prune_by_age(full_backups, cutoff_full, minimum_keep=1))
        to_delete.update(self._prune_by_age(custom_backups, cutoff_custom, minimum_keep=1))

        return await self._execute_deletions(to_delete)

    async def enforce_max_storage(self) -> dict[str, Any]:
        """Remove oldest backups until total size is below the configured cap.

        Respects a minimum of one backup per known type.

        Returns a summary dict with counts and bytes reclaimed.
        """
        files = await self._fs.list_files_recursive(self._base_path, pattern="backup_*.tar.gz")
        if not files:
            return {"deleted_count": 0, "reclaimed_bytes": 0, "errors": []}

        backups = await self._build_backup_descriptors(files)
        total_size = sum(b["size"] for b in backups)

        if total_size <= self._max_bytes:
            return {"deleted_count": 0, "reclaimed_bytes": 0, "errors": []}

        full_backups = [b for b in backups if b["type"] == "full"]
        custom_backups = [b for b in backups if b["type"] == "custom"]

        to_delete = self._prune_by_size(
            backups,
            total_size,
            self._max_bytes,
            full_backups=full_backups,
            custom_backups=custom_backups,
        )

        return await self._execute_deletions(to_delete)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _build_backup_descriptors(
        self,
        files: list[Path],
    ) -> list[dict[str, Any]]:
        """Build a list of backup descriptors with metadata."""
        backups: list[dict[str, Any]] = []
        for file_path in files:
            mtime = await self._fs.get_modification_time(file_path)
            btype = self._classify_type(file_path)
            size = await self._fs.get_folder_size(file_path)
            backups.append(
                {
                    "path": file_path,
                    "type": btype,
                    "mtime": mtime,
                    "size": size,
                }
            )
        return backups

    async def _execute_deletions(self, to_delete: set[Path]) -> dict[str, Any]:
        """Delete the given paths and return a summary."""
        deleted_count = 0
        reclaimed_bytes = 0
        errors: list[str] = []

        running_jobs: list[BackupJob] = []
        if self._job_repository is not None:
            running_jobs = await self._job_repository.list_by_status(
                JobStatus.RUNNING, page=1, page_size=1000
            )

        for path in to_delete:
            if self._is_path_in_use(path, running_jobs):
                errors.append(
                    f"Skipped deletion of {path}: currently in use by a running backup job"
                )
                continue
            try:
                size = await self._fs.get_folder_size(path)
                await self._fs.delete(path)
                deleted_count += 1
                reclaimed_bytes += size
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Failed to delete {path}: {exc}")

        return {
            "deleted_count": deleted_count,
            "reclaimed_bytes": reclaimed_bytes,
            "errors": errors,
        }

    @staticmethod
    def _is_path_in_use(path: Path, running_jobs: list[BackupJob]) -> bool:
        """Return ``True`` when *path* is inside the output directory of a running job."""
        for job in running_jobs:
            if job.output_path is not None:
                try:
                    path.relative_to(job.output_path)
                    return True
                except ValueError:
                    pass
        return False

    @staticmethod
    def _classify_type(path: Path) -> str:
        """Derive backup type from filename or parent directory name."""
        name = path.name.lower()
        if name.startswith("backup_full_") and name.endswith(".tar.gz"):
            return "full"
        if name.startswith("backup_custom_") and name.endswith(".tar.gz"):
            return "custom"
        parent = path.parent.name.lower()
        if parent == "full":
            return "full"
        if parent == "custom":
            return "custom"
        return "unknown"

    @staticmethod
    def _prune_by_age(
        sorted_backups: list[dict[str, Any]],
        cutoff: datetime,
        *,
        minimum_keep: int = 1,
    ) -> set[Path]:
        """Return paths older than *cutoff* while keeping *minimum_keep* items."""
        to_delete: set[Path] = set()
        for backup in sorted_backups:
            if backup["mtime"] < cutoff:
                kept = len(sorted_backups) - len(to_delete)
                if kept > minimum_keep:
                    to_delete.add(backup["path"])
        return to_delete

    @staticmethod
    def _prune_by_size(
        all_backups: list[dict[str, Any]],
        current_size: int,
        max_size: int,
        *,
        full_backups: list[dict[str, Any]],
        custom_backups: list[dict[str, Any]],
    ) -> set[Path]:
        """Remove oldest backups until *current_size* is below *max_size*.

        Respects a minimum of one backup per known type.
        """
        to_delete: set[Path] = set()
        candidates = sorted(all_backups, key=lambda b: b["mtime"])

        for backup in candidates:
            if current_size <= max_size:
                break

            btype = backup["type"]
            remaining_full = [b for b in full_backups if b["path"] not in to_delete]
            remaining_custom = [b for b in custom_backups if b["path"] not in to_delete]

            if btype == "full" and len(remaining_full) <= 1:
                continue
            if btype == "custom" and len(remaining_custom) <= 1:
                continue

            to_delete.add(backup["path"])
            current_size -= backup["size"]

        return to_delete
