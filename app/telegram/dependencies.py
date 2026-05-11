"""Dependency wiring for the Telegram interface layer.

Provides a concrete dependency container and a router-level middleware
so that FSM handlers can access application services without global state.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.ports import IFsUtils, IJobQueue, IMongoMetadata
from app.application.services.audit_service import AuditService
from app.application.services.job_manager import JobManager
from app.application.services.permission_service import PermissionService
from app.application.services.size_query_service import SizeQueryService
from app.application.use_cases.query_size import QuerySizeUseCase
from app.application.use_cases.request_backup import RequestBackupUseCase
from app.config import AppConfig
from app.infrastructure.filesystem.aio_fs_utils import AioFsUtils
from app.infrastructure.mongo.mongo_connection import MongoConnection
from app.infrastructure.mongo.mongo_metadata_adapter import MongoMetadataAdapter
from app.infrastructure.persistence.sql_audit_repository import SQLAuditRepository
from app.infrastructure.persistence.sql_job_repository import SQLJobRepository
from app.infrastructure.persistence.sql_rate_limit_repository import SQLRateLimitRepository
from app.infrastructure.queue.redis_connection import RedisConnection
from app.infrastructure.queue.rq_job_queue import RQJobQueue


@dataclass(frozen=True)
class TelegramDependencies:
    """All out-ports required by Telegram FSM handlers.

    Attributes
    ----------
    config:
        Validated application settings.
    session_factory:
        SQLAlchemy async session maker.  Handlers open a transactional
        scope, flush, and commit on success.
    mongo_metadata:
        Port for database / collection introspection.
    mongo_connection:
        Underlying Motor connection (kept open for the bot lifetime).
    redis_connection:
        Underlying Redis connection (kept open for RQ enqueueing).
    aioredis_client:
        Async Redis client for FSM timeout tracking.
    fs_utils:
        Async filesystem adapter.
    permission_service:
        RBAC evaluator.
    """

    config: AppConfig
    session_factory: async_sessionmaker[AsyncSession]
    mongo_metadata: IMongoMetadata
    mongo_connection: MongoConnection
    redis_connection: RedisConnection
    aioredis_client: aioredis.Redis
    fs_utils: IFsUtils
    permission_service: PermissionService


class DependencyInjectionMiddleware(BaseMiddleware):
    """Injects :class:`TelegramDependencies` into ``data['telegram_deps']``."""

    def __init__(self, deps: TelegramDependencies) -> None:
        self._deps = deps

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["telegram_deps"] = self._deps
        return await handler(event, data)


def build_telegram_dependencies(
    config: AppConfig,
    session_factory: async_sessionmaker[AsyncSession],
) -> TelegramDependencies:
    """Wire every out-port needed by Telegram handlers.

    .. note::
        This function calls ``connect()`` on both MongoDB and Redis
        connections.  Callers are responsible for graceful ``close()``
        during shutdown.
    """
    mongo_conn = MongoConnection.from_config(config)
    mongo_conn.connect()
    mongo_meta: IMongoMetadata = MongoMetadataAdapter(mongo_conn)

    redis_conn = RedisConnection.from_config(config)
    redis_conn.connect()

    aioredis_client = aioredis.Redis.from_url(config.redis_url)

    fs_utils: IFsUtils = AioFsUtils()
    perms = PermissionService()

    return TelegramDependencies(
        config=config,
        session_factory=session_factory,
        mongo_metadata=mongo_meta,
        mongo_connection=mongo_conn,
        redis_connection=redis_conn,
        aioredis_client=aioredis_client,
        fs_utils=fs_utils,
        permission_service=perms,
    )


def build_request_backup_use_case(
    deps: TelegramDependencies,
    session: AsyncSession,
) -> RequestBackupUseCase:
    """Assemble a :class:`RequestBackupUseCase` wired to SQL persistence.

    Each invocation creates fresh repository instances tied to *session*.
    """
    rate_limit_repo = SQLRateLimitRepository(session)
    audit_repo = SQLAuditRepository(session)
    audit_svc = AuditService(audit_repo)
    job_repo = SQLJobRepository(session)
    job_queue: IJobQueue = RQJobQueue(deps.redis_connection)
    job_manager = JobManager(
        job_repository=job_repo,
        job_queue=job_queue,
        permission_service=deps.permission_service,
        audit_service=audit_svc,
    )
    return RequestBackupUseCase(
        permission_service=deps.permission_service,
        rate_limit_repo=rate_limit_repo,
        fs_utils=deps.fs_utils,
        job_manager=job_manager,
        audit_service=audit_svc,
        backup_base_path=deps.config.backup_base_path,
        max_backup_rate=deps.config.rate_limit_max_requests,
        backup_rate_window=deps.config.rate_limit_window_seconds,
        min_free_disk_bytes=1_073_741_824,
    )


def build_query_size_use_case(
    deps: TelegramDependencies,
    session: AsyncSession,
) -> QuerySizeUseCase:
    """Assemble a :class:`QuerySizeUseCase` wired to SQL persistence."""
    audit_repo = SQLAuditRepository(session)
    audit_svc = AuditService(audit_repo)
    size_query_svc = SizeQueryService(deps.mongo_metadata)
    return QuerySizeUseCase(
        size_query_service=size_query_svc,
        audit_service=audit_svc,
    )
