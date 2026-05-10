"""Unit tests for the Telegram bot and dispatcher factory."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Dispatcher, Router
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import AppConfig
from app.telegram.bot import BotBuilder


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig(
        telegram_bot_token="bot123",
        telegram_chat_id="-100",
        mongodb_uri="mongodb://localhost:27017",
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
    )


def _make_redis_storage_patch(target: str) -> Any:
    """Patch *target* so that ``RedisStorage(...)`` returns a valid ``BaseStorage``."""
    return patch(target, side_effect=lambda **_: MemoryStorage())


def _fresh_routers() -> list[Router]:
    """Return a list of fresh Router instances for testing."""
    return [
        Router(name="backup"),
        Router(name="size"),
        Router(name="admin"),
        Router(name="error"),
    ]


class TestCreateDispatcher:
    def test_returns_dispatcher(
        self,
        app_config: AppConfig,
    ) -> None:
        with (
            _make_redis_storage_patch("app.telegram.bot.RedisStorage"),
            patch("app.telegram.bot.RedisEventIsolation"),
            patch("app.telegram.bot.get_routers", return_value=_fresh_routers()),
        ):
            builder = BotBuilder(app_config)
            dp = builder.create_dispatcher()

        assert isinstance(dp, Dispatcher)

    def test_includes_default_routers(
        self,
        app_config: AppConfig,
    ) -> None:
        with (
            _make_redis_storage_patch("app.telegram.bot.RedisStorage"),
            patch("app.telegram.bot.RedisEventIsolation"),
            patch("app.telegram.bot.get_routers", return_value=_fresh_routers()),
        ):
            builder = BotBuilder(app_config)
            dp = builder.create_dispatcher()

        names = {router.name for router in dp.sub_routers}
        assert "backup" in names
        assert "size" in names
        assert "admin" in names
        assert "error" in names

    def test_allows_custom_routers(
        self,
        app_config: AppConfig,
    ) -> None:
        custom = Router(name="custom")
        with (
            _make_redis_storage_patch("app.telegram.bot.RedisStorage"),
            patch("app.telegram.bot.RedisEventIsolation"),
            patch("app.telegram.bot.get_routers", return_value=_fresh_routers()),
        ):
            builder = BotBuilder(app_config)
            dp = builder.create_dispatcher(routers=[custom])

        assert any(router.name == "custom" for router in dp.sub_routers)
        assert len(dp.sub_routers) == 1

    def test_allows_custom_middlewares(
        self,
        app_config: AppConfig,
    ) -> None:
        mock_mw = MagicMock()
        with (
            _make_redis_storage_patch("app.telegram.bot.RedisStorage"),
            patch("app.telegram.bot.RedisEventIsolation"),
            patch("app.telegram.bot.get_routers", return_value=_fresh_routers()),
        ):
            builder = BotBuilder(app_config)
            dp = builder.create_dispatcher(middlewares=[mock_mw])

        assert isinstance(dp, Dispatcher)

    def test_creates_redis_storage_with_async_client(
        self,
        app_config: AppConfig,
    ) -> None:
        mock_storage_cls = MagicMock(side_effect=lambda **_: MemoryStorage())
        mock_isolation_cls = MagicMock()
        with (
            patch("app.telegram.bot.RedisStorage", mock_storage_cls),
            patch("app.telegram.bot.RedisEventIsolation", mock_isolation_cls),
            patch("app.telegram.bot.aioredis.Redis.from_url") as mock_redis,
            patch("app.telegram.bot.get_routers", return_value=_fresh_routers()),
        ):
            builder = BotBuilder(app_config)
            builder.create_dispatcher()

        mock_redis.assert_called_once_with("redis://localhost:6379/0")
        mock_storage_cls.assert_called_once()
        mock_isolation_cls.assert_called_once()


class TestStart:
    @patch("app.telegram.bot.AiogramBot")
    async def test_returns_bot_and_dispatcher(
        self,
        mock_bot_cls: MagicMock,
        app_config: AppConfig,
    ) -> None:
        mock_bot = MagicMock()
        mock_bot_cls.from_config.return_value = mock_bot

        builder = BotBuilder(app_config)

        # Patch create_dispatcher so we do not need Redis mocks here.
        with patch.object(builder, "create_dispatcher", return_value=MagicMock()) as mock_create:
            bot, dp = await builder.start()

            mock_bot_cls.from_config.assert_called_once_with(app_config)
            mock_bot.start.assert_called_once()
            mock_create.assert_called_once()
            assert bot is mock_bot
            assert dp is mock_create.return_value


class TestShutdown:
    async def test_shuts_down_bot(self, app_config: AppConfig) -> None:
        mock_bot = AsyncMock()
        mock_dp = MagicMock()

        builder = BotBuilder(app_config)
        await builder.shutdown(mock_bot, mock_dp)

        mock_bot.shutdown.assert_awaited_once()
