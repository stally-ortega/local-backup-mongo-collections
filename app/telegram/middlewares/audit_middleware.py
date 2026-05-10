"""Audit-log middleware.

Records every handled action to the audit log after the handler finishes.
Full implementation in Tarea 5.2.7.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class AuditMiddleware(BaseMiddleware):
    """Placeholder: logs the action result after the handler runs."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        return await handler(event, data)
