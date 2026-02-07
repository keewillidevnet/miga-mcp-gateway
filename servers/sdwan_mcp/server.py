"""SD-WAN MCP Server — Cisco SD-WAN (Catalyst SD-WAN) [STUB].

Roles: Configuration, Automation
"""
from __future__ import annotations
import json, os
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field
from miga_shared.agntcy import OASFRecord
from miga_shared.models import MIGARole, PlatformCapability, PlatformType
from miga_shared.server_base import add_health_tool, miga_lifespan

OASF = OASFRecord(
    name="sdwan_mcp",
    description="[STUB] Cisco Catalyst SD-WAN — WAN Fabric Orchestration and Analytics",
    platform=PlatformType.SDWAN,
    roles=[MIGARole.CONFIGURATION, MIGARole.AUTOMATION],
    skills=["wan_health", "tunnel_status", "policy_management", "device_templates"],
    domains=["wan", "sdwan", "routing", "overlay"],
    endpoint=f"http://sdwan-mcp:{os.getenv('SDWAN_MCP_PORT', '8010')}",
    capabilities=[
        PlatformCapability(tool_name="sdwan_get_device_health", description="Get SD-WAN edge device health", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.SDWAN),
        PlatformCapability(tool_name="sdwan_get_tunnel_status", description="Get IPsec tunnel status across fabric", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.SDWAN),
        PlatformCapability(tool_name="sdwan_get_policies", description="Get active routing and security policies", roles=[MIGARole.CONFIGURATION], platform=PlatformType.SDWAN),
        PlatformCapability(tool_name="sdwan_get_alarms", description="Get active alarms and events", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.SDWAN),
    ],
    metadata={"status": "stub"},
)

@asynccontextmanager
async def app_lifespan():
    async with miga_lifespan(OASF) as state:
        yield state

mcp = FastMCP("sdwan_mcp", lifespan=app_lifespan)
add_health_tool(mcp, PlatformType.SDWAN, "sdwan")
STUB_MSG = "\n\n> ⚠️ **STUB** — Returns mock data. See `docs/CONTRIBUTING.md` to implement."

@mcp.tool(name="sdwan_get_device_health", annotations={"readOnlyHint": True})
async def get_device_health(ctx=None) -> str:
    """[STUB] Get SD-WAN edge device health and reachability."""
    return json.dumps({"devices": [
        {"hostname": "branch-edge-01", "system_ip": "10.0.0.1", "site_id": 100, "model": "C8300-1N1S-4T2X", "status": "reachable", "cpu": 23, "memory": 41},
        {"hostname": "branch-edge-02", "system_ip": "10.0.0.2", "site_id": 200, "model": "C8300-1N1S-4T2X", "status": "reachable", "cpu": 45, "memory": 62},
        {"hostname": "dc-edge-01", "system_ip": "10.0.0.10", "site_id": 1, "model": "C8500-12X4QC", "status": "reachable", "cpu": 12, "memory": 35},
    ], "_stub": True}, indent=2) + STUB_MSG

@mcp.tool(name="sdwan_get_tunnel_status", annotations={"readOnlyHint": True})
async def get_tunnel_status(ctx=None) -> str:
    """[STUB] Get IPsec tunnel status across the SD-WAN fabric."""
    return json.dumps({"tunnels": [
        {"source": "10.0.0.1", "destination": "10.0.0.10", "color": "mpls", "state": "up", "jitter_ms": 2, "loss_pct": 0.0, "latency_ms": 15},
        {"source": "10.0.0.1", "destination": "10.0.0.10", "color": "biz-internet", "state": "up", "jitter_ms": 8, "loss_pct": 0.1, "latency_ms": 42},
        {"source": "10.0.0.2", "destination": "10.0.0.10", "color": "mpls", "state": "down", "jitter_ms": 0, "loss_pct": 100, "latency_ms": 0},
    ], "_stub": True}, indent=2) + STUB_MSG

@mcp.tool(name="sdwan_get_policies", annotations={"readOnlyHint": True})
async def get_policies(ctx=None) -> str:
    """[STUB] Get active SD-WAN routing and security policies."""
    return json.dumps({"policies": [
        {"name": "Business-Critical", "type": "app-route", "sequences": 5, "sites": [100, 200, 300]},
        {"name": "Default-Security", "type": "security", "sequences": 12, "sites": "all"},
    ], "_stub": True}, indent=2) + STUB_MSG

@mcp.tool(name="sdwan_get_alarms", annotations={"readOnlyHint": True})
async def get_alarms(ctx=None) -> str:
    """[STUB] Get active SD-WAN alarms."""
    return json.dumps({"alarms": [
        {"severity": "critical", "type": "control-vbond", "device": "branch-edge-02", "message": "MPLS tunnel to DC down", "timestamp": "2025-01-15T14:30:00Z"},
    ], "_stub": True}, indent=2) + STUB_MSG

if __name__ == "__main__":
    mcp.run(transport="streamable_http", port=int(os.getenv("SDWAN_MCP_PORT", "8010")))
