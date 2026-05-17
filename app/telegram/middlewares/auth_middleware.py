"""Authentication / whitelist middleware.

Extracts the sender's ``telegram_id``, queries the user repository, and
injects the :class:`~app.domain.entities.user.User` instance into
``data["user"]`` when the user is registered and active.

Unrecognised senders receive a ``"No autorizado"`` reply and an
``AUTH_DENIED`` audit entry.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.services.audit_service import AuditService
from app.config import AppConfig
from app.domain.entities.user import User
from app.domain.value_objects.enums import UserRole
from app.infrastructure.logging.structured_logger import get_logger
from app.infrastructure.persistence.sql_audit_repository import SQLAuditRepository
from app.infrastructure.persistence.sql_user_repository import SQLUserRepository
from app.telegram.middlewares._utils import (
    extract_context,
    resolve_topic,
    safe_send_message,
)


class AuthMiddleware(BaseMiddleware):
    """Validates whitelist and injects user context."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        audit_service: AuditService | None = None,
        config: AppConfig | None = None,
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
            return None

        ctx = extract_context(event)
        if ctx.user_id is None:
            self._logger.warning("missing_user_id_in_event", update_id=ctx.update_id)
            return None

        async with self._session_factory() as session:
            user_repo = SQLUserRepository(session)
            user = await user_repo.get_by_telegram_id(ctx.user_id)

            if user is None or not user.is_active:
                await self._reply_unauthorized(ctx, data)
                await self._log_denied(session, ctx)
                await session.commit()
                return None

            data["user"] = user
            await session.commit()

        return await handler(event, data)

    async def _reply_unauthorized(
        self,
        ctx: Any,
        data: dict[str, Any],
    ) -> None:
        if ctx.chat_id is not None:
            await safe_send_message(
                data,
                chat_id=ctx.chat_id,
                text="No autorizado",
                topic_id=ctx.topic_id,
            )

    async def _log_denied(
        self,
        session: AsyncSession,
        ctx: Any,
    ) -> None:
        service = self._audit_service or AuditService(SQLAuditRepository(session))
        # Build a transient anonymous user so the audit port stays happy.
        anonymous = User(
            telegram_id=ctx.user_id,
            username="unknown",
            role=UserRole.READONLY,
            is_active=False,
        )
        topic = resolve_topic(ctx.topic_id, self._config) if self._config is not None else "GENERAL"
        await service.log_action(
            action="AUTH_DENIED",
            user=anonymous,
            topic=topic,
            result="DENIED",
        )
