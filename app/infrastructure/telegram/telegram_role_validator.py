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
        chat_id: int,
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
        cached: bool | None = self._cache.get(user_id)
        if cached is not None:
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
            logger.warning(
                "telegram_role_validator_api_error",
                exc_info=exc,
                user_id=user_id,
                chat_id=self._chat_id,
            )
            return False

        self._cache[user_id] = is_admin
        return is_admin
