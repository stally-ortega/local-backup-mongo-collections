"""Cross-platform backup compressor using Python's stdlib ``tarfile``.

All blocking I/O is offloaded to ``asyncio.to_thread`` so the event loop
remains responsive when compressing large backup directories.
"""

import asyncio
import logging
import tarfile
from pathlib import Path

logger = logging.getLogger(__name__)


class BackupCompressor:
    """Create and verify ``tar.gz`` archives from backup directories.

    Uses the standard library ``tarfile`` module so it works identically on
    Linux and Windows without external dependencies.
    """

    async def compress_directory(self, source: Path, destination: Path) -> None:
        """Create a gzipped tar archive at *destination* from *source*.

        The archive stores paths relative to *source* so extracting it later
        yields a clean directory tree.

        Parameters
        ----------
        source:
            Directory to archive.
        destination:
            Path where the ``.tar.gz`` file will be written.

        Raises
        ------
        FileNotFoundError
            When *source* does not exist.
        OSError
            When the archive cannot be written.
        """
        if not await asyncio.to_thread(source.exists):
            raise FileNotFoundError(f"Source directory not found: {source}")

        logger.info("Compressing %s -> %s", source, destination)

        def _compress() -> None:
            with tarfile.open(destination, "w:gz") as tar:
                tar.add(source, arcname=source.name)

        await asyncio.to_thread(_compress)
        logger.info("Compression complete: %s", destination)

    async def verify_archive(self, path: Path) -> bool:
        """Perform a basic integrity check on a ``tar.gz`` archive.

        Returns ``True`` when *path* is a valid tar archive and its member
        list can be read without error.  Returns ``False`` on any problem.
        """

        def _verify() -> bool:
            if not tarfile.is_tarfile(path):
                return False
            try:
                with tarfile.open(path, "r:gz") as tar:
                    tar.getmembers()
                return True
            except (tarfile.TarError, OSError):
                return False

        try:
            return await asyncio.to_thread(_verify)
        except Exception as exc:
            logger.warning("Archive verification failed for %s: %s", path, exc)
            return False
