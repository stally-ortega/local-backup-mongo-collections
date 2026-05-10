"""Topic filter middleware.

Rejects messages that do not belong to a recognised topic.
Full implementation in Tarea 5.2.3.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class TopicFilterMiddleware(BaseMiddleware):
    """Placeholder: validates ``message_thread_id`` against configured topics."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        return await handler(event, data)
