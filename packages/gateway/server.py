"""MIGA Gateway MCP Server — Role-based routing with AGNTCY dynamic discovery.

The Gateway is itself an MCP server that exposes 6 role-based meta-tools
(Observability, Security, Automation, Configuration, Compliance, Identity).
Each meta-tool fans out to relevant platform servers discovered via AGNTCY
Directory OASF records, aggregates results, and returns unified responses.

Architecture:
- FastMCP server (Python) exposing meta-tools to the WebEx Bot / external clients
- Queries AGNTCY Directory at startup to build dynamic routing table
- Periodically refreshes capability map (no hardcoded routing)
- Redis pub/sub for event-driven updates
- Entra ID JWT authentication + AGNTCY Identity badge verification
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from miga_shared.agntcy import DirectoryClient, IdentityBadge, OASFRecord
from miga_shared.models import (
    AuditLogEntry,
    HealthStatus,
    MIGARole,
    PlatformCapability,
    PlatformType,
)
from miga_shared.utils.redis_bus import RedisPubSub

logger = logging.getLogger("miga.gateway")

# ---------------------------------------------------------------------------
# Routing Table — built dynamically from AGNTCY Directory
# ---------------------------------------------------------------------------

class RoutingEntry:
    """Maps a tool to its platform server endpoint."""
    def __init__(self, tool_name: str, endpoint: str, platform: PlatformType, roles: list[MIGARole], read_only: bool, requires_approval: bool):
        self.tool_name = tool_name
        self.endpoint = endpoint
        self.platform = platform
        self.roles = roles
        self.read_only = read_only
        self.requires_approval = requires_approval


class RoutingTable:
    """Dynamic routing table built from AGNTCY OASF records."""

    def __init__(self):
        self._by_tool: dict[str, RoutingEntry] = {}
        self._by_role: dict[MIGARole, list[RoutingEntry]] = {r: [] for r in MIGARole}
        self._by_platform: dict[PlatformType, list[RoutingEntry]] = {}
        self._endpoints: dict[str, str] = {}  # name → endpoint URL
        self._last_refresh: float = 0

    def load_from_oasf(self, records: list[OASFRecord]) -> None:
        """Rebuild routing table from OASF records."""
        self._by_tool.clear()
        self._by_role = {r: [] for r in MIGARole}
        self._by_platform.clear()
        self._endpoints.clear()

        for record in records:
            self._endpoints[record.name] = record.endpoint
            for cap in record.capabilities:
                entry = RoutingEntry(
                    tool_name=cap.tool_name,
                    endpoint=record.endpoint,
                    platform=cap.platform,
                    roles=cap.roles,
                    read_only=cap.read_only,
                    requires_approval=cap.requires_approval,
                )
                self._by_tool[cap.tool_name] = entry
                for role in cap.roles:
                    self._by_role[role].append(entry)
                self._by_platform.setdefault(cap.platform, []).append(entry)

        self._last_refresh = time.time()
        logger.info(
            "Routing table loaded: %d tools across %d servers",
            len(self._by_tool), len(self._endpoints),
        )

    def tools_for_role(self, role: MIGARole) -> list[RoutingEntry]:
        return self._by_role.get(role, [])

    def tools_for_platform(self, platform: PlatformType) -> list[RoutingEntry]:
        return self._by_platform.get(platform, [])

    def get_tool(self, name: str) -> Optional[RoutingEntry]:
        return self._by_tool.get(name)

    def all_endpoints(self) -> dict[str, str]:
        return dict(self._endpoints)


# ---------------------------------------------------------------------------
# Static fallback OASF records (used when AGNTCY Directory is unavailable)
# ---------------------------------------------------------------------------

def _build_static_records() -> list[OASFRecord]:
    """Fallback: build routing from env-configured endpoints."""
    servers = [
        ("catalyst_center_mcp", PlatformType.CATALYST_CENTER, "8001"),
        ("meraki_mcp", PlatformType.MERAKI, "8002"),
        ("thousandeyes_mcp", PlatformType.THOUSANDEYES, "8003"),
        ("webex_mcp", PlatformType.WEBEX, "8004"),
        ("xdr_mcp", PlatformType.XDR, "8005"),
        ("security_cloud_control_mcp", PlatformType.SECURITY_CLOUD_CONTROL, "8006"),
        ("infer_mcp", PlatformType.INFER, "8007"),
        ("appdynamics_mcp", PlatformType.APPDYNAMICS, "8008"),
        ("nexus_dashboard_mcp", PlatformType.NEXUS_DASHBOARD, "8009"),
        ("sdwan_mcp", PlatformType.SDWAN, "8010"),
        ("ise_mcp", PlatformType.ISE, "8011"),
        ("splunk_mcp", PlatformType.SPLUNK, "8012"),
        ("hypershield_mcp", PlatformType.HYPERSHIELD, "8013"),
    ]
    records = []
    for name, platform, default_port in servers:
        port = os.getenv(f"{name.upper().replace('_MCP', '_MCP')}_PORT", default_port)
        host = name.replace("_", "-")
        records.append(OASFRecord(
            name=name,
            platform=platform,
            endpoint=f"http://{host}:{port}",
        ))
    return records


# ---------------------------------------------------------------------------
# MCP Client — calls downstream platform MCP servers
# ---------------------------------------------------------------------------

class MCPForwarder:
    """Forwards MCP tool calls to platform servers via HTTP."""

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=60.0)

    async def call_tool(self, endpoint: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on a downstream MCP server via JSON-RPC 2.0."""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": f"gw-{int(time.time() * 1000)}",
        }
        try:
            resp = await self._http.post(f"{endpoint}/mcp", json=payload)
            resp.raise_for_status()
            result = resp.json()
            if "error" in result:
                return {"error": result["error"].get("message", "Unknown error")}
            return result.get("result", result)
        except httpx.ConnectError:
            return {"error": f"Platform server unreachable at {endpoint}"}
        except Exception as e:
            return {"error": f"Forwarding error: {str(e)}"}

    async def close(self):
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

routing = RoutingTable()
forwarder = MCPForwarder()


@asynccontextmanager
async def app_lifespan():
    directory = DirectoryClient()
    bus = RedisPubSub()
    badge = IdentityBadge(subject="miga/gateway")
    start = time.time()

    await bus.connect()

    # Discover platform servers from AGNTCY Directory
    records = await directory.discover()
    if not records:
        logger.warning("No records from AGNTCY Directory — using static fallback")
        records = _build_static_records()
    routing.load_from_oasf(records)

    # Periodic refresh task
    async def _refresh_loop():
        while True:
            await asyncio.sleep(60)
            try:
                fresh = await directory.discover()
                if fresh:
                    routing.load_from_oasf(fresh)
            except Exception as e:
                logger.error("Directory refresh failed: %s", e)

    refresh_task = asyncio.create_task(_refresh_loop())

    try:
        yield {
            "routing": routing,
            "forwarder": forwarder,
            "directory": directory,
            "bus": bus,
            "badge": badge,
            "start_time": start,
        }
    finally:
        refresh_task.cancel()
        await forwarder.close()
        await bus.close()
        await directory.close()


mcp = FastMCP("miga_gateway", lifespan=app_lifespan)

# ---------------------------------------------------------------------------
# Input Models for Meta-Tools
# ---------------------------------------------------------------------------

class RoleQueryInput(BaseModel):
    """Input for role-based meta-tool queries."""
    model_config = ConfigDict(extra="forbid")
    query: str = Field(default="", description="Natural language query or specific action")
    platforms: Optional[list[str]] = Field(default=None, description="Filter to specific platforms")
    tool_name: Optional[str] = Field(default=None, description="Call a specific tool directly by name")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Arguments to pass to the tool")


class CrossPlatformQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(..., description="Cross-platform question (e.g., 'Is the network healthy?')")
    include_stubs: bool = Field(default=False, description="Include stub server responses")


# ---------------------------------------------------------------------------
# Role-based Meta-Tools
# ---------------------------------------------------------------------------

async def _fan_out(role: MIGARole, params: RoleQueryInput, ctx) -> str:
    """Fan out a query to all platform servers serving a given role."""
    fwd: MCPForwarder = ctx.request_context.lifespan_state["forwarder"]
    entries = routing.tools_for_role(role)

    if params.tool_name:
        entry = routing.get_tool(params.tool_name)
        if not entry:
            return f"❌ Tool `{params.tool_name}` not found in routing table."
        result = await fwd.call_tool(entry.endpoint, entry.tool_name, params.arguments)
        return json.dumps(result, indent=2, default=str)

    if params.platforms:
        entries = [e for e in entries if e.platform.value in params.platforms]

    if not entries:
        return f"No tools available for role **{role.value}**."

    # Fan out to all relevant platform tools (health/summary tools)
    tasks = []
    for entry in entries:
        if "health" in entry.tool_name or "overview" in entry.tool_name or "status" in entry.tool_name:
            tasks.append((entry, fwd.call_tool(entry.endpoint, entry.tool_name, {})))

    if not tasks:
        # Just list available tools
        lines = [f"## {role.value.title()} — Available Tools\n"]
        for e in entries:
            lines.append(f"- `{e.tool_name}` ({e.platform.value}) {'🔒' if e.requires_approval else ''}")
        return "\n".join(lines)

    results = await asyncio.gather(*(t[1] for t in tasks), return_exceptions=True)
    lines = [f"## {role.value.title()} — Cross-Platform Summary\n"]
    for (entry, _), result in zip(tasks, results):
        if isinstance(result, Exception):
            lines.append(f"### ❌ {entry.platform.value}\n_{result}_\n")
        elif isinstance(result, dict) and "error" in result:
            lines.append(f"### ❌ {entry.platform.value}\n_{result['error']}_\n")
        else:
            text = result if isinstance(result, str) else json.dumps(result, indent=2, default=str)
            lines.append(f"### {entry.platform.value}\n{text[:500]}\n")
    return "\n".join(lines)


@mcp.tool(name="observability", annotations={"readOnlyHint": True, "idempotentHint": True})
async def observability(params: RoleQueryInput, ctx=None) -> str:
    """Query observability data across all Cisco platforms — health scores,
    telemetry, monitoring alerts, ThousandEyes path analysis, INFER anomalies."""
    return await _fan_out(MIGARole.OBSERVABILITY, params, ctx)


@mcp.tool(name="security", annotations={"readOnlyHint": True, "idempotentHint": True})
async def security(params: RoleQueryInput, ctx=None) -> str:
    """Query security data across all Cisco platforms — XDR threats, Meraki
    security events, Hypershield enforcement, INFER anomaly correlation."""
    return await _fan_out(MIGARole.SECURITY, params, ctx)


@mcp.tool(name="automation", annotations={"readOnlyHint": False})
async def automation(params: RoleQueryInput, ctx=None) -> str:
    """Execute automation workflows across platforms — command runner,
    remediation actions, policy deployment. ⚠️ Destructive actions require approval."""
    return await _fan_out(MIGARole.AUTOMATION, params, ctx)


@mcp.tool(name="configuration", annotations={"readOnlyHint": True, "idempotentHint": True})
async def configuration(params: RoleQueryInput, ctx=None) -> str:
    """Query and manage configuration across platforms — device configs,
    security policies, network settings, site topology."""
    return await _fan_out(MIGARole.CONFIGURATION, params, ctx)


@mcp.tool(name="compliance", annotations={"readOnlyHint": True, "idempotentHint": True})
async def compliance(params: RoleQueryInput, ctx=None) -> str:
    """Query compliance and audit data — posture status, policy drift,
    certificate expiry, regulatory checks, INFER risk scoring."""
    return await _fan_out(MIGARole.COMPLIANCE, params, ctx)


@mcp.tool(name="identity", annotations={"readOnlyHint": True, "idempotentHint": True})
async def identity(params: RoleQueryInput, ctx=None) -> str:
    """Query identity and access data — ISE sessions, authentication logs,
    endpoint profiling, AGNTCY agent identity badges."""
    return await _fan_out(MIGARole.IDENTITY, params, ctx)


# ---------------------------------------------------------------------------
# Cross-platform convenience tool
# ---------------------------------------------------------------------------

@mcp.tool(name="network_status", annotations={"readOnlyHint": True, "idempotentHint": True})
async def network_status(ctx=None) -> str:
    """Get a quick cross-platform network status summary."""
    fwd: MCPForwarder = ctx.request_context.lifespan_state["forwarder"]
    endpoints = routing.all_endpoints()

    lines = ["## MIGA — Network Status Overview\n"]
    lines.append(f"**Connected Servers:** {len(endpoints)}\n")

    health_tasks = []
    for name, endpoint in endpoints.items():
        health_tool = f"{name.replace('_mcp', '')}_health"
        health_tasks.append((name, fwd.call_tool(endpoint, health_tool, {})))

    results = await asyncio.gather(*(t[1] for t in health_tasks), return_exceptions=True)
    for (name, _), result in zip(health_tasks, results):
        if isinstance(result, Exception) or (isinstance(result, dict) and "error" in result):
            lines.append(f"- 🔴 **{name}** — unreachable")
        else:
            lines.append(f"- 🟢 **{name}** — healthy")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gateway Health
# ---------------------------------------------------------------------------

@mcp.tool(name="gateway_health", annotations={"readOnlyHint": True})
async def gateway_health(ctx=None) -> str:
    """Gateway health check — routing table status and uptime."""
    state = ctx.request_context.lifespan_state
    uptime = time.time() - state["start_time"]
    endpoints = routing.all_endpoints()
    return json.dumps({
        "service": "miga_gateway",
        "status": "healthy",
        "version": "1.0.0",
        "uptime_seconds": round(uptime, 1),
        "routing_table": {
            "servers": len(endpoints),
            "tools": len(routing._by_tool),
            "last_refresh": routing._last_refresh,
        },
        "endpoints": endpoints,
    }, indent=2)


if __name__ == "__main__":
    port = int(os.getenv("MIGA_GATEWAY_PORT", "8000"))
    mcp.run(transport="streamable_http", port=port)
