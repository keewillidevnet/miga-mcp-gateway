"""Catalyst Center MCP Server — AI Network Analytics, Assurance, and Automation.

Roles: Observability, Configuration, Automation
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from miga_shared.agntcy import OASFRecord
from miga_shared.clients import CiscoAPIClient
from miga_shared.models import (
    CorrelatedEvent, MIGARole, PlatformCapability, PlatformType, SeverityLevel, ToolResponse,
)
from miga_shared.server_base import add_health_tool, miga_lifespan
from miga_shared.utils.formatters import Fmt

# -- OASF record -------------------------------------------------------------
OASF = OASFRecord(
    name="catalyst_center_mcp",
    description="Cisco Catalyst Center AI Network Analytics, Assurance, and Configuration",
    platform=PlatformType.CATALYST_CENTER,
    roles=[MIGARole.OBSERVABILITY, MIGARole.CONFIGURATION, MIGARole.AUTOMATION],
    skills=["network_assurance", "device_inventory", "issue_detection", "topology", "command_runner"],
    domains=["networking", "campus", "wireless", "assurance"],
    endpoint=f"http://catalyst-center-mcp:{os.getenv('CATALYST_CENTER_MCP_PORT', '8001')}",
    capabilities=[
        PlatformCapability(tool_name="catalyst_network_health", description="Overall network health scores", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.CATALYST_CENTER),
        PlatformCapability(tool_name="catalyst_device_list", description="Managed device inventory", roles=[MIGARole.OBSERVABILITY, MIGARole.CONFIGURATION], platform=PlatformType.CATALYST_CENTER),
        PlatformCapability(tool_name="catalyst_issues", description="AI-detected issues with root cause", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.CATALYST_CENTER),
        PlatformCapability(tool_name="catalyst_client_health", description="Wired/wireless client health", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.CATALYST_CENTER),
        PlatformCapability(tool_name="catalyst_site_topology", description="Site hierarchy", roles=[MIGARole.CONFIGURATION], platform=PlatformType.CATALYST_CENTER),
        PlatformCapability(tool_name="catalyst_device_config", description="Device running config", roles=[MIGARole.CONFIGURATION], platform=PlatformType.CATALYST_CENTER),
        PlatformCapability(tool_name="catalyst_run_command", description="Execute CLI on device", roles=[MIGARole.AUTOMATION], read_only=False, requires_approval=True, platform=PlatformType.CATALYST_CENTER),
    ],
)


@asynccontextmanager
async def lifespan():
    async with miga_lifespan(OASF, CiscoAPIClient.for_catalyst_center) as state:
        yield state


mcp = FastMCP("catalyst_center_mcp", lifespan=lifespan)
add_health_tool(mcp, PlatformType.CATALYST_CENTER, "catalyst")


# -- Input schemas -----------------------------------------------------------

class HealthIn(BaseModel):
    site_id: Optional[str] = Field(default=None, description="Filter by site ID")

class DeviceListIn(BaseModel):
    hostname: Optional[str] = None
    platform_id: Optional[str] = Field(default=None, description="e.g. C9300")
    family: Optional[str] = Field(default=None, description="e.g. Switches and Hubs")
    limit: int = Field(default=25, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

class IssuesIn(BaseModel):
    priority: Optional[str] = Field(default=None, description="P1, P2, P3, or P4")
    device_id: Optional[str] = None
    ai_driven: bool = True
    limit: int = Field(default=25, ge=1, le=200)

class ClientHealthIn(BaseModel):
    site_id: Optional[str] = None

class DeviceConfigIn(BaseModel):
    device_id: str = Field(..., min_length=1)

class CommandRunnerIn(BaseModel):
    device_ids: list[str] = Field(..., min_length=1, max_length=5)
    command: str = Field(..., min_length=1, max_length=500)


# -- Tools -------------------------------------------------------------------

@mcp.tool(name="catalyst_network_health", annotations={"readOnlyHint": True})
async def network_health(params: HealthIn, ctx=None) -> str:
    """Get overall network health scores from Catalyst Center AI Analytics."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    bus = ctx.request_context.lifespan_state["bus"]

    qp = {}
    if params.site_id:
        qp["siteId"] = params.site_id

    data = await api.get("/dna/intent/api/v1/network-health", params=qp)
    h = data.get("response", [{}])
    h = h[0] if isinstance(h, list) and h else h

    await bus.publish_telemetry("catalyst_center", {"type": "network_health", "data": h})

    score = h.get("networkHealthAverage", 0)
    return f"""## Catalyst Center — Network Health

**Overall:** {Fmt.health_badge(float(score))}

{Fmt.md_table(
    ["Status", "Count"],
    [
        ["🟢 Good", h.get("goodDeviceCount", 0)],
        ["🟡 Fair", h.get("fairDeviceCount", 0)],
        ["🔴 Bad", h.get("badDeviceCount", 0)],
        ["⚪ Unmonitored", h.get("unmonitoredDeviceCount", 0)],
        ["**Total**", f"**{h.get('totalDeviceCount', 0)}**"],
    ],
)}"""


@mcp.tool(name="catalyst_device_list", annotations={"readOnlyHint": True})
async def device_list(params: DeviceListIn, ctx=None) -> str:
    """List managed network devices from Catalyst Center inventory."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    qp: dict[str, Any] = {"limit": params.limit, "offset": params.offset}
    if params.hostname: qp["hostname"] = params.hostname
    if params.platform_id: qp["platformId"] = params.platform_id
    if params.family: qp["family"] = params.family

    data = await api.get("/dna/intent/api/v1/network-device", params=qp)
    return Fmt.devices_md(data.get("response", []))


@mcp.tool(name="catalyst_issues", annotations={"readOnlyHint": True})
async def issues(params: IssuesIn, ctx=None) -> str:
    """Get AI-detected network issues with root cause analysis and remediation guidance."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    bus = ctx.request_context.lifespan_state["bus"]

    qp: dict[str, Any] = {"limit": params.limit}
    if params.priority: qp["priority"] = params.priority
    if params.device_id: qp["deviceId"] = params.device_id
    if params.ai_driven: qp["aiDriven"] = "true"

    data = await api.get("/dna/intent/api/v1/issues", params=qp)
    items = data.get("response", [])

    for iss in items:
        if iss.get("priority") in ("P1", "P2"):
            await bus.publish_event(CorrelatedEvent(
                source_platform=PlatformType.CATALYST_CENTER,
                event_type="ai_issue",
                severity=SeverityLevel.CRITICAL if iss["priority"] == "P1" else SeverityLevel.HIGH,
                affected_entities=[iss.get("deviceId", "")],
                raw_data=iss, tags=["ai_detected", iss.get("priority", "")],
            ).model_dump(mode="json"))

    if not items:
        return "## Catalyst Center Issues\n\n✅ No active AI-detected issues."

    lines = [f"## Catalyst Center — Issues ({len(items)})\n"]
    for iss in items[:15]:
        p = iss.get("priority", "P4")
        emoji = {"P1": "🔴", "P2": "🟠", "P3": "🟡"}.get(p, "🔵")
        lines.append(f"- {emoji} **[{p}]** {iss.get('name', 'Untitled')}")
        if iss.get("suggestionMessage"):
            lines.append(f"  💡 _{iss['suggestionMessage']}_")
    return "\n".join(lines)


@mcp.tool(name="catalyst_client_health", annotations={"readOnlyHint": True})
async def client_health(params: ClientHealthIn, ctx=None) -> str:
    """Get wireless and wired client health statistics."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    qp = {"siteId": params.site_id} if params.site_id else {}
    data = await api.get("/dna/intent/api/v1/client-health", params=qp)
    clients = data.get("response", [])

    lines = ["## Client Health\n"]
    for cat in clients:
        for s in cat.get("scoreDetail", []):
            val = s.get("scoreCategory", {}).get("value", "unknown")
            lines.append(f"- **{val}**: {s.get('clientCount', 0)} clients ({s.get('scorePercentage', 0)}%)")
    return "\n".join(lines) if len(lines) > 1 else "## Client Health\n\n_No data available._"


@mcp.tool(name="catalyst_site_topology", annotations={"readOnlyHint": True})
async def site_topology(ctx=None) -> str:
    """Get full site hierarchy and topology."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    data = await api.get("/dna/intent/api/v1/topology/site-topology")
    sites = data.get("response", {}).get("sites", [])

    lines = [f"## Site Topology ({len(sites)} sites)\n"]
    for s in sites[:30]:
        lines.append(f"- **{s.get('name', '?')}** ({s.get('locationType', '')}) — Parent: {s.get('parentName', 'Root')}")
    return "\n".join(lines)


@mcp.tool(name="catalyst_device_config", annotations={"readOnlyHint": True})
async def device_config(params: DeviceConfigIn, ctx=None) -> str:
    """Retrieve device running configuration."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    data = await api.get(f"/dna/intent/api/v1/network-device/{params.device_id}/config")
    cfg = data.get("response", "No configuration available.")
    return f"## Device Config\n\n**ID:** `{params.device_id}`\n\n```\n{cfg}\n```"


@mcp.tool(name="catalyst_run_command", annotations={"readOnlyHint": False, "destructiveHint": False})
async def run_command(params: CommandRunnerIn, ctx=None) -> str:
    """Execute CLI command on devices via Command Runner. ⚠️ Requires approval."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    bus = ctx.request_context.lifespan_state["bus"]

    await bus.request_approval({
        "tool": "catalyst_run_command", "command": params.command,
        "device_ids": params.device_ids, "platform": "catalyst_center",
    })

    data = await api.post("/dna/intent/api/v1/network-device-poller/cli/read-request", json_data={
        "commands": [params.command], "deviceUuids": params.device_ids,
    })
    task_id = data.get("response", {}).get("taskId", "unknown")
    return f"## Command Submitted\n\n`{params.command}` → {len(params.device_ids)} devices\nTask: `{task_id}`"


if __name__ == "__main__":
    mcp.run(transport="streamable_http", port=int(os.getenv("CATALYST_CENTER_MCP_PORT", "8001")))
