"""Unit tests for AuditLog domain entity."""

import pytest

from app.domain.entities.audit_log import AuditLog


class TestAuditLogIpValidation:
    def test_accepts_valid_ipv4(self) -> None:
        log = AuditLog(
            telegram_id=1,
            action="BACKUP",
            topic="BACKUP_REQUESTS",
            result="SUCCESS",
            ip_address="192.168.1.1",
        )
        assert log.ip_address == "192.168.1.1"

    def test_accepts_valid_ipv6(self) -> None:
        log = AuditLog(
            telegram_id=1,
            action="BACKUP",
            topic="BACKUP_REQUESTS",
            result="SUCCESS",
            ip_address="2001:0db8:85a3::8a2e:0370:7334",
        )
        assert log.ip_address == "2001:0db8:85a3::8a2e:0370:7334"

    def test_accepts_none(self) -> None:
        log = AuditLog(
            telegram_id=1,
            action="BACKUP",
            topic="BACKUP_REQUESTS",
            result="SUCCESS",
            ip_address=None,
        )
        assert log.ip_address is None

    def test_rejects_invalid_ip(self) -> None:
        with pytest.raises(ValueError, match="invalid IP address"):
            AuditLog(
                telegram_id=1,
                action="BACKUP",
                topic="BACKUP_REQUESTS",
                result="SUCCESS",
                ip_address="not-an-ip",
            )

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError, match="invalid IP address"):
            AuditLog(
                telegram_id=1,
                action="BACKUP",
                topic="BACKUP_REQUESTS",
                result="SUCCESS",
                ip_address="",
            )

    def test_rejects_out_of_range_octets(self) -> None:
        with pytest.raises(ValueError, match="invalid IP address"):
            AuditLog(
                telegram_id=1,
                action="BACKUP",
                topic="BACKUP_REQUESTS",
                result="SUCCESS",
                ip_address="256.1.1.1",
            )
