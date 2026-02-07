"""Tests for miga_shared models, formatters, AGNTCY, and error handling."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from miga_shared.models import (
    AuditLogEntry,
    CorrelatedEvent,
    HealthStatus,
    MIGARole,
    PlatformCapability,
    PlatformType,
    SeverityLevel,
    ToolResponse,
)
from miga_shared.errors import (
    ApprovalRequiredError,
    AuthenticationError,
    MIGAError,
    PlatformAPIError,
    RateLimitError,
)
from miga_shared.utils.formatters import Fmt
from miga_shared.agntcy import OASFRecord


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TestMIGARole:
    def test_all_roles_defined(self):
        roles = list(MIGARole)
        assert len(roles) == 6
        assert MIGARole.OBSERVABILITY in roles
        assert MIGARole.SECURITY in roles
        assert MIGARole.AUTOMATION in roles
        assert MIGARole.CONFIGURATION in roles
        assert MIGARole.COMPLIANCE in roles
        assert MIGARole.IDENTITY in roles


class TestPlatformType:
    def test_all_platforms_defined(self):
        platforms = list(PlatformType)
        assert len(platforms) == 13
        assert PlatformType.CATALYST_CENTER in platforms
        assert PlatformType.INFER in platforms
        assert PlatformType.HYPERSHIELD in platforms


class TestToolResponse:
    def test_default_values(self):
        resp = ToolResponse(
            platform=PlatformType.MERAKI,
            tool_name="meraki_get_org_overview",
            data={"networks": 5},
        )
        assert resp.success is True
        assert resp.cached is False
        assert resp.error is None
        assert resp.correlation_id  # auto-generated UUID
        assert resp.timestamp

    def test_to_text(self):
        resp = ToolResponse(
            platform=PlatformType.XDR,
            tool_name="xdr_get_incidents",
            data={"count": 3},
        )
        text = resp.to_text()
        parsed = json.loads(text)
        assert parsed["platform"] == "xdr"
        assert parsed["data"]["count"] == 3

    def test_error_response(self):
        resp = ToolResponse(
            platform=PlatformType.CATALYST_CENTER,
            tool_name="catalyst_get_health",
            success=False,
            error="Connection timeout",
        )
        assert resp.success is False
        assert "timeout" in resp.error.lower()


class TestCorrelatedEvent:
    def test_overlaps_with_same_entity_within_window(self):
        now = datetime.now(timezone.utc)
        e1 = CorrelatedEvent(
            source_platform=PlatformType.THOUSANDEYES,
            event_type="path_loss",
            timestamp=now,
            affected_entities=["switch-01", "10.1.1.1"],
        )
        e2 = CorrelatedEvent(
            source_platform=PlatformType.MERAKI,
            event_type="vpn_tunnel_flap",
            timestamp=now + timedelta(seconds=120),
            affected_entities=["switch-01", "10.2.2.2"],
        )
        assert e1.overlaps_with(e2, window_seconds=300)

    def test_no_overlap_different_entities(self):
        now = datetime.now(timezone.utc)
        e1 = CorrelatedEvent(
            source_platform=PlatformType.XDR,
            event_type="alert",
            timestamp=now,
            affected_entities=["host-a"],
        )
        e2 = CorrelatedEvent(
            source_platform=PlatformType.MERAKI,
            event_type="alert",
            timestamp=now + timedelta(seconds=60),
            affected_entities=["host-b"],
        )
        assert not e1.overlaps_with(e2)

    def test_no_overlap_outside_window(self):
        now = datetime.now(timezone.utc)
        e1 = CorrelatedEvent(
            source_platform=PlatformType.CATALYST_CENTER,
            event_type="issue",
            timestamp=now,
            affected_entities=["switch-01"],
        )
        e2 = CorrelatedEvent(
            source_platform=PlatformType.MERAKI,
            event_type="alert",
            timestamp=now + timedelta(seconds=600),
            affected_entities=["switch-01"],
        )
        assert not e1.overlaps_with(e2, window_seconds=300)


class TestAuditLogEntry:
    def test_creates_with_required_fields(self):
        entry = AuditLogEntry(
            correlation_id="test-123",
            tool_name="catalyst_run_command",
            platform=PlatformType.CATALYST_CENTER,
            action_type="execute",
            parameters_hash="abc123",
        )
        assert entry.audit_id  # auto UUID
        assert entry.user_upn is None
        assert entry.approved_by is None


class TestHealthStatus:
    def test_defaults(self):
        h = HealthStatus(service="test_service")
        assert h.status == "healthy"
        assert h.version == "1.0.0"


class TestPlatformCapability:
    def test_read_only_by_default(self):
        cap = PlatformCapability(
            tool_name="test_tool",
            description="A test tool",
            roles=[MIGARole.OBSERVABILITY],
            platform=PlatformType.MERAKI,
        )
        assert cap.read_only is True
        assert cap.destructive is False
        assert cap.requires_approval is False


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class TestErrors:
    def test_miga_error_to_tool_error(self):
        err = MIGAError("Something failed", details="Check logs")
        msg = err.to_tool_error()
        assert "Something failed" in msg
        assert "Check logs" in msg

    def test_platform_api_error_includes_platform(self):
        err = PlatformAPIError("meraki", "Rate limited", status_code=429)
        assert "meraki" in str(err)
        assert "429" in str(err)

    def test_rate_limit_error(self):
        err = RateLimitError("thousandeyes", retry_after=30.0)
        assert err.retry_after == 30.0
        assert err.status_code == 429

    def test_auth_error(self):
        err = AuthenticationError("Invalid token")
        assert "Invalid token" in str(err)


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

class TestFormatters:
    def test_severity_emoji(self):
        assert Fmt.severity_emoji("critical") == "🔴"
        assert Fmt.severity_emoji("high") == "🟠"
        assert Fmt.severity_emoji("medium") == "🟡"
        assert Fmt.severity_emoji("low") == "🔵"
        assert Fmt.severity_emoji("info") == "⚪"
        assert Fmt.severity_emoji("unknown") == "⚪"

    def test_health_badge(self):
        assert "🟢" in Fmt.health_badge(95.0)
        assert "🟡" in Fmt.health_badge(75.0)
        assert "🟠" in Fmt.health_badge(55.0)
        assert "🔴" in Fmt.health_badge(30.0)

    def test_status_dot(self):
        assert Fmt.status_dot("online") == "🟢"
        assert Fmt.status_dot("reachable") == "🟢"
        assert Fmt.status_dot("offline") == "🔴"
        assert Fmt.status_dot("unknown") == "🔴"

    def test_ts_none(self):
        assert Fmt.ts(None) == "N/A"


# ---------------------------------------------------------------------------
# AGNTCY OASF
# ---------------------------------------------------------------------------

class TestOASFRecord:
    def test_to_dict(self):
        record = OASFRecord(
            name="test_mcp",
            description="Test server",
            platform=PlatformType.MERAKI,
            roles=[MIGARole.OBSERVABILITY, MIGARole.SECURITY],
            skills=["monitoring"],
            endpoint="http://test:8000",
            capabilities=[
                PlatformCapability(
                    tool_name="test_tool",
                    description="A tool",
                    roles=[MIGARole.OBSERVABILITY],
                    platform=PlatformType.MERAKI,
                ),
            ],
        )
        d = record.to_dict()
        assert d["name"] == "test_mcp"
        assert d["attributes"]["platform"] == "meraki"
        assert "observability" in d["attributes"]["roles"]
        assert len(d["modules"]["mcp_server"]["tools"]) == 1

    def test_from_dict(self):
        raw = {
            "name": "test_mcp",
            "version": "1.0.0",
            "description": "Test",
            "attributes": {
                "platform": "xdr",
                "roles": ["security"],
                "transport": "streamable_http",
                "endpoint": "http://xdr:8005",
            },
            "skills": ["threats"],
            "domains": ["security"],
            "modules": {
                "mcp_server": {
                    "tools": [
                        {"name": "xdr_get_incidents", "description": "Get incidents", "roles": ["security"], "read_only": True, "destructive": False, "requires_approval": False},
                    ]
                }
            },
        }
        record = OASFRecord.from_dict(raw)
        assert record.name == "test_mcp"
        assert record.platform == PlatformType.XDR
        assert len(record.capabilities) == 1
        assert record.capabilities[0].tool_name == "xdr_get_incidents"
