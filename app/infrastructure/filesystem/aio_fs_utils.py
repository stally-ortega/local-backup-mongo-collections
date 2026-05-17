"""Async filesystem adapter implementing :class:`~app.application.ports.ports.IFsUtils`.

All blocking I/O is offloaded to ``asyncio.to_thread`` so the event loop
remains responsive when traversing large backup trees or writing to slow
storage.  Uses only the standard library for cross-platform compatibility.
"""

import asyncio
import logging
import shutil
import tarfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class AioFsUtils:
    """Async-friendly filesystem utilities backed by ``asyncio.to_thread``.

    Every public method is ``async`` and safe to call from an ``asyncio``
    event loop without monopolising the thread.

    Parameters
    ----------
    base_path:
        Optional root directory that all operations must remain within.
        When provided, any path that resolves outside *base_path* raises
        :class:`ValueError`.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        self._base_path = base_path

    def _validate_path(self, path: Path) -> Path:
        """Resolve *path* and verify it stays within ``base_path``.

        Raises
        ------
        ValueError
            When the resolved path escapes the authorized base directory.
        """
        resolved = path.resolve()
        if self._base_path is not None and not resolved.is_relative_to(self._base_path.resolve()):
            raise ValueError(f"Path {resolved} is outside the authorized base path")
        return resolved

    async def ensure_dir(self, path: Path) -> None:
        """Create directory tree if it does not already exist."""
        self._validate_path(path)
        await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)

    async def write_text(self, path: Path, content: str) -> None:
        """Write UTF-8 text to *path*, creating parent directories first."""
        self._validate_path(path)
        await self.ensure_dir(path.parent)
        await asyncio.to_thread(path.write_text, content, encoding="utf-8")

    async def get_folder_size(self, path: Path) -> int:
        """Return total size in bytes of *path* and its descendants."""
        self._validate_path(path)

        def _walk() -> int:
            total = 0
            if not path.exists():
                return total
            if path.is_file():
                return path.stat().st_size
            for item in path.rglob("*"):
                if item.is_file():
                    total += item.stat().st_size
            return total

        return await asyncio.to_thread(_walk)

    async def get_disk_usage(self, path: Path) -> tuple[int, int, int]:
        """Return ``(total, used, free)`` bytes for the volume containing *path*."""
        usage = await asyncio.to_thread(shutil.disk_usage, path)
        return (usage.total, usage.used, usage.free)

    async def compress(self, source: Path, destination: Path) -> None:
        """Create a gzipped tar archive at *destination* from *source*."""
        self._validate_path(source)
        self._validate_path(destination)
        if not await asyncio.to_thread(source.exists):
            raise FileNotFoundError(f"Source not found: {source}")

        logger.info("Compressing %s -> %s", source, destination)

        def _compress() -> None:
            with tarfile.open(destination, "w:gz") as tar:
                tar.add(source, arcname=source.name)

        await asyncio.to_thread(_compress)
        logger.info("Compression complete: %s", destination)

    async def delete(self, path: Path) -> None:
        """Remove *path* — file or directory tree."""
        self._validate_path(path)

        def _remove() -> None:
            if not path.exists():
                return
            if path.is_file() or path.is_symlink():
                path.unlink()
            else:
                shutil.rmtree(path)

        await asyncio.to_thread(_remove)

    async def list_files(self, path: Path, pattern: str = "*") -> list[Path]:
        """Return files directly under *path* matching *pattern*."""
        self._validate_path(path)

        def _glob() -> list[Path]:
            if not path.exists():
                return []
            return list(path.glob(pattern))

        return await asyncio.to_thread(_glob)

    async def list_files_recursive(self, path: Path, pattern: str = "**/*") -> list[Path]:
        """Return files recursively under *path* matching *pattern*."""
        self._validate_path(path)

        def _rglob() -> list[Path]:
            if not path.exists():
                return []
            return list(path.glob(pattern))

        return await asyncio.to_thread(_rglob)

    async def get_modification_time(self, path: Path) -> datetime:
        """Return the last modification time of *path* as a UTC datetime."""
        self._validate_path(path)
        mtime: float = await asyncio.to_thread(lambda: path.stat().st_mtime)
        return datetime.utcfromtimestamp(mtime)

    async def move(self, source: Path, destination: Path) -> None:
        """Move *source* to *destination* (file or directory).

        This method is not part of the :class:`IFsUtils` protocol but is
        required by the work-plan and may be promoted to the port in the
        future.
        """
        self._validate_path(source)
        self._validate_path(destination)
        await asyncio.to_thread(shutil.move, str(source), str(destination))
