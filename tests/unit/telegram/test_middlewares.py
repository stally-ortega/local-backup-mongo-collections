"""Unit tests for the Telegram middleware stack.

Each middleware is exercised in isolation with mocked aiogram events and
synthetic dependencies so that no real database or Telegram network call is
required.
"""

from collections.abc import Generator
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Bot
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.audit_service import AuditService
from app.application.services.permission_service import PermissionService
from app.config import AppConfig
from app.domain.entities.user import User
from app.domain.value_objects.enums import UserRole
from app.telegram.middlewares import (
    AuditMiddleware,
    AuthMiddleware,
    ErrorHandlerMiddleware,
    LoggingMiddleware,
    RateLimitMiddleware,
    RoleMiddleware,
    TopicFilterMiddleware,
)
from app.telegram.middlewares._utils import UpdateContext, extract_command, extract_context

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig(
        telegram_bot_token="bot123",
        telegram_chat_id="-100",
        mongodb_uri="mongodb://localhost:27017",
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        topic_backup_requests=1,
        topic_size_ask=2,
        topic_execution_errors=3,
        topic_admin=4,
    )


@pytest.fixture
def mock_handler() -> AsyncMock:
    return AsyncMock(return_value="handler_result")


@pytest.fixture
def mock_bot() -> MagicMock:
    bot = MagicMock(spec=Bot)
    bot.send_message = AsyncMock(return_value=None)
    bot.send_document = AsyncMock(return_value=None)
    return bot


@pytest.fixture
def mock_settings(app_config: AppConfig) -> Generator[AppConfig, None, None]:
    with patch("app.telegram.middlewares.error_handler_middleware.settings", app_config):
        yield app_config


def _make_message_update(
    *,
    text: str = "/backup",
    user_id: int = 42,
    chat_id: int = -100,
    topic_id: int | None = 1,
) -> Update:
    """Build a synthetic aiogram Update wrapping a Message."""
    return Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=datetime.now(),
            chat=Chat(id=chat_id, type="supergroup"),
            from_user=TelegramUser(id=user_id, is_bot=False, first_name="Alice"),
            text=text,
            message_thread_id=topic_id,
        ),
    )


def _make_data(bot: MagicMock | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if bot is not None:
        data["bot"] = bot
    return data


# ---------------------------------------------------------------------------
# _utils
# ---------------------------------------------------------------------------


class TestExtractContext:
    def test_extracts_from_update_with_message(self) -> None:
        update = _make_message_update(user_id=7, chat_id=-200, topic_id=3)
        ctx = extract_context(update)
        assert ctx == UpdateContext(update_id=1, user_id=7, chat_id=-200, topic_id=3)

    def test_returns_none_for_empty_update(self) -> None:
        update = Update(update_id=5)
        ctx = extract_context(update)
        assert ctx == UpdateContext(update_id=5, user_id=None, chat_id=None, topic_id=None)


class TestExtractCommand:
    def test_extracts_slash_command(self) -> None:
        update = _make_message_update(text="/backup")
        assert extract_command(update) == "BACKUP"

    def test_extracts_with_mention(self) -> None:
        update = _make_message_update(text="/backup@MyBot")
        assert extract_command(update) == "BACKUP"

    def test_returns_none_for_plain_text(self) -> None:
        update = _make_message_update(text="hello world")
        assert extract_command(update) is None


# ---------------------------------------------------------------------------
# LoggingMiddleware
# ---------------------------------------------------------------------------


class TestLoggingMiddleware:
    async def test_logs_update_and_calls_handler(
        self,
        mock_handler: AsyncMock,
    ) -> None:
        mw = LoggingMiddleware()
        update = _make_message_update()
        with patch.object(mw, "_logger") as mock_logger:
            result = await mw(mock_handler, update, _make_data())
        assert result == "handler_result"
        mock_logger.info.assert_called_once()
        call_kwargs = mock_logger.info.call_args.kwargs
        assert call_kwargs["update_id"] == 1
        assert call_kwargs["user_id"] == 42


# ---------------------------------------------------------------------------
# ErrorHandlerMiddleware
# ---------------------------------------------------------------------------


class TestErrorHandlerMiddleware:
    async def test_catches_exception_and_returns_none(
        self,
        app_config: AppConfig,
        mock_handler: AsyncMock,
        mock_bot: MagicMock,
        mock_settings: AppConfig,
    ) -> None:
        mock_handler.side_effect = RuntimeError("boom")
        mw = ErrorHandlerMiddleware(config=app_config)
        data = _make_data(mock_bot)
        result = await mw(mock_handler, _make_message_update(topic_id=2), data)
        assert result is None
        mock_bot.send_message.assert_awaited_once()
        mock_bot.send_document.assert_awaited_once()

    async def test_does_not_notify_execution_errors_topic(
        self,
        app_config: AppConfig,
        mock_handler: AsyncMock,
        mock_bot: MagicMock,
        mock_settings: AppConfig,
    ) -> None:
        mock_handler.side_effect = RuntimeError("boom")
        mw = ErrorHandlerMiddleware(config=app_config)
        data = _make_data(mock_bot)
        await mw(
            mock_handler,
            _make_message_update(topic_id=app_config.topic_execution_errors),
            data,
        )
        mock_bot.send_message.assert_awaited_once()
        mock_bot.send_document.assert_not_awaited()

    async def test_passes_through_when_no_error(
        self,
        app_config: AppConfig,
        mock_handler: AsyncMock,
    ) -> None:
        mw = ErrorHandlerMiddleware(config=app_config)
        result = await mw(mock_handler, _make_message_update(), _make_data())
        assert result == "handler_result"


# ---------------------------------------------------------------------------
# TopicFilterMiddleware
# ---------------------------------------------------------------------------


class TestTopicFilterMiddleware:
    async def test_allows_known_topic(
        self,
        app_config: AppConfig,
        mock_handler: AsyncMock,
    ) -> None:
        mw = TopicFilterMiddleware(config=app_config)
        result = await mw(mock_handler, _make_message_update(topic_id=1), _make_data())
        assert result == "handler_result"

    async def test_blocks_wrong_chat_id(
        self,
        app_config: AppConfig,
        mock_handler: AsyncMock,
        mock_bot: MagicMock,
    ) -> None:
        mw = TopicFilterMiddleware(config=app_config)
        data = _make_data(mock_bot)
        result = await mw(mock_handler, _make_message_update(chat_id=-200, topic_id=1), data)
        assert result is None
        mock_handler.assert_not_awaited()
        mock_bot.send_message.assert_not_awaited()

    async def test_blocks_unknown_topic(
        self,
        app_config: AppConfig,
        mock_handler: AsyncMock,
        mock_bot: MagicMock,
    ) -> None:
        mw = TopicFilterMiddleware(config=app_config)
        data = _make_data(mock_bot)
        result = await mw(mock_handler, _make_message_update(topic_id=99), data)
        assert result is None
        mock_handler.assert_not_awaited()
        mock_bot.send_message.assert_awaited_once()

    async def test_blocks_dm_without_topic(
        self,
        app_config: AppConfig,
        mock_handler: AsyncMock,
        mock_bot: MagicMock,
    ) -> None:
        mw = TopicFilterMiddleware(config=app_config)
        data = _make_data(mock_bot)
        result = await mw(mock_handler, _make_message_update(topic_id=None), data)
        assert result is None
        mock_handler.assert_not_awaited()

    async def test_fallback_when_no_config(
        self,
        mock_handler: AsyncMock,
    ) -> None:
        mw = TopicFilterMiddleware(config=None)
        result = await mw(mock_handler, _make_message_update(topic_id=99), _make_data())
        assert result is None
        mock_handler.assert_not_awaited()


# ---------------------------------------------------------------------------
# AuthMiddleware
# ---------------------------------------------------------------------------


class TestAuthMiddleware:
    @pytest.fixture
    def mock_session_factory(self) -> MagicMock:
        session = AsyncMock(spec=AsyncSession)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=session)
        return factory

    async def test_injects_user_when_found(
        self,
        mock_session_factory: MagicMock,
        mock_handler: AsyncMock,
    ) -> None:
        user = User(telegram_id=42, username="alice", role=UserRole.ADMIN)
        with patch("app.telegram.middlewares.auth_middleware.SQLUserRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.get_by_telegram_id = AsyncMock(return_value=user)
            mw = AuthMiddleware(session_factory=mock_session_factory)
            data = _make_data()
            result = await mw(mock_handler, _make_message_update(user_id=42), data)
            assert result == "handler_result"
            assert data["user"] is user

    async def test_rejects_unknown_user(
        self,
        mock_session_factory: MagicMock,
        mock_handler: AsyncMock,
        mock_bot: MagicMock,
    ) -> None:
        with patch("app.telegram.middlewares.auth_middleware.SQLUserRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.get_by_telegram_id = AsyncMock(return_value=None)
            mw = AuthMiddleware(session_factory=mock_session_factory)
            data = _make_data(mock_bot)
            result = await mw(mock_handler, _make_message_update(user_id=99), data)
            assert result is None
            mock_handler.assert_not_awaited()
            mock_bot.send_message.assert_awaited_once_with(
                chat_id=-100,
                text="No autorizado",
                message_thread_id=1,
            )

    async def test_rejects_inactive_user(
        self,
        mock_session_factory: MagicMock,
        mock_handler: AsyncMock,
        mock_bot: MagicMock,
    ) -> None:
        inactive_user = User(telegram_id=42, username="bob", role=UserRole.ADMIN, is_active=False)
        with patch("app.telegram.middlewares.auth_middleware.SQLUserRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.get_by_telegram_id = AsyncMock(return_value=inactive_user)
            mw = AuthMiddleware(session_factory=mock_session_factory)
            data = _make_data(mock_bot)
            result = await mw(mock_handler, _make_message_update(user_id=42), data)
            assert result is None
            mock_handler.assert_not_awaited()
            mock_bot.send_message.assert_awaited_once_with(
                chat_id=-100,
                text="No autorizado",
                message_thread_id=1,
            )

    async def test_fallback_when_no_session_factory(
        self,
        mock_handler: AsyncMock,
    ) -> None:
        mw = AuthMiddleware(session_factory=None)
        result = await mw(mock_handler, _make_message_update(), _make_data())
        assert result is None
        mock_handler.assert_not_awaited()


# ---------------------------------------------------------------------------
# RoleMiddleware
# ---------------------------------------------------------------------------


class TestRoleMiddleware:
    @pytest.fixture
    def mock_session_factory(self) -> MagicMock:
        session = AsyncMock(spec=AsyncSession)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=session)
        return factory

    async def test_allows_authorized_command(
        self,
        app_config: AppConfig,
        mock_session_factory: MagicMock,
        mock_handler: AsyncMock,
    ) -> None:
        user = User(telegram_id=42, username="alice", role=UserRole.ADMIN)
        perms = PermissionService()
        mw = RoleMiddleware(
            session_factory=mock_session_factory,
            permission_service=perms,
            config=app_config,
        )
        data = _make_data()
        data["user"] = user
        result = await mw(mock_handler, _make_message_update(text="/backup"), data)
        assert result == "handler_result"

    async def test_blocks_unauthorized_command(
        self,
        app_config: AppConfig,
        mock_session_factory: MagicMock,
        mock_handler: AsyncMock,
        mock_bot: MagicMock,
    ) -> None:
        user = User(telegram_id=42, username="bob", role=UserRole.READONLY)
        perms = PermissionService()
        mw = RoleMiddleware(
            session_factory=mock_session_factory,
            permission_service=perms,
            config=app_config,
        )
        data = _make_data(mock_bot)
        data["user"] = user
        result = await mw(mock_handler, _make_message_update(text="/backup"), data)
        assert result is None
        mock_handler.assert_not_awaited()
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=-100,
            text="Permisos insuficientes",
            message_thread_id=1,
        )

    async def test_allows_when_no_command_extracted(
        self,
        app_config: AppConfig,
        mock_session_factory: MagicMock,
        mock_handler: AsyncMock,
    ) -> None:
        user = User(telegram_id=42, username="alice", role=UserRole.READONLY)
        mw = RoleMiddleware(
            session_factory=mock_session_factory,
            config=app_config,
        )
        data = _make_data()
        data["user"] = user
        update = _make_message_update(text="plain text without command")
        result = await mw(mock_handler, update, data)
        assert result == "handler_result"

    async def test_fallback_when_no_session_factory(
        self,
        mock_handler: AsyncMock,
    ) -> None:
        mw = RoleMiddleware(session_factory=None)
        result = await mw(mock_handler, _make_message_update(), _make_data())
        assert result == "handler_result"
        mock_handler.assert_awaited_once()


# ---------------------------------------------------------------------------
# RateLimitMiddleware
# ---------------------------------------------------------------------------


class TestRateLimitMiddleware:
    @pytest.fixture
    def mock_session_factory(self) -> MagicMock:
        session = AsyncMock(spec=AsyncSession)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=session)
        return factory

    async def test_allows_under_limit(
        self,
        app_config: AppConfig,
        mock_session_factory: MagicMock,
        mock_handler: AsyncMock,
    ) -> None:
        with patch(
            "app.telegram.middlewares.rate_limit_middleware.SQLRateLimitRepository"
        ) as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.check_limit = AsyncMock(return_value=True)
            mock_repo.increment = AsyncMock(return_value=1)
            user = User(telegram_id=42, username="alice", role=UserRole.ADMIN)
            mw = RateLimitMiddleware(
                session_factory=mock_session_factory,
                config=app_config,
            )
            data = _make_data()
            data["user"] = user
            result = await mw(mock_handler, _make_message_update(), data)
            assert result == "handler_result"
            mock_repo.increment.assert_awaited_once()

    async def test_blocks_when_limit_exceeded(
        self,
        app_config: AppConfig,
        mock_session_factory: MagicMock,
        mock_handler: AsyncMock,
        mock_bot: MagicMock,
    ) -> None:
        with patch(
            "app.telegram.middlewares.rate_limit_middleware.SQLRateLimitRepository"
        ) as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.check_limit = AsyncMock(return_value=False)
            user = User(telegram_id=42, username="alice", role=UserRole.ADMIN)
            mw = RateLimitMiddleware(
                session_factory=mock_session_factory,
                config=app_config,
            )
            data = _make_data(mock_bot)
            data["user"] = user
            result = await mw(mock_handler, _make_message_update(), data)
            assert result is None
            mock_handler.assert_not_awaited()
            mock_repo.increment.assert_not_called()

    async def test_fallback_when_no_deps(
        self,
        mock_handler: AsyncMock,
    ) -> None:
        mw = RateLimitMiddleware(session_factory=None, config=None)
        result = await mw(mock_handler, _make_message_update(), _make_data())
        assert result == "handler_result"
        mock_handler.assert_awaited_once()


# ---------------------------------------------------------------------------
# AuditMiddleware
# ---------------------------------------------------------------------------


class TestAuditMiddleware:
    @pytest.fixture
    def mock_session_factory(self) -> MagicMock:
        session = AsyncMock(spec=AsyncSession)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=session)
        return factory

    async def test_logs_success_after_handler(
        self,
        mock_session_factory: MagicMock,
        mock_handler: AsyncMock,
    ) -> None:
        audit_svc = AsyncMock(spec=AuditService)
        mw = AuditMiddleware(
            session_factory=mock_session_factory,
            audit_service=audit_svc,
        )
        user = User(telegram_id=42, username="alice", role=UserRole.ADMIN)
        data = _make_data()
        data["user"] = user
        result = await mw(mock_handler, _make_message_update(), data)
        assert result == "handler_result"
        audit_svc.log_action.assert_awaited_once()
        call_kwargs = audit_svc.log_action.await_args.kwargs
        assert call_kwargs["result"] == "SUCCESS"
        assert call_kwargs["user"] is user

    async def test_logs_error_when_handler_raises(
        self,
        mock_session_factory: MagicMock,
        mock_handler: AsyncMock,
    ) -> None:
        mock_handler.side_effect = RuntimeError("boom")
        audit_svc = AsyncMock(spec=AuditService)
        mw = AuditMiddleware(
            session_factory=mock_session_factory,
            audit_service=audit_svc,
        )
        user = User(telegram_id=42, username="alice", role=UserRole.ADMIN)
        data = _make_data()
        data["user"] = user
        with pytest.raises(RuntimeError, match="boom"):
            await mw(mock_handler, _make_message_update(), data)
        audit_svc.log_action.assert_awaited_once()
        call_kwargs = audit_svc.log_action.await_args.kwargs
        assert call_kwargs["result"] == "ERROR: RuntimeError"

    async def test_skips_when_no_user(
        self,
        mock_session_factory: MagicMock,
        mock_handler: AsyncMock,
    ) -> None:
        audit_svc = AsyncMock(spec=AuditService)
        mw = AuditMiddleware(
            session_factory=mock_session_factory,
            audit_service=audit_svc,
        )
        result = await mw(mock_handler, _make_message_update(), _make_data())
        assert result == "handler_result"
        audit_svc.log_action.assert_not_awaited()

    async def test_fallback_when_no_session_factory(
        self,
        mock_handler: AsyncMock,
    ) -> None:
        mw = AuditMiddleware(session_factory=None)
        result = await mw(mock_handler, _make_message_update(), _make_data())
        assert result == "handler_result"
