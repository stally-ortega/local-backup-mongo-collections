"""Unit tests for the traceback sanitizer.

Ensures that sensitive URIs and tokens are redacted before tracebacks
are sent to external systems (Telegram, log aggregators, etc.).
"""

from app.infrastructure.logging.sanitizer import sanitize_traceback


class TestSanitizeTraceback:
    def test_redacts_mongodb_uri(self) -> None:
        raw = (
            "pymongo.errors.ConnectionFailure: " "mongodb+srv://user:secret@cluster.mongodb.net/db"
        )
        result = sanitize_traceback(raw)
        assert "[REDACTED_MONGODB_URI]" in result
        assert "secret" not in result

    def test_redacts_redis_url(self) -> None:
        raw = "redis://:myredispass@localhost:6379/0"
        result = sanitize_traceback(raw)
        assert "[REDACTED_REDIS_URL]" in result
        assert "myredispass" not in result

    def test_redacts_telegram_token(self) -> None:
        raw = "ValueError: invalid token " "123456789:AAH0LyA-Agf59Nme92lc5yT_Lo_b7k3XlxQ"
        result = sanitize_traceback(raw)
        assert "[REDACTED_TELEGRAM_TOKEN]" in result
        assert "AAH0LyA" not in result

    def test_leaves_safe_text_untouched(self) -> None:
        safe = "RuntimeError: something went wrong in module.py:42"
        result = sanitize_traceback(safe)
        assert result == safe

    def test_redacts_multiple_occurrences(self) -> None:
        raw = "conn1: mongodb://u:p@host1/db\n" "conn2: mongodb://u:p@host2/db"
        result = sanitize_traceback(raw)
        assert result.count("[REDACTED_MONGODB_URI]") == 2
