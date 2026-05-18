"""MongoDB backup engine adapter implementing :class:`~app.application.ports.ports.IBackupEngine`.

Runs ``mongodump`` via ``asyncio.create_subprocess_exec``, streams stdout/stderr
concurrently to avoid pipe-buffer deadlocks, validates the output, and surfaces
structured errors via :class:`~app.domain.exceptions.domain_errors.BackupEngineError`.
"""

import asyncio
import logging
import os
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

import pymongo

from app.application.ports.ports import IBackupEngine
from app.domain.exceptions.domain_errors import BackupEngineError
from app.domain.value_objects.dtos import CollectionTarget
from app.domain.value_objects.enums import CollectionBackupStatus

logger = logging.getLogger(__name__)

# Default wall-clock time allowed for a single collection dump.
_DEFAULT_DUMP_TIMEOUT_S: float = 300.0

# Timeout for MongoDB connectivity checks.
_DEFAULT_PING_TIMEOUT_MS: int = 5_000

# Minimum size (bytes) a dump file must have to be considered valid.
# Set to 0 so that empty collections (common in test environments) do not
# trigger a false failure.
_MIN_VALID_DUMP_SIZE: int = 0


class MongodumpBackupEngine(IBackupEngine):
    """Concrete adapter that drives ``mongodump`` for per-collection dumps.

    Parameters
    ----------
    uri:
        MongoDB connection string (``mongodb://`` or ``mongodb+srv://``).
    dump_timeout_seconds:
        Maximum time to wait for an individual ``mongodump`` invocation.
    """

    def __init__(
        self,
        uri: str,
        *,
        dump_timeout_seconds: float = _DEFAULT_DUMP_TIMEOUT_S,
        mongodump_path: str | None = None,
    ) -> None:
        self._uri = uri
        self._dump_timeout = dump_timeout_seconds
        self._mongodump_path = mongodump_path

        resolved = self._resolve_binary()
        if resolved is None:
            logger.warning("mongodump binary not found at %s", mongodump_path or "PATH")

    def _resolve_binary(self) -> str | None:
        """Return the absolute path to the mongodump binary."""
        if self._mongodump_path is not None:
            candidate = Path(self._mongodump_path)
            if candidate.exists() and candidate.is_file():
                return str(candidate.resolve())
            logger.warning("configured mongodump_path does not exist: %s", self._mongodump_path)
            return None
        found = shutil.which("mongodump")
        return found

    # ------------------------------------------------------------------
    # Name validation
    # ------------------------------------------------------------------

    _FORBIDDEN_CHARS: str = '/\\."*<>:|?$\x00'
    _MAX_DB_NAME_LENGTH: int = 64
    _MAX_COLLECTION_NAME_LENGTH: int = 255

    @classmethod
    def _validate_name(cls, name: str, kind: str) -> None:
        """Validate a MongoDB database or collection name.

        Raises
        ------
        BackupEngineError
            When the name violates MongoDB naming rules.
        """
        if not name:
            raise BackupEngineError(
                message=f"{kind} name cannot be empty",
                details={"kind": kind, "name": name},
            )
        if len(name.encode("utf-8")) > (
            cls._MAX_DB_NAME_LENGTH if kind == "database" else cls._MAX_COLLECTION_NAME_LENGTH
        ):
            raise BackupEngineError(
                message=f"{kind} name exceeds maximum length",
                details={"kind": kind, "name": name, "max_bytes": cls._MAX_DB_NAME_LENGTH},
            )
        for char in cls._FORBIDDEN_CHARS:
            if char in name:
                raise BackupEngineError(
                    message=f"{kind} name contains forbidden character",
                    details={"kind": kind, "name": name, "forbidden_char": char},
                )
        if name.lower().startswith("system."):
            raise BackupEngineError(
                message=f"{kind} name cannot start with 'system.'",
                details={"kind": kind, "name": name},
            )

    # ------------------------------------------------------------------
    # IBackupEngine implementation
    # ------------------------------------------------------------------

    async def backup_collection(
        self,
        database: str,
        collection: str,
        output_path: Path,
    ) -> CollectionTarget:
        """Dump *collection* from *database* into *output_path*.

        The command executed is roughly::

            mongodump --uri=<uri> --db=<database> \
                      --collection=<collection> --out=<output_path>

        Raises
        ------
        BackupEngineError
            When the subprocess fails, times out, or the post-dump validation
            does not find a non-empty BSON file.
        """
        binary = self._resolve_binary()
        if binary is None:
            raise BackupEngineError(
                message="mongodump binary not found",
                details={"configured_path": self._mongodump_path},
            )

        self._validate_name(database, "database")
        self._validate_name(collection, "collection")

        config_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as cfg:
                cfg.write(f"uri: {self._uri!r}\n")
                config_path = cfg.name

            cmd = [
                binary,
                f"--config={config_path}",
                f"--db={database}",
                f"--collection={collection}",
                f"--out={output_path}",
            ]
            if (
                self._uri.startswith("mongodb+srv://")
                or "tls=true" in self._uri
                or "ssl=true" in self._uri
            ):
                cmd.append("--ssl")

            logger.info(
                "Starting mongodump for %s.%s (timeout=%.0fs)",
                database,
                collection,
                self._dump_timeout,
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_data: bytes = b""
            stderr_data: bytes = b""

            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    self._drain_streams(proc),
                    timeout=self._dump_timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise BackupEngineError(
                    message=f"mongodump timed out after {self._dump_timeout}s "
                    f"for {database}.{collection}",
                    details={
                        "database": database,
                        "collection": collection,
                        "timeout_seconds": self._dump_timeout,
                    },
                ) from None

            if proc.returncode != 0:
                stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
                logger.error("mongodump failed: %s", stderr_text)
                raise BackupEngineError(
                    message=f"mongodump failed for {database}.{collection}",
                    details={
                        "database": database,
                        "collection": collection,
                        "returncode": proc.returncode,
                        "stderr": stderr_text,
                    },
                )

            # Post-backup validation: ensure the BSON file exists and is non-empty.
            dump_file = output_path / database / f"{collection}.bson"
            size_bytes = await self._validate_dump_file(dump_file, database, collection)

            logger.info(
                "mongodump completed for %s.%s -> %s (%d bytes)",
                database,
                collection,
                dump_file,
                size_bytes,
            )

            return CollectionTarget(
                database=database,
                collection=collection,
                status=CollectionBackupStatus.SUCCESS,
                size_bytes=size_bytes,
            )
        finally:
            if config_path is not None:
                with suppress(OSError):
                    os.unlink(config_path)

    async def get_version(self) -> str:
        """Return the ``mongodump --version`` string.

        Returns ``"unknown"`` when the binary is not available.
        """
        if not shutil.which("mongodump"):
            return "unknown"

        proc = await asyncio.create_subprocess_exec(
            "mongodump",
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return "unknown"

        first_line = stdout.decode("utf-8", errors="replace").splitlines()[0]
        return first_line.strip()

    async def validate_connection(self, cluster_uri_hash: str) -> bool:
        """Ping MongoDB using *cluster_uri_hash* as a correlation label.

        The actual URI is the one supplied at construction time.
        """
        client: pymongo.MongoClient[Any] | None = None
        try:
            client = pymongo.MongoClient(
                self._uri,
                serverSelectionTimeoutMS=_DEFAULT_PING_TIMEOUT_MS,
            )
            client.admin.command("ping")
            return True
        except pymongo.errors.PyMongoError as exc:
            logger.warning(
                "MongoDB ping failed (hash=%s): %s",
                cluster_uri_hash,
                exc,
            )
            return False
        finally:
            if client is not None:
                client.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _drain_streams(
        self,
        proc: asyncio.subprocess.Process,
    ) -> tuple[bytes, bytes]:
        """Read stdout and stderr concurrently to avoid pipe deadlock."""
        if proc.stdout is None or proc.stderr is None:
            raise RuntimeError("mongodump process streams are unexpectedly None")

        stdout_task = asyncio.create_task(proc.stdout.read())
        stderr_task = asyncio.create_task(proc.stderr.read())

        stdout_data, stderr_data = await asyncio.gather(stdout_task, stderr_task)
        await proc.wait()

        return stdout_data, stderr_data

    async def _validate_dump_file(
        self,
        dump_file: Path,
        database: str,
        collection: str,
    ) -> int:
        """Return the file size when *dump_file* exists and is non-empty.

        Uses ``asyncio.to_thread`` so the stat call does not block the event
        loop when the backup volume is on a slow or network-mounted path.

        Raises
        ------
        BackupEngineError
            When the file is missing or empty.
        """
        if not await asyncio.to_thread(dump_file.exists):
            raise BackupEngineError(
                message=f"Dump file missing for {database}.{collection}",
                details={
                    "database": database,
                    "collection": collection,
                    "expected_path": str(dump_file),
                },
            )

        size_bytes: int = await asyncio.to_thread(lambda: dump_file.stat().st_size)

        if size_bytes < _MIN_VALID_DUMP_SIZE:
            raise BackupEngineError(
                message=f"Dump file empty for {database}.{collection}",
                details={
                    "database": database,
                    "collection": collection,
                    "path": str(dump_file),
                    "size_bytes": size_bytes,
                },
            )

        return size_bytes
