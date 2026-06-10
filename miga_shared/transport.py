"""MCP client transport abstraction for the MIGA gateway.

The gateway connects to each downstream server as an MCP **client** over that
server's *native* transport. This module wraps the official MCP Python SDK client
sessions and selects the right one from a :class:`~miga_shared.registry.ServerSpec`:

* ``http``  -> Streamable HTTP endpoint (optionally bearer/header auth)
* ``sse``   -> HTTP+SSE endpoint
* ``stdio`` -> a spawned subprocess speaking MCP over stdio. This also covers the
  ``docker run -i ...`` pattern (``command: docker``, ``args: [run, -i, --rm, ...]``)
  and bundled local processes (``fastmcp run ...``, ``python -m ...``).

MIGA does not re-vendor or re-implement any upstream server logic; it only opens a
client session and forwards ``tools/list`` and ``tools/call``.

Sessions are opened per call (connect -> initialize -> call -> close). This keeps
subprocess and HTTP lifecycles simple and robust for a fan-out gateway. The SDK
imports are deferred so this module can be imported (and mocked in tests) without
the ``mcp`` package present.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from miga_shared.registry import ServerSpec

logger = logging.getLogger("miga.transport")


class MCPTransportError(Exception):
    """Raised when a downstream MCP server cannot be reached or returns an error."""


def _normalize_result(result: Any) -> Any:
    """Flatten an MCP ``CallToolResult`` into plain text / structured data."""
    # Prefer structured content when the server provides it.
    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured
    content = getattr(result, "content", None)
    if content is None:
        return result
    texts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            texts.append(text)
    if getattr(result, "isError", False):
        raise MCPTransportError("; ".join(texts) or "downstream tool error")
    return "\n".join(texts) if texts else content


class MCPClientPool:
    """Opens transient MCP client sessions to downstream servers from their specs.

    A "pool" in name and intent — connection reuse can be layered in later — but
    today each call opens and tears down its own session, which is the safe default
    for mixed HTTP and subprocess transports.
    """

    def __init__(self, *, environ: dict[str, str] | None = None, timeout: float = 60.0):
        self._environ = environ if environ is not None else os.environ
        self._timeout = timeout

    # -- session construction -------------------------------------------------

    @asynccontextmanager
    async def _session(self, spec: ServerSpec):
        """Yield an initialized MCP ``ClientSession`` for ``spec`` over the right
        transport. Defers all SDK imports so the module stays import-safe."""
        from datetime import timedelta

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.sse import sse_client
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamablehttp_client

        ttype = spec.transport_type
        read_timeout = timedelta(seconds=self._timeout)

        if ttype in ("http", "sse"):
            url = spec.url
            if not url:
                raise MCPTransportError(f"{spec.name}: http/sse transport missing url")
            headers = spec.auth_headers(environ=self._environ)
            client = (
                streamablehttp_client(url, headers=headers)
                if ttype == "http"
                else sse_client(url, headers=headers)
            )
            async with client as streams:
                # streamable_http yields (read, write, get_session_id); sse yields (read, write)
                read, write = streams[0], streams[1]
                async with ClientSession(read, write, read_timeout_seconds=read_timeout) as session:
                    await session.initialize()
                    yield session

        elif ttype == "stdio":
            command = spec.command
            if not command:
                raise MCPTransportError(f"{spec.name}: stdio transport missing command")
            # Pass declared env through to the child (covers `docker run -e VAR`,
            # which reads VAR from the gateway's environment).
            child_env = dict(self._environ)
            params = StdioServerParameters(command=command, args=spec.args, env=child_env)
            async with (
                stdio_client(params) as (read, write),
                ClientSession(read, write, read_timeout_seconds=read_timeout) as session,
            ):
                await session.initialize()
                yield session
        else:
            raise MCPTransportError(f"{spec.name}: unsupported transport type {ttype!r}")

    # -- operations -----------------------------------------------------------

    async def list_tools(self, spec: ServerSpec) -> list[dict[str, Any]]:
        """Return the downstream server's advertised tools (dynamic discovery)."""
        async with self._session(spec) as session:
            result = await session.list_tools()
            return [
                {"name": t.name, "description": getattr(t, "description", "") or ""}
                for t in result.tools
            ]

    async def call_tool(self, spec: ServerSpec, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call ``tool_name`` on the downstream server and return normalized output."""
        try:
            async with self._session(spec) as session:
                result = await session.call_tool(tool_name, arguments or {})
                return _normalize_result(result)
        except MCPTransportError:
            raise
        except Exception as exc:  # pragma: no cover - network/subprocess failure paths
            raise MCPTransportError(f"{spec.name}: {exc}") from exc

    async def close(self) -> None:
        """No persistent state today; present for lifecycle symmetry."""
        return None
