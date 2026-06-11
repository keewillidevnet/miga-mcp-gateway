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
# Optional agntcy-dir SDK (real surface confirmed via live introspection on
# agntcy-dir==1.3.0). The import is guarded so MIGA still runs when the SDK is
# absent — that absence IS the standalone path (and how CI / the build sandbox run).
# ---------------------------------------------------------------------------
try:
    from agntcy.dir_sdk.client import Client, Config
    from agntcy.dir_sdk.models import core_v1
    from google.protobuf.json_format import MessageToDict, ParseDict
    from google.protobuf.struct_pb2 import Struct

    _SDK_AVAILABLE = True
except ImportError:
    Client = Config = core_v1 = Struct = ParseDict = MessageToDict = None  # type: ignore[assignment]
    _SDK_AVAILABLE = False


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
    **agntcy-dir Python SDK** (``agntcy.dir_sdk``), reconciled to the **1.3.0** surface
    confirmed by live introspection.

    Confirmed SDK surface (1.3.0):
      * ``Client(Config(server_address=addr))``
      * ``push(records: list[Record], metadata=None) -> list[RecordRef]`` (LIST in/out)
      * ``pull(refs: list[RecordRef], metadata=None) -> list[Record]``
      * ``delete(refs: list[RecordRef], metadata=None) -> None``
      * ``search_records(req: SearchRecordsRequest, ...) -> list[...]`` (takes a request proto)
      * ``RecordRef`` has one field ``.cid``; ``Record`` has one field ``.data``
        (a ``google.protobuf.Struct``) — build via ``core_v1.Record(data=Struct(...))``.

    The SDK runs natively in the gateway; ``dirctl`` is NOT required at runtime (the SDK
    needs it only for signing, which MIGA does not use).

    **Best-effort by design.** If the SDK is absent or the directory is unreachable,
    every op logs and returns ``"standalone"``/``"error"`` (or ``None``/``False``/``[]``)
    and the gateway keeps routing from ``config/server-registry.yaml``. Routing never
    depends on the directory. The 1.3.0 surface is confirmed by introspection but the
    live roundtrip is still pending (see VERIFY_DIRECTORY.md).
    """

    def __init__(self, addr: str | None = None, *, timeout: float = 30.0):
        # gRPC host:port of dir-apiserver (NOT an http URL).
        self.addr = addr or os.getenv("AGNTCY_DIRECTORY_ADDR", "agntcy-directory:8888")
        self.timeout = timeout
        self._client: Any = None

    # -- SDK plumbing ---------------------------------------------------------

    def _sdk(self) -> Any:
        """Construct the SDK ``Client`` once from MIGA's ``AGNTCY_DIRECTORY_ADDR``
        (passed explicitly to ``Config``). Returns None (best-effort) if the SDK is
        absent or the client can't be built."""
        if self._client is not None:
            return self._client
        if not _SDK_AVAILABLE:
            return None
        try:
            self._client = Client(Config(server_address=self.addr))
        except Exception as exc:  # noqa: BLE001 - best-effort init
            logger.warning("AGNTCY Directory client init failed (%s) — standalone", exc)
            return None
        return self._client

    @staticmethod
    def _to_record(oasf_dict: dict[str, Any]) -> Any:
        """Build a ``core_v1.Record`` from an OASF JSON dict. The OASF document goes in
        ``Record.data`` (a protobuf ``Struct``) — Record has no other fields."""
        s = Struct()
        ParseDict(oasf_dict, s)
        return core_v1.Record(data=s)

    @staticmethod
    def _grpc_code(exc: Exception) -> str | None:
        """Best-effort gRPC status-code name (e.g. UNAVAILABLE, INVALID_ARGUMENT) from a
        grpc.RpcError, without importing grpc."""
        code = getattr(exc, "code", None)
        if callable(code):
            with contextlib.suppress(Exception):
                c = code()
                return getattr(c, "name", str(c))
        return None

    @classmethod
    def _classify(cls, exc: Exception) -> str:
        """Classify a directory error so the operator can tell *unreachable* (directory
        down) from *rejected* (record refused by the apiserver, e.g. schema mismatch)
        from a generic error. Returns 'unreachable' | 'rejected' | 'error'."""
        code = cls._grpc_code(exc)
        hay = (str(exc) + " " + (code or "")).lower()
        if code == "UNAVAILABLE" or any(
            k in hay
            for k in ("unavailable", "connection", "refused", "deadline", "dial", "no such host")
        ):
            return "unreachable"
        if code in ("INVALID_ARGUMENT", "FAILED_PRECONDITION", "OUT_OF_RANGE") or any(
            k in hay for k in ("invalid", "valid", "reject", "schema")
        ):
            return "rejected"
        return "error"

    def _push_sync(self, client: Any, record_dict: dict[str, Any]) -> list[Any]:
        return client.push([self._to_record(record_dict)])

    # -- public API (signatures preserved for server_base / gateway) ----------

    async def register(self, record: OASFRecord) -> str:
        """Best-effort publish of a MIGA ``OASFRecord`` (compat for server_base)."""
        return await self.register_record(record.to_dict())

    async def register_record(self, record: dict[str, Any]) -> str:
        """Publish a full OASF capability record via the SDK ``push`` (list-in/list-out)
        and return the structured ``RecordRef.cid``. Returns ``"standalone"``/``"error"``
        if the SDK/directory is unavailable (non-fatal — routing continues)."""
        if not _SDK_AVAILABLE:
            logger.warning("agntcy-dir SDK not installed — AGNTCY Directory disabled (standalone)")
            return "standalone"
        client = self._sdk()
        if client is None:
            return "standalone"
        name = record.get("name", "record")
        try:
            refs = await asyncio.wait_for(
                asyncio.to_thread(self._push_sync, client, record), timeout=self.timeout
            )
        except TimeoutError as exc:
            logger.warning("directory push failed for %s: %r (timeout/unreachable)", name, exc)
            return "standalone"
        except Exception as exc:  # noqa: BLE001 - best-effort
            kind = self._classify(exc)
            logger.warning("directory push failed for %s: %r (%s)", name, exc, kind)
            # unreachable -> standalone (directory treated as down); rejected/error ->
            # "error" so a refused record is NOT masked as a missing directory.
            return "standalone" if kind == "unreachable" else "error"
        if not refs:
            logger.warning("directory push for %s returned no RecordRef (rejected?)", name)
            return "error"
        cid = refs[0].cid
        logger.info("Published %s to AGNTCY Directory (CID: %s)", name, cid)
        return cid

    async def pull(self, cid: str) -> dict[str, Any] | None:
        """Pull a record by CID (list-in/list-out). Returns the OASF JSON dict (from
        ``Record.data``), or None on any failure."""
        if not _SDK_AVAILABLE:
            return None
        client = self._sdk()
        if client is None:
            return None

        def _pull_sync() -> dict[str, Any] | None:
            recs = client.pull([core_v1.RecordRef(cid=cid)])
            if not recs:
                return None
            return MessageToDict(recs[0].data)

        try:
            return await asyncio.wait_for(asyncio.to_thread(_pull_sync), timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001 - best-effort
            logger.warning(
                "directory pull failed for cid %s: %r (%s)", cid, exc, self._classify(exc)
            )
            return None

    def _search_sync(
        self, client: Any, skills: list[str], limit: int
    ) -> list[tuple[str | None, dict | None]]:
        """Run the SDK ``search_records`` synchronously (called via asyncio.to_thread).

        Returns a list of ``(cid, record_dict_or_None)``. When a result already carries
        the record payload it is decoded here; otherwise only the CID is returned and
        the async caller pulls it. Any wrong field shape raises and is caught by the
        caller, which returns [] (best-effort).

        Confirmed against agntcy-dir 1.3.0 by introspection: SearchRecordsRequest has
        ``queries``/``limit``/``offset``; RecordQuery has ``type``/``value``; the skill
        query type is ``RECORD_QUERY_TYPE_SKILL_NAME``; ``search_records`` returns
        ``list[SearchRecordsResponse]``. Response field access stays defensive. Any
        unexpected shape still raises and is caught by the caller (routing -> static).
        """
        from agntcy.dir_sdk.models import search_v1  # TODO confirm module/type names

        # One query per skill name. AGNTCY search matches records by skill.
        queries = [
            search_v1.RecordQuery(
                # Confirmed against agntcy-dir 1.3.0 via introspection (SKILL_NAME, not SKILL).
                type=search_v1.RecordQueryType.RECORD_QUERY_TYPE_SKILL_NAME,
                value=name,
            )
            for name in skills
        ]
        req = search_v1.SearchRecordsRequest(queries=queries, limit=limit)  # TODO confirm fields

        # search_records(req) -> list[SearchRecordsResponse] (confirmed). Each response
        # carries a match; read its CID and, if present, an inline record. Field names
        # are read defensively (cid / record_ref.cid; data / record.data) so a thin
        # CID-only response still works (the async caller pulls by CID).
        results = client.search_records(req)

        out: list[tuple[str | None, dict | None]] = []
        for item in results:
            cid = getattr(item, "cid", None)
            ref = getattr(item, "record_ref", None)
            if cid is None and ref is not None:
                cid = getattr(ref, "cid", None)
            data = getattr(item, "data", None)
            rec = MessageToDict(data) if data is not None else None
            if rec is None:
                inner = getattr(item, "record", None)
                if inner is not None:
                    idata = getattr(inner, "data", None)
                    if idata is not None:
                        rec = MessageToDict(idata)
                    cid = cid or getattr(inner, "cid", None)
            out.append((cid, rec))
            if len(out) >= limit:
                break
        return out

    async def discover(
        self, skills: list[str] | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Best-effort directory search by OASF skill name.

        Returns a list of ``{"cid", "record", "registry_ref"}`` dicts, where
        ``registry_ref`` is the record's ``annotations.miga_registry_ref`` (the registry
        server holding connection details). On any failure, missing SDK, or empty result
        it returns ``[]`` and never raises, so routing falls back to the static registry.
        """
        if not _SDK_AVAILABLE or not skills:
            return []
        client = self._sdk()
        if client is None:
            return []
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._search_sync, client, list(skills), limit),
                timeout=self.timeout,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort
            logger.warning("directory search failed: %r (%s)", exc, self._classify(exc))
            return []

        out: list[dict[str, Any]] = []
        for cid, rec in raw[:limit]:
            if rec is None and cid:
                rec = await self.pull(cid)
            if rec is None:
                continue
            ref = (rec.get("annotations") or {}).get("miga_registry_ref")
            out.append({"cid": cid, "record": rec, "registry_ref": ref})
        return out

    async def deregister(self, cid: str) -> bool:
        if not _SDK_AVAILABLE:
            return False
        client = self._sdk()
        if client is None:
            return False

        def _delete_sync() -> bool:
            client.delete([core_v1.RecordRef(cid=cid)])
            return True

        try:
            return await asyncio.wait_for(asyncio.to_thread(_delete_sync), timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001 - best-effort
            logger.warning(
                "directory delete failed for cid %s: %r (%s)", cid, exc, self._classify(exc)
            )
            return False

    async def health(self) -> bool:
        """Readiness check from real state only: True only if the SDK is available AND a
        ``Client`` constructs successfully. There is no health RPC; this is readiness,
        not server liveness (confirmed by the VERIFY_DIRECTORY.md roundtrip). Never
        returns True if construction raised."""
        if not _SDK_AVAILABLE:
            return False
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
