"""AGNTCY integration — OASF records, Agent Directory, and Identity badges."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from miga_shared.models import MIGARole, PlatformCapability, PlatformType

logger = logging.getLogger("miga.agntcy")


# ---------------------------------------------------------------------------
# OASF Record
# ---------------------------------------------------------------------------


@dataclass
class OASFRecord:
    """Open Agent Schema Framework record — each MCP server publishes one."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    platform: PlatformType | None = None
    skills: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    capabilities: list[PlatformCapability] = field(default_factory=list)
    roles: list[MIGARole] = field(default_factory=list)
    transport: str = "streamable_http"
    endpoint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "attributes": {
                "platform": self.platform.value if self.platform else None,
                "roles": [r.value for r in self.roles],
                "transport": self.transport,
                "endpoint": self.endpoint,
            },
            "skills": self.skills,
            "domains": self.domains,
            "modules": {
                "mcp_server": {
                    "tools": [
                        {
                            "name": c.tool_name,
                            "description": c.description,
                            "roles": [r.value for r in c.roles],
                            "read_only": c.read_only,
                            "destructive": c.destructive,
                            "requires_approval": c.requires_approval,
                        }
                        for c in self.capabilities
                    ]
                }
            },
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OASFRecord:
        attrs = data.get("attributes", {})
        tools = data.get("modules", {}).get("mcp_server", {}).get("tools", [])
        platform = PlatformType(attrs["platform"]) if attrs.get("platform") else None
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            platform=platform,
            roles=[MIGARole(r) for r in attrs.get("roles", [])],
            transport=attrs.get("transport", "streamable_http"),
            endpoint=attrs.get("endpoint", ""),
            skills=data.get("skills", []),
            domains=data.get("domains", []),
            capabilities=[
                PlatformCapability(
                    tool_name=t["name"],
                    description=t.get("description", ""),
                    roles=[MIGARole(r) for r in t.get("roles", [])],
                    read_only=t.get("read_only", True),
                    destructive=t.get("destructive", False),
                    requires_approval=t.get("requires_approval", False),
                    platform=platform or PlatformType.INFER,
                )
                for t in tools
            ],
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Agent Directory Client
# ---------------------------------------------------------------------------


class DirectoryClient:
    """Client for the real AGNTCY Directory (``dir-apiserver``) via the official
    **Python SDK** ``agntcy-dir`` (``agntcy.dir_sdk.client``).

    The SDK is a native gRPC client (install: ``uv add agntcy-dir --index
    https://buf.build/gen/python``); it does **not** require the ``dirctl`` binary at
    runtime — per the SDK docs, ``dirctl`` is only needed for *signing*, which MIGA
    does not use (Agent Badges are "planned"). This replaces the earlier
    dirctl-subprocess client; the false "dir is Go-only" premise has been corrected.

    Mapping (confirmed from the dir client source — Go names; the Python SDK mirrors
    these and the exact Python casing is flagged for verification in
    VERIFY_DIRECTORY.md):
      * ``Push(record) -> RecordRef`` (structured, carries ``.cid``) — publish.
      * ``Pull(ref) -> Record`` — fetch by ref/CID.
      * ``SearchRecords`` / ``SearchCIDs`` — discovery.
      * ``Delete(ref)`` — remove.

    **Best-effort by design.** If the SDK is not installed or the directory is
    unreachable, methods log and return ``"standalone"``/``"error"`` and the gateway
    keeps routing from ``config/server-registry.yaml``. Routing never depends on the
    directory. NOT verified against a live directory in this environment (no buf.build
    egress / no live stack) — treat as drafted-pending-verification.
    """

    def __init__(self, addr: str | None = None, *, timeout: float = 30.0):
        # gRPC host:port of dir-apiserver (NOT an http URL).
        self.addr = addr or os.getenv("AGNTCY_DIRECTORY_ADDR", "agntcy-directory:8888")
        self.timeout = timeout
        self._client: Any = None  # lazily-constructed SDK Client

    # -- SDK plumbing ---------------------------------------------------------

    def _sdk(self) -> Any:
        """Lazily construct the agntcy-dir SDK ``Client``. Returns None (best-effort)
        if the SDK isn't installed or the client can't be constructed — the gateway
        then runs standalone. The SDK import is deferred so this module imports fine
        without ``agntcy-dir`` present (e.g. in CI/sandbox)."""
        if self._client is not None:
            return self._client
        try:
            from agntcy.dir_sdk.client import Client, Config
        except ImportError:
            logger.warning(
                "agntcy-dir SDK not installed — AGNTCY Directory disabled (standalone). "
                "Install: uv add agntcy-dir --index https://buf.build/gen/python"
            )
            return None
        # The SDK also reads DIRECTORY_CLIENT_SERVER_ADDRESS; set it for consistency.
        os.environ.setdefault("DIRECTORY_CLIENT_SERVER_ADDRESS", self.addr)
        try:
            self._client = Client(Config(server_address=self.addr))
        except Exception as exc:  # noqa: BLE001 - best-effort init
            logger.warning("AGNTCY Directory client init failed (%s) — standalone", exc)
            return None
        return self._client

    @staticmethod
    def _resolve(client: Any, names: tuple[str, ...]):
        """Return the first existing callable among ``names`` on the SDK client.

        The Go client uses PascalCase (Push/Pull/Delete); the Python wrapper's exact
        casing is confirmed during live verification, so we accept both forms."""
        for n in names:
            m = getattr(client, n, None)
            if callable(m):
                return m
        raise AttributeError(f"agntcy-dir SDK Client exposes none of {names}")

    @staticmethod
    def _to_record(record_dict: dict[str, Any]) -> Any:
        """Build the SDK Record message from an OASF JSON dict via protobuf JSON
        parsing. The exact model module path is flagged for verification."""
        from agntcy.dir_sdk.models import core_v1  # path to confirm (core_v1)
        from google.protobuf import json_format

        return json_format.ParseDict(record_dict, core_v1.Record())

    @staticmethod
    def _cid_of(ref: Any) -> str:
        """Extract the CID from a structured RecordRef (no string scraping)."""
        for attr in ("cid", "Cid"):
            v = getattr(ref, attr, None)
            if v:
                return str(v)
        getter = getattr(ref, "GetCid", None) or getattr(ref, "get_cid", None)
        if callable(getter):
            v = getter()
            if v:
                return str(v)
        return "unknown"

    @staticmethod
    def _is_unreachable(exc: Exception) -> bool:
        low = str(exc).lower()
        return any(
            k in low
            for k in ("unavailable", "connection", "refused", "deadline", "dial", "no such host")
        )

    def _push_sync(self, client: Any, record_dict: dict[str, Any]) -> str:
        record = self._to_record(record_dict)
        push = self._resolve(client, ("push", "Push"))
        return self._cid_of(push(record))

    # -- public API (signatures preserved for server_base / gateway) ----------

    async def register(self, record: OASFRecord) -> str:
        """Best-effort publish of a MIGA ``OASFRecord`` (compat for server_base).
        Prefer ``register_record()`` with a full OASF document."""
        return await self.register_record(record.to_dict())

    async def register_record(self, record: dict[str, Any]) -> str:
        """Publish a full OASF capability record (a parsed ``oasf/records/*.json``
        document) via the SDK ``Push`` and return its structured CID. Returns
        ``"standalone"``/``"error"`` if the SDK/directory is unavailable (non-fatal —
        routing continues from the registry)."""
        client = self._sdk()
        if client is None:
            return "standalone"
        name = record.get("name", "record")
        try:
            cid = await asyncio.wait_for(
                asyncio.to_thread(self._push_sync, client, record), timeout=self.timeout
            )
        except TimeoutError:
            logger.warning("AGNTCY Directory push timed out — standalone")
            return "standalone"
        except Exception as exc:  # noqa: BLE001 - best-effort
            if self._is_unreachable(exc):
                logger.warning("AGNTCY Directory unreachable at %s — standalone", self.addr)
                return "standalone"
            logger.error("Directory push failed for %s: %s", name, exc)
            return "error"
        logger.info("Published %s to AGNTCY Directory (CID: %s)", name, cid)
        return cid

    async def pull(self, cid: str) -> dict[str, Any] | None:
        """Pull a record by CID. Returns the OASF JSON dict, or None on any failure."""
        client = self._sdk()
        if client is None:
            return None

        def _pull_sync() -> dict[str, Any] | None:
            from agntcy.dir_sdk.models import core_v1
            from google.protobuf import json_format

            ref = core_v1.RecordRef(cid=cid)
            pull = self._resolve(client, ("pull", "Pull"))
            rec = pull(ref)
            return json_format.MessageToDict(rec)

        try:
            return await asyncio.wait_for(asyncio.to_thread(_pull_sync), timeout=self.timeout)
        except Exception:  # noqa: BLE001 - best-effort
            return None

    async def discover(
        self,
        skills: list[str] | None = None,
        roles: list[MIGARole] | None = None,
        platform: PlatformType | None = None,
    ) -> list[OASFRecord]:
        """Best-effort discovery via the SDK search. NOTE: routing does **not** depend
        on this — the gateway routes from ``config/server-registry.yaml``. Returns
        ``[]`` on any error. Search→OASFRecord mapping is intentionally left empty
        (search returns CIDs/identifiers); wiring discovery into routing is a future
        step, not done now."""
        client = self._sdk()
        if client is None:
            return []
        return []

    async def deregister(self, cid: str) -> bool:
        client = self._sdk()
        if client is None:
            return False

        def _delete_sync() -> bool:
            from agntcy.dir_sdk.models import core_v1

            ref = core_v1.RecordRef(cid=cid)
            delete = self._resolve(client, ("delete", "Delete"))
            delete(ref)
            return True

        try:
            return await asyncio.wait_for(asyncio.to_thread(_delete_sync), timeout=self.timeout)
        except Exception:  # noqa: BLE001 - best-effort
            return False

    async def health(self) -> bool:
        """Client-readiness check: True only if the agntcy-dir SDK is importable and a
        Client can be constructed. This does NOT confirm the server is live — real
        reachability is verified by the VERIFY_DIRECTORY.md runbook."""
        return self._sdk() is not None

    async def close(self):
        """Close the SDK client if it exposes a close()/Close()."""
        if self._client is None:
            return
        closer = getattr(self._client, "close", None) or getattr(self._client, "Close", None)
        if callable(closer):
            with contextlib.suppress(Exception):
                await asyncio.to_thread(closer)
        self._client = None


# ---------------------------------------------------------------------------
# Identity Badge
# ---------------------------------------------------------------------------


@dataclass
class IdentityBadge:
    """AGNTCY Identity badge — cryptographic server identity."""

    subject: str  # e.g. "miga/meraki_mcp"
    issuer: str = ""
    badge_type: str = "mcp_server"
    public_key: str | None = None
    signature: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.issuer:
            self.issuer = os.getenv("AGNTCY_IDENTITY_ISSUER", "miga")

    def verify(self) -> bool:
        if os.getenv("MIGA_ENV") == "development":
            return True
        return bool(self.signature and self.public_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "issuer": self.issuer,
            "badge_type": self.badge_type,
            "claims": self.claims,
        }
