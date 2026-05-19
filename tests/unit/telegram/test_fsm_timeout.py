"""Unit tests for the FSM timeout monitor.

The monitor is exercised with mocked Redis, aiogram storage, and bot so
that no real network or persistence layer is required.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Bot
from aiogram.fsm.storage.redis import RedisStorage

from app.config import AppConfig
from app.telegram.fsm_timeout import FSMTimeoutMonitor
from app.telegram.states.backup_states import BackupStates


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig(
        telegram_bot_token="bot123",
        telegram_chat_id="-100",
        mongodb_uri="mongodb://localhost:27017",
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
    )


@pytest.fixture
def mock_bot() -> MagicMock:
    bot = MagicMock(spec=Bot)
    bot.id = 1
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def mock_storage() -> MagicMock:
    return MagicMock(spec=RedisStorage)


@pytest.fixture
def mock_redis() -> MagicMock:
    redis = AsyncMock()
    redis.close = AsyncMock()
    return redis


class TestFSMTimeoutMonitor:
    async def test_touch_records_timestamp(self, mock_redis: MagicMock) -> None:
        with patch("redis.asyncio.Redis.from_url", return_value=mock_redis):
            _ = FSMTimeoutMonitor(
                bot=MagicMock(),
                storage=MagicMock(),
                config=MagicMock(redis_url="redis://localhost"),
            )
            await FSMTimeoutMonitor.touch(mock_redis, user_id=42)

        mock_redis.zadd.assert_awaited_once()
        args = mock_redis.zadd.await_args.args
        assert args[0] == "fsm:backup:active"
        # args[1] is a dict {str(user_id): timestamp}
        scores = list(args[1].values())
        assert len(scores) == 1
        assert isinstance(scores[0], float)

    async def test_check_timeouts_resets_stale_sessions(
        self,
        app_config: AppConfig,
        mock_bot: MagicMock,
        mock_storage: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_redis.zrangebyscore = AsyncMock(return_value=[b"42"])
        mock_redis.zremrangebyscore = AsyncMock()

        # Simulate FSMContext.get_state returning a non-idle state
        mock_fsm_ctx = AsyncMock()
        mock_fsm_ctx.get_state = AsyncMock(return_value=BackupStates.selecting_backup_type.state)
        mock_fsm_ctx.set_state = AsyncMock()
        mock_fsm_ctx.set_data = AsyncMock()

        with patch("redis.asyncio.Redis.from_url", return_value=mock_redis):
            monitor = FSMTimeoutMonitor(
                bot=mock_bot,
                storage=mock_storage,
                config=app_config,
            )
            with patch("app.telegram.fsm_timeout.FSMContext", return_value=mock_fsm_ctx):
                await monitor._check_timeouts()

        mock_fsm_ctx.set_state.assert_awaited_once_with(BackupStates.idle)
        mock_fsm_ctx.set_data.assert_awaited_once_with({})
        mock_bot.send_message.assert_awaited_once()
        mock_redis.zremrangebyscore.assert_awaited_once()

    async def test_check_timeouts_skips_idle_sessions(
        self,
        app_config: AppConfig,
        mock_bot: MagicMock,
        mock_storage: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_redis.zrangebyscore = AsyncMock(return_value=[b"42"])
        mock_redis.zremrangebyscore = AsyncMock()

        mock_fsm_ctx = AsyncMock()
        mock_fsm_ctx.get_state = AsyncMock(return_value=BackupStates.idle.state)
        mock_fsm_ctx.set_state = AsyncMock()

        with patch("redis.asyncio.Redis.from_url", return_value=mock_redis):
            monitor = FSMTimeoutMonitor(
                bot=mock_bot,
                storage=mock_storage,
                config=app_config,
            )
            with patch("app.telegram.fsm_timeout.FSMContext", return_value=mock_fsm_ctx):
                await monitor._check_timeouts()

        mock_fsm_ctx.set_state.assert_not_awaited()
        mock_bot.send_message.assert_not_awaited()
        mock_redis.zremrangebyscore.assert_awaited_once()

    async def test_check_timeouts_skips_when_no_expired(
        self,
        app_config: AppConfig,
        mock_bot: MagicMock,
        mock_storage: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_redis.zrangebyscore = AsyncMock(return_value=[])
        mock_redis.zremrangebyscore = AsyncMock()

        with patch("redis.asyncio.Redis.from_url", return_value=mock_redis):
            monitor = FSMTimeoutMonitor(
                bot=mock_bot,
                storage=mock_storage,
                config=app_config,
            )
            await monitor._check_timeouts()

        mock_redis.zremrangebyscore.assert_not_awaited()
        mock_bot.send_message.assert_not_awaited()

    async def test_stop_cancels_task_and_closes_redis(
        self,
        app_config: AppConfig,
        mock_bot: MagicMock,
        mock_storage: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        with patch("redis.asyncio.Redis.from_url", return_value=mock_redis):
            monitor = FSMTimeoutMonitor(
                bot=mock_bot,
                storage=mock_storage,
                config=app_config,
            )
            # Start and immediately stop
            monitor.start()
            await asyncio.sleep(0.05)
            await monitor.stop()

        mock_redis.close.assert_awaited_once()
        assert monitor._task is None
