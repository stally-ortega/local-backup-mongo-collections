"""Audit-log middleware.

Records every handled action to the audit trail **after** the handler
finishes.  Both successful executions and unhandled exceptions (caught by the
outer :class:`ErrorHandlerMiddleware`) are persisted with command, user,
topic, timestamp and elapsed duration.
"""

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.services.audit_service import AuditService
from app.domain.entities.user import User
from app.infrastructure.logging.structured_logger import get_logger
from app.infrastructure.persistence.sql_audit_repository import SQLAuditRepository
from app.telegram.middlewares._utils import extract_command, extract_context, resolve_topic


class AuditMiddleware(BaseMiddleware):
    """Logs the action result after the handler runs."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        audit_service: AuditService | None = None,
        config: Any | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._audit_service = audit_service
        self._config = config
        self._logger = get_logger(__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if self._session_factory is None:
            return await handler(event, data)

        user = data.get("user")
        if not isinstance(user, User):
            # Auth did not inject a user → nothing to audit.
            return await handler(event, data)

        ctx = extract_context(event)
        topic = resolve_topic(ctx.topic_id, self._config) if self._config else "GENERAL"
        command = extract_command(event)

        start = time.monotonic()
        error: Exception | None = None
        result = "SUCCESS"

        try:
            return await handler(event, data)
        except Exception as exc:
            error = exc
            result = f"ERROR: {type(exc).__name__}"
            raise
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            await self._persist(
                user=user,
                topic=topic,
                command=command,
                result=result,
                duration_ms=duration_ms,
                error=error,
                topic_id=ctx.topic_id,
            )

    async def _persist(
        self,
        *,
        user: User,
        topic: str,
        command: str | None,
        result: str,
        duration_ms: int,
        error: Exception | None,
        topic_id: int | None,
    ) -> None:
        if self._session_factory is None:
            return
        async with self._session_factory() as session:
            service = self._audit_service or AuditService(SQLAuditRepository(session))
            try:
                await service.log_action(
                    action="TELEGRAM_INTERACTION",
                    user=user,
                    topic=topic,
                    command=command,
                    result=result,
                    duration_ms=duration_ms,
                    context={
                        "error_message": str(error) if error else None,
                        "topic_id": topic_id,
                    },
                )
                await session.commit()
            except Exception as audit_exc:
                self._logger.error(
                    "failed_to_write_audit_log",
                    exc_info=audit_exc,
                    user_id=user.telegram_id,
                )
