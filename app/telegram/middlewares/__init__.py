"""Telegram middleware exports."""

from aiogram import BaseMiddleware

from app.telegram.middlewares.audit_middleware import AuditMiddleware
from app.telegram.middlewares.auth_middleware import AuthMiddleware
from app.telegram.middlewares.error_handler_middleware import ErrorHandlerMiddleware
from app.telegram.middlewares.logging_middleware import LoggingMiddleware
from app.telegram.middlewares.rate_limit_middleware import RateLimitMiddleware
from app.telegram.middlewares.role_middleware import RoleMiddleware
from app.telegram.middlewares.topic_filter_middleware import TopicFilterMiddleware

__all__ = ["get_global_middlewares"]


_middlewares: list[BaseMiddleware] | None = None


def get_global_middlewares() -> list[BaseMiddleware]:
    """Return the global middleware stack in execution order.

    Lazily initialised so that middleware objects are not created at import
    time, which simplifies patching during tests.

    Order (outer → inner):
    1. LoggingMiddleware
    2. ErrorHandlerMiddleware
    3. TopicFilterMiddleware
    4. AuthMiddleware
    5. RoleMiddleware
    6. RateLimitMiddleware
    7. AuditMiddleware
    """
    global _middlewares
    if _middlewares is None:
        _middlewares = [
            LoggingMiddleware(),
            ErrorHandlerMiddleware(),
            TopicFilterMiddleware(),
            AuthMiddleware(),
            RoleMiddleware(),
            RateLimitMiddleware(),
            AuditMiddleware(),
        ]
    return _middlewares
