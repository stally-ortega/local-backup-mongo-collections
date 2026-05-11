"""SQLAlchemy implementation of :class:`~app.domain.repositories.repositories.IUserRepository`.

Maps between :class:`~app.domain.entities.user.User` (domain entity) and
:class:`~app.infrastructure.persistence.models.user.UserORM` (SQLAlchemy model).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.user import User
from app.domain.repositories.repositories import IUserRepository
from app.domain.value_objects.enums import UserRole
from app.infrastructure.persistence.models.user import UserORM


class SQLUserRepository(IUserRepository):
    """Async SQLAlchemy adapter for user persistence.

    Parameters
    ----------
    session:
        An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.  The caller is
        responsible for commit/rollback lifecycle (typically managed by a
        unit-of-work or FastAPI dependency).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        """Fetch a user by Telegram ID or return ``None``."""
        result = await self._session.execute(
            select(UserORM).where(UserORM.telegram_id == telegram_id)
        )
        orm = result.scalar_one_or_none()
        return self._to_entity(orm) if orm else None

    async def list_all(self) -> list[User]:
        """Return every registered user ordered by creation time."""
        result = await self._session.execute(select(UserORM).order_by(UserORM.created_at))
        return [self._to_entity(row) for row in result.scalars().all()]

    async def save(self, user: User) -> None:
        """Persist *user*, updating an existing row when the Telegram ID already exists."""
        existing = await self._session.execute(
            select(UserORM).where(UserORM.telegram_id == user.telegram_id)
        )
        orm = existing.scalar_one_or_none()

        if orm is None:
            self._session.add(self._to_orm(user))
        else:
            orm.username = user.username
            orm.role = user.role.value
            orm.is_active = user.is_active
            orm.updated_at = user.created_at  # best-effort sync; DB onupdate wins
            await self._session.flush()

    async def update_role(self, telegram_id: int, role: UserRole) -> User | None:
        """Change the role of the user identified by *telegram_id*.

        Returns the updated domain entity, or ``None`` when no user matches.
        """
        result = await self._session.execute(
            select(UserORM).where(UserORM.telegram_id == telegram_id)
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            return None

        orm.role = role.value
        await self._session.flush()

        return self._to_entity(orm)

    async def toggle_active(self, telegram_id: int) -> User | None:
        """Flip the ``is_active`` flag of the user identified by *telegram_id*."""
        result = await self._session.execute(
            select(UserORM).where(UserORM.telegram_id == telegram_id)
        )
        orm = result.scalar_one_or_none()
        if orm is None:
            return None

        orm.is_active = not orm.is_active
        await self._session.flush()

        return self._to_entity(orm)

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_entity(orm: UserORM) -> User:
        """Map an ORM row to the domain :class:`User`."""
        return User(
            telegram_id=orm.telegram_id,
            username=orm.username,
            role=UserRole(orm.role),
            is_active=orm.is_active,
            created_at=orm.created_at,
        )

    @staticmethod
    def _to_orm(user: User) -> UserORM:
        """Map a domain :class:`User` to a new ORM row.

        .. note::
            The returned instance is **not** yet attached to a session; callers
            must ``session.add()`` it.
        """
        return UserORM(
            telegram_id=user.telegram_id,
            username=user.username,
            role=user.role.value,
            is_active=user.is_active,
            created_at=user.created_at,
        )
