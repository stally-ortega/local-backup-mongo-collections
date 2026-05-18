"""Unit tests for TelegramNotifier."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.notifier.telegram_notifier import TelegramNotifier
from app.infrastructure.telegram.aiogram_bot import AiogramBot


@pytest.fixture
def mock_bot() -> MagicMock:
    mock = MagicMock()
    mock.send_message = AsyncMock()
    mock.edit_message_text = AsyncMock()
    mock.send_document = AsyncMock()
    return mock


@pytest.fixture
def aiogram_bot(mock_bot: MagicMock) -> AiogramBot:
    wrapper = AiogramBot(token="test-token")
    wrapper._bot = MagicMock()
    wrapper._bot.send_message = mock_bot.send_message
    wrapper._bot.edit_message_text = mock_bot.edit_message_text
    wrapper._bot.send_document = mock_bot.send_document
    return wrapper


@pytest.fixture
def notifier(aiogram_bot: AiogramBot) -> TelegramNotifier:
    return TelegramNotifier(aiogram_bot)


class TestSendMessage:
    async def test_calls_bot_with_html_and_topic(
        self,
        notifier: TelegramNotifier,
        mock_bot: MagicMock,
    ) -> None:
        await notifier.send_message(
            chat_id=-100,
            text="<b>Hello</b>",
            topic_id=5,
        )

        mock_bot.send_message.assert_awaited_once_with(
            chat_id=-100,
            text="&lt;b&gt;Hello&lt;/b&gt;",
            message_thread_id=5,
            request_timeout=30,
        )

    async def test_retries_on_failure_then_succeeds(
        self,
        notifier: TelegramNotifier,
        mock_bot: MagicMock,
    ) -> None:
        mock_bot.send_message.side_effect = [
            ConnectionError("Telegram down"),
            None,
        ]

        await notifier.send_message(chat_id=1, text="msg")

        assert mock_bot.send_message.await_count == 2

    async def test_swallows_error_after_max_retries(
        self,
        notifier: TelegramNotifier,
        mock_bot: MagicMock,
    ) -> None:
        mock_bot.send_message.side_effect = ConnectionError("Telegram down")

        # Should not raise; error is logged and swallowed.
        await notifier.send_message(chat_id=1, text="msg")

        assert mock_bot.send_message.await_count == 3

    async def test_escapes_html_in_text(
        self,
        notifier: TelegramNotifier,
        mock_bot: MagicMock,
    ) -> None:
        await notifier.send_message(
            chat_id=1,
            text="<script>alert('xss')</script>",
        )

        mock_bot.send_message.assert_awaited_once_with(
            chat_id=1,
            text="&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;",
            message_thread_id=None,
            request_timeout=30,
        )


class TestEditMessage:
    async def test_calls_edit_message_text(
        self,
        notifier: TelegramNotifier,
        mock_bot: MagicMock,
    ) -> None:
        await notifier.edit_message(
            chat_id=-100,
            message_id=42,
            text="Updated",
        )

        mock_bot.edit_message_text.assert_awaited_once_with(
            chat_id=-100,
            message_id=42,
            text="Updated",
            request_timeout=30,
        )

    async def test_escapes_html_in_edit(
        self,
        notifier: TelegramNotifier,
        mock_bot: MagicMock,
    ) -> None:
        await notifier.edit_message(
            chat_id=-100,
            message_id=42,
            text="<a href='http://evil.com'>click</a>",
        )

        mock_bot.edit_message_text.assert_awaited_once_with(
            chat_id=-100,
            message_id=42,
            text="&lt;a href=&#x27;http://evil.com&#x27;&gt;click&lt;/a&gt;",
            request_timeout=30,
        )


class TestSendDocument:
    async def test_calls_send_document_with_fsinputfile(
        self,
        notifier: TelegramNotifier,
        mock_bot: MagicMock,
    ) -> None:
        with patch("app.infrastructure.notifier.telegram_notifier.FSInputFile") as mock_fs:
            mock_fs.return_value = MagicMock()

            await notifier.send_document(
                chat_id=-100,
                file_path=Path("/tmp/backup.tar.gz"),
                caption="Archive",
                topic_id=3,
            )

            mock_fs.assert_called_once_with(str(Path("/tmp/backup.tar.gz").resolve()))
            mock_bot.send_document.assert_awaited_once_with(
                chat_id=-100,
                document=mock_fs.return_value,
                caption="Archive",
                message_thread_id=3,
                request_timeout=30,
            )

    async def test_escapes_html_in_caption(
        self,
        notifier: TelegramNotifier,
        mock_bot: MagicMock,
    ) -> None:
        with patch("app.infrastructure.notifier.telegram_notifier.FSInputFile") as mock_fs:
            mock_fs.return_value = MagicMock()

            await notifier.send_document(
                chat_id=-100,
                file_path=Path("/tmp/backup.tar.gz"),
                caption="<script>pwn</script>",
            )

            mock_bot.send_document.assert_awaited_once_with(
                chat_id=-100,
                document=mock_fs.return_value,
                caption="&lt;script&gt;pwn&lt;/script&gt;",
                message_thread_id=None,
                request_timeout=30,
            )

    async def test_rejects_path_outside_base(
        self,
        aiogram_bot: AiogramBot,
        mock_bot: MagicMock,
    ) -> None:
        notifier = TelegramNotifier(aiogram_bot, base_path=Path("/safe/backups"))

        with pytest.raises(ValueError, match="outside the authorized base path"):
            await notifier.send_document(
                chat_id=-100,
                file_path=Path("/etc/passwd"),
            )

        mock_bot.send_document.assert_not_awaited()

    async def test_allows_path_inside_base(
        self,
        aiogram_bot: AiogramBot,
        mock_bot: MagicMock,
    ) -> None:
        notifier = TelegramNotifier(aiogram_bot, base_path=Path("/safe/backups"))

        with patch("app.infrastructure.notifier.telegram_notifier.FSInputFile") as mock_fs:
            mock_fs.return_value = MagicMock()

            await notifier.send_document(
                chat_id=-100,
                file_path=Path("/safe/backups/job.tar.gz"),
            )

            mock_bot.send_document.assert_awaited_once()


class TestRateLimiting:
    async def test_throttles_rapid_calls(
        self,
        notifier: TelegramNotifier,
        mock_bot: MagicMock,
    ) -> None:
        mock_bot.send_message.return_value = None

        t0 = asyncio.get_event_loop().time()
        for _ in range(35):
            await notifier.send_message(chat_id=1, text="x")
        t1 = asyncio.get_event_loop().time()

        # 35 messages with a 30 msg/s limit must span at least ~1 second.
        assert t1 - t0 >= 0.9
        assert mock_bot.send_message.await_count == 35


class TestRedisGlobalRateLimiter:
    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        redis = MagicMock()
        redis.zremrangebyscore = AsyncMock()
        redis.zcard = AsyncMock(return_value=0)
        redis.zadd = AsyncMock()
        redis.expire = AsyncMock()
        redis.zrange = AsyncMock(return_value=[])
        return redis

    async def test_acquire_records_request(self, mock_redis: MagicMock) -> None:
        from app.infrastructure.notifier.telegram_notifier import _RedisGlobalRateLimiter

        limiter = _RedisGlobalRateLimiter(mock_redis, limit=5, window_seconds=1.0)
        await limiter.acquire()

        mock_redis.zadd.assert_awaited_once()
        mock_redis.expire.assert_awaited_once()

    async def test_acquire_sleeps_when_limit_reached(self, mock_redis: MagicMock) -> None:
        import time

        from app.infrastructure.notifier.telegram_notifier import _RedisGlobalRateLimiter

        mock_redis.zcard = AsyncMock(return_value=5)
        mock_redis.zrange = AsyncMock(return_value=[(b"member", int(time.time() * 1000) - 500)])

        limiter = _RedisGlobalRateLimiter(mock_redis, limit=5, window_seconds=1.0)

        t0 = asyncio.get_event_loop().time()
        await limiter.acquire()
        t1 = asyncio.get_event_loop().time()

        assert t1 - t0 >= 0.4
        mock_redis.zadd.assert_awaited_once()

    async def test_acquire_trims_old_entries(self, mock_redis: MagicMock) -> None:
        from app.infrastructure.notifier.telegram_notifier import _RedisGlobalRateLimiter

        limiter = _RedisGlobalRateLimiter(mock_redis, limit=5, window_seconds=1.0)
        await limiter.acquire()

        mock_redis.zremrangebyscore.assert_awaited_once()


class TestTelegramNotifierWithRedisRateLimiter:
    async def test_uses_injected_redis_limiter(
        self, aiogram_bot: AiogramBot, mock_bot: MagicMock
    ) -> None:
        from app.infrastructure.notifier.telegram_notifier import _RedisGlobalRateLimiter

        mock_redis = MagicMock()
        mock_redis.zremrangebyscore = AsyncMock()
        mock_redis.zcard = AsyncMock(return_value=0)
        mock_redis.zadd = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=[])

        limiter = _RedisGlobalRateLimiter(mock_redis, limit=30, window_seconds=1.0)
        notifier = TelegramNotifier(aiogram_bot, rate_limiter=limiter)

        await notifier.send_message(chat_id=1, text="hello")

        mock_redis.zadd.assert_awaited_once()
        mock_bot.send_message.assert_awaited_once()
