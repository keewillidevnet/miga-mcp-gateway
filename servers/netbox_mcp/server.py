"""NetBox MCP Server — DCIM, IPAM, and Infrastructure Source of Truth [STUB].

Roles: Configuration, Compliance
"""
from __future__ import annotations
import json, os
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP
from miga_shared.agntcy import OASFRecord
from miga_shared.models import MIGARole, PlatformCapability, PlatformType
from miga_shared.server_base import add_health_tool, miga_lifespan

OASF = OASFRecord(
    name="netbox_mcp",
    description="[STUB] NetBox — DCIM, IPAM, Circuit Tracking, and Infrastructure Source of Truth",
    platform=PlatformType.NETBOX,
    roles=[MIGARole.CONFIGURATION, MIGARole.COMPLIANCE],
    skills=["dcim", "ipam", "circuit_tracking", "topology", "cable_tracing"],
    domains=["infrastructure", "inventory", "ip_management", "documentation"],
    endpoint=f"http://netbox-mcp:{os.getenv('NETBOX_MCP_PORT', '8015')}",
    capabilities=[
        PlatformCapability(tool_name="netbox_get_device", description="Get device details by name, IP, or serial", roles=[MIGARole.CONFIGURATION], platform=PlatformType.NETBOX),
        PlatformCapability(tool_name="netbox_get_interfaces", description="List interfaces and connections for a device", roles=[MIGARole.CONFIGURATION], platform=PlatformType.NETBOX),
        PlatformCapability(tool_name="netbox_trace_cable", description="Trace cable path from a device interface to its endpoint", roles=[MIGARole.CONFIGURATION], platform=PlatformType.NETBOX),
        PlatformCapability(tool_name="netbox_get_circuit", description="Get circuit details including provider, bandwidth, and endpoints", roles=[MIGARole.CONFIGURATION], platform=PlatformType.NETBOX),
        PlatformCapability(tool_name="netbox_get_prefixes", description="List IP prefixes for a site, VLAN, or VRF", roles=[MIGARole.CONFIGURATION], platform=PlatformType.NETBOX),
        PlatformCapability(tool_name="netbox_get_ip_address", description="Look up an IP address and its assigned device/interface", roles=[MIGARole.CONFIGURATION], platform=PlatformType.NETBOX),
        PlatformCapability(tool_name="netbox_get_site", description="Get site details including location, devices, and rack count", roles=[MIGARole.CONFIGURATION], platform=PlatformType.NETBOX),
        PlatformCapability(tool_name="netbox_get_rack", description="Get rack details including devices and power utilization", roles=[MIGARole.CONFIGURATION], platform=PlatformType.NETBOX),
    ],
    metadata={"status": "stub"},
)

@asynccontextmanager
async def app_lifespan():
    async with miga_lifespan(OASF) as state:
        yield state

mcp = FastMCP("netbox_mcp", lifespan=app_lifespan)
add_health_tool(mcp, PlatformType.NETBOX, "netbox")
STUB = "\n\n> ⚠️ **STUB** — Returns mock data."


# ---------------------------------------------------------------------------
# DCIM — Devices
# ---------------------------------------------------------------------------

@mcp.tool(name="netbox_get_device", annotations={"readOnlyHint": True})
async def get_device(query: str = "switch-br-01", ctx=None) -> str:
    """[STUB] Look up a device by name, IP, serial number, or asset tag."""
    return json.dumps({
        "_stub": True,
        "result": {
            "id": 142,
            "name": "switch-br-01",
            "device_type": {"manufacturer": "Cisco", "model": "Catalyst 9300-48P"},
            "role": {"name": "Access Switch"},
            "serial": "FOC2345X0AB",
            "asset_tag": "ASSET-00142",
            "site": {"name": "Building C", "region": "Campus North"},
            "location": {"name": "Floor 2"},
            "rack": {"name": "Rack 14", "facility_id": "C2-R14"},
            "position": 20,
            "face": "front",
            "status": "active",
            "primary_ip4": {"address": "10.1.50.1/24"},
            "platform": {"name": "IOS-XE 17.09.04a"},
            "tenant": {"name": "Engineering"},
            "tags": ["production", "branch", "poe"],
            "custom_fields": {
                "warranty_end": "2026-06-15",
                "last_backup": "2025-02-06T23:00:00Z",
                "smartnet_contract": "CON-SNT-C93004P",
            },
            "interface_count": 52,
            "created": "2023-06-15",
            "last_updated": "2025-02-01T14:30:00Z",
        },
    }) + STUB


@mcp.tool(name="netbox_get_interfaces", annotations={"readOnlyHint": True})
async def get_interfaces(device_name: str = "switch-br-01", ctx=None) -> str:
    """[STUB] List all interfaces and their connections for a device."""
    return json.dumps({
        "_stub": True,
        "result": {
            "device": device_name,
            "interface_count": 52,
            "connected": 38,
            "interfaces": [
                {"name": "GigabitEthernet1/0/1", "type": "1000base-t", "enabled": True, "mtu": 9000, "mac_address": "AA:BB:CC:DD:01:01", "connected_endpoint": {"device": "core-sw-01", "interface": "GigabitEthernet1/0/24"}, "cable": {"id": 301, "label": "CAB-C2R14-01"}, "tagged_vlans": [10, 20, 30], "untagged_vlan": 1, "mode": "tagged"},
                {"name": "GigabitEthernet1/0/2", "type": "1000base-t", "enabled": True, "connected_endpoint": {"device": "ap-br-01", "interface": "Ethernet0"}, "cable": {"id": 302, "label": ""}, "untagged_vlan": 100, "mode": "access", "poe_mode": "pse", "poe_type": "type2-ieee802.3at"},
                {"name": "GigabitEthernet1/0/3", "type": "1000base-t", "enabled": True, "connected_endpoint": {"device": "ap-br-02", "interface": "Ethernet0"}, "cable": {"id": 303, "label": ""}, "untagged_vlan": 100, "mode": "access", "poe_mode": "pse"},
                {"name": "GigabitEthernet1/0/4", "type": "1000base-t", "enabled": True, "connected_endpoint": {"device": "ap-br-03", "interface": "Ethernet0"}, "cable": {"id": 304, "label": ""}, "untagged_vlan": 100, "mode": "access", "poe_mode": "pse"},
                {"name": "TenGigabitEthernet1/1/1", "type": "10gbase-x-sfpp", "enabled": True, "connected_endpoint": {"device": "core-sw-01", "interface": "TenGigabitEthernet1/1/8"}, "cable": {"id": 305, "label": "SM-FIBER-C2R14-MDF"}, "lag": "Port-channel1", "mode": "tagged"},
            ],
        },
    }) + STUB


# ---------------------------------------------------------------------------
# DCIM — Cable Tracing
# ---------------------------------------------------------------------------

@mcp.tool(name="netbox_trace_cable", annotations={"readOnlyHint": True})
async def trace_cable(device_name: str = "switch-br-01", interface_name: str = "TenGigabitEthernet1/1/1", ctx=None) -> str:
    """[STUB] Trace the physical cable path from a device interface to its far end."""
    return json.dumps({
        "_stub": True,
        "result": {
            "origin": {"device": device_name, "interface": interface_name},
            "path": [
                {"device": device_name, "interface": interface_name, "cable": "SM-FIBER-C2R14-MDF", "cable_type": "smf-os2"},
                {"device": "patch-panel-c2", "port": "Port 14", "cable": "SM-FIBER-MDF-CORE", "cable_type": "smf-os2"},
                {"device": "core-sw-01", "interface": "TenGigabitEthernet1/1/8", "cable": None, "cable_type": None},
            ],
            "total_segments": 3,
            "total_length_m": 45.0,
            "status": "connected",
        },
    }) + STUB


# ---------------------------------------------------------------------------
# Circuits
# ---------------------------------------------------------------------------

@mcp.tool(name="netbox_get_circuit", annotations={"readOnlyHint": True})
async def get_circuit(circuit_id: str = "CKT-00412", ctx=None) -> str:
    """[STUB] Get circuit details including provider, bandwidth, and termination endpoints."""
    return json.dumps({
        "_stub": True,
        "result": {
            "cid": circuit_id,
            "provider": {"name": "Lumen", "account": "ACCT-77234"},
            "type": "MPLS",
            "status": "active",
            "commit_rate_kbps": 1000000,
            "description": "Building C WAN — Primary MPLS to Campus Core",
            "tenant": {"name": "Engineering"},
            "termination_a": {
                "site": {"name": "Building C"},
                "device": "wan-edge-01",
                "interface": "GigabitEthernet0/0/1",
                "port_speed_kbps": 1000000,
            },
            "termination_z": {
                "site": {"name": "Campus Core DC"},
                "provider_network": "Lumen MPLS Backbone",
            },
            "contract_start": "2023-01-01",
            "contract_end": "2026-01-01",
            "monthly_cost": 2500.00,
            "custom_fields": {
                "sla_uptime": "99.95%",
                "noc_phone": "+1-800-555-LUMN",
                "escalation_email": "noc@lumen.com",
            },
        },
    }) + STUB


# ---------------------------------------------------------------------------
# IPAM
# ---------------------------------------------------------------------------

@mcp.tool(name="netbox_get_prefixes", annotations={"readOnlyHint": True})
async def get_prefixes(site: str = "Building C", vrf: str = "", ctx=None) -> str:
    """[STUB] List IP prefixes for a site, optionally filtered by VRF."""
    return json.dumps({
        "_stub": True,
        "result": [
            {"prefix": "10.1.50.0/24", "vrf": "CORP", "vlan": {"vid": 50, "name": "MGMT"}, "status": "active", "utilization": 68, "site": site, "role": "Management"},
            {"prefix": "10.1.100.0/24", "vrf": "CORP", "vlan": {"vid": 100, "name": "WIRELESS"}, "status": "active", "utilization": 45, "site": site, "role": "Wireless"},
            {"prefix": "10.1.200.0/24", "vrf": "CORP", "vlan": {"vid": 200, "name": "VOIP"}, "status": "active", "utilization": 35, "site": site, "role": "VoIP"},
            {"prefix": "172.16.10.0/24", "vrf": "IOT", "vlan": {"vid": 300, "name": "IOT"}, "status": "active", "utilization": 12, "site": site, "role": "IoT"},
        ],
    }) + STUB


@mcp.tool(name="netbox_get_ip_address", annotations={"readOnlyHint": True})
async def get_ip_address(address: str = "10.1.50.1", ctx=None) -> str:
    """[STUB] Look up an IP address and its assigned device and interface."""
    return json.dumps({
        "_stub": True,
        "result": {
            "address": f"{address}/24",
            "status": "active",
            "dns_name": "switch-br-01.building-c.campus.local",
            "vrf": {"name": "CORP"},
            "tenant": {"name": "Engineering"},
            "assigned_object": {
                "device": "switch-br-01",
                "interface": "Vlan50",
                "device_type": "Catalyst 9300-48P",
                "site": "Building C",
            },
            "nat_inside": None,
            "role": "loopback",
            "tags": ["management", "monitored"],
        },
    }) + STUB


# ---------------------------------------------------------------------------
# Sites & Racks
# ---------------------------------------------------------------------------

@mcp.tool(name="netbox_get_site", annotations={"readOnlyHint": True})
async def get_site(name: str = "Building C", ctx=None) -> str:
    """[STUB] Get site details including location, device count, and rack summary."""
    return json.dumps({
        "_stub": True,
        "result": {
            "name": name,
            "status": "active",
            "region": "Campus North",
            "facility": "Engineering Building",
            "physical_address": "100 Campus Drive, Building C",
            "latitude": 33.7490,
            "longitude": -84.3880,
            "tenant": {"name": "Engineering"},
            "device_count": 47,
            "rack_count": 6,
            "prefix_count": 12,
            "circuit_count": 3,
            "vlan_count": 8,
            "contact_name": "Keenan Williams",
            "contact_phone": "+1-504-555-0142",
            "tags": ["production", "branch"],
        },
    }) + STUB


@mcp.tool(name="netbox_get_rack", annotations={"readOnlyHint": True})
async def get_rack(site: str = "Building C", rack_name: str = "Rack 14", ctx=None) -> str:
    """[STUB] Get rack details including installed devices and power utilization."""
    return json.dumps({
        "_stub": True,
        "result": {
            "name": rack_name,
            "facility_id": "C2-R14",
            "site": site,
            "location": "Floor 2, IDF",
            "status": "active",
            "u_height": 42,
            "u_utilized": 28,
            "u_available": 14,
            "power_utilization_watts": 2840,
            "max_power_watts": 5000,
            "devices": [
                {"name": "switch-br-01", "position": 20, "height": 1, "role": "Access Switch", "status": "active"},
                {"name": "switch-br-02", "position": 18, "height": 1, "role": "Access Switch", "status": "active"},
                {"name": "ups-br-01", "position": 1, "height": 4, "role": "UPS", "status": "active"},
                {"name": "patch-panel-c2", "position": 22, "height": 1, "role": "Patch Panel", "status": "active"},
            ],
            "tags": ["production", "poe-heavy"],
        },
    }) + STUB


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.getenv("NETBOX_MCP_PORT", "8015")))
