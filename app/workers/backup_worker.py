"""RQ worker that executes backup jobs by bridging sync RQ to async use cases.

When RQ forks a worker process it calls :func:`_backup_worker_fn`.
That function sets up structured logging (correlation_id), wires the full
dependency graph, and runs :class:`ExecuteBackupUseCase` inside an
``asyncio`` event loop.

SIGTERM handling is cooperative: a signal handler sets a module-level flag
that is polled by the use case via ``cancel_check`` between collection
backups.
"""

import asyncio
import logging
import signal
from typing import TYPE_CHECKING, Any

from app.application.dtos import ExecuteBackupDto
from app.application.services.audit_service import AuditService
from app.application.services.retention_manager import RetentionManager
from app.application.use_cases.execute_backup import ExecuteBackupUseCase
from app.config import AppConfig
from app.infrastructure.backup.mongodump_engine import MongodumpBackupEngine

if TYPE_CHECKING:
    from app.domain.repositories.repositories import IAuditRepository, IJobRepository
from app.infrastructure.filesystem.aio_fs_utils import AioFsUtils
from app.infrastructure.logging import clear_correlation_id, set_correlation_id
from app.infrastructure.mongo.mongo_connection import MongoConnection
from app.infrastructure.mongo.mongo_metadata_adapter import MongoMetadataAdapter
from app.infrastructure.notifier.logging_notifier import LoggingNotifier
from app.infrastructure.persistence.database import (
    create_engine,
    create_session_factory,
    dispose_engine,
)
from app.infrastructure.persistence.sql_audit_repository import SQLAuditRepository
from app.infrastructure.persistence.sql_job_repository import SQLJobRepository
from app.infrastructure.queue.redis_connection import RedisConnection
from app.infrastructure.queue.redis_lock_manager import RedisLockManager

logger = logging.getLogger(__name__)

# Module-level flag set by SIGTERM handler for cooperative shutdown.
_shutdown_requested: bool = False


def _handle_sigterm(signum: int, _frame: Any) -> None:
    """Set the shutdown flag so the running job can abort gracefully."""
    global _shutdown_requested
    _shutdown_requested = True
    logger.warning("SIGTERM received; requesting graceful shutdown")


async def _cancel_check() -> bool:
    """Return ``True`` when a shutdown has been requested."""
    return _shutdown_requested


async def _execute(job_id: str) -> None:
    """Build the dependency graph and run the backup use case."""
    config = AppConfig()  # type: ignore[call-arg]
    engine = await create_engine(config)

    try:
        session_factory = await create_session_factory(engine)
        async with session_factory() as session:
            # Repositories
            job_repo: IJobRepository = SQLJobRepository(session)
            audit_repo: IAuditRepository = SQLAuditRepository(session)

            # Services
            audit_service = AuditService(repository=audit_repo)
            fs_utils = AioFsUtils()

            # Infrastructure adapters
            mongo_conn = MongoConnection.from_config(config)
            mongo_conn.connect()
            redis_conn = RedisConnection.from_config(config)
            redis_conn.connect()
            try:
                backup_engine = MongodumpBackupEngine(config.mongodb_uri)
                mongo_metadata = MongoMetadataAdapter(mongo_conn)
                notifier = LoggingNotifier()
                retention_manager = RetentionManager(
                    fs_utils=fs_utils,
                    backup_base_path=config.backup_base_path,
                    retention_full_weeks=config.retention_full_weeks,
                    retention_custom_weeks=config.retention_custom_weeks,
                    retention_max_gb=config.retention_max_gb,
                )
                lock_manager = RedisLockManager(redis_conn)

                use_case = ExecuteBackupUseCase(
                    job_repository=job_repo,
                    backup_engine=backup_engine,
                    mongo_metadata=mongo_metadata,
                    audit_service=audit_service,
                    notifier=notifier,
                    retention_manager=retention_manager,
                    fs_utils=fs_utils,
                    lock_manager=lock_manager,
                    backup_base_path=config.backup_base_path,
                )

                dto = ExecuteBackupDto(job_id=job_id)
                await use_case.execute(dto, cancel_check=_cancel_check)
            finally:
                mongo_conn.close()
                redis_conn.close()
    finally:
        await dispose_engine(engine)


def _backup_worker_fn(
    job_id: str,
    job_type: str = "backup",
    payload: dict[str, Any] | None = None,
) -> None:
    """Entry point invoked by the RQ worker process.

    Parameters
    ----------
    job_id:
        The platform job identifier to execute.
    job_type:
        Discriminator forwarded by the queue (unused at present).
    payload:
        Additional metadata forwarded by the queue (unused at present).
    """
    _ = job_type, payload  # reserved for future use

    # Register SIGTERM handler for graceful shutdown.
    signal.signal(signal.SIGTERM, _handle_sigterm)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, _handle_sigterm)

    set_correlation_id(job_id)
    logger.info("Backup worker started for job %s", job_id)

    try:
        asyncio.run(_execute(job_id))
    except Exception:
        logger.exception("Backup worker failed for job %s", job_id)
        raise
    finally:
        logger.info("Backup worker finished for job %s", job_id)
        clear_correlation_id()
        # Reset the shutdown flag so the next job in the same worker
        # process starts with a clean slate.
        global _shutdown_requested
        _shutdown_requested = False
