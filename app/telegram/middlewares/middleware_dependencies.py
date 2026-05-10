"""Dependency container for the Telegram middleware stack.

Provides a single immutable dataclass that carries every out-port required by
middlewares (repositories, services, configuration).  This keeps
:func:`~app.telegram.middlewares.get_global_middlewares` testable and free of
global state.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.services.audit_service import AuditService
from app.application.services.permission_service import PermissionService
from app.config import AppConfig


@dataclass(frozen=True)
class MiddlewareDependencies:
    """All dependencies needed to construct the production middleware stack.

    Attributes
    ----------
    config:
        Validated application settings (topics, rate limits, chat id).
    session_factory:
        SQLAlchemy async session maker.  Each middleware opens its own
        transactional scope so that failures in one layer do not leak
        into another.
    permission_service:
        Optional RBAC evaluator.  When absent, :class:`RoleMiddleware` falls
        back to the default matrix embedded in :class:`~app.domain.entities.user.User`.
    audit_service:
        Optional audit facade.  When absent, middlewares that need auditing
        instantiate one on-the-fly from the session.
    """

    config: AppConfig
    session_factory: async_sessionmaker[AsyncSession]
    permission_service: PermissionService | None = None
    audit_service: AuditService | None = None
