"""Unit tests for the size-query router.

Each handler is exercised in isolation with mocked aiogram events and
synthetic :class:`TelegramDependencies` so that no real MongoDB or
Telegram network call is required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import CallbackQuery, Chat, Message
from aiogram.types import User as TelegramUser

from app.domain.entities.user import User
from app.domain.value_objects.enums import UserRole
from app.telegram.dependencies import TelegramDependencies
from app.telegram.keyboards.size_keyboards import SizeCollPageCallback, SizeDbCallback
from app.telegram.routers.size import (
    cmd_size,
    cmd_size_collection,
    cmd_size_db,
    on_size_collection_page,
    on_size_db_selected,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user() -> User:
    return User(telegram_id=42, username="alice", role=UserRole.ADMIN)


def _make_deps() -> TelegramDependencies:
    config = MagicMock()
    config.cluster_uri_hash = "abc123def"

    mongo_meta = AsyncMock()
    mongo_meta.list_databases = AsyncMock(return_value=["db1", "db2"])

    session = AsyncMock()
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


def _make_message(text: str = "/size") -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    msg.message_thread_id = 1
    msg.chat = MagicMock(spec=Chat)
    msg.chat.id = -100
    msg.from_user = MagicMock(spec=TelegramUser)
    msg.from_user.id = 42
    msg.text = text
    msg.bot = AsyncMock()
    return msg


def _make_callback() -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.message.message_thread_id = 1
    cb.message.chat = MagicMock(spec=Chat)
    cb.message.chat.id = -100
    cb.answer = AsyncMock()
    cb.from_user = MagicMock(spec=TelegramUser)
    cb.from_user.id = 42
    return cb


def _make_cluster_result() -> MagicMock:
    result = MagicMock()
    result.cluster_uri_hash = "abc123def"
    result.total_size_bytes = 1_073_741_824
    db1 = MagicMock()
    db1.database = "db1"
    db1.size_bytes = 536_870_912
    db1.collection_count = 2
    db2 = MagicMock()
    db2.database = "db2"
    db2.size_bytes = 536_870_912
    db2.collection_count = 1
    result.databases = [db1, db2]
    result.collections = None
    return result


def _make_db_result() -> MagicMock:
    result = MagicMock()
    result.cluster_uri_hash = "abc123def"
    result.total_size_bytes = 1_073_741_824
    db1 = MagicMock()
    db1.database = "db1"
    db1.size_bytes = 536_870_912
    db1.collection_count = 2
    db2 = MagicMock()
    db2.database = "db2"
    db2.size_bytes = 536_870_912
    db2.collection_count = 1
    result.databases = [db1, db2]
    result.collections = None
    return result


def _make_collection_result() -> MagicMock:
    result = MagicMock()
    result.cluster_uri_hash = "abc123def"
    result.total_size_bytes = 536_870_912
    result.databases = None
    c1 = MagicMock()
    c1.collection = "coll1"
    c1.size_bytes = 300_000
    c1.document_count = 100
    c2 = MagicMock()
    c2.collection = "coll2"
    c2.size_bytes = 236_870_912
    c2.document_count = 200
    result.collections = [c1, c2]
    return result


# ---------------------------------------------------------------------------
# cmd_size
# ---------------------------------------------------------------------------


class TestCmdSize:
    async def test_renders_cluster_size(self) -> None:
        message = _make_message("/size")
        deps = _make_deps()
        user = _make_user()

        with patch("app.telegram.routers.size.build_query_size_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(return_value=_make_cluster_result())
            mock_builder.return_value = mock_use_case

            await cmd_size(message, deps, user)

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        assert "Tamaño del Cluster" in text
        assert "1.00 GB" in text


# ---------------------------------------------------------------------------
# cmd_size_db
# ---------------------------------------------------------------------------


class TestCmdSizeDb:
    async def test_renders_database_sizes(self) -> None:
        message = _make_message("/size_db")
        deps = _make_deps()
        user = _make_user()

        with patch("app.telegram.routers.size.build_query_size_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(return_value=_make_db_result())
            mock_builder.return_value = mock_use_case

            await cmd_size_db(message, deps, user)

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        assert "Tamaño por Base de Datos" in text
        assert "db1" in text
        assert "db2" in text


# ---------------------------------------------------------------------------
# cmd_size_collection
# ---------------------------------------------------------------------------


class TestCmdSizeCollection:
    async def test_with_db_argument_sends_collections(self) -> None:
        message = _make_message("/size_collection db1")
        deps = _make_deps()
        user = _make_user()

        with patch("app.telegram.routers.size.build_query_size_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(return_value=_make_collection_result())
            mock_builder.return_value = mock_use_case

            await cmd_size_collection(message, deps, user)

        message.bot.send_message.assert_awaited_once()
        text = message.bot.send_message.await_args.kwargs.get("text", "")
        assert "Colecciones: db1" in text
        assert "coll1" in text

    async def test_without_argument_shows_database_selector(self) -> None:
        message = _make_message("/size_collection")
        deps = _make_deps()
        user = _make_user()

        await cmd_size_collection(message, deps, user)

        message.answer.assert_awaited_once()
        text = message.answer.await_args.args[0]
        assert "Selecciona una base de datos" in text
        reply_markup = message.answer.await_args.kwargs.get("reply_markup")
        assert reply_markup is not None

    async def test_no_databases_found(self) -> None:
        message = _make_message("/size_collection")
        deps = _make_deps()
        deps.mongo_metadata.list_databases = AsyncMock(return_value=[])  # type: ignore[method-assign]
        user = _make_user()

        await cmd_size_collection(message, deps, user)

        message.answer.assert_awaited_once_with("No se encontraron bases de datos.")


# ---------------------------------------------------------------------------
# on_size_db_selected
# ---------------------------------------------------------------------------


class TestOnSizeDbSelected:
    async def test_edits_message_with_collections(self) -> None:
        callback = _make_callback()
        callback_data = SizeDbCallback(database="db1")
        deps = _make_deps()
        user = _make_user()

        with patch("app.telegram.routers.size.build_query_size_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(return_value=_make_collection_result())
            mock_builder.return_value = mock_use_case

            await on_size_db_selected(callback, callback_data, deps, user)

        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once()
        text = callback.message.edit_text.await_args.kwargs.get("text", "")
        assert "Colecciones: db1" in text


# ---------------------------------------------------------------------------
# on_size_collection_page
# ---------------------------------------------------------------------------


class TestOnSizeCollectionPage:
    async def test_edits_message_for_next_page(self) -> None:
        callback = _make_callback()
        callback_data = SizeCollPageCallback(database="db1", page=1)
        deps = _make_deps()
        user = _make_user()

        with patch("app.telegram.routers.size.build_query_size_use_case") as mock_builder:
            mock_use_case = AsyncMock()
            mock_use_case.execute = AsyncMock(return_value=_make_collection_result())
            mock_builder.return_value = mock_use_case

            await on_size_collection_page(callback, callback_data, deps, user)

        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once()
        text = callback.message.edit_text.await_args.kwargs.get("text", "")
        assert "Colecciones: db1" in text
