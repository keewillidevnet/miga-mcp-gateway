"""AGNTCY integration — OASF records, Agent Directory, and Identity badges."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
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


class DirectoryError(Exception):
    """Raised for non-recoverable dirctl/transport problems (timeouts, etc.)."""


class DirectoryClient:
    """Client for the real AGNTCY Directory (``dir-apiserver``) via the official
    ``dirctl`` CLI.

    The directory exposes a **gRPC** API and stores OASF records as content-addressed
    **OCI artifacts (CIDs)** in a backing registry (zot). Rather than re-vendor that
    OCI packaging + CID computation, this client shells out to ``dirctl`` (argv,
    ``shell=False``) — the official, stable client surface (``push`` / ``pull`` /
    ``search`` / ``delete``). See VERIFY_DIRECTORY.md for the integration rationale,
    the runbook, and the uncertainties that still need live confirmation.

    **Best-effort by design.** If ``dirctl`` is missing or the directory is
    unreachable, ``register``/``register_record`` return ``"standalone"`` (or
    ``"error"``) and the gateway keeps routing from ``config/server-registry.yaml``.
    Routing never depends on the directory.

    NOT verified against a live directory in this environment (no container-registry
    egress). Treat as drafted-pending-verification.
    """

    def __init__(
        self,
        addr: str | None = None,
        *,
        dirctl_bin: str | None = None,
        timeout: float = 30.0,
    ):
        # gRPC host:port of dir-apiserver (NOT an http URL).
        self.addr = addr or os.getenv("AGNTCY_DIRECTORY_ADDR", "agntcy-directory:8888")
        self.dirctl_bin = dirctl_bin or os.getenv("DIRCTL_BIN", "dirctl")
        self.timeout = timeout

    # -- subprocess plumbing --------------------------------------------------

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        # dirctl resolves the server from this env var (or the --server-addr flag).
        env["DIRECTORY_CLIENT_SERVER_ADDRESS"] = self.addr
        return env

    async def _run(self, args: list[str], stdin: bytes | None = None) -> tuple[int, str, str]:
        """Run ``dirctl <args>`` as an argv subprocess (shell=False).

        Returns (returncode, stdout, stderr). Raises FileNotFoundError if the
        ``dirctl`` binary is absent, or DirectoryError on timeout."""
        proc = await asyncio.create_subprocess_exec(
            self.dirctl_bin,
            *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env(),
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(input=stdin), timeout=self.timeout)
        except TimeoutError as exc:
            proc.kill()
            raise DirectoryError(f"dirctl {args[0] if args else ''} timed out") from exc
        return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")

    @staticmethod
    def _parse_cid(stdout: str) -> str:
        """Extract the CID from ``dirctl push`` output. Defensive: the human format
        is ``Pushed record with CID <cid>``; JSON output is also handled. The exact
        format must be confirmed on a live run (see VERIFY_DIRECTORY.md)."""
        m = re.search(r"CID[:\s]+([A-Za-z0-9][A-Za-z0-9:_./-]{15,})", stdout)
        if m:
            return m.group(1).strip().rstrip(".")
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                for k in ("cid", "CID", "record_cid", "ref"):
                    if data.get(k):
                        return str(data[k])
        except (ValueError, TypeError):
            pass
        toks = [
            t
            for t in re.split(r"\s+", stdout.strip())
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_./-]{15,}", t)
        ]
        return toks[-1] if toks else "unknown"

    async def _push_bytes(self, payload: bytes, name: str) -> str:
        try:
            rc, out, err = await self._run(["push", "--stdin"], stdin=payload)
        except FileNotFoundError:
            logger.warning(
                "dirctl not found (%s) — AGNTCY Directory publish skipped (standalone)",
                self.dirctl_bin,
            )
            return "standalone"
        except DirectoryError as exc:
            logger.warning("AGNTCY Directory unavailable (%s) — standalone", exc)
            return "standalone"
        if rc != 0:
            low = (err or out).lower()
            if any(
                k in low for k in ("connection", "unavailable", "dial", "refused", "no such host")
            ):
                logger.warning("AGNTCY Directory unreachable at %s — standalone", self.addr)
                return "standalone"
            logger.error("dirctl push failed for %s: %s", name, (err or out).strip()[:300])
            return "error"
        cid = self._parse_cid(out)
        logger.info("Published %s to AGNTCY Directory (CID: %s)", name, cid)
        return cid

    # -- public API (signatures preserved for server_base / gateway) ----------

    async def register(self, record: OASFRecord) -> str:
        """Best-effort publish of a MIGA ``OASFRecord``. Prefer ``register_record()``
        with a full OASF document; this serializes the in-process record shape and is
        kept for compatibility with ``miga_shared.server_base``."""
        payload = json.dumps(record.to_dict()).encode()
        return await self._push_bytes(payload, getattr(record, "name", "record"))

    async def register_record(self, record: dict[str, Any]) -> str:
        """Publish a full OASF capability record (a parsed ``oasf/records/*.json``
        document) to the directory as an OCI artifact. Returns the assigned CID, or
        ``"standalone"``/``"error"`` if the directory/dirctl is unavailable
        (non-fatal — routing continues from the registry)."""
        payload = json.dumps(record).encode()
        return await self._push_bytes(payload, record.get("name", "record"))

    async def pull(self, cid: str) -> dict[str, Any] | None:
        """Pull a record by CID (or ``name[:version]``). Returns the OASF JSON, or
        None on any failure."""
        try:
            rc, out, _err = await self._run(["pull", cid])
        except (FileNotFoundError, DirectoryError):
            return None
        if rc != 0:
            return None
        try:
            return json.loads(out)
        except (ValueError, TypeError):
            return None

    async def discover(
        self,
        skills: list[str] | None = None,
        roles: list[MIGARole] | None = None,
        platform: PlatformType | None = None,
    ) -> list[OASFRecord]:
        """Best-effort discovery via ``dirctl search``.

        NOTE: routing does **not** depend on this — the gateway routes from
        ``config/server-registry.yaml``. Returns ``[]`` on any error. Search→OASFRecord
        mapping is intentionally left empty here (search returns CIDs/identifiers);
        wiring discovery into routing is a deliberate future step, not done now."""
        try:
            rc, _out, _err = await self._run(["search"])
        except (FileNotFoundError, DirectoryError):
            return []
        _ = rc
        return []

    async def deregister(self, cid: str) -> bool:
        try:
            rc, _out, _err = await self._run(["delete", cid])
        except (FileNotFoundError, DirectoryError):
            return False
        return rc == 0

    async def health(self) -> bool:
        """Client-readiness check: True only if the ``dirctl`` binary is resolvable.
        This does NOT confirm the server is live — real reachability is verified by
        the VERIFY_DIRECTORY.md runbook on a networked Docker host."""
        if os.path.isabs(self.dirctl_bin):
            return os.path.exists(self.dirctl_bin)
        return shutil.which(self.dirctl_bin) is not None

    async def close(self):
        # No persistent connection; each call is an independent dirctl invocation.
        return None


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
