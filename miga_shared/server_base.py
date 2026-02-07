"""Base MCP server lifecycle — AGNTCY registration, Redis connect, health check."""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from miga_shared.agntcy import DirectoryClient, IdentityBadge, OASFRecord
from miga_shared.clients import CiscoAPIClient
from miga_shared.models import HealthStatus, PlatformType
from miga_shared.utils.redis_bus import RedisPubSub

logger = logging.getLogger("miga.base")


@asynccontextmanager
async def miga_lifespan(
    oasf: OASFRecord,
    api_factory=None,
):
    """Standard lifespan for every MIGA MCP server.

    Yields a dict with: api, bus, directory, badge, cid, start_time
    """
    start = time.time()
    api = api_factory() if api_factory else None
    bus = RedisPubSub()
    directory = DirectoryClient()
    badge = IdentityBadge(subject=f"miga/{oasf.name}")

    await bus.connect()
    cid = await directory.register(oasf)

    try:
        yield {
            "api": api,
            "bus": bus,
            "directory": directory,
            "badge": badge,
            "cid": cid,
            "start_time": start,
            "oasf": oasf,
        }
    finally:
        if cid and cid not in ("standalone", "error"):
            await directory.deregister(cid)
        await bus.close()
        if api:
            await api.close()
        await directory.close()


def add_health_tool(mcp_server: FastMCP, platform: PlatformType, name: str):
    """Add a standard /health tool to any MCP server."""

    @mcp_server.tool(
        name=f"{name}_health",
        annotations={"title": f"{name} Health Check", "readOnlyHint": True},
    )
    async def health_check(ctx=None) -> str:
        """Return service health status."""
        import json
        state = ctx.request_context.lifespan_state
        uptime = time.time() - state.get("start_time", time.time())
        status = HealthStatus(
            service=name,
            platform=platform,
            uptime_seconds=uptime,
            details={"cid": state.get("cid", "unknown")},
        )
        return json.dumps(status.model_dump(mode="json"), indent=2)
