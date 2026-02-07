"""ThousandEyes MCP Server — Digital Experience Observability, Path Analysis.

Roles: Observability
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from miga_shared.agntcy import OASFRecord
from miga_shared.clients import CiscoAPIClient
from miga_shared.models import (
    CorrelatedEvent, MIGARole, PlatformCapability, PlatformType, SeverityLevel,
)
from miga_shared.server_base import add_health_tool, miga_lifespan
from miga_shared.utils.formatters import Fmt

OASF = OASFRecord(
    name="thousandeyes_mcp",
    description="Cisco ThousandEyes digital experience monitoring and path analysis",
    platform=PlatformType.THOUSANDEYES,
    roles=[MIGARole.OBSERVABILITY],
    skills=["test_results", "path_visualization", "alert_monitoring", "agent_status", "outage_detection"],
    domains=["digital_experience", "internet_insights", "path_analysis", "synthetic_monitoring"],
    endpoint=f"http://thousandeyes-mcp:{os.getenv('THOUSANDEYES_MCP_PORT', '8003')}",
    capabilities=[
        PlatformCapability(tool_name="te_tests_list", description="List configured tests", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.THOUSANDEYES),
        PlatformCapability(tool_name="te_test_results", description="Get test results with metrics", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.THOUSANDEYES),
        PlatformCapability(tool_name="te_active_alerts", description="Active alert rules and violations", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.THOUSANDEYES),
        PlatformCapability(tool_name="te_path_visualization", description="Network path trace results", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.THOUSANDEYES),
        PlatformCapability(tool_name="te_agent_list", description="Enterprise and cloud agent status", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.THOUSANDEYES),
        PlatformCapability(tool_name="te_internet_insights", description="Internet outage detection", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.THOUSANDEYES),
    ],
)


@asynccontextmanager
async def lifespan():
    async with miga_lifespan(OASF, CiscoAPIClient.for_thousandeyes) as state:
        yield state

mcp = FastMCP("thousandeyes_mcp", lifespan=lifespan)
add_health_tool(mcp, PlatformType.THOUSANDEYES, "thousandeyes")


# -- Input schemas -----------------------------------------------------------

class TestIdIn(BaseModel):
    test_id: str = Field(..., min_length=1)

class AlertsIn(BaseModel):
    window: Optional[str] = Field(default=None, description="Time window e.g. 1h, 24h")


# -- Tools -------------------------------------------------------------------

@mcp.tool(name="te_tests_list", annotations={"readOnlyHint": True})
async def tests_list(ctx=None) -> str:
    """List all configured ThousandEyes tests."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    data = await api.get("/tests")
    tests = data.get("tests", data.get("test", []))

    if not tests:
        return "_No tests configured._"

    rows = [
        [t.get("testName", "?"), t.get("type", ""), str(t.get("testId", "")),
         "✅" if t.get("enabled") else "❌", t.get("interval", "")]
        for t in tests[:30]
    ]
    return f"## ThousandEyes Tests ({len(tests)})\n\n{Fmt.md_table(['Name', 'Type', 'ID', 'Enabled', 'Interval'], rows)}"


@mcp.tool(name="te_test_results", annotations={"readOnlyHint": True})
async def test_results(params: TestIdIn, ctx=None) -> str:
    """Get the latest results and metrics for a specific test."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    bus = ctx.request_context.lifespan_state["bus"]

    data = await api.get(f"/tests/{params.test_id}/results/network")
    results = data.get("net", data.get("results", []))

    await bus.publish_telemetry("thousandeyes", {"type": "test_results", "test_id": params.test_id, "count": len(results)})

    if not results:
        return f"_No results for test `{params.test_id}`._"

    lines = [f"## Test Results — {params.test_id}\n"]
    for r in results[:10]:
        agent = r.get("agentName", r.get("agentId", "?"))
        loss = r.get("loss", 0)
        latency = r.get("avgLatency", 0)
        jitter = r.get("jitter", 0)
        loss_emoji = "🟢" if loss == 0 else "🟠" if loss < 5 else "🔴"
        lines.append(f"- {loss_emoji} **{agent}** — Loss: {loss}% | Latency: {latency:.1f}ms | Jitter: {jitter:.1f}ms")

        if loss >= 10:
            await bus.publish_event(CorrelatedEvent(
                source_platform=PlatformType.THOUSANDEYES, event_type="path_degradation",
                severity=SeverityLevel.HIGH, affected_entities=[agent, params.test_id],
                raw_data=r, tags=["packet_loss", f"loss_{loss}pct"],
            ).model_dump(mode="json"))

    return "\n".join(lines)


@mcp.tool(name="te_active_alerts", annotations={"readOnlyHint": True})
async def active_alerts(params: AlertsIn, ctx=None) -> str:
    """Get active ThousandEyes alerts."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    bus = ctx.request_context.lifespan_state["bus"]

    data = await api.get("/alerts")
    alerts = data.get("alert", data.get("alerts", []))

    for a in alerts:
        if a.get("severity", 0) >= 3:
            await bus.publish_alert(CorrelatedEvent(
                source_platform=PlatformType.THOUSANDEYES, event_type="te_alert",
                severity=SeverityLevel.HIGH, affected_entities=[str(a.get("testId", ""))],
                raw_data=a, tags=["alert", a.get("ruleName", "")],
            ).model_dump(mode="json"))

    if not alerts:
        return "## ThousandEyes Alerts\n\n✅ No active alerts."

    lines = [f"## ThousandEyes Alerts ({len(alerts)})\n"]
    for a in alerts[:20]:
        rule = a.get("ruleName", "Unknown Rule")
        test = a.get("testName", a.get("testId", "?"))
        active = "🔴 Active" if a.get("active") else "✅ Cleared"
        lines.append(f"- {active} **{rule}** — Test: {test}")
    return "\n".join(lines)


@mcp.tool(name="te_path_visualization", annotations={"readOnlyHint": True})
async def path_visualization(params: TestIdIn, ctx=None) -> str:
    """Get network path trace visualization for a test."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    data = await api.get(f"/tests/{params.test_id}/results/path-vis")
    paths = data.get("pathVis", data.get("results", []))

    if not paths:
        return f"_No path data for test `{params.test_id}`._"

    lines = [f"## Path Visualization — {params.test_id}\n"]
    for p in paths[:5]:
        agent = p.get("agentName", "?")
        target = p.get("server", p.get("target", "?"))
        hops = p.get("routes", [])
        lines.append(f"### {agent} → {target} ({len(hops)} paths)")
        for route in hops[:3]:
            hop_list = route.get("hops", [])
            hop_str = " → ".join(h.get("ipAddress", "?") for h in hop_list[:8])
            if len(hop_list) > 8:
                hop_str += f" → …({len(hop_list)} total)"
            lines.append(f"  `{hop_str}`")
    return "\n".join(lines)


@mcp.tool(name="te_agent_list", annotations={"readOnlyHint": True})
async def agent_list(ctx=None) -> str:
    """List enterprise and cloud agents with status."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    data = await api.get("/agents")
    agents = data.get("agents", [])

    if not agents:
        return "_No agents found._"

    rows = [
        [a.get("agentName", "?"), a.get("agentType", ""), a.get("countryId", ""),
         Fmt.status_dot("online" if a.get("enabled") else "offline"), a.get("ipAddresses", [""])[0] if a.get("ipAddresses") else ""]
        for a in agents[:30]
    ]
    return f"## ThousandEyes Agents ({len(agents)})\n\n{Fmt.md_table(['Name', 'Type', 'Country', 'Status', 'IP'], rows)}"


@mcp.tool(name="te_internet_insights", annotations={"readOnlyHint": True})
async def internet_insights(ctx=None) -> str:
    """Get Internet Insights — global outage detection and ISP issues."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    data = await api.get("/internet-insights/outages")
    outages = data.get("outages", [])

    if not outages:
        return "## Internet Insights\n\n✅ No active internet outages detected."

    lines = [f"## Internet Insights — Outages ({len(outages)})\n"]
    for o in outages[:15]:
        provider = o.get("providerName", "Unknown")
        scope = o.get("scope", "?")
        start = Fmt.ts(o.get("startDate"))
        lines.append(f"- 🔴 **{provider}** — {scope} (started {start})")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="streamable_http", port=int(os.getenv("THOUSANDEYES_MCP_PORT", "8003")))
