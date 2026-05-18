"""Telegram-native role validator with in-memory TTL cache.

Encapsulates the logic of querying the Telegram Bot API for a user's
chat-member status and caching the result to avoid rate-limiting.
"""

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from cachetools import TTLCache

from app.infrastructure.logging.structured_logger import get_logger

logger = get_logger(__name__)

_DEFAULT_CACHE_MAXSIZE: int = 1000
_DEFAULT_CACHE_TTL_SECONDS: int = 600


class TelegramRoleValidator:
    """Validates whether a Telegram user holds an elevated role (creator or
    administrator) in a specific chat.

    Results are cached in memory with a TTL to prevent flooding the
    Telegram Bot API.
    """

    def __init__(
        self,
        bot: Bot,
        chat_id: int | str,
        *,
        ttl_seconds: int = _DEFAULT_CACHE_TTL_SECONDS,
        maxsize: int = _DEFAULT_CACHE_MAXSIZE,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._cache: TTLCache[int, bool] = TTLCache(maxsize=maxsize, ttl=ttl_seconds)

    async def is_admin(self, user_id: int) -> bool:
        """Return ``True`` when *user_id* is a creator or administrator of
        the configured chat.

        Caches the result for the configured TTL.  If the Telegram API call
        fails the method returns ``False`` (fail-closed).
        """
        logger.info(
            "-> Verificando Telegram Admin para user %s en chat %s",
            user_id,
            self._chat_id,
        )

        cached: bool | None = self._cache.get(user_id)
        if cached is not None:
            logger.info("-> Cache Hit: %s", cached)
            return cached

        try:
            member = await self._bot.get_chat_member(self._chat_id, user_id)
            logger.info(
                "Telegram Auth Check - User: %s, Status: %s",
                user_id,
                member.status,
            )
            is_admin = member.status in {
                ChatMemberStatus.CREATOR,
                ChatMemberStatus.ADMINISTRATOR,
            }
        except TelegramAPIError as exc:
            logger.error(
                "-> Error API Telegram: %s",
                exc,
                exc_info=True,
            )
            return False

        self._cache[user_id] = is_admin
        return is_admin
