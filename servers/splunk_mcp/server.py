"""Splunk MCP Server — Security and Observability Analytics [STUB].

Roles: Observability, Security
"""
from __future__ import annotations
import json, os
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP
from miga_shared.agntcy import OASFRecord
from miga_shared.models import MIGARole, PlatformCapability, PlatformType
from miga_shared.server_base import add_health_tool, miga_lifespan

OASF = OASFRecord(
    name="splunk_mcp",
    description="[STUB] Splunk — Security Analytics, Log Management, and Threat Intelligence",
    platform=PlatformType.SPLUNK,
    roles=[MIGARole.OBSERVABILITY, MIGARole.SECURITY],
    skills=["log_search", "security_analytics", "dashboards", "threat_detection"],
    domains=["siem", "logging", "analytics", "threat_intelligence"],
    endpoint=f"http://splunk-mcp:{os.getenv('SPLUNK_MCP_PORT', '8012')}",
    capabilities=[
        PlatformCapability(tool_name="splunk_search", description="Run an SPL search query", roles=[MIGARole.OBSERVABILITY, MIGARole.SECURITY], platform=PlatformType.SPLUNK),
        PlatformCapability(tool_name="splunk_get_notable_events", description="Get notable/security events from ES", roles=[MIGARole.SECURITY], platform=PlatformType.SPLUNK),
        PlatformCapability(tool_name="splunk_get_threat_intel", description="Get threat intelligence matches", roles=[MIGARole.SECURITY], platform=PlatformType.SPLUNK),
    ],
    metadata={"status": "stub"},
)

@asynccontextmanager
async def app_lifespan():
    async with miga_lifespan(OASF) as state:
        yield state

mcp = FastMCP("splunk_mcp", lifespan=app_lifespan)
add_health_tool(mcp, PlatformType.SPLUNK, "splunk")
STUB = "\n\n> ⚠️ **STUB** — Returns mock data."

@mcp.tool(name="splunk_search", annotations={"readOnlyHint": True})
async def search(query: str = "index=main earliest=-1h | stats count by sourcetype", ctx=None) -> str:
    """[STUB] Run an SPL search query against Splunk."""
    return json.dumps({"results": [
        {"sourcetype": "cisco:asa", "count": 24500},
        {"sourcetype": "cisco:ios", "count": 18200},
        {"sourcetype": "pan:traffic", "count": 12800},
        {"sourcetype": "linux:syslog", "count": 9400},
    ], "query": query, "_stub": True}, indent=2) + STUB

@mcp.tool(name="splunk_get_notable_events", annotations={"readOnlyHint": True})
async def get_notable_events(ctx=None) -> str:
    """[STUB] Get Splunk Enterprise Security notable events."""
    return json.dumps({"notable_events": [
        {"title": "Brute Force Access Behavior Detected", "severity": "high", "src": "10.5.1.200", "dest": "10.1.1.5", "status": "new", "timestamp": "2025-01-15T14:10:00Z"},
        {"title": "Excessive DNS Queries", "severity": "medium", "src": "10.10.2.100", "dest": "8.8.8.8", "status": "in_progress", "timestamp": "2025-01-15T13:45:00Z"},
    ], "_stub": True}, indent=2) + STUB

@mcp.tool(name="splunk_get_threat_intel", annotations={"readOnlyHint": True})
async def get_threat_intel(indicator: str = "203.0.113.50", ctx=None) -> str:
    """[STUB] Look up threat intelligence for an indicator (IP, domain, hash)."""
    return json.dumps({"indicator": indicator, "matches": [
        {"source": "abuse.ch", "threat_type": "C2", "confidence": 85, "first_seen": "2025-01-10"},
        {"source": "talos", "threat_type": "malware_distribution", "confidence": 72, "first_seen": "2025-01-12"},
    ], "_stub": True}, indent=2) + STUB

if __name__ == "__main__":
    mcp.run(transport="streamable_http", port=int(os.getenv("SPLUNK_MCP_PORT", "8012")))
