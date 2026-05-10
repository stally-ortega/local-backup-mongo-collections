"""Authentication / whitelist middleware.

Injects the :class:`~app.domain.entities.user.User` into ``data["user"]``
if the telegram_id exists in the whitelist.
Full implementation in Tarea 5.2.4.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class AuthMiddleware(BaseMiddleware):
    """Placeholder: validates whitelist and injects user context."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        return await handler(event, data)
