"""Unit tests for QuerySizeUseCase."""

from datetime import datetime

import pytest

from app.application.dtos import QuerySizeDto, QuerySizeResult
from app.application.services.audit_service import AuditService
from app.application.services.size_query_service import SizeQueryService
from app.application.use_cases.query_size import QuerySizeUseCase
from app.domain.entities.audit_log import AuditLog
from app.domain.entities.size_report import CollectionSize, DatabaseSize, SizeReport
from app.domain.entities.user import User
from app.domain.exceptions.domain_errors import DomainPermissionError
from app.domain.repositories.repositories import IAuditRepository
from app.domain.value_objects.enums import UserRole


class _FakeMongoMetadata:
    def __init__(self) -> None:
        self._report = SizeReport(
            cluster_uri_hash="hash123",
            databases=[
                DatabaseSize(database="db1", size_bytes=1_000, collection_count=2),
                DatabaseSize(database="db2", size_bytes=2_000, collection_count=1),
            ],
            collections=[
                CollectionSize(
                    database="db1", collection="col1", size_bytes=500, document_count=10
                ),
                CollectionSize(
                    database="db1", collection="col2", size_bytes=500, document_count=20
                ),
                CollectionSize(
                    database="db2", collection="col3", size_bytes=2_000, document_count=5
                ),
            ],
        )

    async def list_databases(self, cluster_uri_hash: str) -> list[str]:
        return [db.database for db in self._report.databases]

    async def list_collections(self, cluster_uri_hash: str, database: str) -> list[str]:
        return [col.collection for col in self._report.collections if col.database == database]

    async def get_size_stats(self, cluster_uri_hash: str) -> SizeReport:
        return self._report


class _FakeAuditRepo:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    async def log(self, entry: AuditLog) -> None:
        self.entries.append(entry)

    async def list_by_user(self, telegram_id: int) -> list[AuditLog]:
        return [e for e in self.entries if e.telegram_id == telegram_id]

    async def list_by_job(self, job_id: str) -> list[AuditLog]:
        return []

    async def list_by_date_range(self, start: datetime, end: datetime) -> list[AuditLog]:
        return []


@pytest.fixture
def size_query_service() -> SizeQueryService:
    return SizeQueryService(mongo_metadata=_FakeMongoMetadata())


@pytest.fixture
def audit_repo() -> IAuditRepository:
    return _FakeAuditRepo()


@pytest.fixture
def audit_service(audit_repo: IAuditRepository) -> AuditService:
    return AuditService(repository=audit_repo)


@pytest.fixture
def use_case(
    size_query_service: SizeQueryService,
    audit_service: AuditService,
) -> QuerySizeUseCase:
    return QuerySizeUseCase(
        size_query_service=size_query_service,
        audit_service=audit_service,
    )


@pytest.fixture
def admin_user() -> User:
    return User(telegram_id=1, role=UserRole.ADMIN)


class TestQuerySizeClusterScope:
    @pytest.mark.asyncio
    async def test_returns_cluster_report(
        self,
        use_case: QuerySizeUseCase,
        admin_user: User,
    ) -> None:
        dto = QuerySizeDto(
            user=admin_user,
            scope="cluster",
            cluster_uri_hash="hash123",
        )

        result = await use_case.execute(dto)

        assert isinstance(result, QuerySizeResult)
        assert result.scope == "cluster"
        assert result.cluster_uri_hash == "hash123"
        assert result.total_size_bytes == 3_000
        assert result.databases is not None
        assert len(result.databases) == 2
        assert result.collections is not None
        assert len(result.collections) == 3

    @pytest.mark.asyncio
    async def test_includes_databases_and_collections(
        self,
        use_case: QuerySizeUseCase,
        admin_user: User,
    ) -> None:
        dto = QuerySizeDto(
            user=admin_user,
            scope="cluster",
            cluster_uri_hash="hash123",
        )

        result = await use_case.execute(dto)

        assert result.databases is not None
        assert result.databases[0].database == "db1"
        assert result.collections is not None
        assert result.collections[0].database == "db1"


class TestQuerySizeDatabaseScope:
    @pytest.mark.asyncio
    async def test_returns_database_list(
        self,
        use_case: QuerySizeUseCase,
        admin_user: User,
    ) -> None:
        dto = QuerySizeDto(
            user=admin_user,
            scope="database",
            cluster_uri_hash="hash123",
        )

        result = await use_case.execute(dto)

        assert result.scope == "database"
        assert result.total_size_bytes == 3_000
        assert result.databases is not None
        assert len(result.databases) == 2
        assert result.collections is None


class TestQuerySizeCollectionScope:
    @pytest.mark.asyncio
    async def test_returns_all_collections(
        self,
        use_case: QuerySizeUseCase,
        admin_user: User,
    ) -> None:
        dto = QuerySizeDto(
            user=admin_user,
            scope="collection",
            cluster_uri_hash="hash123",
        )

        result = await use_case.execute(dto)

        assert result.scope == "collection"
        assert result.total_size_bytes == 3_000
        assert result.collections is not None
        assert len(result.collections) == 3

    @pytest.mark.asyncio
    async def test_filters_by_database(
        self,
        use_case: QuerySizeUseCase,
        admin_user: User,
    ) -> None:
        dto = QuerySizeDto(
            user=admin_user,
            scope="collection",
            cluster_uri_hash="hash123",
            database_name="db1",
        )

        result = await use_case.execute(dto)

        assert result.collections is not None
        assert len(result.collections) == 2
        assert all(c.database == "db1" for c in result.collections)
        assert result.total_size_bytes == 1_000

    @pytest.mark.asyncio
    async def test_respects_pagination(
        self,
        use_case: QuerySizeUseCase,
        admin_user: User,
    ) -> None:
        dto = QuerySizeDto(
            user=admin_user,
            scope="collection",
            cluster_uri_hash="hash123",
            page=1,
            page_size=2,
        )

        result = await use_case.execute(dto)

        assert result.collections is not None
        assert len(result.collections) == 2


class TestQuerySizePermissionError:
    @pytest.mark.asyncio
    async def test_inactive_user_denied(
        self,
        use_case: QuerySizeUseCase,
    ) -> None:
        inactive = User(telegram_id=2, role=UserRole.READONLY)
        inactive.is_active = False
        dto = QuerySizeDto(
            user=inactive,
            scope="cluster",
            cluster_uri_hash="hash123",
        )

        with pytest.raises(DomainPermissionError) as exc_info:
            await use_case.execute(dto)
        assert exc_info.value.code == "PERMISSION_DENIED"


class TestQuerySizeAudit:
    @pytest.mark.asyncio
    async def test_logs_size_queried_event(
        self,
        use_case: QuerySizeUseCase,
        admin_user: User,
        audit_repo: _FakeAuditRepo,
    ) -> None:
        dto = QuerySizeDto(
            user=admin_user,
            scope="cluster",
            cluster_uri_hash="hash123",
        )

        await use_case.execute(dto)

        audit = [e for e in audit_repo.entries if e.action == "SIZE_QUERIED"]
        assert len(audit) == 1
        assert audit[0].telegram_id == admin_user.telegram_id
