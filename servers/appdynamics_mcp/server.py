"""AppDynamics MCP Server — Application Performance Monitoring [STUB].

Roles: Observability
Status: Stubbed with typed tool signatures and mock data.
        Ready for community implementation.

When implemented, will expose:
- Application health and performance scoring
- Business transaction monitoring and anomaly detection
- Infrastructure correlation (server, container, network)
- Error analytics and root cause analysis
- AI-driven anomaly detection (Cognition Engine)
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from miga_shared.agntcy import OASFRecord
from miga_shared.models import MIGARole, PlatformCapability, PlatformType
from miga_shared.server_base import add_health_tool, miga_lifespan

OASF = OASFRecord(
    name="appdynamics_mcp",
    description="[STUB] Cisco AppDynamics — Application Performance Monitoring and AI Analytics",
    platform=PlatformType.APPDYNAMICS,
    roles=[MIGARole.OBSERVABILITY],
    skills=["application_health", "business_transactions", "error_analytics", "anomaly_detection"],
    domains=["apm", "observability", "application"],
    endpoint=f"http://appdynamics-mcp:{os.getenv('APPDYNAMICS_MCP_PORT', '8008')}",
    capabilities=[
        PlatformCapability(tool_name="appdynamics_get_app_health", description="Get application health overview", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.APPDYNAMICS),
        PlatformCapability(tool_name="appdynamics_get_business_transactions", description="Get business transaction performance", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.APPDYNAMICS),
        PlatformCapability(tool_name="appdynamics_get_errors", description="Get error analytics and stack traces", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.APPDYNAMICS),
        PlatformCapability(tool_name="appdynamics_get_anomalies", description="Get Cognition Engine anomaly detections", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.APPDYNAMICS),
    ],
    metadata={"status": "stub", "contribution_guide": "docs/CONTRIBUTING.md"},
)


@asynccontextmanager
async def app_lifespan():
    async with miga_lifespan(OASF, api_factory=None) as state:
        yield state

mcp = FastMCP("appdynamics_mcp", lifespan=app_lifespan)
add_health_tool(mcp, PlatformType.APPDYNAMICS, "appdynamics")

# -- Stub Input Models -------------------------------------------------------

class AppHealthInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_name: str = Field(default="", description="Application name (empty = all apps)")
    time_range: str = Field(default="last_1_hour", description="Time range: last_15_minutes, last_1_hour, last_6_hours, last_24_hours")

class BusinessTxInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_id: int = Field(..., description="AppDynamics application ID")
    tier: str = Field(default="", description="Filter by tier name")
    limit: int = Field(default=25, ge=1, le=200)

class ErrorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_id: int = Field(..., description="AppDynamics application ID")
    severity: str = Field(default="ERROR", description="ERROR or WARN")
    limit: int = Field(default=25, ge=1, le=200)

# -- Stub Tools ---------------------------------------------------------------

STUB_MSG = "\n\n> ⚠️ **STUB** — This server returns mock data. See `docs/CONTRIBUTING.md` to implement."

@mcp.tool(name="appdynamics_get_app_health", annotations={"readOnlyHint": True})
async def get_app_health(params: AppHealthInput, ctx=None) -> str:
    """[STUB] Get application health overview from AppDynamics."""
    return json.dumps({
        "applications": [
            {"name": "ecommerce-web", "id": 101, "health": "NORMAL", "calls_per_min": 12450, "avg_response_ms": 142, "error_rate": 0.3},
            {"name": "payment-service", "id": 102, "health": "WARNING", "calls_per_min": 3200, "avg_response_ms": 890, "error_rate": 2.1},
            {"name": "inventory-api", "id": 103, "health": "NORMAL", "calls_per_min": 8700, "avg_response_ms": 45, "error_rate": 0.1},
        ],
        "_stub": True,
    }, indent=2) + STUB_MSG

@mcp.tool(name="appdynamics_get_business_transactions", annotations={"readOnlyHint": True})
async def get_business_transactions(params: BusinessTxInput, ctx=None) -> str:
    """[STUB] Get business transaction performance metrics."""
    return json.dumps({
        "transactions": [
            {"name": "/api/checkout", "tier": "web-tier", "calls": 450, "avg_response_ms": 1200, "errors": 12, "slow": True},
            {"name": "/api/search", "tier": "web-tier", "calls": 8200, "avg_response_ms": 85, "errors": 3, "slow": False},
            {"name": "/api/payment/process", "tier": "payment-tier", "calls": 430, "avg_response_ms": 2300, "errors": 28, "slow": True},
        ],
        "_stub": True,
    }, indent=2) + STUB_MSG

@mcp.tool(name="appdynamics_get_errors", annotations={"readOnlyHint": True})
async def get_errors(params: ErrorInput, ctx=None) -> str:
    """[STUB] Get error analytics and exception details."""
    return json.dumps({
        "errors": [
            {"name": "NullPointerException", "count": 142, "first_seen": "2025-01-15T10:00:00Z", "transaction": "/api/checkout"},
            {"name": "ConnectionTimeoutException", "count": 87, "first_seen": "2025-01-15T14:30:00Z", "transaction": "/api/payment/process"},
        ],
        "_stub": True,
    }, indent=2) + STUB_MSG

@mcp.tool(name="appdynamics_get_anomalies", annotations={"readOnlyHint": True})
async def get_anomalies(ctx=None) -> str:
    """[STUB] Get Cognition Engine anomaly detections."""
    return json.dumps({
        "anomalies": [
            {"type": "RESPONSE_TIME", "app": "payment-service", "severity": "WARNING", "deviation_pct": 340, "detected_at": "2025-01-15T14:25:00Z"},
        ],
        "_stub": True,
    }, indent=2) + STUB_MSG

if __name__ == "__main__":
    mcp.run(transport="streamable_http", port=int(os.getenv("APPDYNAMICS_MCP_PORT", "8008")))
