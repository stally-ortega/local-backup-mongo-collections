"""Injectable wrapper around the aiogram 3.x ``Bot`` instance.

Manages the bot lifecycle (start / shutdown) and centralises default
properties such as ``parse_mode=HTML``.
"""

import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from app.config import AppConfig

logger = logging.getLogger(__name__)

_DEFAULT_PARSE_MODE: str = "HTML"


class AiogramBot:
    """Singleton-like wrapper for the Telegram Bot API client.

    Parameters
    ----------
    token:
        Bot token from @BotFather.
    parse_mode:
        Default parse mode for outgoing messages (``HTML`` by design).
    """

    def __init__(self, token: str, *, parse_mode: str = _DEFAULT_PARSE_MODE) -> None:
        self._token = token
        self._parse_mode = parse_mode
        self._bot: Bot | None = None

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: AppConfig) -> "AiogramBot":
        """Build from validated application settings."""
        return cls(token=config.telegram_bot_token)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Create the underlying aiogram ``Bot``."""
        if self._bot is not None:
            logger.warning("AiogramBot already started; recreating")
        self._bot = Bot(
            token=self._token,
            default=DefaultBotProperties(parse_mode=self._parse_mode),
        )
        logger.info("AiogramBot started")

    async def shutdown(self) -> None:
        """Close the aiohttp session and release resources."""
        if self._bot is not None:
            await self._bot.session.close()
            self._bot = None
            logger.info("AiogramBot shut down")

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def bot(self) -> Bot:
        """Return the active aiogram ``Bot`` instance.

        Raises
        ------
        RuntimeError
            When :meth:`start` has not been called.
        """
        if self._bot is None:
            raise RuntimeError("AiogramBot not started; call start() first")
        return self._bot

    @property
    def is_started(self) -> bool:
        """Return ``True`` when the bot instance has been created."""
        return self._bot is not None
