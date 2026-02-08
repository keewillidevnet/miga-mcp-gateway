"""Core data models shared across all MIGA services."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class MIGARole(str, Enum):
    """Gateway role taxonomy — the six categories of meta-tools."""
    OBSERVABILITY = "observability"
    SECURITY = "security"
    AUTOMATION = "automation"
    CONFIGURATION = "configuration"
    COMPLIANCE = "compliance"
    IDENTITY = "identity"


class PlatformType(str, Enum):
    """All supported Cisco platforms."""
    CATALYST_CENTER = "catalyst_center"
    MERAKI = "meraki"
    THOUSANDEYES = "thousandeyes"
    WEBEX = "webex"
    XDR = "xdr"
    SECURITY_CLOUD_CONTROL = "security_cloud_control"
    APPDYNAMICS = "appdynamics"
    NEXUS_DASHBOARD = "nexus_dashboard"
    SDWAN = "sdwan"
    ISE = "ise"
    SPLUNK = "splunk"
    HYPERSHIELD = "hypershield"
    SERVICENOW = "servicenow"
    NETBOX = "netbox"
    INFER = "infer"


class SeverityLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ToolResponse(BaseModel):
    """Standardized response wrapper for all MCP tool outputs."""
    model_config = ConfigDict(ser_json_timedelta="float")

    success: bool = True
    platform: PlatformType
    tool_name: str
    data: Any = None
    error: Optional[str] = None
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cached: bool = False

    def to_text(self) -> str:
        import json
        return json.dumps(self.model_dump(mode="json"), indent=2)


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    count: int
    offset: int = 0
    has_more: bool = False


# ---------------------------------------------------------------------------
# Event models (INFER / cross-platform)
# ---------------------------------------------------------------------------

class CorrelatedEvent(BaseModel):
    """Cross-platform event for INFER correlation engine."""
    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_platform: PlatformType
    event_type: str
    severity: SeverityLevel = SeverityLevel.INFO
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    affected_entities: list[str] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    correlation_group: Optional[str] = None

    def overlaps_with(self, other: CorrelatedEvent, window_seconds: int = 300) -> bool:
        delta = abs((self.timestamp - other.timestamp).total_seconds())
        return delta <= window_seconds and bool(
            set(self.affected_entities) & set(other.affected_entities)
        )


class AuditLogEntry(BaseModel):
    """Immutable audit record for every MCP tool invocation."""
    audit_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_upn: Optional[str] = None
    agntcy_badge_subject: Optional[str] = None
    tool_name: str
    platform: PlatformType
    action_type: str  # read | write | delete | execute
    parameters_hash: str
    result_summary: str = ""
    approved_by: Optional[str] = None


class HealthStatus(BaseModel):
    """Service health check response."""
    service: str
    status: str = "healthy"
    version: str = "1.0.0"
    platform: Optional[PlatformType] = None
    uptime_seconds: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)


class PlatformCapability(BaseModel):
    """Describes a single capability exposed by a platform server."""
    tool_name: str
    description: str
    roles: list[MIGARole]
    read_only: bool = True
    destructive: bool = False
    requires_approval: bool = False
    platform: PlatformType
