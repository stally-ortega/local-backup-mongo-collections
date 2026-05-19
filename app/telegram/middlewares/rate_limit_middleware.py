"""Rate-limiting middleware.

Throttles actions per user inside a sliding time window backed by either
:class:`~app.infrastructure.queue.redis_rate_limit_repository.RedisRateLimitRepository`
(when Redis is available) or
:class:`~app.infrastructure.persistence.sql_rate_limit_repository.SQLRateLimitRepository`
as a fallback.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import AppConfig
from app.infrastructure.logging.structured_logger import get_logger
from app.infrastructure.persistence.sql_rate_limit_repository import SQLRateLimitRepository
from app.infrastructure.queue.redis_rate_limit_repository import RedisRateLimitRepository
from app.telegram.middlewares._utils import extract_command, extract_context, safe_send_message


class RateLimitMiddleware(BaseMiddleware):
    """Applies rate limits per user and action.

    Parameters
    ----------
    session_factory:
        SQLAlchemy async session maker.  Required when *redis_async_client* is
        ``None`` so that the SQL fallback can be used.
    config:
        Application settings containing rate-limit thresholds.
    redis_async_client:
        Optional async Redis client.  When provided, rate-limit counters are
        stored in Redis with automatic TTL expiration.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        config: AppConfig | None = None,
        redis_async_client: aioredis.Redis | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._config = config
        self._redis_async_client = redis_async_client
        self._logger = get_logger(__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if self._config is None:
            return await handler(event, data)

        # RateLimitMiddleware runs BEFORE AuthMiddleware in the global stack,
        # so data["user"] does not exist yet. Extract the telegram_id from the
        # raw aiogram user injected by the dispatcher into data["event_from_user"].
        event_user = data.get("event_from_user")
        if event_user is not None:
            user_id: int | None = event_user.id
        else:
            ctx = extract_context(event)
            user_id = ctx.user_id

        if user_id is None:
            # System events or webhooks without a user – skip rate limiting.
            return await handler(event, data)

        command = extract_command(event)
        action = command or "GENERIC"

        # Prefer Redis when available; otherwise fall back to SQL.
        if self._redis_async_client is not None:
            allowed = await self._check_with_redis(user_id, action)
            if not allowed:
                ctx = extract_context(event)
                await self._reply_throttled(ctx, data)
                return None
            await self._increment_with_redis(user_id, action)
        else:
            if self._session_factory is None:
                return await handler(event, data)

            async with self._session_factory() as session:
                repo = SQLRateLimitRepository(session)

                allowed = await repo.check_limit(
                    user_id,
                    action,
                    max_allowed=self._config.rate_limit_max_requests,
                    window_seconds=self._config.rate_limit_window_seconds,
                )

                if not allowed:
                    ctx = extract_context(event)
                    await self._reply_throttled(ctx, data)
                    return None

                await repo.increment(
                    user_id,
                    action,
                    window_seconds=self._config.rate_limit_window_seconds,
                )

        return await handler(event, data)

    async def _check_with_redis(self, telegram_id: int, action: str) -> bool:
        if self._redis_async_client is None or self._config is None:
            raise RuntimeError("Redis rate limiter not configured")
        repo = RedisRateLimitRepository(self._redis_async_client)
        return await repo.check_limit(
            telegram_id,
            action,
            max_allowed=self._config.rate_limit_max_requests,
            window_seconds=self._config.rate_limit_window_seconds,
        )

    async def _increment_with_redis(self, telegram_id: int, action: str) -> int:
        if self._redis_async_client is None or self._config is None:
            raise RuntimeError("Redis rate limiter not configured")
        repo = RedisRateLimitRepository(self._redis_async_client)
        return await repo.increment(
            telegram_id,
            action,
            window_seconds=self._config.rate_limit_window_seconds,
        )

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
