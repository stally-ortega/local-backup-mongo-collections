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
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from rq import Worker

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
from app.infrastructure.notifier.telegram_notifier import TelegramNotifier
from app.infrastructure.persistence.database import (
    create_engine,
    create_session_factory,
    dispose_engine,
)
from app.infrastructure.persistence.sql_audit_repository import SQLAuditRepository
from app.infrastructure.persistence.sql_job_repository import SQLJobRepository
from app.infrastructure.queue.redis_connection import RedisConnection
from app.infrastructure.queue.redis_lock_manager import RedisLockManager
from app.infrastructure.telegram.aiogram_bot import AiogramBot

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


async def _execute(job_id: str, payload: dict[str, Any] | None = None) -> None:
    """Build the dependency graph and run the backup use case."""
    config = AppConfig()
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
            import redis.asyncio as aioredis

            mongo_conn = MongoConnection.from_config(config)
            mongo_conn.connect()
            redis_conn = RedisConnection.from_config(config)
            redis_conn.connect()
            aioredis_client = aioredis.Redis.from_url(config.redis_url)

            aiogram_bot = AiogramBot.from_config(config)
            aiogram_bot.start()
            try:
                backup_engine = MongodumpBackupEngine(config.mongodb_uri)
                mongo_metadata = MongoMetadataAdapter(mongo_conn)
                notifier = TelegramNotifier(
                    aiogram_bot,
                    base_path=config.backup_base_path,
                )
                retention_manager = RetentionManager(
                    fs_utils=fs_utils,
                    backup_base_path=config.backup_base_path,
                    retention_full_weeks=config.retention_full_weeks,
                    retention_custom_weeks=config.retention_custom_weeks,
                    retention_max_gb=config.retention_max_gb,
                )
                lock_manager = RedisLockManager(aioredis_client)

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

                payload = payload or {}
                dto = ExecuteBackupDto(
                    job_id=job_id,
                    chat_id=payload.get("chat_id"),
                    topic_id=payload.get("topic_id"),
                    status_message_id=payload.get("status_message_id"),
                    correlation_id=payload.get("correlation_id"),
                )
                try:
                    await use_case.execute(dto, cancel_check=_cancel_check)
                except Exception:
                    # A. Update the original status message so the UI is not left hanging.
                    if dto.chat_id is not None and dto.status_message_id is not None:
                        with suppress(Exception):
                            await notifier.edit_message(
                                chat_id=dto.chat_id,
                                message_id=dto.status_message_id,
                                text="❌ FAILED: Error interno en el worker",
                            )

                    # B. Notify execution-errors topic with a generic message.
                    # Full traceback is logged internally via correlation_id.
                    logger.exception("Backup execution failed for job %s", job_id)
                    try:
                        await notifier.send_message(
                            chat_id=int(config.telegram_chat_id),
                            text=(
                                f"🚨 Worker Error\n"
                                f"Job: {job_id}\n"
                                f"Consulta los logs (correlation_id={job_id}) para detalles."
                            ),
                            topic_id=config.topic_execution_errors,
                        )
                    except Exception as inner_e:
                        logger.error(
                            "No se pudo enviar la alerta a Telegram: %s",
                            inner_e,
                        )
                    raise
            finally:
                mongo_conn.close()
                redis_conn.close()
                await aioredis_client.close()
                await aiogram_bot.shutdown()
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
        asyncio.run(_execute(job_id, payload))
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


if __name__ == "__main__":
    from pathlib import Path

    import redis as sync_redis
    from rq.serializers import JSONSerializer

    from app.infrastructure.logging.structured_logger import configure_logging

    config = AppConfig()
    configure_logging(log_dir=Path("logs"), level=config.log_level)

    logger.info("Connecting to Redis at %s for RQ worker", config.redis_url)
    redis_client = sync_redis.from_url(config.redis_url)  # type: ignore[no-untyped-call,unused-ignore]

    logger.info("Starting RQ worker on queue 'default'...")
    worker = Worker(
        queues=["default"],
        connection=redis_client,
        name="mongo_ops_backup_worker",
        serializer=JSONSerializer,
    )
    worker.work(with_scheduler=True)
