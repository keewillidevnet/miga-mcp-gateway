"""MIGA Gateway MCP Server — Role-based routing with AGNTCY dynamic discovery.

The Gateway is itself an MCP server that exposes 6 role-based meta-tools
(Observability, Security, Automation, Configuration, Compliance, Identity).
Each meta-tool fans out to the relevant **real, external** platform MCP servers
and to MIGA's own INFER fusion engine, aggregates results, and returns unified
responses.

Architecture (post real-server migration):
- FastMCP server exposing meta-tools to the Webex Bot / external clients.
- Connections are driven entirely by ``config/server-registry.yaml`` (no hardcoded
  endpoints). Each entry declares how to reach a published upstream MCP server.
- The gateway talks to every downstream server as an MCP **client** via the
  transport abstraction (``miga_shared.transport``): remote HTTP/SSE URLs and local
  stdio subprocesses (including the ``docker run -i`` pattern).
- At startup the gateway publishes each server's OASF capability record to the
  AGNTCY Directory so dynamic discovery keeps working, then periodically refreshes.
- INFER consumes the normalized output of whatever servers are registered.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from miga_shared.agntcy import DirectoryClient, IdentityBadge
from miga_shared.models import MIGARole
from miga_shared.registry import ServerSpec, load_registry
from miga_shared.role_skills import load_role_skills
from miga_shared.transport import MCPClientPool, MCPTransportError
from miga_shared.utils.redis_bus import RedisPubSub


def _configure_logging() -> None:
    """Make the ``miga.*`` loggers' INFO output (e.g. the OASF publish count) survive
    uvicorn's logging reconfiguration when FastMCP runs over streamable-http. Called at
    import AND again at lifespan start (which runs after uvicorn has reconfigured).
    NOTE (cosmetic, not live-verified): pending operator re-run on a networked host."""
    lg = logging.getLogger("miga")
    lg.setLevel(logging.INFO)
    lg.disabled = False
    if not any(getattr(h, "_miga", False) for h in lg.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler._miga = True  # type: ignore[attr-defined]
        lg.addHandler(handler)


_configure_logging()
logger = logging.getLogger("miga.gateway")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Defense-in-depth cap on output forwarded from untrusted upstream servers.
MAX_FORWARDED_CHARS = int(os.getenv("MIGA_MAX_TOOL_RESPONSE_CHARS", "50000"))


def _cap(text: str) -> str:
    if len(text) > MAX_FORWARDED_CHARS:
        return text[:MAX_FORWARDED_CHARS] + "\n…[truncated by MIGA gateway]"
    return text


# Tool-name fragments that are safe, read-only "summary" calls to fan out with no
# arguments during a role sweep.
_SUMMARY_HINTS = ("health", "overview", "status", "summary", "list")


# ---------------------------------------------------------------------------
# Routing Table — built from the config registry (no hardcoded endpoints)
# ---------------------------------------------------------------------------


class RoutingTable:
    """Maps roles to the registered downstream servers that serve them.

    Connection details live on each :class:`ServerSpec`; the gateway resolves a
    role to a set of servers and uses the transport pool to reach them.
    """

    def __init__(self) -> None:
        self._by_name: dict[str, ServerSpec] = {}
        self._by_role: dict[MIGARole, list[ServerSpec]] = {r: [] for r in MIGARole}
        self._last_refresh: float = 0.0

    def load_from_registry(self, specs: list[ServerSpec]) -> None:
        self._by_name = {s.name: s for s in specs}
        self._by_role = {r: [] for r in MIGARole}
        for spec in specs:
            for role in spec.roles:
                try:
                    self._by_role[MIGARole(role)].append(spec)
                except ValueError:
                    logger.warning("Server %s declares unknown role %r", spec.name, role)
        self._last_refresh = time.time()
        logger.info(
            "Routing table loaded from registry: %d servers across %d roles",
            len(self._by_name),
            sum(1 for v in self._by_role.values() if v),
        )

    def servers_for_role(self, role: MIGARole) -> list[ServerSpec]:
        return list(self._by_role.get(role, []))

    async def discovered_servers_for_role(
        self,
        role: MIGARole,
        directory,
        role_skills: dict[str, list[str]],
    ) -> list[ServerSpec] | None:
        """Resolve a role's servers via a live directory search.

        Searches the AGNTCY Directory for the role's OASF skills, maps each matched
        record back to a registry ServerSpec via its ``miga_registry_ref`` annotation,
        dedupes, and keeps only specs whose registry roles include this role. Returns
        ``None`` (not ``[]``) when discovery is unavailable or yields nothing, to signal
        "fall back to the static registry". Never raises; the directory client is
        best-effort.
        """
        role_value = role.value if hasattr(role, "value") else str(role)
        skills = role_skills.get(role_value) or []
        if not skills:
            return None
        try:
            results = await directory.discover(skills=skills)
        except Exception as exc:  # noqa: BLE001 - defensive; discovery must not break routing
            logger.warning("directory discovery raised for role %s: %r", role_value, exc)
            return None
        if not results:
            return None
        specs: list[ServerSpec] = []
        seen: set[str] = set()
        for r in results:
            ref = r.get("registry_ref")
            spec = self._by_name.get(ref) if ref else None
            if spec is None or spec.name in seen or role_value not in spec.roles:
                continue
            seen.add(spec.name)
            specs.append(spec)
        return specs or None

    def get(self, name: str) -> ServerSpec | None:
        return self._by_name.get(name)

    def all(self) -> dict[str, ServerSpec]:
        return dict(self._by_name)


# ---------------------------------------------------------------------------
# AGNTCY directory publishing of OASF capability records
# ---------------------------------------------------------------------------


async def _publish_oasf_records(directory: DirectoryClient, specs: list[ServerSpec]) -> int:
    """Best-effort publish of each server's OASF capability record (the JSON files
    under ``oasf/records/``) into the AGNTCY Directory so discovery keeps working.
    Non-fatal: a missing directory or record only logs a warning."""
    published = 0
    for spec in specs:
        record_path = _REPO_ROOT / spec.oasf_record
        if not record_path.exists():
            logger.warning("OASF record missing for %s at %s", spec.name, record_path)
            continue
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            await directory.register_record(record)
            published += 1
        except Exception as exc:  # pragma: no cover - network failure path
            logger.warning("Failed to publish OASF record for %s: %s", spec.name, exc)
    return published


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

routing = RoutingTable()
pool = MCPClientPool()


@asynccontextmanager
async def app_lifespan(_server: FastMCP):
    # FastMCP's lifespan_wrapper calls lifespan(server), so this MUST accept the server
    # argument. Defining it with no parameter raised TypeError per request, which closed
    # the response stream and surfaced as anyio.ClosedResourceError / HTTP 500 on /mcp.
    _configure_logging()  # re-assert after uvicorn's logging reconfiguration
    directory = DirectoryClient()
    bus = RedisPubSub()
    badge = IdentityBadge(subject="miga/gateway")
    start = time.time()

    await bus.connect()

    specs = load_registry()
    routing.load_from_registry(specs)
    role_skills = load_role_skills()
    _published = await _publish_oasf_records(directory, specs)
    logger.info("Published %d/%d OASF records to AGNTCY Directory", _published, len(specs))

    async def _refresh_loop():
        while True:
            await asyncio.sleep(60)
            try:
                routing.load_from_registry(load_registry())
            except Exception as exc:
                logger.error("Registry refresh failed: %s", exc)

    refresh_task = asyncio.create_task(_refresh_loop())
    try:
        yield {
            "routing": routing,
            "pool": pool,
            "directory": directory,
            "role_skills": role_skills,
            "bus": bus,
            "badge": badge,
            "start_time": start,
        }
    finally:
        refresh_task.cancel()
        await pool.close()
        await bus.close()
        await directory.close()


mcp = FastMCP(
    "miga_gateway",
    lifespan=app_lifespan,
    host="0.0.0.0",
    port=int(os.getenv("MIGA_GATEWAY_PORT", "8000")),
)


@mcp.custom_route("/health", methods=["GET"])
async def _http_health(_request) -> JSONResponse:
    """Plain-HTTP health endpoint for the container HEALTHCHECK. FastMCP serves the MCP
    protocol at /mcp, so a `curl /health` probe 404s without this lightweight route —
    lower-risk than probing the MCP path. NOTE (cosmetic, not live-verified)."""
    return JSONResponse({"status": "ok", "service": "miga_gateway"})


def _serialize_tool_result(result: Any) -> list[dict[str, str]]:
    """Flatten a FastMCP ``call_tool`` result (Sequence[ContentBlock] | dict) into
    MCP-shaped text content blocks."""
    if isinstance(result, dict):
        return [{"type": "text", "text": json.dumps(result, default=str)}]
    blocks: list[dict[str, str]] = []
    for block in result or []:
        text = getattr(block, "text", None)
        if text is not None:
            blocks.append({"type": "text", "text": text})
    return blocks


@mcp.custom_route("/internal/call", methods=["POST"])
async def _internal_call(request) -> JSONResponse:
    """Dev-only internal fallback. POST {"tool", "arguments"} -> invoke the tool and
    return MCP-shaped {"content": [{"type": "text", "text": ...}]}.

    The MCP streamable-http client is the PRIMARY path the Webex bot uses (the bot is an
    MCP client). This route exists ONLY so a single demo session can still succeed if the
    streamable-http handshake misbehaves in the operator's environment. It is a dev
    convenience and fallback, not a replacement for the MCP client and not a claim that
    the bot is not an MCP client. Guarded to development mode and loopback/private callers
    so it cannot be reached from the public internet.
    """
    import ipaddress

    if os.getenv("MIGA_ENV", "development") != "development":
        return JSONResponse(
            {"error": "internal route disabled outside development"}, status_code=403
        )
    host = request.client.host if request.client else ""
    try:
        ok_local = (
            host == ""
            or ipaddress.ip_address(host).is_loopback
            or ipaddress.ip_address(host).is_private
        )
    except ValueError:
        ok_local = host in ("localhost", "")
    if not ok_local:
        return JSONResponse({"error": "internal route is loopback/private only"}, status_code=403)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - malformed body
        return JSONResponse({"error": "invalid json body"}, status_code=400)
    tool = body.get("tool")
    arguments = body.get("arguments") or {}
    if not tool:
        return JSONResponse({"error": "missing 'tool'"}, status_code=400)
    try:
        result = await mcp.call_tool(tool, arguments)
    except Exception as exc:  # noqa: BLE001 - dev convenience: return error as text, never 500
        return JSONResponse({"content": [{"type": "text", "text": f"tool error: {exc}"}]})
    return JSONResponse({"content": _serialize_tool_result(result)})


# ---------------------------------------------------------------------------
# Input Models for Meta-Tools
# ---------------------------------------------------------------------------


class RoleQueryInput(BaseModel):
    """Input for role-based meta-tool queries."""

    model_config = ConfigDict(extra="forbid")
    query: str = Field(default="", description="Natural language query or specific action")
    platforms: list[str] | None = Field(
        default=None, description="Filter to specific server names (registry names)"
    )
    tool_name: str | None = Field(
        default=None, description="Call a specific downstream tool directly by name"
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Arguments to pass to the tool"
    )


# ---------------------------------------------------------------------------
# Fan-out logic
# ---------------------------------------------------------------------------


async def _call_named_tool(
    servers: list[ServerSpec], tool_name: str, arguments: dict[str, Any]
) -> str:
    """Find which registered server advertises ``tool_name`` and call it."""
    for spec in servers:
        try:
            tools = await pool.list_tools(spec)
        except MCPTransportError as exc:
            logger.debug("list_tools failed for %s: %s", spec.name, exc)
            continue
        if any(t["name"] == tool_name for t in tools):
            try:
                result = await pool.call_tool(spec, tool_name, arguments)
                text = (
                    result if isinstance(result, str) else json.dumps(result, indent=2, default=str)
                )
                return _cap(text)
            except MCPTransportError as exc:
                return f"❌ `{tool_name}` on {spec.display_name} failed: {exc}"
    return f"❌ Tool `{tool_name}` not found on any server for this role."


def _discovery_enabled() -> bool:
    return os.getenv("MIGA_DISCOVERY_ROUTING", "").strip().lower() in ("1", "true", "yes", "on")


async def _resolve_servers(role: MIGARole, ctx) -> list[ServerSpec]:
    """Pick the servers for a role. Default: the static registry (byte-for-byte the
    prior behavior). With MIGA_DISCOVERY_ROUTING enabled and a directory in
    lifespan_context, try a live directory search first and fall back to static on any
    empty/unavailable result."""
    if _discovery_enabled() and ctx is not None:
        state = getattr(getattr(ctx, "request_context", None), "lifespan_context", None) or {}
        directory = state.get("directory")
        role_skills = state.get("role_skills") or {}
        if directory is not None:
            discovered = await routing.discovered_servers_for_role(role, directory, role_skills)
            if discovered:
                logger.info(
                    "role %s resolved via directory search: %s",
                    role.value,
                    [s.name for s in discovered],
                )
                return discovered
            logger.info(
                "directory discovery empty/unavailable for role %s; using static registry",
                role.value,
            )
    return routing.servers_for_role(role)


async def _fan_out(role: MIGARole, params: RoleQueryInput, ctx) -> str:
    """Fan out a query to all real servers (plus INFER) serving a given role."""
    servers = await _resolve_servers(role, ctx)
    if params.platforms:
        wanted = set(params.platforms)
        servers = [s for s in servers if s.name in wanted]

    if not servers:
        return f"No servers registered for role **{role.value}**."

    if params.tool_name:
        return await _call_named_tool(servers, params.tool_name, params.arguments)

    # Discovery sweep: list tools per server and call read-only summary tools.
    lines = [f"## {role.value.title()} — Cross-Platform Summary\n"]

    async def _probe(spec: ServerSpec) -> tuple[ServerSpec, Any]:
        try:
            tools = await pool.list_tools(spec)
        except MCPTransportError as exc:
            return spec, exc
        summary_tools = [
            t["name"] for t in tools if any(h in t["name"].lower() for h in _SUMMARY_HINTS)
        ]
        if not summary_tools:
            return spec, {"tools": [t["name"] for t in tools]}
        try:
            return spec, await pool.call_tool(spec, summary_tools[0], {})
        except MCPTransportError as exc:
            return spec, exc

    results = await asyncio.gather(*(_probe(s) for s in servers), return_exceptions=True)
    for item in results:
        if isinstance(item, Exception):
            lines.append(f"### ❌ (gateway error)\n_{item}_\n")
            continue
        spec, result = item
        if isinstance(result, (MCPTransportError, Exception)):
            lines.append(f"### 🔴 {spec.display_name}\n_unreachable: {result}_\n")
        else:
            text = result if isinstance(result, str) else json.dumps(result, indent=2, default=str)
            lines.append(f"### {spec.display_name}\n{text[:500]}\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Role-based Meta-Tools
# ---------------------------------------------------------------------------


@mcp.tool(name="observability", annotations={"readOnlyHint": True, "idempotentHint": True})
async def observability(params: RoleQueryInput, ctx: Context) -> str:
    """Query observability data across the registered platforms — health,
    telemetry, ThousandEyes path analysis, Catalyst Center/Meraki assurance, and
    INFER anomalies."""
    return await _fan_out(MIGARole.OBSERVABILITY, params, ctx)


@mcp.tool(name="security", annotations={"readOnlyHint": True, "idempotentHint": True})
async def security(params: RoleQueryInput, ctx: Context) -> str:
    """Query security data across the registered platforms — Splunk/Meraki security
    events, ISE posture, and INFER anomaly correlation."""
    return await _fan_out(MIGARole.SECURITY, params, ctx)


@mcp.tool(name="automation", annotations={"readOnlyHint": False})
async def automation(params: RoleQueryInput, ctx: Context) -> str:
    """Execute automation workflows across platforms — SD-WAN/Catalyst Center
    actions and ServiceNow ticketing. ⚠️ Destructive actions require approval."""
    return await _fan_out(MIGARole.AUTOMATION, params, ctx)


@mcp.tool(name="configuration", annotations={"readOnlyHint": True, "idempotentHint": True})
async def configuration(params: RoleQueryInput, ctx: Context) -> str:
    """Query and manage configuration across platforms — Meraki/SD-WAN/Catalyst
    Center settings and NetBox source-of-truth data."""
    return await _fan_out(MIGARole.CONFIGURATION, params, ctx)


@mcp.tool(name="compliance", annotations={"readOnlyHint": True, "idempotentHint": True})
async def compliance(params: RoleQueryInput, ctx: Context) -> str:
    """Query compliance and audit data — ISE posture, NetBox change history, and
    INFER risk scoring."""
    return await _fan_out(MIGARole.COMPLIANCE, params, ctx)


@mcp.tool(name="identity", annotations={"readOnlyHint": True, "idempotentHint": True})
async def identity(params: RoleQueryInput, ctx: Context) -> str:
    """Query identity and access data — Cisco ISE sessions, endpoints, and
    authorization posture."""
    return await _fan_out(MIGARole.IDENTITY, params, ctx)


# ---------------------------------------------------------------------------
# Cross-platform convenience + health
# ---------------------------------------------------------------------------


@mcp.tool(name="network_status", annotations={"readOnlyHint": True, "idempotentHint": True})
async def network_status(ctx: Context) -> str:
    """Get a quick cross-platform reachability summary of all registered servers."""
    servers = routing.all()
    lines = ["## MIGA — Network Status Overview\n", f"**Registered Servers:** {len(servers)}\n"]

    async def _check(spec: ServerSpec):
        try:
            await pool.list_tools(spec)
            return spec, True
        except Exception:
            return spec, False

    results = await asyncio.gather(*(_check(s) for s in servers.values()), return_exceptions=True)
    for item in results:
        if isinstance(item, Exception):
            continue
        spec, ok = item
        dot = "🟢" if ok else "🔴"
        state = "reachable" if ok else "unreachable"
        lines.append(f"- {dot} **{spec.display_name}** (`{spec.name}`) — {state}")
    return "\n".join(lines)


@mcp.tool(name="gateway_health", annotations={"readOnlyHint": True})
async def gateway_health(ctx: Context) -> str:
    """Gateway health check — routing table status and uptime."""
    state = ctx.request_context.lifespan_context
    uptime = time.time() - state["start_time"]
    servers = routing.all()
    return json.dumps(
        {
            "service": "miga_gateway",
            "status": "healthy",
            "version": "1.0.0",
            "uptime_seconds": round(uptime, 1),
            "routing_table": {
                "servers": len(servers),
                "last_refresh": routing._last_refresh,
            },
            "servers": {
                name: {"transport": spec.transport_type, "roles": spec.roles, "status": spec.status}
                for name, spec in servers.items()
            },
        },
        indent=2,
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
