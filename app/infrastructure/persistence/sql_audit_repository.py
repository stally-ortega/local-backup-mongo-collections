"""SQLAlchemy implementation of :class:`~app.domain.repositories.repositories.IAuditRepository`.

Maps between :class:`~app.domain.entities.audit_log.AuditLog` (domain entity) and
:class:`~app.infrastructure.persistence.models.audit_log.AuditLogORM` (SQLAlchemy model).
"""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.audit_log import AuditLog
from app.domain.repositories.repositories import IAuditRepository
from app.infrastructure.persistence.models.audit_log import AuditLogORM


class SQLAuditRepository(IAuditRepository):
    """Async SQLAlchemy adapter for audit-log persistence.

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

    async def log(self, entry: AuditLog) -> None:
        """Persist an audit entry."""
        orm = self._to_orm(entry)
        self._session.add(orm)
        await self._session.flush()

    async def list_by_user(
        self,
        telegram_id: int,
        page: int = 1,
        page_size: int = 50,
    ) -> list[AuditLog]:
        """Return audit entries for a specific Telegram user."""
        result = await self._session.execute(
            select(AuditLogORM)
            .where(AuditLogORM.telegram_id == telegram_id)
            .order_by(AuditLogORM.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._to_entity(row) for row in result.scalars().all()]

    async def list_by_job(
        self,
        job_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> list[AuditLog]:
        """Return audit entries related to a specific job."""
        result = await self._session.execute(
            select(AuditLogORM)
            .where(AuditLogORM.job_id == job_id)
            .order_by(AuditLogORM.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._to_entity(row) for row in result.scalars().all()]

    async def list_by_date_range(
        self,
        start: datetime,
        end: datetime,
        page: int = 1,
        page_size: int = 50,
    ) -> list[AuditLog]:
        """Return audit entries whose timestamp falls within [*start*, *end*]."""
        result = await self._session.execute(
            select(AuditLogORM)
            .where(
                AuditLogORM.timestamp >= start,
                AuditLogORM.timestamp <= end,
            )
            .order_by(AuditLogORM.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._to_entity(row) for row in result.scalars().all()]

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_entity(orm: AuditLogORM) -> AuditLog:
        """Map an ORM row to the domain :class:`AuditLog`."""
        return AuditLog(
            id=orm.id,
            telegram_id=orm.telegram_id or 0,
            action=orm.action,
            topic=orm.topic or "",
            command=orm.command,
            job_id=orm.job_id,
            cluster_uri_hash=orm.cluster_uri_hash,
            databases=SQLAuditRepository._loads_json_list(orm.databases),
            collections=SQLAuditRepository._loads_json_list(orm.collections),
            result=orm.result or "",
            duration_ms=orm.duration_ms,
            ip_address=orm.ip_address,
            user_agent=orm.user_agent,
            timestamp=orm.timestamp,
            details=SQLAuditRepository._loads_json_dict(orm.details),
        )

    @staticmethod
    def _to_orm(entry: AuditLog) -> AuditLogORM:
        """Map a domain :class:`AuditLog` to a new ORM row."""
        return AuditLogORM(
            telegram_id=entry.telegram_id,
            action=entry.action,
            topic=entry.topic,
            command=entry.command,
            job_id=entry.job_id,
            cluster_uri_hash=entry.cluster_uri_hash,
            databases=SQLAuditRepository._dumps_json(entry.databases),
            collections=SQLAuditRepository._dumps_json(entry.collections),
            result=entry.result,
            duration_ms=entry.duration_ms,
            ip_address=entry.ip_address,
            user_agent=entry.user_agent,
            timestamp=entry.timestamp,
            details=SQLAuditRepository._dumps_json(entry.details),
        )

    # ------------------------------------------------------------------
    # JSON helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _dumps_json(value: Any) -> str | None:
        """Serialize *value* to a JSON string, or ``None`` if *value* is ``None``."""
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _loads_json_list(value: str | None) -> list[str] | None:
        """Deserialize a JSON string into a list of strings."""
        if value is None:
            return None
        parsed: list[str] = json.loads(value)
        return parsed

    @staticmethod
    def _loads_json_dict(value: str | None) -> dict[str, Any] | None:
        """Deserialize a JSON string into a dictionary."""
        if value is None:
            return None
        parsed: dict[str, Any] = json.loads(value)
        return parsed
