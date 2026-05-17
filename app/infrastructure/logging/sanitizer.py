"""Traceback sanitization utilities.

Removes sensitive data (URIs, passwords, tokens) from strings before
they are sent to external systems such as Telegram or log aggregators.
"""

import re

_MONGODB_URI_RE = re.compile(r"mongodb(?:\+srv)?://[^\s'\"<>]+")
_REDIS_URL_RE = re.compile(r"rediss?://[^\s'\"<>]+")
_TELEGRAM_TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{20,}")


def sanitize_traceback(text: str) -> str:
    """Redact credentials and secrets from *text*.

    Replaces MongoDB URIs, Redis URLs, and Telegram bot tokens with
    safe placeholders so that stack traces can be shared externally
    without leaking secrets.

    Parameters
    ----------
    text:
        Raw traceback or any string that may contain secrets.

    Returns
    -------
    Sanitized copy of *text*.
    """
    text = _MONGODB_URI_RE.sub("[REDACTED_MONGODB_URI]", text)
    text = _REDIS_URL_RE.sub("[REDACTED_REDIS_URL]", text)
    text = _TELEGRAM_TOKEN_RE.sub("[REDACTED_TELEGRAM_TOKEN]", text)
    return text
