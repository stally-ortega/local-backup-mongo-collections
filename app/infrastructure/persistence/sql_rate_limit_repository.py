"""SQLAlchemy implementation of :class:`~app.domain.repositories.repositories.IRateLimitRepository`.

Maps between :class:`~app.domain.entities.rate_limit.RateLimit` (domain entity) and
:class:`~app.infrastructure.persistence.models.rate_limit.RateLimitORM` (SQLAlchemy model).
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.repositories.repositories import IRateLimitRepository
from app.infrastructure.persistence.models.rate_limit import RateLimitORM


class SQLRateLimitRepository(IRateLimitRepository):
    """Async SQLAlchemy adapter for rate-limit persistence.

    Parameters
    ----------
    session:
        An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.  The caller is
        responsible for commit/rollback lifecycle.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def check_limit(
        self,
        telegram_id: int,
        action: str,
        max_allowed: int,
        window_seconds: int,
    ) -> bool:
        """Return ``True`` when the user has not exceeded the rate limit."""
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=window_seconds)

        result = await self._session.execute(
            select(RateLimitORM)
            .where(RateLimitORM.telegram_id == telegram_id)
            .where(RateLimitORM.action == action)
            .where(RateLimitORM.window_start >= window_start)
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            return True
        return orm.count < max_allowed

    async def increment(
        self,
        telegram_id: int,
        action: str,
        window_seconds: int,
    ) -> int:
        """Bump the counter and return the new value.

        Creates a fresh window row when the previous one has expired.
        """
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=window_seconds)

        result = await self._session.execute(
            select(RateLimitORM)
            .where(RateLimitORM.telegram_id == telegram_id)
            .where(RateLimitORM.action == action)
            .where(RateLimitORM.window_start >= window_start)
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            orm = RateLimitORM(
                telegram_id=telegram_id,
                action=action,
                window_start=now,
                count=1,
            )
            self._session.add(orm)
        else:
            orm.count += 1
        await self._session.flush()
        return orm.count

    async def reset(self, telegram_id: int, action: str) -> None:
        """Zero out the counter for the given user and action."""
        await self._session.execute(
            delete(RateLimitORM)
            .where(RateLimitORM.telegram_id == telegram_id)
            .where(RateLimitORM.action == action)
        )
