"""Meraki MCP Server — Cloud-managed Analytics, Org-wide Health, Network Configuration.

Roles: Observability, Configuration, Security
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
    name="meraki_mcp",
    description="Cisco Meraki Dashboard cloud-managed analytics and configuration",
    platform=PlatformType.MERAKI,
    roles=[MIGARole.OBSERVABILITY, MIGARole.CONFIGURATION, MIGARole.SECURITY],
    skills=["org_health", "network_clients", "device_status", "security_events", "vpn_status"],
    domains=["cloud_networking", "wireless", "sd_wan", "security_appliance"],
    endpoint=f"http://meraki-mcp:{os.getenv('MERAKI_MCP_PORT', '8002')}",
    capabilities=[
        PlatformCapability(tool_name="meraki_org_overview", description="Organization-wide overview and license", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.MERAKI),
        PlatformCapability(tool_name="meraki_network_list", description="List all networks in organization", roles=[MIGARole.OBSERVABILITY, MIGARole.CONFIGURATION], platform=PlatformType.MERAKI),
        PlatformCapability(tool_name="meraki_device_statuses", description="Device online/offline/alerting status", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.MERAKI),
        PlatformCapability(tool_name="meraki_network_clients", description="Connected clients on a network", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.MERAKI),
        PlatformCapability(tool_name="meraki_security_events", description="Security appliance threat events", roles=[MIGARole.SECURITY], platform=PlatformType.MERAKI),
        PlatformCapability(tool_name="meraki_vpn_statuses", description="Site-to-site VPN tunnel status", roles=[MIGARole.OBSERVABILITY, MIGARole.CONFIGURATION], platform=PlatformType.MERAKI),
        PlatformCapability(tool_name="meraki_switch_port_statuses", description="Switch port utilization", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.MERAKI),
    ],
)

ORG_ID = os.getenv("MERAKI_ORG_ID", "")


@asynccontextmanager
async def lifespan():
    async with miga_lifespan(OASF, CiscoAPIClient.for_meraki) as state:
        yield state

mcp = FastMCP("meraki_mcp", lifespan=lifespan)
add_health_tool(mcp, PlatformType.MERAKI, "meraki")


# -- Input schemas -----------------------------------------------------------

class NetworkIdIn(BaseModel):
    network_id: str = Field(..., min_length=1)

class DeviceStatusIn(BaseModel):
    network_ids: Optional[list[str]] = None
    serials: Optional[list[str]] = None

class ClientsIn(BaseModel):
    network_id: str = Field(..., min_length=1)
    timespan: int = Field(default=86400, description="Timespan in seconds (default 24h)")
    per_page: int = Field(default=50, ge=1, le=200)

class SecurityEventsIn(BaseModel):
    network_id: str = Field(..., min_length=1)
    timespan: int = Field(default=86400)
    per_page: int = Field(default=50, ge=1, le=200)

class SwitchPortIn(BaseModel):
    serial: str = Field(..., min_length=1, description="Switch serial number")


# -- Tools -------------------------------------------------------------------

@mcp.tool(name="meraki_org_overview", annotations={"readOnlyHint": True})
async def org_overview(ctx=None) -> str:
    """Get Meraki organization overview — networks, licenses, device counts."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]

    org = await api.get(f"/organizations/{ORG_ID}")
    license_info = await api.get(f"/organizations/{ORG_ID}/licenses/overview")
    inv = await api.get(f"/organizations/{ORG_ID}/inventoryDevices", params={"perPage": 5})

    name = org.get("name", "Unknown")
    status = license_info.get("status", "N/A")
    exp = license_info.get("expirationDate", "N/A")
    licensed = license_info.get("licensedDeviceCounts", {})

    lines = [
        f"## Meraki Organization: {name}\n",
        f"**License Status:** {status}  ",
        f"**Expiration:** {exp}\n",
        "### Licensed Devices",
    ]
    for model, count in licensed.items():
        lines.append(f"- {model}: {count}")
    return "\n".join(lines)


@mcp.tool(name="meraki_network_list", annotations={"readOnlyHint": True})
async def network_list(ctx=None) -> str:
    """List all networks in the Meraki organization."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    networks = await api.get(f"/organizations/{ORG_ID}/networks")
    if not networks:
        return "_No networks found._"

    rows = [
        [n.get("name", "?"), n.get("id", ""), ", ".join(n.get("productTypes", [])), n.get("timeZone", "")]
        for n in networks[:30]
    ]
    return f"## Networks ({len(networks)})\n\n{Fmt.md_table(['Name', 'ID', 'Products', 'Timezone'], rows)}"


@mcp.tool(name="meraki_device_statuses", annotations={"readOnlyHint": True})
async def device_statuses(params: DeviceStatusIn, ctx=None) -> str:
    """Get device online/offline/alerting status across the organization."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    bus = ctx.request_context.lifespan_state["bus"]

    qp: dict[str, Any] = {"perPage": 100}
    if params.network_ids:
        qp["networkIds[]"] = params.network_ids

    devices = await api.get(f"/organizations/{ORG_ID}/devices/statuses", params=qp)
    if not devices:
        return "_No device statuses._"

    # Publish offline devices to event bus
    offline = [d for d in devices if d.get("status") == "offline"]
    if offline:
        await bus.publish_event(CorrelatedEvent(
            source_platform=PlatformType.MERAKI, event_type="device_offline",
            severity=SeverityLevel.HIGH,
            affected_entities=[d.get("serial", "") for d in offline],
            raw_data={"offline_count": len(offline)},
            tags=["device_down"],
        ).model_dump(mode="json"))

    online = sum(1 for d in devices if d.get("status") == "online")
    alert = sum(1 for d in devices if d.get("status") == "alerting")

    lines = [
        f"## Device Status ({len(devices)} total)\n",
        f"🟢 Online: {online} | 🟠 Alerting: {alert} | 🔴 Offline: {len(offline)}\n",
    ]
    if offline:
        lines.append("### Offline Devices")
        for d in offline[:10]:
            lines.append(f"- 🔴 **{d.get('name', d.get('serial', '?'))}** — {d.get('model', '?')} ({d.get('lanIp', 'N/A')})")
    return "\n".join(lines)


@mcp.tool(name="meraki_network_clients", annotations={"readOnlyHint": True})
async def network_clients(params: ClientsIn, ctx=None) -> str:
    """List connected clients on a Meraki network."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    clients = await api.get(f"/networks/{params.network_id}/clients", params={
        "timespan": params.timespan, "perPage": params.per_page,
    })
    if not clients:
        return "_No clients found._"

    rows = [
        [c.get("description", c.get("mac", "?")), c.get("ip", "N/A"),
         c.get("vlan", ""), f"{c.get('usage', {}).get('sent', 0) / 1e6:.1f} MB"]
        for c in clients[:30]
    ]
    return f"## Network Clients ({len(clients)})\n\n{Fmt.md_table(['Client', 'IP', 'VLAN', 'Sent'], rows)}"


@mcp.tool(name="meraki_security_events", annotations={"readOnlyHint": True})
async def security_events(params: SecurityEventsIn, ctx=None) -> str:
    """Get security appliance threat detection events."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    bus = ctx.request_context.lifespan_state["bus"]

    events = await api.get(f"/networks/{params.network_id}/appliance/security/events", params={
        "timespan": params.timespan, "perPage": params.per_page,
    })

    for ev in (events or []):
        if ev.get("priority", 0) <= 2:
            await bus.publish_alert(CorrelatedEvent(
                source_platform=PlatformType.MERAKI, event_type="security_event",
                severity=SeverityLevel.HIGH,
                affected_entities=[ev.get("srcIp", ""), ev.get("destIp", "")],
                raw_data=ev, tags=["threat", ev.get("eventType", "")],
            ).model_dump(mode="json"))

    return Fmt.alerts_md([
        {"severity": "high" if e.get("priority", 5) <= 2 else "medium",
         "title": f"{e.get('eventType', '?')} — {e.get('message', '')}",
         "timestamp": e.get("ts")}
        for e in (events or [])
    ])


@mcp.tool(name="meraki_vpn_statuses", annotations={"readOnlyHint": True})
async def vpn_statuses(ctx=None) -> str:
    """Get site-to-site VPN tunnel statuses across the organization."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    statuses = await api.get(f"/organizations/{ORG_ID}/appliance/vpn/statuses")
    if not statuses:
        return "_No VPN tunnels._"

    lines = [f"## VPN Tunnels ({len(statuses)})\n"]
    for vpn in statuses[:20]:
        name = vpn.get("networkName", vpn.get("networkId", "?"))
        mode = vpn.get("deviceStatus", "unknown")
        uplinks = vpn.get("uplinks", [])
        up_str = ", ".join(f"{u.get('interface','?')}:{u.get('publicIp','')}" for u in uplinks)
        lines.append(f"- {Fmt.status_dot(mode)} **{name}** ({mode}) — {up_str}")
    return "\n".join(lines)


@mcp.tool(name="meraki_switch_port_statuses", annotations={"readOnlyHint": True})
async def switch_port_statuses(params: SwitchPortIn, ctx=None) -> str:
    """Get switch port utilization and status for a specific switch."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    ports = await api.get(f"/devices/{params.serial}/switch/ports/statuses")
    if not ports:
        return "_No port data._"

    rows = [
        [p.get("portId", "?"), Fmt.status_dot(p.get("status", "")),
         p.get("speed", "N/A"), p.get("duplex", ""), str(p.get("clientCount", 0))]
        for p in ports[:48]
    ]
    return f"## Switch Ports — {params.serial}\n\n{Fmt.md_table(['Port', 'Status', 'Speed', 'Duplex', 'Clients'], rows)}"


if __name__ == "__main__":
    mcp.run(transport="streamable_http", port=int(os.getenv("MERAKI_MCP_PORT", "8002")))
