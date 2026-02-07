"""AGNTCY integration — OASF records, Agent Directory, and Identity badges."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
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
    platform: Optional[PlatformType] = None
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
    """Client for the AGNTCY Agent Directory Service (ADS)."""

    def __init__(self, url: Optional[str] = None):
        self.url = (url or os.getenv("AGNTCY_DIRECTORY_URL", "http://agntcy-directory:8500")).rstrip("/")
        self._http = httpx.AsyncClient(timeout=15.0)

    async def register(self, record: OASFRecord) -> str:
        """Register MCP server. Returns CID or 'standalone' if Directory unavailable."""
        try:
            resp = await self._http.post(f"{self.url}/v1/records", json=record.to_dict())
            resp.raise_for_status()
            cid = resp.json().get("cid", resp.json().get("id", "unknown"))
            logger.info("Registered %s (CID: %s)", record.name, cid)
            return cid
        except httpx.ConnectError:
            logger.warning("AGNTCY Directory unavailable — standalone mode")
            return "standalone"
        except Exception as e:
            logger.error("Registration failed: %s", e)
            return "error"

    async def discover(
        self,
        skills: Optional[list[str]] = None,
        roles: Optional[list[MIGARole]] = None,
        platform: Optional[PlatformType] = None,
    ) -> list[OASFRecord]:
        params: dict[str, str] = {}
        if skills:
            params["skills"] = ",".join(skills)
        if roles:
            params["roles"] = ",".join(r.value for r in roles)
        if platform:
            params["platform"] = platform.value
        try:
            resp = await self._http.get(f"{self.url}/v1/records", params=params)
            resp.raise_for_status()
            data = resp.json()
            records = data.get("records", data) if isinstance(data, dict) else data
            return [OASFRecord.from_dict(r) for r in records]
        except Exception as e:
            logger.error("Discovery failed: %s", e)
            return []

    async def deregister(self, cid: str) -> bool:
        try:
            resp = await self._http.delete(f"{self.url}/v1/records/{cid}")
            return resp.status_code < 400
        except Exception:
            return False

    async def health(self) -> bool:
        try:
            return (await self._http.get(f"{self.url}/health")).status_code == 200
        except Exception:
            return False

    async def close(self):
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Identity Badge
# ---------------------------------------------------------------------------

@dataclass
class IdentityBadge:
    """AGNTCY Identity badge — cryptographic server identity."""
    subject: str  # e.g. "miga/meraki_mcp"
    issuer: str = ""
    badge_type: str = "mcp_server"
    public_key: Optional[str] = None
    signature: Optional[str] = None
    claims: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.issuer:
            self.issuer = os.getenv("AGNTCY_IDENTITY_ISSUER", "miga")

    def verify(self) -> bool:
        if os.getenv("MIGA_ENV") == "development":
            return True
        return bool(self.signature and self.public_key)

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "issuer": self.issuer, "badge_type": self.badge_type, "claims": self.claims}
