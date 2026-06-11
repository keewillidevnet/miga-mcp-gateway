"""Module entry point so ``python -m servers.infer_mcp`` starts INFER over stdio.

This is a convenience entry point for local / non-Docker use. In the Docker stack
INFER runs as the long-lived ``infer-mcp`` HTTP service (Dockerfile target ``infer``;
``server.py``'s own ``__main__`` serves StreamableHTTP on ``INFER_MCP_PORT``), and the
gateway connects to it over HTTP per ``config/server-registry.yaml`` -- it does NOT
spawn INFER as a stdio child. Without this file, ``python -m servers.infer_mcp`` fails
with "No module named servers.infer_mcp.__main__". Internals are untouched: this only
re-exports the existing ``mcp`` object and runs it on the stdio transport.
"""

from __future__ import annotations

from servers.infer_mcp.server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
