"""Module entry point so ``python -m servers.infer_mcp`` starts INFER over stdio.

The server registry (``config/server-registry.yaml``) launches INFER as a spawned stdio
subprocess with the command ``python -m servers.infer_mcp``. Without this file the package
cannot be executed directly -- Python raises "No module named servers.infer_mcp.__main__;
'servers.infer_mcp' is a package and cannot be directly executed" -- so the gateway could
never connect to INFER and every INFER-backed tool call failed downstream (surfacing as an
"unhandled errors in a TaskGroup" error from the gateway role meta-tools).

Running over stdio matches the registry's ``transport.type: stdio``. ``server.py``'s own
``__main__`` block runs an HTTP variant for standalone use; this stdio entry point is the
one the gateway spawns. Internals are untouched: this only re-exports the existing ``mcp``
object and runs it on the stdio transport.
"""

from __future__ import annotations

from servers.infer_mcp.server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
