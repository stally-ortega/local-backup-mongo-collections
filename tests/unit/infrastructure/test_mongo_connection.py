"""Unit tests for MongoConnection."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import AppConfig
from app.infrastructure.mongo.mongo_connection import MongoConnection


class TestMongoConnectionLifecycle:
    def test_client_raises_before_connect(self) -> None:
        conn = MongoConnection("mongodb://localhost:27017")
        with pytest.raises(RuntimeError, match="not open"):
            _ = conn.client

    def test_is_open_false_before_connect(self) -> None:
        conn = MongoConnection("mongodb://localhost:27017")
        assert conn.is_open is False

    @patch("app.infrastructure.mongo.mongo_connection.AsyncIOMotorClient")
    def test_connect_creates_client(self, mock_client_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance

        conn = MongoConnection("mongodb://localhost:27017")
        conn.connect()

        assert conn.is_open is True
        assert conn.client is mock_instance
        mock_client_cls.assert_called_once_with(
            "mongodb://localhost:27017",
            serverSelectionTimeoutMS=5_000,
            connectTimeoutMS=5_000,
            socketTimeoutMS=10_000,
            maxPoolSize=50,
        )

    @patch("app.infrastructure.mongo.mongo_connection.AsyncIOMotorClient")
    def test_connect_recreates_when_already_open(self, mock_client_cls: MagicMock) -> None:
        first = MagicMock()
        second = MagicMock()
        mock_client_cls.side_effect = [first, second]

        conn = MongoConnection("mongodb://localhost:27017")
        conn.connect()
        conn.connect()

        assert conn.client is second
        first.close.assert_called_once()
        assert mock_client_cls.call_count == 2

    @patch("app.infrastructure.mongo.mongo_connection.AsyncIOMotorClient")
    def test_close_is_idempotent(self, mock_client_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance

        conn = MongoConnection("mongodb://localhost:27017")
        conn.connect()
        conn.close()
        conn.close()

        assert conn.is_open is False
        mock_instance.close.assert_called_once()


class TestMongoConnectionPing:
    @patch("app.infrastructure.mongo.mongo_connection.AsyncIOMotorClient")
    async def test_ping_returns_false_when_not_connected(self, _mock: MagicMock) -> None:
        conn = MongoConnection("mongodb://localhost:27017")
        result = await conn.ping()
        assert result is False

    @patch("app.infrastructure.mongo.mongo_connection.AsyncIOMotorClient")
    async def test_ping_returns_true_on_success(self, mock_client_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_admin = MagicMock()
        mock_admin.command = AsyncMock(return_value={"ok": 1})
        mock_instance.admin = mock_admin
        mock_client_cls.return_value = mock_instance

        conn = MongoConnection("mongodb://localhost:27017")
        conn.connect()
        result = await conn.ping()

        assert result is True
        mock_admin.command.assert_awaited_once_with("ping")

    @patch("app.infrastructure.mongo.mongo_connection.AsyncIOMotorClient")
    async def test_ping_returns_false_on_exception(self, mock_client_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_admin = MagicMock()
        mock_admin.command = AsyncMock(side_effect=ConnectionError("boom"))
        mock_instance.admin = mock_admin
        mock_client_cls.return_value = mock_instance

        conn = MongoConnection("mongodb://localhost:27017")
        conn.connect()
        result = await conn.ping()

        assert result is False


class TestMongoConnectionFromConfig:
    @patch("app.infrastructure.mongo.mongo_connection.AsyncIOMotorClient")
    def test_from_config_uses_uri(self, mock_client_cls: MagicMock) -> None:
        cfg = AppConfig(
            telegram_bot_token="t",
            telegram_chat_id="-100",
            mongodb_uri="mongodb://user:pass@host:27017/db",
            database_url="sqlite+aiosqlite:///:memory:",
        )
        conn = MongoConnection.from_config(cfg)
        assert conn._uri == "mongodb://user:pass@host:27017/db"


class TestMongoConnectionUriMasking:
    def test_uri_masked_with_credentials(self) -> None:
        conn = MongoConnection("mongodb://user:secret@mongodb.example.com:27017")
        assert conn._uri_masked == "mongodb://***@mongodb.example.com"

    def test_uri_masked_without_credentials(self) -> None:
        conn = MongoConnection("mongodb://localhost:27017")
        assert conn._uri_masked == "mongodb://***@localhost"

    def test_uri_masked_malformed_fallback(self) -> None:
        conn = MongoConnection("not-a-valid-uri")
        assert conn._uri_masked == "mongodb://***@unknown"
