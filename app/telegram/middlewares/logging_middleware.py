"""Global logging middleware.

Emits a structured log entry for every incoming update so that operations
can be traced by ``update_id``, ``user_id``, ``chat_id`` and ``topic_id``.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.infrastructure.logging.structured_logger import get_logger
from app.telegram.middlewares._utils import extract_context


class LoggingMiddleware(BaseMiddleware):
    """Logs every incoming update with correlation context."""

    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        ctx = extract_context(event)
        self._logger.info(
            "telegram_update_received",
            update_id=ctx.update_id,
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            topic_id=ctx.topic_id,
        )
        return await handler(event, data)
