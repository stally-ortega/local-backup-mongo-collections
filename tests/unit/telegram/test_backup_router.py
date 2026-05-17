"""Unit tests for the backup FSM router.

Each handler is exercised in isolation with mocked aiogram events,
synthetic :class:`TelegramDependencies`, and an in-memory
:class:`MockFSMContext` so that no real Redis or Telegram network
call is required.
"""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import CallbackQuery, Chat, Message
from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos import RequestBackupResult
from app.domain.entities.size_report import CollectionSize, DatabaseSize, SizeReport
from app.domain.entities.user import User
from app.domain.value_objects.enums import JobStatus, UserRole
from app.telegram.dependencies import TelegramDependencies
from app.telegram.keyboards.backup_keyboards import (
    BackupTypeCallback,
    CollectionCallback,
    ConfirmCallback,
    DatabaseCallback,
    PageCallback,
)
from app.telegram.routers.backup import (
    cmd_backup,
    on_cancelar,
    on_coll_confirmar,
    on_coll_toggle,
    on_custom_type,
    on_db_continuar,
    on_db_toggle,
    on_ejecutar,
    on_full_type,
    on_page_nav,
)
from app.telegram.states.backup_states import BackupStates

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user() -> User:
    return User(telegram_id=42, username="alice", role=UserRole.ADMIN)


def _make_deps(
    session_factory: MagicMock | None = None,
) -> TelegramDependencies:
    config = MagicMock()
    config.cluster_uri_hash = "abc123def"
    config.topic_backup_requests = 1
    config.rate_limit_max_requests = 10
    config.rate_limit_window_seconds = 60
    config.backup_base_path = Path("/tmp/backups")

    mongo_meta = AsyncMock()
    mongo_meta.list_databases = AsyncMock(return_value=["db1", "db2"])
    mongo_meta.list_collections = AsyncMock(return_value=["coll1", "coll2"])
    mongo_meta.get_size_stats = AsyncMock(
        return_value=SizeReport(
            cluster_uri_hash="abc123def",
            databases=[
                DatabaseSize(database="db1", size_bytes=100_000, collection_count=2),
                DatabaseSize(database="db2", size_bytes=200_000, collection_count=1),
            ],
            collections=[
                CollectionSize(
                    database="db1", collection="coll1", size_bytes=50_000, document_count=100
                ),
                CollectionSize(
                    database="db1", collection="coll2", size_bytes=50_000, document_count=200
                ),
                CollectionSize(
                    database="db2", collection="coll3", size_bytes=200_000, document_count=500
                ),
            ],
        )
    )

    if session_factory is None:
        session = AsyncMock(spec=AsyncSession)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session_factory = MagicMock(return_value=session)

    redis_conn = MagicMock()
    aioredis_client = AsyncMock()
    fs_utils = AsyncMock()
    perms = MagicMock()

    return TelegramDependencies(
        config=config,
        session_factory=session_factory,
        mongo_metadata=mongo_meta,
        mongo_connection=MagicMock(),
        redis_connection=redis_conn,
        aioredis_client=aioredis_client,
        fs_utils=fs_utils,
        permission_service=perms,
    )


def _make_message() -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    msg.message_thread_id = 1
    msg.chat = MagicMock(spec=Chat)
    msg.chat.id = -100
    msg.from_user = MagicMock(spec=TelegramUser)
    msg.from_user.id = 42
    return msg


def _make_callback() -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.message.message_id = 1
    cb.message.message_thread_id = 1
    cb.message.chat = MagicMock(spec=Chat)
    cb.message.chat.id = -100
    cb.answer = AsyncMock()
    cb.from_user = MagicMock(spec=TelegramUser)
    cb.from_user.id = 42
    return cb


class MockFSMContext:
    """Lightweight in-memory FSM context for unit tests."""

    def __init__(self, state: str | None = None, data: dict[str, object] | None = None) -> None:
        self._state = state
        self._data = data or {}

    async def get_state(self) -> str | None:
        return self._state

    async def set_state(self, state: str | None) -> None:
        self._state = state

    async def get_data(self) -> dict[str, object]:
        return self._data.copy()

    async def set_data(self, data: dict[str, object]) -> None:
        self._data = data

    async def update_data(self, **kwargs: object) -> None:
        self._data.update(kwargs)

    async def clear(self) -> None:
        self._state = None
        self._data = {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_touch() -> Iterator[AsyncMock]:
    with patch(
        "app.telegram.routers.backup.FSMTimeoutMonitor.touch",
        new_callable=AsyncMock,
    ) as m:
        yield m


# ---------------------------------------------------------------------------
# cmd_backup
# ---------------------------------------------------------------------------


class TestCmdBackup:
    async def test_sets_selecting_backup_type(self, mock_touch: AsyncMock) -> None:
        message = _make_message()
        state = MockFSMContext()
        deps = _make_deps()
        user = _make_user()

        await cmd_backup(message, state, deps, user)

        assert state._state == BackupStates.selecting_backup_type
        assert state._data.get("topic_id") == 1
        message.answer.assert_awaited_once()
        mock_touch.assert_awaited_once_with(deps.aioredis_client, 42)


# ---------------------------------------------------------------------------
# on_full_type
# ---------------------------------------------------------------------------


class TestOnFullType:
    async def test_goes_to_confirming_with_summary(self, mock_touch: AsyncMock) -> None:
        callback = _make_callback()
        callback_data = BackupTypeCallback(action="full")
        state = MockFSMContext(state=BackupStates.selecting_backup_type.state, data={"topic_id": 1})
        deps = _make_deps()
        user = _make_user()

        await on_full_type(callback, callback_data, state, deps, user)

        assert state._state == BackupStates.confirming.state
        assert state._data.get("backup_type") == "FULL"
        callback.message.edit_text.assert_awaited_once()
        mock_touch.assert_awaited_once()


# ---------------------------------------------------------------------------
# on_custom_type
# ---------------------------------------------------------------------------


class TestOnCustomType:
    async def test_goes_to_selecting_databases(self, mock_touch: AsyncMock) -> None:
        callback = _make_callback()
        callback_data = BackupTypeCallback(action="custom")
        state = MockFSMContext(state=BackupStates.selecting_backup_type.state, data={"topic_id": 1})
        deps = _make_deps()
        user = _make_user()

        await on_custom_type(callback, callback_data, state, deps, user)

        assert state._state == BackupStates.selecting_databases.state
        assert state._data.get("backup_type") == "CUSTOM"
        callback.message.edit_text.assert_awaited_once()
        mock_touch.assert_awaited_once()


# ---------------------------------------------------------------------------
# on_db_toggle
# ---------------------------------------------------------------------------


class TestOnDbToggle:
    async def test_toggles_and_refreshes_keyboard(self, mock_touch: AsyncMock) -> None:
        callback = _make_callback()
        callback_data = DatabaseCallback(database="db1", action="toggle")
        state = MockFSMContext(
            state=BackupStates.selecting_databases.state,
            data={"all_databases": ["db1", "db2"], "selected_databases": []},
        )
        deps = _make_deps()
        user = _make_user()

        await on_db_toggle(callback, callback_data, state, deps, user)

        assert state._data["selected_databases"] == ["db1"]
        callback.message.edit_text.assert_awaited_once()
        mock_touch.assert_awaited_once()

    async def test_untoggles_when_already_selected(self, mock_touch: AsyncMock) -> None:
        callback = _make_callback()
        callback_data = DatabaseCallback(database="db1", action="toggle")
        state = MockFSMContext(
            state=BackupStates.selecting_databases.state,
            data={"all_databases": ["db1", "db2"], "selected_databases": ["db1"]},
        )
        deps = _make_deps()
        user = _make_user()

        await on_db_toggle(callback, callback_data, state, deps, user)

        assert state._data["selected_databases"] == []
        mock_touch.assert_awaited_once()


# ---------------------------------------------------------------------------
# on_db_continuar
# ---------------------------------------------------------------------------


class TestOnDbContinuar:
    async def test_warns_when_no_db_selected(self, mock_touch: AsyncMock) -> None:
        callback = _make_callback()
        callback_data = DatabaseCallback(database="_", action="continuar")
        state = MockFSMContext(
            state=BackupStates.selecting_databases.state,
            data={"all_databases": ["db1", "db2"], "selected_databases": []},
        )
        deps = _make_deps()
        user = _make_user()

        await on_db_continuar(callback, callback_data, state, deps, user)

        assert state._state == BackupStates.selecting_databases.state
        callback.answer.assert_awaited_once_with(
            "Selecciona al menos una base de datos",
            show_alert=True,
        )
        callback.message.edit_text.assert_not_awaited()
        mock_touch.assert_awaited_once()

    async def test_advances_to_collections(self, mock_touch: AsyncMock) -> None:
        callback = _make_callback()
        callback_data = DatabaseCallback(database="_", action="continuar")
        state = MockFSMContext(
            state=BackupStates.selecting_databases.state,
            data={"all_databases": ["db1"], "selected_databases": ["db1"]},
        )
        deps = _make_deps()
        user = _make_user()

        await on_db_continuar(callback, callback_data, state, deps, user)

        assert state._state == BackupStates.selecting_collections.state
        assert state._data.get("current_page") == 0
        callback.message.edit_text.assert_awaited_once()
        mock_touch.assert_awaited_once()


# ---------------------------------------------------------------------------
# on_coll_toggle
# ---------------------------------------------------------------------------


class TestOnCollToggle:
    async def test_toggles_and_refreshes_keyboard(self, mock_touch: AsyncMock) -> None:
        callback = _make_callback()
        callback_data = CollectionCallback(database="db1", collection="coll1", action="toggle")
        state = MockFSMContext(
            state=BackupStates.selecting_collections.state,
            data={
                "all_collections": ["db1.coll1", "db1.coll2"],
                "selected_collections": [],
                "current_page": 0,
            },
        )
        deps = _make_deps()
        user = _make_user()

        await on_coll_toggle(callback, callback_data, state, deps, user)

        assert state._data["selected_collections"] == ["db1.coll1"]
        callback.message.edit_text.assert_awaited_once()
        mock_touch.assert_awaited_once()


# ---------------------------------------------------------------------------
# on_page_nav
# ---------------------------------------------------------------------------


class TestOnPageNav:
    async def test_updates_page(self, mock_touch: AsyncMock) -> None:
        callback = _make_callback()
        callback_data = PageCallback(page=1)
        state = MockFSMContext(
            state=BackupStates.selecting_collections.state,
            data={
                "all_collections": ["db1.coll1", "db1.coll2"],
                "selected_collections": [],
                "current_page": 0,
            },
        )
        deps = _make_deps()
        user = _make_user()

        await on_page_nav(callback, callback_data, state, deps, user)

        assert state._data["current_page"] == 1
        callback.message.edit_text.assert_awaited_once()
        mock_touch.assert_awaited_once()


# ---------------------------------------------------------------------------
# on_coll_confirmar
# ---------------------------------------------------------------------------


class TestOnCollConfirmar:
    async def test_warns_when_no_collections(self, mock_touch: AsyncMock) -> None:
        callback = _make_callback()
        callback_data = ConfirmCallback(action="confirmar")
        state = MockFSMContext(
            state=BackupStates.selecting_collections.state,
            data={
                "selected_databases": ["db1"],
                "selected_collections": [],
            },
        )
        deps = _make_deps()
        user = _make_user()

        await on_coll_confirmar(callback, callback_data, state, deps, user)

        assert state._state == BackupStates.selecting_collections.state
        callback.answer.assert_awaited_once_with(
            "Selecciona al menos una colección",
            show_alert=True,
        )
        mock_touch.assert_awaited_once()

    async def test_goes_to_confirming_with_summary(self, mock_touch: AsyncMock) -> None:
        callback = _make_callback()
        callback_data = ConfirmCallback(action="confirmar")
        state = MockFSMContext(
            state=BackupStates.selecting_collections.state,
            data={
                "selected_databases": ["db1"],
                "selected_collections": ["db1.coll1"],
            },
        )
        deps = _make_deps()
        user = _make_user()

        await on_coll_confirmar(callback, callback_data, state, deps, user)

        assert state._state == BackupStates.confirming.state
        callback.message.edit_text.assert_awaited_once()
        mock_touch.assert_awaited_once()


# ---------------------------------------------------------------------------
# on_ejecutar
# ---------------------------------------------------------------------------


class TestOnEjecutar:
    @pytest.fixture
    def mock_session_factory(self) -> MagicMock:
        session = AsyncMock(spec=AsyncSession)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=session)
        return factory

    async def test_executes_use_case_and_reports_job_id(
        self,
        mock_touch: AsyncMock,
        mock_session_factory: MagicMock,
    ) -> None:
        callback = _make_callback()
        callback_data = ConfirmCallback(action="ejecutar")
        state = MockFSMContext(
            state=BackupStates.confirming.state,
            data={"backup_type": "FULL"},
        )
        deps = _make_deps(session_factory=mock_session_factory)
        user = _make_user()

        with patch("app.telegram.routers.backup.build_request_backup_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                return_value=RequestBackupResult(
                    job_id="job-123",
                    status=JobStatus.QUEUED,
                )
            )
            mock_builder.return_value = mock_use_case

            await on_ejecutar(callback, callback_data, state, deps, user)

        assert state._state is None
        assert state._data == {}
        callback.message.edit_text.assert_awaited_once()
        text = callback.message.edit_text.await_args.kwargs.get("text", "")
        assert "job-123" in text
        mock_touch.assert_awaited_once()

    async def test_handles_rate_limit_error(
        self,
        mock_touch: AsyncMock,
        mock_session_factory: MagicMock,
    ) -> None:
        from app.domain.exceptions.domain_errors import RateLimitError

        callback = _make_callback()
        callback_data = ConfirmCallback(action="ejecutar")
        state = MockFSMContext(
            state=BackupStates.confirming.state,
            data={"backup_type": "FULL"},
        )
        deps = _make_deps(session_factory=mock_session_factory)
        user = _make_user()

        with patch("app.telegram.routers.backup.build_request_backup_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                side_effect=RateLimitError(
                    message="Too many requests",
                    details={"window_seconds": 60},
                )
            )
            mock_builder.return_value = mock_use_case

            await on_ejecutar(callback, callback_data, state, deps, user)

        assert state._state is None
        text = callback.message.edit_text.await_args.kwargs.get("text", "")
        assert "Rate limit" in text

    async def test_handles_disk_space_error(
        self,
        mock_touch: AsyncMock,
        mock_session_factory: MagicMock,
    ) -> None:
        from app.domain.exceptions.domain_errors import DiskSpaceError

        callback = _make_callback()
        callback_data = ConfirmCallback(action="ejecutar")
        state = MockFSMContext(
            state=BackupStates.confirming.state,
            data={"backup_type": "FULL"},
        )
        deps = _make_deps(session_factory=mock_session_factory)
        user = _make_user()

        with patch("app.telegram.routers.backup.build_request_backup_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(
                side_effect=DiskSpaceError(
                    message="No space left",
                    details={},
                )
            )
            mock_builder.return_value = mock_use_case

            await on_ejecutar(callback, callback_data, state, deps, user)

        assert state._state is None
        text = callback.message.edit_text.await_args.kwargs.get("text", "")
        assert "Sin espacio" in text


# ---------------------------------------------------------------------------
# on_cancelar
# ---------------------------------------------------------------------------


class TestOnCancelar:
    async def test_clears_state_and_shows_cancelled(self, mock_touch: AsyncMock) -> None:
        callback = _make_callback()
        callback_data = ConfirmCallback(action="cancelar")
        state = MockFSMContext(
            state=BackupStates.confirming.state,
            data={"backup_type": "FULL"},
        )
        deps = _make_deps()
        user = _make_user()

        await on_cancelar(callback, callback_data, state, deps, user)

        assert state._state is None
        assert state._data == {}
        callback.message.edit_text.assert_awaited_once_with(text="Backup cancelado.")
        mock_touch.assert_awaited_once()
