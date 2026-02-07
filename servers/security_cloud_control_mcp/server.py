"""Security Cloud Control MCP Server — Unified Security Policy Management.

"How things are configured" — Firewall, Segmentation, Secure Access, AI Defense.
Roles: Security, Configuration, Compliance
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from miga_shared.agntcy import OASFRecord
from miga_shared.clients import CiscoAPIClient
from miga_shared.models import MIGARole, PlatformCapability, PlatformType
from miga_shared.server_base import add_health_tool, miga_lifespan
from miga_shared.utils.formatters import Fmt

OASF = OASFRecord(
    name="security_cloud_control_mcp",
    description="Cisco Security Cloud Control — unified policy across Firewall, Secure Access, Workload, AI Defense",
    platform=PlatformType.SECURITY_CLOUD_CONTROL,
    roles=[MIGARole.SECURITY, MIGARole.CONFIGURATION, MIGARole.COMPLIANCE],
    skills=["firewall_policy", "access_policy", "segmentation", "compliance_check", "ai_defense"],
    domains=["security_policy", "firewall", "zero_trust", "compliance"],
    endpoint=f"http://scc-mcp:{os.getenv('SCC_MCP_PORT', '8006')}",
    capabilities=[
        PlatformCapability(tool_name="scc_managed_devices", description="List managed security devices", roles=[MIGARole.CONFIGURATION], platform=PlatformType.SECURITY_CLOUD_CONTROL),
        PlatformCapability(tool_name="scc_access_policies", description="Access control policies", roles=[MIGARole.SECURITY, MIGARole.CONFIGURATION], platform=PlatformType.SECURITY_CLOUD_CONTROL),
        PlatformCapability(tool_name="scc_policy_changes", description="Recent policy change log", roles=[MIGARole.COMPLIANCE], platform=PlatformType.SECURITY_CLOUD_CONTROL),
        PlatformCapability(tool_name="scc_compliance_status", description="Policy compliance status", roles=[MIGARole.COMPLIANCE], platform=PlatformType.SECURITY_CLOUD_CONTROL),
        PlatformCapability(tool_name="scc_secure_access_users", description="Secure Access (ZTNA) user sessions", roles=[MIGARole.SECURITY, MIGARole.IDENTITY], platform=PlatformType.SECURITY_CLOUD_CONTROL),
        PlatformCapability(tool_name="scc_ai_defense_status", description="AI Defense guardrail status", roles=[MIGARole.SECURITY], platform=PlatformType.SECURITY_CLOUD_CONTROL),
    ],
)


@asynccontextmanager
async def lifespan():
    async with miga_lifespan(OASF, CiscoAPIClient.for_security_cloud_control) as state:
        yield state

mcp = FastMCP("security_cloud_control_mcp", lifespan=lifespan)
add_health_tool(mcp, PlatformType.SECURITY_CLOUD_CONTROL, "scc")


class DevicesIn(BaseModel):
    device_type: Optional[str] = Field(default=None, description="FTD, ASA, Multicloud, Workload")
    limit: int = Field(default=50, ge=1, le=200)

class PoliciesIn(BaseModel):
    device_uid: Optional[str] = None
    policy_type: Optional[str] = Field(default=None, description="access, prefilter, nat, identity")

class ChangeLogIn(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)
    pending_only: bool = Field(default=False, description="Show only pending (undeployed) changes")

class SecureAccessIn(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)


@mcp.tool(name="scc_managed_devices", annotations={"readOnlyHint": True})
async def managed_devices(params: DevicesIn, ctx=None) -> str:
    """List security devices managed by Security Cloud Control."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    qp = {"limit": params.limit}
    if params.device_type: qp["deviceType"] = params.device_type

    data = await api.get("/api/v1/devices", params=qp)
    devices = data.get("items", data.get("devices", []))

    if not devices:
        return "_No managed devices found._"

    rows = [
        [d.get("name", "?"), d.get("deviceType", ""), d.get("ipAddress", ""),
         Fmt.status_dot(d.get("connectivityState", "")), d.get("softwareVersion", "")]
        for d in devices[:30]
    ]
    return f"## Managed Security Devices ({len(devices)})\n\n{Fmt.md_table(['Name', 'Type', 'IP', 'Status', 'Version'], rows)}"


@mcp.tool(name="scc_access_policies", annotations={"readOnlyHint": True})
async def access_policies(params: PoliciesIn, ctx=None) -> str:
    """Get access control policies from Security Cloud Control."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    qp = {}
    if params.device_uid: qp["deviceUid"] = params.device_uid
    if params.policy_type: qp["policyType"] = params.policy_type

    data = await api.get("/api/v1/policies/access", params=qp)
    policies = data.get("items", data.get("policies", []))

    if not policies:
        return "_No access policies found._"

    lines = [f"## Access Policies ({len(policies)})\n"]
    for p in policies[:20]:
        name = p.get("name", "Unnamed")
        rules = p.get("ruleCount", len(p.get("rules", [])))
        status = p.get("deploymentStatus", "?")
        lines.append(f"- 🛡️ **{name}** — {rules} rules ({status})")
    return "\n".join(lines)


@mcp.tool(name="scc_policy_changes", annotations={"readOnlyHint": True})
async def policy_changes(params: ChangeLogIn, ctx=None) -> str:
    """Get recent policy change log — audit trail for compliance."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    qp = {"limit": params.limit}
    if params.pending_only: qp["status"] = "pending"

    data = await api.get("/api/v1/changelog", params=qp)
    changes = data.get("items", data.get("changes", []))

    if not changes:
        return "## Policy Changes\n\n_No recent changes._"

    lines = [f"## Policy Change Log ({len(changes)})\n"]
    for c in changes[:20]:
        user = c.get("user", c.get("modifiedBy", "?"))
        action = c.get("action", c.get("changeType", "?"))
        target = c.get("objectName", c.get("target", "?"))
        ts = Fmt.ts(c.get("timestamp", c.get("modifiedAt")))
        status = c.get("status", "")
        emoji = "🟡" if status == "pending" else "✅"
        lines.append(f"- {emoji} **{action}** on `{target}` by {user} ({ts})")
    return "\n".join(lines)


@mcp.tool(name="scc_compliance_status", annotations={"readOnlyHint": True})
async def compliance_status(ctx=None) -> str:
    """Get policy compliance status across all managed devices."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    data = await api.get("/api/v1/compliance/summary")

    compliant = data.get("compliant", 0)
    non_compliant = data.get("nonCompliant", 0)
    total = data.get("total", compliant + non_compliant)
    pct = (compliant / total * 100) if total > 0 else 0

    lines = [
        "## Compliance Status\n",
        f"**Overall:** {Fmt.health_badge(pct)}\n",
        f"- ✅ Compliant: {compliant}",
        f"- ❌ Non-compliant: {non_compliant}",
        f"- **Total:** {total}",
    ]

    violations = data.get("topViolations", [])
    if violations:
        lines.append("\n### Top Violations")
        for v in violations[:10]:
            lines.append(f"- ⚠️ {v.get('ruleName', '?')} — {v.get('deviceCount', 0)} devices")

    return "\n".join(lines)


@mcp.tool(name="scc_secure_access_users", annotations={"readOnlyHint": True})
async def secure_access_users(params: SecureAccessIn, ctx=None) -> str:
    """Get Secure Access (ZTNA) user sessions."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    data = await api.get("/api/v1/secure-access/sessions", params={"limit": params.limit})
    sessions = data.get("items", data.get("sessions", []))

    if not sessions:
        return "_No active Secure Access sessions._"

    rows = [
        [s.get("userName", "?"), s.get("sourceIp", ""), s.get("applicationName", ""),
         s.get("action", ""), Fmt.ts(s.get("timestamp"))]
        for s in sessions[:30]
    ]
    return f"## Secure Access Sessions ({len(sessions)})\n\n{Fmt.md_table(['User', 'Source IP', 'App', 'Action', 'Time'], rows)}"


@mcp.tool(name="scc_ai_defense_status", annotations={"readOnlyHint": True})
async def ai_defense_status(ctx=None) -> str:
    """Get AI Defense guardrail status — monitoring AI application security."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    data = await api.get("/api/v1/ai-defense/status")

    status = data.get("status", "unknown")
    guardrails = data.get("guardrails", [])
    violations_24h = data.get("violations24h", 0)

    lines = [
        f"## AI Defense Status\n",
        f"**Status:** {Fmt.status_dot(status)} {status}",
        f"**Violations (24h):** {violations_24h}\n",
    ]
    if guardrails:
        lines.append("### Active Guardrails")
        for g in guardrails[:15]:
            name = g.get("name", "?")
            enabled = "✅" if g.get("enabled") else "❌"
            triggered = g.get("triggeredCount", 0)
            lines.append(f"- {enabled} **{name}** — triggered {triggered}x")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="streamable_http", port=int(os.getenv("SCC_MCP_PORT", "8006")))
