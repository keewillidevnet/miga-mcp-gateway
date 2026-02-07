"""Cisco XDR MCP Server — Threat Detection, Investigation, Incident Response.

"What's happening" — real-time security posture.
Roles: Security
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
    CorrelatedEvent, MIGARole, PlatformCapability, PlatformType, SeverityLevel,
)
from miga_shared.server_base import add_health_tool, miga_lifespan
from miga_shared.utils.formatters import Fmt

OASF = OASFRecord(
    name="xdr_mcp",
    description="Cisco XDR threat detection, investigation, incident response, and Talos intelligence",
    platform=PlatformType.XDR,
    roles=[MIGARole.SECURITY],
    skills=["threat_detection", "incident_response", "investigation", "talos_intel", "sighting_search"],
    domains=["security", "threat_intelligence", "incident_response", "soc"],
    endpoint=f"http://xdr-mcp:{os.getenv('XDR_MCP_PORT', '8005')}",
    capabilities=[
        PlatformCapability(tool_name="xdr_incidents", description="Active security incidents", roles=[MIGARole.SECURITY], platform=PlatformType.XDR),
        PlatformCapability(tool_name="xdr_sightings", description="Observable sightings across sources", roles=[MIGARole.SECURITY], platform=PlatformType.XDR),
        PlatformCapability(tool_name="xdr_investigate", description="Investigate an observable (IP, domain, hash)", roles=[MIGARole.SECURITY], platform=PlatformType.XDR),
        PlatformCapability(tool_name="xdr_talos_lookup", description="Talos threat intelligence lookup", roles=[MIGARole.SECURITY], platform=PlatformType.XDR),
        PlatformCapability(tool_name="xdr_response_actions", description="Available response actions", roles=[MIGARole.SECURITY], read_only=False, requires_approval=True, platform=PlatformType.XDR),
    ],
)


@asynccontextmanager
async def lifespan():
    async with miga_lifespan(OASF, CiscoAPIClient.for_xdr) as state:
        yield state

mcp = FastMCP("xdr_mcp", lifespan=lifespan)
add_health_tool(mcp, PlatformType.XDR, "xdr")


class IncidentsIn(BaseModel):
    status: Optional[str] = Field(default="open", description="open, closed, or all")
    severity: Optional[str] = Field(default=None, description="critical, high, medium, low")
    limit: int = Field(default=25, ge=1, le=200)

class SightingsIn(BaseModel):
    observable_value: str = Field(..., min_length=1, description="IP, domain, file hash, or URL")
    observable_type: Optional[str] = Field(default=None, description="ip, domain, sha256, url")

class InvestigateIn(BaseModel):
    observable: str = Field(..., min_length=1, description="IP, domain, SHA-256, or URL to investigate")
    observable_type: Optional[str] = None

class TalosIn(BaseModel):
    observable: str = Field(..., min_length=1, description="IP, domain, or hash")

class ResponseActionsIn(BaseModel):
    incident_id: str = Field(..., min_length=1)


@mcp.tool(name="xdr_incidents", annotations={"readOnlyHint": True})
async def incidents(params: IncidentsIn, ctx=None) -> str:
    """Get active security incidents from Cisco XDR."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    bus = ctx.request_context.lifespan_state["bus"]

    payload: dict[str, Any] = {"source": "all"}
    if params.status and params.status != "all":
        payload["status"] = params.status
    if params.severity:
        payload["severity"] = params.severity

    data = await api.post("/iroh/iroh-enrich/observe/incidents", json_data=payload)
    incidents_list = data.get("data", data.get("incidents", []))

    for inc in incidents_list:
        if inc.get("severity", "").lower() in ("critical", "high"):
            await bus.publish_alert(CorrelatedEvent(
                source_platform=PlatformType.XDR, event_type="security_incident",
                severity=SeverityLevel.CRITICAL if inc.get("severity", "").lower() == "critical" else SeverityLevel.HIGH,
                affected_entities=[inc.get("id", "")],
                raw_data=inc, tags=["incident", inc.get("type", "")],
            ).model_dump(mode="json"))

    if not incidents_list:
        return "## XDR Incidents\n\n✅ No active incidents matching criteria."

    lines = [f"## XDR Incidents ({len(incidents_list)})\n"]
    for inc in incidents_list[:20]:
        sev = inc.get("severity", "unknown")
        title = inc.get("title", inc.get("short_description", "Untitled"))
        status = inc.get("status", "?")
        ts = Fmt.ts(inc.get("timestamp", inc.get("created_at")))
        lines.append(f"- {Fmt.severity_emoji(sev)} **{title}**")
        lines.append(f"  Severity: {sev} | Status: {status} | {ts}")
    return "\n".join(lines)


@mcp.tool(name="xdr_sightings", annotations={"readOnlyHint": True})
async def sightings(params: SightingsIn, ctx=None) -> str:
    """Search for observable sightings across all connected XDR sources."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]

    payload = {"content": params.observable_value}
    if params.observable_type:
        payload["type"] = params.observable_type

    data = await api.post("/iroh/iroh-enrich/observe/sightings", json_data=payload)
    sightings_list = data.get("data", [])

    if not sightings_list:
        return f"_No sightings found for `{params.observable_value}`._"

    lines = [f"## Sightings for `{params.observable_value}` ({len(sightings_list)})\n"]
    for s in sightings_list[:15]:
        source = s.get("source", "?")
        count = s.get("count", 1)
        observed = Fmt.ts(s.get("observed_time", {}).get("start_time"))
        lines.append(f"- 🔍 **{source}** — {count} sighting(s) (first seen: {observed})")
    return "\n".join(lines)


@mcp.tool(name="xdr_investigate", annotations={"readOnlyHint": True})
async def investigate(params: InvestigateIn, ctx=None) -> str:
    """Deep investigation of an observable — enrich from all intelligence sources."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]

    payload = {"content": params.observable, "type": params.observable_type or "unknown"}
    data = await api.post("/iroh/iroh-enrich/deliberate/observables", json_data=payload)
    verdicts = data.get("data", [])

    if not verdicts:
        return f"_No intelligence found for `{params.observable}`._"

    lines = [f"## Investigation: `{params.observable}`\n"]
    for v in verdicts:
        module = v.get("module", "?")
        disposition = v.get("disposition_name", v.get("verdict", "Unknown"))
        confidence = v.get("confidence", "?")
        emoji = {"Malicious": "🔴", "Suspicious": "🟠", "Clean": "🟢"}.get(disposition, "⚪")
        lines.append(f"- {emoji} **{module}**: {disposition} (confidence: {confidence})")
    return "\n".join(lines)


@mcp.tool(name="xdr_talos_lookup", annotations={"readOnlyHint": True})
async def talos_lookup(params: TalosIn, ctx=None) -> str:
    """Look up an observable in Cisco Talos threat intelligence."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]

    data = await api.post("/iroh/iroh-enrich/observe/observables", json_data={"content": params.observable})
    results = data.get("data", [])

    talos = [r for r in results if "talos" in r.get("module", "").lower()]
    if not talos:
        return f"_No Talos data for `{params.observable}`._"

    lines = [f"## Talos Intelligence: `{params.observable}`\n"]
    for t in talos:
        module = t.get("module", "Talos")
        judgements = t.get("data", {}).get("judgements", {}).get("docs", [])
        for j in judgements[:5]:
            disp = j.get("disposition_name", "Unknown")
            reason = j.get("reason", "")
            lines.append(f"- **{module}**: {disp}")
            if reason:
                lines.append(f"  _{reason}_")
    return "\n".join(lines)


@mcp.tool(name="xdr_response_actions", annotations={"readOnlyHint": True})
async def response_actions(params: ResponseActionsIn, ctx=None) -> str:
    """List available response actions for an incident. ⚠️ Execution requires approval."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]

    data = await api.get(f"/iroh/iroh-response/respond/actions")
    actions = data.get("data", data.get("actions", []))

    if not actions:
        return f"_No response actions available for incident `{params.incident_id}`._"

    lines = [f"## Response Actions — Incident `{params.incident_id}`\n"]
    for a in actions[:15]:
        name = a.get("title", a.get("name", "?"))
        desc = a.get("description", "")
        lines.append(f"- ⚡ **{name}**")
        if desc:
            lines.append(f"  _{desc}_")
    lines.append("\n_To execute an action, approval is required via WebEx._")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="streamable_http", port=int(os.getenv("XDR_MCP_PORT", "8005")))
