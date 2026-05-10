"""Unit tests for AiogramBot."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import AppConfig
from app.infrastructure.telegram.aiogram_bot import AiogramBot


class TestLifecycle:
    @patch("app.infrastructure.telegram.aiogram_bot.Bot")
    @patch("app.infrastructure.telegram.aiogram_bot.DefaultBotProperties")
    def test_start_creates_bot(
        self,
        mock_default_cls: MagicMock,
        mock_bot_cls: MagicMock,
    ) -> None:
        bot = AiogramBot(token="test-token")
        bot.start()

        mock_default_cls.assert_called_once_with(parse_mode="HTML")
        mock_bot_cls.assert_called_once_with(
            token="test-token",
            default=mock_default_cls.return_value,
        )
        assert bot.is_started is True

    def test_bot_property_raises_before_start(self) -> None:
        bot = AiogramBot(token="test-token")

        with pytest.raises(RuntimeError, match="not started"):
            _ = bot.bot

    @patch("app.infrastructure.telegram.aiogram_bot.Bot")
    @patch("app.infrastructure.telegram.aiogram_bot.DefaultBotProperties")
    async def test_shutdown_closes_session(
        self,
        _mock_default: MagicMock,
        mock_bot_cls: MagicMock,
    ) -> None:
        mock_instance = MagicMock()
        mock_instance.session.close = AsyncMock()
        mock_bot_cls.return_value = mock_instance

        bot = AiogramBot(token="test-token")
        bot.start()
        await bot.shutdown()

        mock_instance.session.close.assert_awaited_once()
        assert bot.is_started is False

    @patch("app.infrastructure.telegram.aiogram_bot.Bot")
    @patch("app.infrastructure.telegram.aiogram_bot.DefaultBotProperties")
    async def test_shutdown_is_idempotent(
        self,
        _mock_default: MagicMock,
        mock_bot_cls: MagicMock,
    ) -> None:
        mock_instance = MagicMock()
        mock_instance.session.close = AsyncMock()
        mock_bot_cls.return_value = mock_instance

        bot = AiogramBot(token="test-token")
        bot.start()
        await bot.shutdown()
        await bot.shutdown()

        mock_instance.session.close.assert_called_once()


class TestFactories:
    def test_from_config_uses_telegram_token(self) -> None:
        config = AppConfig(
            telegram_bot_token="bot123",
            telegram_chat_id="-100",
            mongodb_uri="mongodb://localhost:27017",
            database_url="sqlite+aiosqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
        )
        bot = AiogramBot.from_config(config)

        assert bot._token == "bot123"

    def test_custom_parse_mode(self) -> None:
        bot = AiogramBot(token="t", parse_mode="Markdown")
        assert bot._parse_mode == "Markdown"
