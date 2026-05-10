"""Use case: query MongoDB storage sizes.

Orchestrates permission checks, scoped size queries via
:class:`~app.application.services.size_query_service.SizeQueryService`,
and structured audit logging.
"""

from app.application.dtos import QuerySizeDto, QuerySizeResult
from app.application.services.audit_service import AuditService
from app.application.services.size_query_service import SizeQueryService
from app.domain.exceptions.domain_errors import PermissionError


class QuerySizeUseCase:
    """Coordinates size queries with RBAC and audit.

    Parameters
    ----------
    size_query_service:
        Service that wraps ``IMongoMetadata`` with pagination helpers.
    audit_service:
        Structured audit logger.
    """

    def __init__(
        self,
        *,
        size_query_service: SizeQueryService,
        audit_service: AuditService,
    ) -> None:
        self._size_query_service = size_query_service
        self._audit_service = audit_service

    async def execute(self, dto: QuerySizeDto) -> QuerySizeResult:
        """Run a scoped size query.

        Parameters
        ----------
        dto:
            Query payload containing scope, cluster hash, and optional filters.

        Raises
        ------
        PermissionError
            When the user lacks the required role for size queries.
        """
        # Size queries are open to all active roles; the guard here protects
        # against future policy changes without touching business logic.
        if not dto.user.is_active:
            raise PermissionError(
                message="User is not authorised to query sizes",
                details={
                    "user_id": dto.user.telegram_id,
                    "topic": dto.topic,
                },
            )

        scope = dto.scope.lower()

        if scope == "cluster":
            result = await self._query_cluster(dto)
        elif scope == "database":
            result = await self._query_databases(dto)
        else:  # "collection"
            result = await self._query_collections(dto)

        await self._audit_service.log_action(
            action="SIZE_QUERIED",
            user=dto.user,
            topic=dto.topic,
            command=dto.command,
            result="SUCCESS",
            context={
                "scope": scope,
                "cluster_uri_hash": dto.cluster_uri_hash,
                "database_name": dto.database_name,
                "total_size_bytes": result.total_size_bytes,
            },
        )

        return result

    async def _query_cluster(self, dto: QuerySizeDto) -> QuerySizeResult:
        report = await self._size_query_service.get_cluster_size(dto.cluster_uri_hash)
        return QuerySizeResult(
            scope="cluster",
            cluster_uri_hash=dto.cluster_uri_hash,
            total_size_bytes=report.total_size_bytes(),
            databases=report.databases,
            collections=report.collections,
        )

    async def _query_databases(self, dto: QuerySizeDto) -> QuerySizeResult:
        dbs = await self._size_query_service.get_database_sizes(dto.cluster_uri_hash)
        total = sum(db.size_bytes for db in dbs)
        return QuerySizeResult(
            scope="database",
            cluster_uri_hash=dto.cluster_uri_hash,
            total_size_bytes=total,
            databases=dbs,
        )

    async def _query_collections(self, dto: QuerySizeDto) -> QuerySizeResult:
        cols = await self._size_query_service.get_collection_sizes(
            dto.cluster_uri_hash,
            dto.database_name,
            page=dto.page,
            page_size=dto.page_size,
        )
        total = sum(col.size_bytes for col in cols)
        return QuerySizeResult(
            scope="collection",
            cluster_uri_hash=dto.cluster_uri_hash,
            database_name=dto.database_name,
            total_size_bytes=total,
            collections=cols,
        )
