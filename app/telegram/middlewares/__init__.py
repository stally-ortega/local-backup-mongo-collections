"""Telegram middleware exports.

The global stack follows the execution order defined in the work-plan
(Tarea 5.2.x):

1. LoggingMiddleware – structured trace of every update.
2. ErrorHandlerMiddleware – catch-all exception boundary.
3. TopicFilterMiddleware – validates ``message_thread_id``.
4. AuthMiddleware – whitelist check + injects ``data["user"]``.
5. RoleMiddleware – RBAC matrix validation.
6. RateLimitMiddleware – sliding-window throttling.
7. AuditMiddleware – post-handler audit persistence.

Dependencies are injected via :class:`MiddlewareDependencies` so that
middlewares remain testable and free of global state.
"""

from aiogram import BaseMiddleware

from app.telegram.middlewares.audit_middleware import AuditMiddleware
from app.telegram.middlewares.auth_middleware import AuthMiddleware
from app.telegram.middlewares.error_handler_middleware import ErrorHandlerMiddleware
from app.telegram.middlewares.logging_middleware import LoggingMiddleware
from app.telegram.middlewares.middleware_dependencies import MiddlewareDependencies
from app.telegram.middlewares.rate_limit_middleware import RateLimitMiddleware
from app.telegram.middlewares.role_middleware import RoleMiddleware
from app.telegram.middlewares.topic_filter_middleware import TopicFilterMiddleware

__all__ = [
    "get_global_middlewares",
    "MiddlewareDependencies",
    "LoggingMiddleware",
    "ErrorHandlerMiddleware",
    "TopicFilterMiddleware",
    "AuthMiddleware",
    "RoleMiddleware",
    "RateLimitMiddleware",
    "AuditMiddleware",
]


def get_global_middlewares(
    deps: MiddlewareDependencies | None = None,
) -> list[BaseMiddleware]:
    """Return the global middleware stack in execution order.

    Parameters
    ----------
    deps:
        Optional dependency container.  When provided every middleware
        receives its required ports; when ``None`` DB-dependent middlewares
        fall back to pass-through behaviour so that basic dispatcher tests
        do not need a database.

    Returns
    -------
    List of aiogram ``BaseMiddleware`` instances ready for
    ``Dispatcher.update.outer_middleware()``.
    """
    session_factory = deps.session_factory if deps is not None else None
    config = deps.config if deps is not None else None
    permission_service = deps.permission_service if deps is not None else None
    audit_service = deps.audit_service if deps is not None else None

    return [
        LoggingMiddleware(),
        ErrorHandlerMiddleware(config=config),
        TopicFilterMiddleware(config=config),
        AuthMiddleware(
            session_factory=session_factory,
            audit_service=audit_service,
            config=config,
        ),
        RoleMiddleware(
            session_factory=session_factory,
            permission_service=permission_service,
            config=config,
            audit_service=audit_service,
        ),
        RateLimitMiddleware(
            session_factory=session_factory,
            config=config,
        ),
        AuditMiddleware(
            session_factory=session_factory,
            audit_service=audit_service,
        ),
    ]
