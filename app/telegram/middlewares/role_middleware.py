"""Role-based access control (RBAC) middleware.

Validates that the user's role permits the requested command.
Full implementation in Tarea 5.2.5.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class RoleMiddleware(BaseMiddleware):
    """Placeholder: validates RBAC matrix for the current command."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        return await handler(event, data)
