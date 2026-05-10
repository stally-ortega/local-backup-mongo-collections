"""Rate-limiting middleware.

Throttles actions per user inside a sliding time window backed by
:class:`~app.domain.repositories.repositories.IRateLimitRepository`.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import AppConfig
from app.domain.entities.user import User
from app.infrastructure.logging.structured_logger import get_logger
from app.infrastructure.persistence.sql_rate_limit_repository import SQLRateLimitRepository
from app.telegram.middlewares._utils import extract_command, extract_context, safe_send_message


class RateLimitMiddleware(BaseMiddleware):
    """Applies rate limits per user and action."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        config: AppConfig | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._config = config
        self._logger = get_logger(__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if self._session_factory is None or self._config is None:
            return await handler(event, data)

        user = data.get("user")
        if not isinstance(user, User):
            self._logger.warning("rate_limit_missing_user", event_type=type(event).__name__)
            return None

        command = extract_command(event)
        action = command or "GENERIC"

        async with self._session_factory() as session:
            repo = SQLRateLimitRepository(session)

            allowed = await repo.check_limit(
                user.telegram_id,
                action,
                max_allowed=self._config.rate_limit_max_requests,
                window_seconds=self._config.rate_limit_window_seconds,
            )

            if not allowed:
                ctx = extract_context(event)
                await self._reply_throttled(ctx, data)
                await session.commit()
                return None

            await repo.increment(
                user.telegram_id,
                action,
                window_seconds=self._config.rate_limit_window_seconds,
            )
            await session.commit()

        return await handler(event, data)

    async def _reply_throttled(self, ctx: Any, data: dict[str, Any]) -> None:
        if ctx.chat_id is not None and self._config is not None:
            await safe_send_message(
                data,
                chat_id=ctx.chat_id,
                text=(
                    f"Rate limit excedido, espere {self._config.rate_limit_window_seconds} segundos"
                ),
                topic_id=ctx.topic_id,
            )
