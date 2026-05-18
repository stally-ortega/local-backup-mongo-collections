"""Role-based access control (RBAC) middleware.

Validates that the authenticated user's role permits the requested command
inside the current topic.  Violations receive a ``"Permisos insuficientes"``
reply and an ``PERMISSION_DENIED`` audit entry.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.services.audit_service import AuditService
from app.application.services.permission_service import PermissionService
from app.config import AppConfig
from app.domain.entities.user import User
from app.infrastructure.logging.structured_logger import get_logger
from app.infrastructure.persistence.sql_audit_repository import SQLAuditRepository
from app.telegram.middlewares._utils import (
    extract_command,
    extract_context,
    resolve_topic,
    safe_send_message,
)


class RoleMiddleware(BaseMiddleware):
    """Validates RBAC matrix for the current command."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        permission_service: PermissionService | None = None,
        config: AppConfig | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._permission_service = permission_service or PermissionService()
        self._config = config
        self._audit_service = audit_service
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
        self._logger.info(
            "-> RoleMiddleware evaluando a user_id=%s con rol=%s",
            getattr(user, "telegram_id", "None"),
            getattr(user, "role", "None"),
        )
        if not isinstance(user, User):
            # No authenticated user injected by AuthMiddleware.
            # Allow the handler to deal with it (e.g. system events, webhooks).
            return await handler(event, data)

        ctx = extract_context(event)
        command = extract_command(event)
        topic = resolve_topic(ctx.topic_id, self._config) if self._config else "GENERAL"

        # When no command can be inferred we allow the interaction; FSM
        # callbacks or plain text fall through to the handler which may
        # enforce its own finer-grained checks.
        if command is None:
            return await handler(event, data)

        if not self._permission_service.can_execute(user, command, topic):
            await self._reply_forbidden(ctx, data)
            await self._log_denied(
                session_factory=self._session_factory,
                ctx=ctx,
                user=user,
                command=command,
                topic=topic,
            )
            return None

        return await handler(event, data)

    async def _reply_forbidden(self, ctx: Any, data: dict[str, Any]) -> None:
        if ctx.chat_id is not None:
            await safe_send_message(
                data,
                chat_id=ctx.chat_id,
                text="Permisos insuficientes",
                topic_id=ctx.topic_id,
            )

    async def _log_denied(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        ctx: Any,
        user: User,
        command: str,
        topic: str,
    ) -> None:
        async with session_factory() as session:
            service = self._audit_service or AuditService(SQLAuditRepository(session))
            await service.log_action(
                action="PERMISSION_DENIED",
                user=user,
                topic=topic,
                command=command,
                result="DENIED",
            )
