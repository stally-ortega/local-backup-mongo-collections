"""Tests for the structured logging factory."""

import json
import logging
from pathlib import Path
from typing import Generator

import pytest
import structlog

from app.infrastructure.logging.structured_logger import (
    clear_correlation_id,
    configure_logging,
    get_audit_logger,
    get_logger,
    set_correlation_id,
)


@pytest.fixture(autouse=True)
def _reset_logging_state() -> Generator[None, None, None]:
    """Reset structlog and stdlib logging state before and after each test."""
    structlog.reset_defaults()
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    audit = logging.getLogger("audit")
    for handler in audit.handlers[:]:
        audit.removeHandler(handler)
    root.setLevel(logging.WARNING)
    audit.setLevel(logging.WARNING)
    audit.propagate = False
    yield
    structlog.reset_defaults()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    for handler in audit.handlers[:]:
        audit.removeHandler(handler)
    root.setLevel(logging.WARNING)
    audit.setLevel(logging.WARNING)
    audit.propagate = False


class TestConfigureLogging:
    def test_creates_expected_handlers(self, tmp_path: Path) -> None:
        configure_logging(log_dir=tmp_path, json_format=True)
        root = logging.getLogger()
        assert len(root.handlers) == 3

        audit = logging.getLogger("audit")
        assert len(audit.handlers) == 2
        assert audit.propagate is False

    def test_json_format(self, tmp_path: Path) -> None:
        configure_logging(log_dir=tmp_path, json_format=True)
        logger = get_logger("test_json")
        set_correlation_id("corr-123")
        logger.info("json_event", source="pytest")

        for handler in logging.getLogger().handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        ops_log = tmp_path / "ops.log"
        assert ops_log.exists()
        lines = ops_log.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event"] == "json_event"
        assert data["level"] == "info"
        assert data["logger"] == "test_json"
        assert data["correlation_id"] == "corr-123"
        assert "timestamp" in data
        assert data["source"] == "pytest"

    def test_pretty_format(self, tmp_path: Path) -> None:
        configure_logging(log_dir=tmp_path, json_format=False)
        logger = get_logger("test_pretty")
        set_correlation_id("corr-pretty")
        logger.info("pretty_event")

        for handler in logging.getLogger().handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        ops_log = tmp_path / "ops.log"
        assert ops_log.exists()
        content = ops_log.read_text()
        assert "pretty_event" in content
        assert "corr-pretty" in content
        assert "info" in content
        assert "test_pretty" in content

    def test_audit_logger_routes_to_audit_stream(self, tmp_path: Path) -> None:
        configure_logging(log_dir=tmp_path, json_format=True)
        logger = get_audit_logger()
        logger.info("audit_event")

        for handler in logging.getLogger("audit").handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        audit_log = tmp_path / "audit.log"
        ops_log = tmp_path / "ops.log"

        assert audit_log.exists()
        lines = audit_log.read_text().strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["event"] == "audit_event"

        if ops_log.exists():
            assert ops_log.read_text().strip() == ""

    def test_regular_logger_routes_to_ops(self, tmp_path: Path) -> None:
        configure_logging(log_dir=tmp_path, json_format=True)
        logger = get_logger("test_ops")
        logger.info("ops_event")

        for handler in logging.getLogger().handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        ops_log = tmp_path / "ops.log"
        assert ops_log.exists()
        lines = ops_log.read_text().strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["event"] == "ops_event"

    def test_error_routes_to_both(self, tmp_path: Path) -> None:
        configure_logging(log_dir=tmp_path, json_format=True)
        logger = get_logger("test_err")
        logger.error("err_event")

        for handler in logging.getLogger().handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        ops_log = tmp_path / "ops.log"
        errors_log = tmp_path / "errors.log"

        assert ops_log.exists()
        assert errors_log.exists()
        ops_lines = ops_log.read_text().strip().splitlines()
        errors_lines = errors_log.read_text().strip().splitlines()
        assert len(ops_lines) == 1
        assert len(errors_lines) == 1
        assert json.loads(ops_lines[0])["event"] == "err_event"
        assert json.loads(errors_lines[0])["event"] == "err_event"

    def test_level_parameter_filters(self, tmp_path: Path) -> None:
        configure_logging(log_dir=tmp_path, json_format=True, level="WARNING")
        logger = get_logger("test_level")
        logger.info("should_not_appear")

        for handler in logging.getLogger().handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        ops_log = tmp_path / "ops.log"
        if ops_log.exists():
            assert ops_log.read_text().strip() == ""


class TestCorrelationId:
    def test_set_and_clear(self, tmp_path: Path) -> None:
        configure_logging(log_dir=tmp_path, json_format=True)
        logger = get_logger("test_cid")
        set_correlation_id("abc-123")
        logger.info("with_cid")

        for handler in logging.getLogger().handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        ops_log = tmp_path / "ops.log"
        data = json.loads(ops_log.read_text().strip().splitlines()[0])
        assert data["correlation_id"] == "abc-123"

        clear_correlation_id()
        logger.info("no_cid")

        for handler in logging.getLogger().handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        lines = ops_log.read_text().strip().splitlines()
        assert len(lines) == 2
        second = json.loads(lines[1])
        assert "correlation_id" not in second


