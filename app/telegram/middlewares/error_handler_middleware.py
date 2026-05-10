"""Global error-handler middleware.

Catches unhandled exceptions and forwards them to the EXECUTION_ERRORS topic.
Full implementation in Tarea 5.2.2.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class ErrorHandlerMiddleware(BaseMiddleware):
    """Placeholder: catches exceptions around handlers."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        return await handler(event, data)
